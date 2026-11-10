from __future__ import annotations

import json
import re
from copy import deepcopy
from typing import Any


TARGETS = {
    "insights-average-utilization": "utilizationKpi",
    "insights-utilization-kpi-building": "utilizationKpi",
    "insights-utilizations": "utilizations",
    "insights-utilization-kpi": "utilizationKpi",
    "insights-schema-wifi-utilization-kpi": "wifiUtilizationKpi",
}
DEFAULT_DATE_RANGE = {
    "start": "2026-07-19T00:00:00Z",
    "end": "2026-07-19T23:59:59Z",
}


def _valid_variables(value: Any) -> dict[str, Any]:
    if not isinstance(value, str):
        return {}
    try:
        parsed = json.loads(value)
    except (TypeError, json.JSONDecodeError):
        return {}
    return parsed if isinstance(parsed, dict) else {}


def _variable_operation(query: str) -> str:
    if re.search(r"\$dateRange\s*:\s*DateRange!", query):
        return query
    return re.sub(
        r"(\bquery\s+[A-Za-z_][A-Za-z0-9_]*)\s*\{",
        r"\1($pageNumber: Int!, $pageSize: Int!, $dateRange: DateRange!) {",
        query,
        count=1,
    )


def _variable_arguments(query: str) -> str:
    query = re.sub(
        r"dateRange\s*:\s*\{[^{}]*\}",
        "dateRange: $dateRange",
        query,
        count=1,
        flags=re.DOTALL,
    )
    query = re.sub(
        r"page\s*:\s*\{[^{}]*\}",
        "page: { number: $pageNumber, size: $pageSize }",
        query,
        count=1,
        flags=re.DOTALL,
    )
    return query


def configure_query(query: dict[str, Any]) -> dict[str, Any]:
    root_field = TARGETS.get(str(query.get("id", "")))
    if root_field is None or query.get("group") != "Insights" or query.get("apiMode") != "graphql":
        return query

    updated = deepcopy(query)
    query_text = str(updated.get("query", ""))
    query_text = _variable_arguments(_variable_operation(query_text))
    updated["query"] = query_text

    variables = _valid_variables(updated.get("variablesText"))
    date_range = variables.get("dateRange")
    if not isinstance(date_range, dict):
        date_range = deepcopy(DEFAULT_DATE_RANGE)
    date_range.setdefault("start", DEFAULT_DATE_RANGE["start"])
    date_range.setdefault("end", DEFAULT_DATE_RANGE["end"])
    variables["dateRange"] = date_range
    variables.setdefault("pageNumber", 1)
    variables.setdefault("pageSize", 100)
    updated["variablesText"] = json.dumps(variables, indent=2, ensure_ascii=False)

    pagination = deepcopy(updated.get("pagination") or {})
    pagination.update({
        "mode": "page",
        "items_path": f"data.{root_field}.data",
        "record_path": "",
        "page_size": int(variables.get("pageSize") or 100),
        "page_count": "all",
        "max_pages": max(500, int(pagination.get("max_pages") or 500)),
        "page_variable": "pageNumber",
        "page_size_variable": "pageSize",
        "starting_page": 1,
        "total_pages_path": "",
    })
    updated["pagination"] = pagination

    iteration = deepcopy(updated.get("iteration") or {})
    iteration.update({
        "enabled": True,
        "mode": "date",
        "parameter_path": "dateRange.start",
        "end_parameter_path": "dateRange.end",
        "step": 1,
        "location": "query",
        "max_iterations": max(1000, int(iteration.get("max_iterations") or 1000)),
        "delay_ms": int(iteration.get("delay_ms") or 0),
    })
    iteration.setdefault("start_value", str(date_range["start"])[:10])
    iteration.setdefault("end_value", str(date_range["end"])[:10])
    updated["iteration"] = iteration
    return updated


def configure_catalogue(queries: list[dict[str, Any]]) -> list[dict[str, Any]]:
    return [configure_query(query) for query in queries]
