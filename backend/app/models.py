from __future__ import annotations

from enum import Enum
from typing import Any, Literal

from pydantic import BaseModel, Field, HttpUrl, field_validator, model_validator


class PaginationMode(str, Enum):
    NONE = "none"
    CURSOR = "cursor"
    PAGE = "page"
    OFFSET = "offset"
    TOKEN = "token"


class PaginationConfig(BaseModel):
    mode: PaginationMode = PaginationMode.NONE
    items_path: str = "data"
    record_path: str | None = None
    page_size: int = Field(default=100, ge=1, le=10000)
    page_count: int | Literal["all"] = 1
    max_pages: int = Field(default=500, ge=1, le=10000)
    delay_ms: int = Field(default=0, ge=0, le=30000)

    page_variable: str = "page"
    page_size_variable: str = "pageSize"
    starting_page: int = Field(default=1, ge=0)
    total_pages_path: str | None = None

    offset_variable: str = "offset"
    limit_variable: str = "limit"
    starting_offset: int = Field(default=0, ge=0)

    cursor_variable: str = "after"
    cursor_page_size_variable: str = "first"
    has_next_page_path: str = "data.pageInfo.hasNextPage"
    next_cursor_path: str = "data.pageInfo.endCursor"

    token_variable: str = "nextToken"
    next_token_path: str = "data.nextToken"

    @model_validator(mode="after")
    def validate_paths(self) -> "PaginationConfig":
        if isinstance(self.page_count, int) and self.page_count < 1:
            raise ValueError("page_count must be at least 1")

        required_fields = {
            PaginationMode.PAGE: ("page_variable", "page_size_variable"),
            PaginationMode.OFFSET: ("offset_variable", "limit_variable"),
            PaginationMode.CURSOR: (
                "cursor_variable",
                "cursor_page_size_variable",
                "has_next_page_path",
                "next_cursor_path",
            ),
            PaginationMode.TOKEN: ("token_variable", "next_token_path"),
        }
        missing = [
            field_name
            for field_name in required_fields.get(self.mode, ())
            if not str(getattr(self, field_name)).strip()
        ]
        if missing:
            raise ValueError(f"pagination fields cannot be blank: {', '.join(missing)}")
        return self


class GraphQLRunRequest(BaseModel):
    endpoint: HttpUrl
    bearer_token: str | None = None
    headers: dict[str, str] = Field(default_factory=dict)
    query: str = Field(min_length=1)
    variables: dict[str, Any] = Field(default_factory=dict)
    pagination: PaginationConfig = Field(default_factory=PaginationConfig)
    timeout_seconds: float = Field(default=60.0, gt=0, le=600)
    verify_ssl: bool = True

    @field_validator("query")
    @classmethod
    def query_must_not_be_blank(cls, value: str) -> str:
        if not value.strip():
            raise ValueError("query cannot be blank")
        return value


class RestRunRequest(BaseModel):
    endpoint: HttpUrl
    method: Literal["GET", "POST", "PUT", "PATCH", "DELETE", "COPY"] = "GET"
    bearer_token: str | None = None
    headers: dict[str, str] = Field(default_factory=dict)
    query_params: dict[str, Any] = Field(default_factory=dict)
    body: dict[str, Any] | None = None
    body_format: Literal["json", "form"] = "json"
    pagination: PaginationConfig = Field(default_factory=lambda: PaginationConfig(items_path=""))
    pagination_location: Literal["query", "body"] = "query"
    timeout_seconds: float = Field(default=60.0, gt=0, le=600)
    verify_ssl: bool = True

    @model_validator(mode="after")
    def post_body_is_required_for_body_pagination(self) -> "RestRunRequest":
        if self.pagination_location == "body" and self.method == "GET":
            raise ValueError("body pagination requires a method that supports a request body")
        return self


class RunError(BaseModel):
    page: int
    message: str
    details: Any | None = None


class ApiRunResponse(BaseModel):
    records: list[dict[str, Any]]
    pages: list[Any]
    page_count: int
    record_count: int
    duration_ms: int
    errors: list[RunError]
    stopped_reason: str


class ConnectionTestRequest(BaseModel):
    endpoint: HttpUrl
    bearer_token: str | None = None
    headers: dict[str, str] = Field(default_factory=dict)
    timeout_seconds: float = Field(default=30.0, gt=0, le=120)
    verify_ssl: bool = True


class RestConnectionTestRequest(BaseModel):
    endpoint: HttpUrl
    method: Literal["GET", "POST", "PUT", "PATCH", "DELETE", "COPY"] = "GET"
    bearer_token: str | None = None
    headers: dict[str, str] = Field(default_factory=dict)
    query_params: dict[str, Any] = Field(default_factory=dict)
    body: dict[str, Any] | None = None
    body_format: Literal["json", "form"] = "json"
    timeout_seconds: float = Field(default=30.0, gt=0, le=120)
    verify_ssl: bool = True


class OpenApiImportRequest(BaseModel):
    url: HttpUrl


class DocumentationRefreshRequest(BaseModel):
    bearer_token: str | None = None
    timeout_seconds: float = Field(default=60.0, gt=0, le=120)
    verify_ssl: bool = True


class ExportRequest(BaseModel):
    format: Literal["xlsx", "csv", "json"]
    records: list[dict[str, Any]]
    query: str = ""
    variables: dict[str, Any] = Field(default_factory=dict)
    endpoint: str = ""
    run_summary: dict[str, Any] = Field(default_factory=dict)
    errors: list[dict[str, Any]] = Field(default_factory=list)
    filename: str = "graphql-report"
