import asyncio

import pytest

from app.models import ApiRunResponse, GraphQLRunRequest, IterationConfig, PaginationConfig
from app.services.iteration import execute_graphql_with_iteration


def response_for(value: str) -> ApiRunResponse:
    return ApiRunResponse(
        records=[{"date": value}],
        pages=[{"date": value}],
        page_count=1,
        record_count=1,
        duration_ms=5,
        errors=[],
        stopped_reason="single page completed",
    )


def test_date_range_iteration_preserves_times_and_aggregates(monkeypatch):
    received: list[dict] = []

    async def fake_execute(request: GraphQLRunRequest) -> ApiRunResponse:
        received.append(request.variables)
        return response_for(request.variables["dateRange"]["start"])

    monkeypatch.setattr("app.services.iteration.execute_paginated", fake_execute)
    request = GraphQLRunRequest(
        endpoint="https://example.com/graphql",
        query="query { utilizationKpi { total } }",
        variables={
            "dateRange": {
                "start": "2026-07-01T00:00:00Z",
                "end": "2026-07-01T23:59:59Z",
            }
        },
        pagination=PaginationConfig(mode="none", items_path="data"),
        iteration=IterationConfig(
            enabled=True,
            mode="date",
            parameter_path="dateRange.start",
            end_parameter_path="dateRange.end",
            start_value="2026-07-01",
            end_value="2026-07-03",
        ),
    )

    result = asyncio.run(execute_graphql_with_iteration(request))

    assert [item["dateRange"] for item in received] == [
        {"start": "2026-07-01T00:00:00Z", "end": "2026-07-01T23:59:59Z"},
        {"start": "2026-07-02T00:00:00Z", "end": "2026-07-02T23:59:59Z"},
        {"start": "2026-07-03T00:00:00Z", "end": "2026-07-03T23:59:59Z"},
    ]
    assert result.iteration_count == 3
    assert result.page_count == 3
    assert result.record_count == 3
    assert result.duration_ms == 15


def test_iteration_enforces_safety_limit(monkeypatch):
    async def fake_execute(_request: GraphQLRunRequest) -> ApiRunResponse:
        pytest.fail("executor should not run above the iteration safety limit")

    monkeypatch.setattr("app.services.iteration.execute_paginated", fake_execute)
    request = GraphQLRunRequest(
        endpoint="https://example.com/graphql",
        query="query { records { id } }",
        iteration=IterationConfig(
            enabled=True,
            mode="number",
            parameter_path="recordId",
            start_value="1",
            end_value="20",
            max_iterations=10,
        ),
    )

    with pytest.raises(ValueError, match="above the configured maximum"):
        asyncio.run(execute_graphql_with_iteration(request))
