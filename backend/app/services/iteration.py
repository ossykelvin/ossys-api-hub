from __future__ import annotations

import asyncio
from datetime import date, timedelta
from decimal import Decimal, InvalidOperation
from typing import Any, Awaitable, Callable, TypeVar

from app.models import (
    ApiRunResponse,
    GraphQLRunRequest,
    IterationConfig,
    IterationMode,
    RestRunRequest,
    RunError,
)
from app.services.graphql_client import execute_paginated
from app.services.paths import get_path, set_path
from app.services.rest_client import execute_rest_paginated


RequestT = TypeVar("RequestT", GraphQLRunRequest, RestRunRequest)


def _date_values(config: IterationConfig) -> list[date]:
    try:
        start = date.fromisoformat(config.start_value[:10])
        end = date.fromisoformat(config.end_value[:10])
    except ValueError as exc:
        raise ValueError("date iteration values must use YYYY-MM-DD or ISO 8601 format") from exc
    if end < start:
        raise ValueError("iteration end date must not be before the start date")
    step = int(config.step)
    if step < 1 or step != config.step:
        raise ValueError("date iteration step must be a whole number of days")
    return [start + timedelta(days=step * index) for index in range(((end - start).days // step) + 1)]


def _number_values(config: IterationConfig) -> list[int | float]:
    try:
        start = Decimal(config.start_value)
        end = Decimal(config.end_value)
        step = Decimal(str(config.step))
    except InvalidOperation as exc:
        raise ValueError("number iteration values must be numeric") from exc
    if end < start:
        raise ValueError("iteration end value must not be below the start value")
    values: list[int | float] = []
    current = start
    while current <= end:
        values.append(int(current) if current == current.to_integral_value() else float(current))
        current += step
    return values


def _format_date_value(value: date, template: Any) -> str:
    if isinstance(template, str) and len(template) > 10 and template[10] == "T":
        return f"{value.isoformat()}{template[10:]}"
    return value.isoformat()


def _apply_iteration(
    request: RequestT,
    value: date | int | float,
) -> RequestT:
    next_request = request.model_copy(deep=True)
    config = next_request.iteration
    next_request.iteration.enabled = False
    if isinstance(next_request, GraphQLRunRequest):
        target = next_request.variables
    else:
        target = next_request.body if config.location == "body" else next_request.query_params
        if target is None:
            target = {}
            next_request.body = target

    if config.mode == IterationMode.DATE:
        existing_start = get_path(target, config.parameter_path)
        set_path(target, config.parameter_path, _format_date_value(value, existing_start))
        if config.end_parameter_path and config.end_parameter_path.strip():
            existing_end = get_path(target, config.end_parameter_path)
            set_path(target, config.end_parameter_path, _format_date_value(value, existing_end))
    else:
        set_path(target, config.parameter_path, value)
    return next_request


async def _execute_iterations(
    request: RequestT,
    executor: Callable[[RequestT], Awaitable[ApiRunResponse]],
) -> ApiRunResponse:
    config = request.iteration
    if not config.enabled:
        return await executor(request)

    values: list[date | int | float]
    values = _date_values(config) if config.mode == IterationMode.DATE else _number_values(config)
    if len(values) > config.max_iterations:
        raise ValueError(
            f"iteration would run {len(values):,} requests, above the configured maximum of {config.max_iterations:,}"
        )

    records: list[dict[str, Any]] = []
    pages: list[Any] = []
    errors: list[RunError] = []
    duration_ms = 0
    completed = 0
    for iteration_number, value in enumerate(values, start=1):
        response = await executor(_apply_iteration(request, value))
        page_offset = len(pages)
        records.extend(response.records)
        pages.extend(response.pages)
        duration_ms += response.duration_ms
        completed += 1
        for error in response.errors:
            details = {
                "iteration": iteration_number,
                "iteration_value": value.isoformat() if isinstance(value, date) else value,
                "response_details": error.details,
            }
            errors.append(RunError(
                page=page_offset + error.page,
                message=f"Iteration {iteration_number} ({details['iteration_value']}): {error.message}",
                details=details,
            ))
        if config.delay_ms and iteration_number < len(values):
            await asyncio.sleep(config.delay_ms / 1000)

    return ApiRunResponse(
        records=records,
        pages=pages,
        page_count=len(pages),
        record_count=len(records),
        duration_ms=duration_ms,
        errors=errors,
        stopped_reason=(
            f"{completed} iterations completed with errors"
            if errors
            else f"{completed} iterations completed"
        ),
        iteration_count=completed,
    )


async def execute_graphql_with_iteration(request: GraphQLRunRequest) -> ApiRunResponse:
    return await _execute_iterations(request, execute_paginated)


async def execute_rest_with_iteration(request: RestRunRequest) -> ApiRunResponse:
    return await _execute_iterations(request, execute_rest_paginated)
