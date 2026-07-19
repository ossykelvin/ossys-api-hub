from __future__ import annotations

import asyncio
import time
from copy import deepcopy
from typing import Any

import httpx

from app.models import ApiRunResponse, GraphQLRunRequest, PaginationMode, RunError
from app.services.paths import get_path, normalize_records


class GraphQLRequestError(RuntimeError):
    pass


_COLLECTION_METADATA_KEYS = {
    "count",
    "total",
    "page",
    "pageInfo",
    "pageNumber",
    "pageSize",
    "totalCount",
    "totalPages",
}


def _infer_graphql_collection(value: Any) -> Any:
    """Unwrap an unambiguous GraphQL connection when no items path was supplied."""
    current = value
    for _ in range(8):
        if isinstance(current, list) or not isinstance(current, dict):
            return current

        if "data" in current and set(current).issubset({"data", "errors", "extensions"}):
            nested = current.get("data")
            if isinstance(nested, (dict, list)):
                current = nested
                continue

        candidates = [
            nested
            for key, nested in current.items()
            if key not in _COLLECTION_METADATA_KEYS and isinstance(nested, (dict, list))
        ]
        scalar_keys = {
            key
            for key, nested in current.items()
            if key not in _COLLECTION_METADATA_KEYS and not isinstance(nested, (dict, list))
        }
        if len(candidates) == 1 and not scalar_keys:
            current = candidates[0]
            continue
        return current
    return current


def build_request_headers(
    custom_headers: dict[str, str],
    bearer_token: str | None = None,
) -> dict[str, str]:
    headers = {"Content-Type": "application/json", "Accept": "application/json", **custom_headers}
    if bearer_token and bearer_token.strip():
        headers["Authorization"] = f"Bearer {bearer_token.strip()}"
    return headers


async def _post_graphql(
    client: httpx.AsyncClient,
    request: GraphQLRunRequest,
    variables: dict[str, Any],
) -> dict[str, Any]:
    response = await client.post(
        str(request.endpoint),
        headers=build_request_headers(request.headers, request.bearer_token),
        json={"query": request.query, "variables": variables},
    )
    response.raise_for_status()
    try:
        body = response.json()
    except ValueError as exc:
        raise GraphQLRequestError("The endpoint returned a non-JSON response") from exc

    if not isinstance(body, dict):
        raise GraphQLRequestError("The endpoint returned an unexpected JSON response")
    return body


async def execute_paginated(request: GraphQLRunRequest) -> ApiRunResponse:
    started = time.perf_counter()
    pagination = request.pagination
    variables = deepcopy(request.variables)
    records: list[dict[str, Any]] = []
    pages: list[dict[str, Any]] = []
    errors: list[RunError] = []
    stopped_reason = "requested page count reached"
    previous_page_records: list[dict[str, Any]] | None = None

    if pagination.mode == PaginationMode.PAGE:
        variables[pagination.page_variable] = pagination.starting_page
        variables[pagination.page_size_variable] = pagination.page_size
    elif pagination.mode == PaginationMode.OFFSET:
        variables[pagination.offset_variable] = pagination.starting_offset
        variables[pagination.limit_variable] = pagination.page_size
    elif pagination.mode == PaginationMode.CURSOR:
        variables[pagination.cursor_page_size_variable] = pagination.page_size
        variables.setdefault(pagination.cursor_variable, None)
    elif pagination.mode == PaginationMode.TOKEN:
        variables.setdefault(pagination.token_variable, None)

    requested_pages = pagination.max_pages if pagination.page_count == "all" else int(pagination.page_count)
    requested_pages = min(requested_pages, pagination.max_pages)

    timeout = httpx.Timeout(request.timeout_seconds)
    async with httpx.AsyncClient(timeout=timeout, verify=request.verify_ssl, follow_redirects=True) as client:
        for page_number in range(1, requested_pages + 1):
            try:
                body = await _post_graphql(client, request, variables)
            except (httpx.HTTPError, GraphQLRequestError) as exc:
                errors.append(RunError(page=page_number, message=str(exc)))
                stopped_reason = "request failed"
                break

            graph_errors = body.get("errors")
            if graph_errors:
                errors.append(
                    RunError(
                        page=page_number,
                        message="GraphQL returned one or more errors",
                        details=graph_errors,
                    )
                )

            items = get_path(body, pagination.items_path)
            if not pagination.items_path.strip():
                items = _infer_graphql_collection(items)
            page_records = normalize_records(items, pagination.record_path)

            if (
                pagination.mode != PaginationMode.NONE
                and previous_page_records is not None
                and page_records
                and page_records == previous_page_records
            ):
                stopped_reason = "page content repeated; verify the query uses the configured pagination variables"
                break

            if pagination.mode != PaginationMode.NONE and not page_records:
                stopped_reason = "no records returned"
                break

            pages.append(body)
            records.extend(page_records)
            previous_page_records = page_records

            if pagination.mode == PaginationMode.NONE:
                stopped_reason = "single page completed"
                break

            if pagination.mode == PaginationMode.PAGE:
                current_page = int(variables.get(pagination.page_variable, pagination.starting_page))
                total_pages = get_path(body, pagination.total_pages_path) if pagination.total_pages_path else None
                if total_pages is not None:
                    try:
                        last_page = int(total_pages)
                    except (TypeError, ValueError):
                        errors.append(
                            RunError(
                                page=page_number,
                                message="The total-pages path did not resolve to an integer",
                                details=total_pages,
                            )
                        )
                        stopped_reason = "invalid pagination metadata"
                        break
                    if current_page >= last_page:
                        stopped_reason = "total pages reached"
                        break
                variables[pagination.page_variable] = current_page + 1

            elif pagination.mode == PaginationMode.OFFSET:
                current_offset = int(variables.get(pagination.offset_variable, pagination.starting_offset))
                variables[pagination.offset_variable] = current_offset + pagination.page_size

            elif pagination.mode == PaginationMode.CURSOR:
                has_next = bool(get_path(body, pagination.has_next_page_path, False))
                next_cursor = get_path(body, pagination.next_cursor_path)
                if not has_next or next_cursor in (None, ""):
                    stopped_reason = "no next cursor"
                    break
                if next_cursor == variables.get(pagination.cursor_variable):
                    stopped_reason = "cursor did not advance"
                    break
                variables[pagination.cursor_variable] = next_cursor

            elif pagination.mode == PaginationMode.TOKEN:
                next_token = get_path(body, pagination.next_token_path)
                if next_token in (None, ""):
                    stopped_reason = "no next token"
                    break
                if next_token == variables.get(pagination.token_variable):
                    stopped_reason = "continuation token did not advance"
                    break
                variables[pagination.token_variable] = next_token

            if pagination.delay_ms:
                await asyncio.sleep(pagination.delay_ms / 1000)
        else:
            stopped_reason = (
                "maximum page limit reached"
                if pagination.page_count == "all" and requested_pages == pagination.max_pages
                else "requested page count reached"
            )

    duration_ms = int((time.perf_counter() - started) * 1000)
    return ApiRunResponse(
        records=records,
        pages=pages,
        page_count=len(pages),
        record_count=len(records),
        duration_ms=duration_ms,
        errors=errors,
        stopped_reason=stopped_reason,
    )
