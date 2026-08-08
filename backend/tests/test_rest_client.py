import asyncio
from copy import deepcopy

import httpx

from app.models import PaginationConfig, RestRunRequest
from app.services.rest_client import execute_rest_paginated, resolve_endpoint_parameters


class FakeAsyncClient:
    def __init__(self, responses: list[object]):
        self._responses = iter(responses)
        self.requests: list[dict] = []

    async def __aenter__(self):
        return self

    async def __aexit__(self, *_args):
        return None

    async def request(self, method: str, url: str, **kwargs):
        self.requests.append({"method": method, "url": url, **deepcopy(kwargs)})
        return httpx.Response(
            200,
            json=next(self._responses),
            request=httpx.Request(method, url),
        )


class ErrorAsyncClient(FakeAsyncClient):
    async def request(self, method: str, url: str, **kwargs):
        self.requests.append({"method": method, "url": url, **deepcopy(kwargs)})
        return httpx.Response(
            400,
            json={"error": "invalid_grant"},
            request=httpx.Request(method, url),
        )


def test_resolve_endpoint_parameters_removes_path_values_from_query_string():
    endpoint, query_params = resolve_endpoint_parameters(
        "https://example.com/{deployment}/users/{Id}",
        {"deployment": "London HQ", "id": 2954, "active": True},
    )

    assert endpoint == "https://example.com/London%20HQ/users/2954"
    assert query_params == {"active": True}


def test_rest_page_pagination_uses_query_parameters(monkeypatch):
    fake_client = FakeAsyncClient([
        {"items": [{"id": 1}], "totalPages": 2},
        {"items": [{"id": 2}], "totalPages": 2},
    ])
    monkeypatch.setattr(
        "app.services.rest_client.httpx.AsyncClient",
        lambda **_kwargs: fake_client,
    )
    request = RestRunRequest(
        endpoint="https://example.com/items",
        query_params={"status": "active"},
        pagination=PaginationConfig(
            mode="page",
            page_count="all",
            items_path="items",
            page_variable="page",
            page_size_variable="per_page",
            page_size=25,
            total_pages_path="totalPages",
        ),
    )

    result = asyncio.run(execute_rest_paginated(request))

    assert result.records == [{"id": 1}, {"id": 2}]
    assert result.stopped_reason == "total pages reached"
    assert fake_client.requests[0]["params"] == {"status": "active", "page": 1, "per_page": 25}
    assert fake_client.requests[1]["params"]["page"] == 2


def test_rest_preserves_query_parameters_embedded_in_endpoint(monkeypatch):
    fake_client = FakeAsyncClient([{"access_token": "secret"}])
    monkeypatch.setattr(
        "app.services.rest_client.httpx.AsyncClient",
        lambda **_kwargs: fake_client,
    )
    request = RestRunRequest(
        endpoint="https://example.com/token?grant_type=password",
        method="POST",
        body={"email": "user@example.com", "password": "password"},
        pagination=PaginationConfig(mode="none", items_path=""),
    )

    result = asyncio.run(execute_rest_paginated(request))

    assert fake_client.requests[0]["url"] == "https://example.com/token?grant_type=password"
    assert fake_client.requests[0]["params"] is None
    assert result.errors == []


def test_rest_supports_root_array_responses(monkeypatch):
    fake_client = FakeAsyncClient([[{"id": 1}, {"id": 2}]])
    monkeypatch.setattr(
        "app.services.rest_client.httpx.AsyncClient",
        lambda **_kwargs: fake_client,
    )
    request = RestRunRequest(
        endpoint="https://example.com/items",
        pagination=PaginationConfig(mode="none", items_path=""),
    )

    result = asyncio.run(execute_rest_paginated(request))

    assert result.record_count == 2
    assert result.pages == [[{"id": 1}, {"id": 2}]]


def test_rest_decodes_json_encoded_array_responses_into_rows(monkeypatch):
    encoded_response = '[{"SurveyID": 2, "Name": "Main"}, {"SurveyID": 3, "Name": "Lab"}]'
    fake_client = FakeAsyncClient([encoded_response])
    monkeypatch.setattr(
        "app.services.rest_client.httpx.AsyncClient",
        lambda **_kwargs: fake_client,
    )
    request = RestRunRequest(
        endpoint="https://example.com/api/Surveys/2",
        pagination=PaginationConfig(mode="none", items_path=""),
    )

    result = asyncio.run(execute_rest_paginated(request))

    assert result.records == [
        {"SurveyID": 2, "Name": "Main"},
        {"SurveyID": 3, "Name": "Lab"},
    ]
    assert result.pages == [encoded_response]


def test_rest_decodes_json_encoded_items_path_into_rows(monkeypatch):
    fake_client = FakeAsyncClient([{
        "Surveys": '[{"SurveyID": 2, "Name": "Main"}, {"SurveyID": 3, "Name": "Lab"}]',
    }])
    monkeypatch.setattr(
        "app.services.rest_client.httpx.AsyncClient",
        lambda **_kwargs: fake_client,
    )
    request = RestRunRequest(
        endpoint="https://example.com/api/Surveys",
        pagination=PaginationConfig(mode="none", items_path="Surveys"),
    )

    result = asyncio.run(execute_rest_paginated(request))

    assert result.records == [
        {"SurveyID": 2, "Name": "Main"},
        {"SurveyID": 3, "Name": "Lab"},
    ]


def test_rest_form_body_uses_url_encoding(monkeypatch):
    fake_client = FakeAsyncClient([{"access_token": "secret"}])
    monkeypatch.setattr(
        "app.services.rest_client.httpx.AsyncClient",
        lambda **_kwargs: fake_client,
    )
    request = RestRunRequest(
        endpoint="https://example.com/token",
        method="POST",
        body={"grant_type": "password", "username": "user"},
        body_format="form",
        pagination=PaginationConfig(mode="none", items_path=""),
    )

    result = asyncio.run(execute_rest_paginated(request))

    sent = fake_client.requests[0]
    assert sent["data"] == {"grant_type": "password", "username": "user"}
    assert "json" not in sent
    assert "Content-Type" not in sent["headers"]
    assert result.record_count == 1


def test_body_pagination_requires_post():
    try:
        RestRunRequest(
            endpoint="https://example.com/items",
            method="GET",
            pagination_location="body",
        )
    except ValueError as exc:
        assert "body pagination requires a method that supports a request body" in str(exc)
    else:
        raise AssertionError("Expected request validation to fail")


def test_rest_http_error_preserves_response_details(monkeypatch):
    fake_client = ErrorAsyncClient([])
    monkeypatch.setattr(
        "app.services.rest_client.httpx.AsyncClient",
        lambda **_kwargs: fake_client,
    )
    request = RestRunRequest(
        endpoint="https://example.com/token",
        method="POST",
        body={"grant_type": "password"},
        body_format="form",
    )

    result = asyncio.run(execute_rest_paginated(request))

    assert result.errors[0].message == "Endpoint returned HTTP 400 Bad Request"
    assert result.errors[0].details == {"error": "invalid_grant"}
