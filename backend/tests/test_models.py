import pytest
from pydantic import ValidationError

from app.models import GraphQLRunRequest, PaginationConfig


def test_page_count_must_be_positive():
    with pytest.raises(ValidationError, match="page_count must be at least 1"):
        PaginationConfig(page_count=0)


def test_cursor_fields_cannot_be_blank():
    with pytest.raises(ValidationError, match="next_cursor_path"):
        PaginationConfig(mode="cursor", next_cursor_path=" ")


def test_query_cannot_be_blank():
    with pytest.raises(ValidationError, match="query cannot be blank"):
        GraphQLRunRequest(endpoint="https://example.com/graphql", query="  \n")
