from __future__ import annotations

import argparse
import json
from copy import deepcopy
from datetime import UTC, datetime
from pathlib import Path
from typing import Any


TARGETS = {
    "insights-utilization-kpi": {
        "operation": "UtilizationKpi",
        "groupBy": ["Building", "Floor"],
        "filters": {
            "building": {"ids": ["471189ad7dc1d217d546f3ab6e92172b"], "name": "The Discovery Centre"},
            "floor": {"ids": ["01143f825db004b13655ec988ceaf814"], "name": "Floor M0"},
            "date": {"daysOfWeek": ["Sunday"]},
            "timeSlot": {"hours": [0]},
            "source": ["VS"],
        },
        "fields": """rowCount
      sumOfOccupancy
      sumOfCapacity
      maxOfCapacity
      minOfCapacity
      maxOfOccupancy
      minOfOccupancy
      averageUtilization
      buildingId
      floorId
      spaceId
      sensorId
      spaceType
      year
      quarter
      month
      day
      dayOfWeek
      date
      hour
      timeSlot
      source
      userDefinedField1Id
      userDefinedField2Id
      userDefinedField3Id""",
    },
    "insights-utilization-kpi-building": {
        "operation": "UtilizationKpiByBuilding",
        "groupBy": ["Building"],
        "filters": {
            "building": {"ids": ["471189ad7dc1d217d546f3ab6e92172b"], "name": "The Discovery Centre"},
            "source": ["VS"],
        },
        "fields": """sumOfOccupancy
      sumOfCapacity
      averageUtilization
      buildingId""",
    },
}


def _query(operation: str, fields: str) -> str:
    return f"""query {operation}($pageNumber: Int!, $pageSize: Int!, $dateRange: DateRange!, $groupBy: [UtilizationGrouping]!, $filters: UtilizationFilters) {{
  utilizationKpi(
    dateRange: $dateRange
    page: {{ number: $pageNumber, size: $pageSize }}
    groupBy: $groupBy
    filters: $filters
  ) {{
    data {{
      {fields}
    }}
    count
    total
    pageNumber
    pageSize
  }}
}}"""


def configure_query(query: dict[str, Any], timestamp: str) -> dict[str, Any]:
    config = TARGETS.get(str(query.get("id", "")))
    if config is None:
        return query
    updated = deepcopy(query)
    updated["query"] = _query(config["operation"], config["fields"])
    updated["variablesText"] = json.dumps(
        {
            "pageNumber": 1,
            "pageSize": 100,
            "dateRange": {"start": "2026-07-19T00:00:00Z", "end": "2026-07-19T23:59:59Z"},
            "groupBy": config["groupBy"],
            "filters": config["filters"],
        },
        indent=2,
    )
    pagination = deepcopy(updated.get("pagination") or {})
    pagination.update(
        {
            "mode": "page",
            "items_path": "data.utilizationKpi.data",
            "record_path": "",
            "page_size": 100,
            "page_count": "all",
            "max_pages": 500,
            "page_variable": "pageNumber",
            "page_size_variable": "pageSize",
            "starting_page": 1,
            "total_pages_path": "",
        }
    )
    updated["pagination"] = pagination
    updated["updatedAt"] = timestamp
    return updated


def configure_catalogue(queries: list[dict[str, Any]], timestamp: str | None = None) -> list[dict[str, Any]]:
    updated_at = timestamp or datetime.now(UTC).isoformat()
    return [configure_query(query, updated_at) for query in queries]


def main() -> None:
    parser = argparse.ArgumentParser(description="Fix pagination for curated Insights utilization KPI queries.")
    parser.add_argument("path", type=Path)
    args = parser.parse_args()
    queries = json.loads(args.path.read_text(encoding="utf-8"))
    updated = configure_catalogue(queries)
    args.path.write_text(json.dumps(updated, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
    print("Updated", ", ".join(TARGETS))


if __name__ == "__main__":
    main()
