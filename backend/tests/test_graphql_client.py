import asyncio

import httpx

from app.models import GraphQLRunRequest, PaginationConfig
from app.services.graphql_client import build_request_headers, execute_paginated


class FakeAsyncClient:
    def __init__(self, responses: list[dict]):
        self._responses = iter(responses)

    async def __aenter__(self):
        return self

    async def __aexit__(self, *_args):
        return None

    async def post(self, url: str, **_kwargs):
        return httpx.Response(
            200,
            json=next(self._responses),
            request=httpx.Request("POST", url),
        )


def test_bearer_token_takes_precedence_without_mutating_custom_headers():
    custom_headers = {"Authorization": "Basic old", "X-Tenant": "one"}

    headers = build_request_headers(custom_headers, "  secret  ")

    assert headers["Authorization"] == "Bearer secret"
    assert headers["X-Tenant"] == "one"
    assert custom_headers["Authorization"] == "Basic old"


def test_cursor_pagination_stops_when_cursor_does_not_advance(monkeypatch):
    fake_client = FakeAsyncClient([
        {
            "data": {
                "records": {
                    "items": [{"id": 1}],
                    "pageInfo": {"hasNextPage": True, "endCursor": "same"},
                }
            }
        },
        {
            "data": {
                "records": {
                    "items": [{"id": 2}],
                    "pageInfo": {"hasNextPage": True, "endCursor": "same"},
                }
            }
        },
    ])
    monkeypatch.setattr(
        "app.services.graphql_client.httpx.AsyncClient",
        lambda **_kwargs: fake_client,
    )
    request = GraphQLRunRequest(
        endpoint="https://example.com/graphql",
        query="query { records { id } }",
        pagination=PaginationConfig(
            mode="cursor",
            page_count="all",
            max_pages=10,
            items_path="data.records.items",
            has_next_page_path="data.records.pageInfo.hasNextPage",
            next_cursor_path="data.records.pageInfo.endCursor",
        ),
    )

    result = asyncio.run(execute_paginated(request))

    assert result.page_count == 2
    assert result.stopped_reason == "cursor did not advance"


def test_invalid_total_pages_metadata_is_reported(monkeypatch):
    fake_client = FakeAsyncClient([
        {"data": {"records": {"items": [{"id": 1}], "totalPages": "many"}}},
    ])
    monkeypatch.setattr(
        "app.services.graphql_client.httpx.AsyncClient",
        lambda **_kwargs: fake_client,
    )
    request = GraphQLRunRequest(
        endpoint="https://example.com/graphql",
        query="query { records { id } }",
        pagination=PaginationConfig(
            mode="page",
            page_count="all",
            max_pages=10,
            items_path="data.records.items",
            total_pages_path="data.records.totalPages",
        ),
    )

    result = asyncio.run(execute_paginated(request))

    assert result.stopped_reason == "invalid pagination metadata"
    assert result.errors[0].details == "many"


def test_blank_items_path_unwraps_nested_graphql_collection(monkeypatch):
    fake_client = FakeAsyncClient([
        {
            "data": {
                "sensorAssignments": {
                    "data": [{"id": "one"}, {"id": "two"}],
                    "count": 2,
                    "total": 2,
                    "pageNumber": 1,
                    "pageSize": 100,
                }
            }
        },
    ])
    monkeypatch.setattr(
        "app.services.graphql_client.httpx.AsyncClient",
        lambda **_kwargs: fake_client,
    )
    request = GraphQLRunRequest(
        endpoint="https://example.com/graphql",
        query="query { sensorAssignments { data { id } } }",
        pagination=PaginationConfig(mode="none", items_path=""),
    )

    result = asyncio.run(execute_paginated(request))

    assert result.records == [{"id": "one"}, {"id": "two"}]
    assert result.record_count == 2


def test_blank_items_path_keeps_single_graphql_object(monkeypatch):
    fake_client = FakeAsyncClient([
        {"data": {"viewer": {"id": "one", "name": "Ada"}}},
    ])
    monkeypatch.setattr(
        "app.services.graphql_client.httpx.AsyncClient",
        lambda **_kwargs: fake_client,
    )
    request = GraphQLRunRequest(
        endpoint="https://example.com/graphql",
        query="query { viewer { id name } }",
        pagination=PaginationConfig(mode="none", items_path=""),
    )

    result = asyncio.run(execute_paginated(request))

    assert result.records == [{"id": "one", "name": "Ada"}]
    assert result.record_count == 1


def test_page_pagination_stops_before_adding_repeated_page(monkeypatch):
    repeated_page = {
        "data": {
            "sensorAssignments": {
                "data": [{"id": "one"}, {"id": "two"}],
                "pageNumber": 1,
                "pageSize": 2,
            }
        }
    }
    fake_client = FakeAsyncClient([repeated_page, repeated_page, repeated_page])
    monkeypatch.setattr(
        "app.services.graphql_client.httpx.AsyncClient",
        lambda **_kwargs: fake_client,
    )
    request = GraphQLRunRequest(
        endpoint="https://example.com/graphql",
        query="query { sensorAssignments(page: { number: 1, size: 2 }) { data { id } } }",
        pagination=PaginationConfig(
            mode="page",
            page_count="all",
            max_pages=500,
            page_size=2,
            items_path="data.sensorAssignments.data",
            page_variable="pageNumber",
            page_size_variable="pageSize",
        ),
    )

    result = asyncio.run(execute_paginated(request))

    assert result.records == [{"id": "one"}, {"id": "two"}]
    assert result.page_count == 1
    assert result.stopped_reason == (
        "page content repeated; verify the query uses the configured pagination variables"
    )


def test_empty_terminal_page_is_not_counted(monkeypatch):
    fake_client = FakeAsyncClient([
        {"data": {"records": {"items": [{"id": "one"}]}}},
        {"data": {"records": {"items": []}}},
    ])
    monkeypatch.setattr(
        "app.services.graphql_client.httpx.AsyncClient",
        lambda **_kwargs: fake_client,
    )
    request = GraphQLRunRequest(
        endpoint="https://example.com/graphql",
        query="query Records($page: Int!, $pageSize: Int!) { records { items { id } } }",
        pagination=PaginationConfig(
            mode="page",
            page_count="all",
            max_pages=10,
            items_path="data.records.items",
        ),
    )

    result = asyncio.run(execute_paginated(request))

    assert result.records == [{"id": "one"}]
    assert result.page_count == 1
    assert result.stopped_reason == "no records returned"
