import json

from app.services.insights_iteration_templates import configure_catalogue, configure_query


def raw_utilizations_query() -> dict:
    return {
        "id": "insights-utilizations",
        "group": "Insights",
        "apiMode": "graphql",
        "query": """query Utilizations {
  utilizations(
    dateRange: { start: $dateRange.start, end: $dateRange.end }
    page: { number: 1, size: 100 }
    filters: { source: [\"VS\"] }
  ) { data { id date } count total pageNumber pageSize }
}""",
        "variablesText": '{"dateRange.start", "dateRange.end"}',
        "pagination": {"mode": "none", "max_pages": 500},
        "iteration": {
            "enabled": True,
            "start_value": "2026-11-01",
            "end_value": "2026-11-20",
        },
    }


def test_repairs_invalid_utilization_variables_and_preserves_range_and_filters():
    updated = configure_query(raw_utilizations_query())

    assert "query Utilizations($pageNumber: Int!, $pageSize: Int!, $dateRange: DateRange!)" in updated["query"]
    assert "dateRange: $dateRange" in updated["query"]
    assert "page: { number: $pageNumber, size: $pageSize }" in updated["query"]
    assert 'filters: { source: ["VS"] }' in updated["query"]
    variables = json.loads(updated["variablesText"])
    assert variables["dateRange"]["start"].endswith("T00:00:00Z")
    assert variables["dateRange"]["end"].endswith("T23:59:59Z")
    assert variables["pageNumber"] == 1
    assert variables["pageSize"] == 100
    assert updated["pagination"]["mode"] == "page"
    assert updated["pagination"]["items_path"] == "data.utilizations.data"
    assert updated["pagination"]["page_count"] == "all"
    assert updated["iteration"]["start_value"] == "2026-11-01"
    assert updated["iteration"]["end_value"] == "2026-11-20"


def test_migration_is_idempotent_and_ignores_unrelated_queries():
    target = raw_utilizations_query()
    unrelated = {"id": "employee-users", "group": "Employee"}
    once = configure_catalogue([target, unrelated])
    twice = configure_catalogue(once)

    assert twice == once
    assert twice[1] == unrelated
