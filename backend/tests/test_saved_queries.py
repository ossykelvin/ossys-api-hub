import json

import pytest

from app.services.saved_queries import (
    delete_saved_query,
    load_saved_queries,
    merge_saved_queries,
    save_saved_queries,
    upsert_saved_query,
)


def test_saved_queries_survive_separate_load(tmp_path):
    store_path = tmp_path / "saved_queries.json"
    queries = [{"id": "query-1", "name": "Users", "updatedAt": "2026-07-19T12:00:00Z"}]

    save_saved_queries(queries, store_path)

    assert load_saved_queries(store_path) == queries
    assert json.loads(store_path.read_text(encoding="utf-8")) == queries


def test_missing_saved_query_store_is_empty(tmp_path):
    assert load_saved_queries(tmp_path / "missing.json") == []


def test_default_store_falls_back_to_example_queries(tmp_path, monkeypatch):
    store_path = tmp_path / "saved_queries.json"
    examples = [{"id": "example", "name": "Example query"}]
    store_path.with_name("saved_queries.example.json").write_text(
        json.dumps(examples),
        encoding="utf-8",
    )
    monkeypatch.setattr("app.services.saved_queries.saved_queries_path", lambda: store_path)

    assert load_saved_queries() == examples


def test_invalid_saved_query_store_reports_an_error(tmp_path):
    store_path = tmp_path / "saved_queries.json"
    store_path.write_text("not-json", encoding="utf-8")

    with pytest.raises(ValueError, match="Could not read saved queries"):
        load_saved_queries(store_path)


def test_catalogue_merge_does_not_delete_queries_missing_from_stale_client():
    current = [
        {"id": "one", "name": "Current", "updatedAt": "2026-07-20T12:00:00Z"},
        {"id": "two", "name": "Preserved", "updatedAt": "2026-07-20T12:00:00Z"},
    ]
    stale = [{"id": "one", "name": "Stale", "updatedAt": "2026-07-19T12:00:00Z"}]

    assert merge_saved_queries(current, stale) == current


def test_single_query_upsert_and_delete_preserve_other_queries(tmp_path):
    store_path = tmp_path / "saved_queries.json"
    save_saved_queries([{"id": "one"}, {"id": "two"}], store_path)

    upsert_saved_query({"id": "one", "name": "Updated"}, store_path)
    assert load_saved_queries(store_path) == [{"id": "one", "name": "Updated"}, {"id": "two"}]

    delete_saved_query("one", store_path)
    assert load_saved_queries(store_path) == [{"id": "two"}]
