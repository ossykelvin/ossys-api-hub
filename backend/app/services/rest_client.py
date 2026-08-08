from __future__ import annotations

import asyncio
import re
import time
from copy import deepcopy
from typing import Any
from urllib.parse import quote

import httpx

from app.models import ApiRunResponse, PaginationMode, RestRunRequest, RunError
from app.services.graphql_client import GraphQLRequestError, build_request_headers
from app.services.paths import get_path, normalize_records


class RestRequestError(RuntimeError):
    def __init__(self, message: str, details: Any | None = None):
        super().__init__(message)
        self.details = details


_PATH_PARAMETER = re.compile(r"\{([^{}]+)\}")


def resolve_endpoint_parameters(endpoint: str, query_params: dict[str, Any]) -> tuple[str, dict[str, Any]]:
    """Substitute URL placeholders and keep only true query-string parameters."""
    resolved_params = deepcopy(query_params)
    keys_by_casefold = {str(key).casefold(): key for key in resolved_params}

    def replace(match: re.Match[str]) -> str:
        parameter_name = match.group(1)
        key = keys_by_casefold.get(parameter_name.casefold())
        if key is None:
            return match.group(0)
        value = resolved_params.pop(key)
        return quote(str(value), safe="")

    return _PATH_PARAMETER.sub(replace, endpoint), resolved_params


async def _request_json(
    client: httpx.AsyncClient,
    request: RestRunRequest,
    query_params: dict[str, Any],
    body: dict[str, Any],
) -> Any:
    headers = build_request_headers(request.headers, request.bearer_token)
    endpoint, request_query_params = resolve_endpoint_parameters(str(request.endpoint), query_params)
    payload: dict[str, Any] = {}
    if request.method != "GET" and body:
        if request.body_format == "form":
            if not any(name.lower() == "content-type" for name in request.headers):
                headers.pop("Content-Type", None)
            payload["data"] = body
        else:
            payload["json"] = body
    response = await client.request(
        request.method,
        endpoint,
        headers=headers,
        # Passing an empty mapping makes httpx replace an endpoint's existing
        # query string. None preserves parameters entered directly in the URL.
        params=request_query_params or None,
        **payload,
    )
    if not response.is_success:
        try:
            details: Any = response.json()
        except ValueError:
            details = response.text[:2000] or None
        raise RestRequestError(
            f"Endpoint returned HTTP {response.status_code} {response.reason_phrase}",
            details,
        )
    try:
        return response.json()
    except ValueError as exc:
        raise GraphQLRequestError("The endpoint returned a non-JSON response") from exc


def _set_initial_pagination_values(request: RestRunRequest, target: dict[str, Any]) -> None:
    pagination = request.pagination
    if pagination.mode == PaginationMode.PAGE:
        target[pagination.page_variable] = pagination.starting_page
        target[pagination.page_size_variable] = pagination.page_size
    elif pagination.mode == PaginationMode.OFFSET:
        target[pagination.offset_variable] = pagination.starting_offset
        target[pagination.limit_variable] = pagination.page_size
    elif pagination.mode == PaginationMode.CURSOR:
        target[pagination.cursor_page_size_variable] = pagination.page_size
        target.setdefault(pagination.cursor_variable, None)
    elif pagination.mode == PaginationMode.TOKEN:
        target.setdefault(pagination.token_variable, None)


async def execute_rest_paginated(request: RestRunRequest) -> ApiRunResponse:
    started = time.perf_counter()
    pagination = request.pagination
    query_params = deepcopy(request.query_params)
    body = deepcopy(request.body) if request.body is not None else {}
    target = body if request.pagination_location == "body" else query_params
    _set_initial_pagination_values(request, target)

    records: list[dict[str, Any]] = []
    pages: list[Any] = []
    errors: list[RunError] = []
    stopped_reason = "requested page count reached"
    requested_pages = pagination.max_pages if pagination.page_count == "all" else int(pagination.page_count)
    requested_pages = min(requested_pages, pagination.max_pages)

    async with httpx.AsyncClient(
        timeout=httpx.Timeout(request.timeout_seconds),
        verify=request.verify_ssl,
        follow_redirects=True,
    ) as client:
        for page_number in range(1, requested_pages + 1):
            try:
                response_body = await _request_json(client, request, query_params, body)
            except RestRequestError as exc:
                errors.append(RunError(page=page_number, message=str(exc), details=exc.details))
                stopped_reason = "request failed"
                break
            except (httpx.HTTPError, GraphQLRequestError) as exc:
                errors.append(RunError(page=page_number, message=str(exc)))
                stopped_reason = "request failed"
                break

            pages.append(response_body)
            page_records = normalize_records(get_path(response_body, pagination.items_path), pagination.record_path)
            records.extend(page_records)

            if pagination.mode == PaginationMode.NONE:
                stopped_reason = "single page completed"
                break
            if not page_records:
                stopped_reason = "no records returned"
                break

            if pagination.mode == PaginationMode.PAGE:
                current_page = int(target.get(pagination.page_variable, pagination.starting_page))
                total_pages = get_path(response_body, pagination.total_pages_path) if pagination.total_pages_path else None
                if total_pages is not None:
                    try:
                        last_page = int(total_pages)
                    except (TypeError, ValueError):
                        errors.append(RunError(
                            page=page_number,
                            message="The total-pages path did not resolve to an integer",
                            details=total_pages,
                        ))
                        stopped_reason = "invalid pagination metadata"
                        break
                    if current_page >= last_page:
                        stopped_reason = "total pages reached"
                        break
                target[pagination.page_variable] = current_page + 1
            elif pagination.mode == PaginationMode.OFFSET:
                current_offset = int(target.get(pagination.offset_variable, pagination.starting_offset))
                target[pagination.offset_variable] = current_offset + pagination.page_size
            elif pagination.mode == PaginationMode.CURSOR:
                has_next = bool(get_path(response_body, pagination.has_next_page_path, False))
                next_cursor = get_path(response_body, pagination.next_cursor_path)
                if not has_next or next_cursor in (None, ""):
                    stopped_reason = "no next cursor"
                    break
                if next_cursor == target.get(pagination.cursor_variable):
                    stopped_reason = "cursor did not advance"
                    break
                target[pagination.cursor_variable] = next_cursor
            elif pagination.mode == PaginationMode.TOKEN:
                next_token = get_path(response_body, pagination.next_token_path)
                if next_token in (None, ""):
                    stopped_reason = "no next token"
                    break
                if next_token == target.get(pagination.token_variable):
                    stopped_reason = "continuation token did not advance"
                    break
                target[pagination.token_variable] = next_token

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
