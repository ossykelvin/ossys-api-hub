import json

from scripts.fix_insights_utilization_pagination import configure_catalogue


def test_utilization_queries_use_configured_page_variables_and_items_path():
    original = {
        "id": "insights-utilization-kpi",
        "query": "query { utilizationKpi(page: { number: 1, size: 100 }) { data { buildingId } } }",
        "variablesText": "{}",
        "pagination": {"mode": "none", "items_path": "", "page_count": 1},
    }

    updated = configure_catalogue([original], "2026-01-01T00:00:00+00:00")[0]

    assert "number: $pageNumber" in updated["query"]
    assert "size: $pageSize" in updated["query"]
    assert "number: 1" not in updated["query"]
    assert json.loads(updated["variablesText"])["pageNumber"] == 1
    assert updated["pagination"]["mode"] == "page"
    assert updated["pagination"]["items_path"] == "data.utilizationKpi.data"
    assert updated["pagination"]["page_variable"] == "pageNumber"
    assert updated["pagination"]["page_size_variable"] == "pageSize"
    assert updated["pagination"]["page_count"] == "all"


def test_unrelated_queries_are_unchanged():
    original = {"id": "another-query", "query": "query Other { other }"}
    assert configure_catalogue([original])[0] is original
