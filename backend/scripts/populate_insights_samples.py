from __future__ import annotations

import json
import re
import sys
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Any

import httpx


BACKEND_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(BACKEND_ROOT))

from app.services.saved_queries import load_saved_queries, save_saved_queries  # noqa: E402
from scripts.complete_insights_catalogue import (  # noqa: E402
    GRAPHQL_ENDPOINT,
    INTROSPECTION_QUERY,
    build_operation,
    root_field_from_query,
)


DATE_RANGE = {
    "start": "2026-07-19T00:00:00Z",
    "end": "2026-07-19T23:59:59Z",
}
DISCOVERY_BUILDING_ID = "471189ad7dc1d217d546f3ab6e92172b"
DISCOVERY_BUILDING_NAME = "The Discovery Centre"
DISCOVERY_FLOOR_ID = "01143f825db004b13655ec988ceaf814"
DISCOVERY_FLOOR_NAME = "Floor M0"
DISCOVERY_SPACE_ID = "5e1eb7ddc45c069804fc10e5e978f383"
DISCOVERY_SPACE_NAME = "F0.2010.008"
DISCOVERY_SPACE_TYPE = "Equipment Bay"
ASSIGNMENT_ID = "8a8ad7d9aa3a861efedee966850d30c9"
ASSIGNMENT_SENSOR_ID = "0516f3d8ccc9532ce12ada6eb608f56a"
ASSIGNMENT_FLOOR_ID = "0285dbeb7b004504b21a6a6ef74e26a1"
ASSIGNMENT_SPACE_ID = "32ca035377e275180b1ebff819e1f316"
SENSOR_ID = "8408d7e493b13db4ffc1748893ff00bd"
SENSOR_TYPE = "MBSC"
AMB_BUILDING_ID = "5d307fe6f0078e0943f2175a8b1347fb"
AMB_BUILDING_NAME = "AMB"
AMB_FLOOR_ID = "91a9c19eeef7d0ace6894ea2af231952"
AMB_FLOOR_NAME = "Floor 2"
ENVIRONMENT_SPACE_ID = "a1797533814026df0cd0356fcc3a7ee4"
ENVIRONMENT_SPACE_NAME = "2.14"
ENVIRONMENT_DEVICE_ID = "700001"


SAMPLE_FILTERS: dict[str, dict[str, Any]] = {
    "bookings": {
        "date": {"daysOfWeek": ["Sunday"]},
        "building": {"ids": [DISCOVERY_BUILDING_ID], "name": DISCOVERY_BUILDING_NAME},
    },
    "bookingDuration": {"ids": [1], "description": "< 15 minutes"},
    "bookingKpi": {
        "date": {"daysOfWeek": ["Sunday"]},
        "building": {"ids": [DISCOVERY_BUILDING_ID], "name": DISCOVERY_BUILDING_NAME},
    },
    "buildings": {"ids": [DISCOVERY_BUILDING_ID], "name": DISCOVERY_BUILDING_NAME},
    "floors": {
        "ids": [DISCOVERY_FLOOR_ID],
        "buildingIds": [DISCOVERY_BUILDING_ID],
        "name": DISCOVERY_FLOOR_NAME,
    },
    "resourceGroups": {"buildingIds": [DISCOVERY_BUILDING_ID]},
    "sensorAssignments": {
        "ids": [ASSIGNMENT_ID],
        "sensorIds": [ASSIGNMENT_SENSOR_ID],
        "buildingIds": [DISCOVERY_BUILDING_ID],
        "floorIds": [ASSIGNMENT_FLOOR_ID],
        "spaceIds": [ASSIGNMENT_SPACE_ID],
    },
    "sensors": {"ids": [SENSOR_ID], "type": SENSOR_TYPE},
    "spaces": {
        "ids": [DISCOVERY_SPACE_ID],
        "floorIds": [DISCOVERY_FLOOR_ID],
        "name": DISCOVERY_SPACE_NAME,
        "type": DISCOVERY_SPACE_TYPE,
    },
    "livemetrics": {
        "building": {"ids": [DISCOVERY_BUILDING_ID], "name": DISCOVERY_BUILDING_NAME},
        "floor": {"ids": [DISCOVERY_FLOOR_ID], "name": DISCOVERY_FLOOR_NAME},
        "metricType": "UTILIZATION",
        "metricName": "Utilization",
        "source": ["VS"],
    },
    "wifiFloor": {
        "building": {"ids": [DISCOVERY_BUILDING_ID], "name": DISCOVERY_BUILDING_NAME},
        "floor": {"ids": [DISCOVERY_FLOOR_ID], "name": DISCOVERY_FLOOR_NAME},
        "date": {"daysOfWeek": ["Sunday"]},
        "timeSlot": {"hours": [0]},
    },
    "wifiBuilding": {
        "building": {"ids": [DISCOVERY_BUILDING_ID], "name": DISCOVERY_BUILDING_NAME},
        "date": {"daysOfWeek": ["Sunday"]},
        "timeSlot": {"hours": [0]},
    },
    "wifiUserEvent": {
        "building": {"ids": [DISCOVERY_BUILDING_ID], "name": DISCOVERY_BUILDING_NAME},
        "floor": {"ids": [DISCOVERY_FLOOR_ID], "name": DISCOVERY_FLOOR_NAME},
    },
    "wifiFloorAttendanceKpi": {
        "building": {"ids": [DISCOVERY_BUILDING_ID], "name": DISCOVERY_BUILDING_NAME},
        "floor": {"ids": [DISCOVERY_FLOOR_ID], "name": DISCOVERY_FLOOR_NAME},
        "date": {"daysOfWeek": ["Sunday"]},
        "timeSlot": {"hours": [0]},
    },
    "wifiBuildingAttendanceKpi": {
        "building": {"ids": [DISCOVERY_BUILDING_ID], "name": DISCOVERY_BUILDING_NAME},
        "date": {"daysOfWeek": ["Sunday"]},
        "timeSlot": {"hours": [0]},
    },
    "wifiUtilizationKpi": {
        "building": {"ids": [DISCOVERY_BUILDING_ID], "name": DISCOVERY_BUILDING_NAME},
        "floor": {"ids": [DISCOVERY_FLOOR_ID], "name": DISCOVERY_FLOOR_NAME},
        "date": {"daysOfWeek": ["Sunday"]},
        "timeSlot": {"hours": [0]},
    },
    "flowCount": {
        "building": {"ids": [DISCOVERY_BUILDING_ID], "name": DISCOVERY_BUILDING_NAME},
        "date": {"daysOfWeek": ["Sunday"]},
        "timeSlot": {"hours": [0]},
    },
    "flowCountKpi": {
        "building": {"ids": [DISCOVERY_BUILDING_ID], "name": DISCOVERY_BUILDING_NAME},
        "date": {"daysOfWeek": ["Sunday"]},
        "timeSlot": {"hours": [0]},
    },
    "environmentalReadingRatings": {"readingType": "CO2"},
    "environmentalReadings": {
        "deviceIds": {"ids": [ENVIRONMENT_DEVICE_ID]},
        "building": {"ids": [AMB_BUILDING_ID], "name": AMB_BUILDING_NAME},
        "floor": {"ids": [AMB_FLOOR_ID], "name": AMB_FLOOR_NAME},
        "space": {"ids": [ENVIRONMENT_SPACE_ID], "name": ENVIRONMENT_SPACE_NAME},
        "date": {"daysOfWeek": ["Sunday"]},
        "timeSlot": {"hours": [0]},
        "metric": {"name": "Temp C"},
        "ratingSeverity": {"name": "Low"},
        "ratingValue": {"name": "Good"},
    },
    "environmentalReadingsLatest": {
        "deviceIds": {"ids": [ENVIRONMENT_DEVICE_ID]},
        "building": {"ids": [AMB_BUILDING_ID], "name": AMB_BUILDING_NAME},
        "floor": {"ids": [AMB_FLOOR_ID], "name": AMB_FLOOR_NAME},
        "space": {"ids": [ENVIRONMENT_SPACE_ID], "name": ENVIRONMENT_SPACE_NAME},
        "metric": {"name": "Temp C"},
        "ratingSeverity": {"name": "Low"},
        "ratingValue": {"name": "Good"},
    },
}


def update_curated_query(query_id: str, query: str) -> str:
    query = re.sub(r'start:\s*"[^"]+"', f'start: "{DATE_RANGE["start"]}"', query)
    query = re.sub(r'end:\s*"[^"]+"', f'end: "{DATE_RANGE["end"]}"', query)

    replacements = {
        "insights-average-utilization": (
            """filters: {
      building: { ids: [\"471189ad7dc1d217d546f3ab6e92172b\"], name: \"The Discovery Centre\" }
      date: { daysOfWeek: [Sunday] }
      timeSlot: { hours: [0] }
    }""",
            r"filters:\s*\{.*?\n\s*\}",
        ),
        "insights-utilization-kpi-building": (
            'filters: { building: { ids: ["471189ad7dc1d217d546f3ab6e92172b"], name: "The Discovery Centre" }, source: ["VS"] }',
            r"filters:\s*\{\}",
        ),
        "insights-utilizations": (
            'filters: { building: { ids: ["471189ad7dc1d217d546f3ab6e92172b"], name: "The Discovery Centre" }, floor: { ids: ["01143f825db004b13655ec988ceaf814"], name: "Floor M0" }, date: { daysOfWeek: [Sunday] }, timeSlot: { hours: [0] }, source: ["VS"] }',
            r"filters:\s*\{\}",
        ),
        "insights-sensor-assignments": (
            'filters: { ids: ["8a8ad7d9aa3a861efedee966850d30c9"], sensorIds: ["0516f3d8ccc9532ce12ada6eb608f56a"], buildingIds: ["471189ad7dc1d217d546f3ab6e92172b"], floorIds: ["0285dbeb7b004504b21a6a6ef74e26a1"], spaceIds: ["32ca035377e275180b1ebff819e1f316"] }',
            r"filters:\s*\{\}",
        ),
        "insights-buildings-filtered": (
            'filters: { ids: ["471189ad7dc1d217d546f3ab6e92172b"], name: "The Discovery Centre" }',
            r'filters:\s*\{\s*name:\s*"[^"]+"\s*\}',
        ),
        "insights-environmental-pir-temperature": (
            'filters: { building: { ids: ["5d307fe6f0078e0943f2175a8b1347fb"], name: "AMB" }, floor: { ids: ["91a9c19eeef7d0ace6894ea2af231952"], name: "Floor 2" }, sensor: { ids: ["8408d7e493b13db4ffc1748893ff00bd"] }, date: { daysOfWeek: [Sunday] }, timeSlot: { hours: [0] }, readingType: { name: "temp" } }',
            r"filters:\s*\{\s*readingType:.*?\}\s*\}",
        ),
        "insights-utilization-kpi": (
            'filters: { building: { ids: ["471189ad7dc1d217d546f3ab6e92172b"], name: "The Discovery Centre" }, floor: { ids: ["01143f825db004b13655ec988ceaf814"], name: "Floor M0" }, date: { daysOfWeek: [Sunday] }, timeSlot: { hours: [0] }, source: ["VS"] }',
            r"filters:\s*\{\}",
        ),
        "insights-buildings": (
            'filters: { ids: ["471189ad7dc1d217d546f3ab6e92172b"], name: "The Discovery Centre" }',
            r"filters:\s*\{\}",
        ),
    }
    replacement = replacements.get(query_id)
    if replacement:
        value, pattern = replacement
        query, count = re.subn(pattern, value, query, count=1, flags=re.DOTALL)
        if count != 1:
            raise RuntimeError(f"Could not update filters for {query_id}")
    return query


def main() -> None:
    saved = load_saved_queries()
    token_template = next(query for query in saved if query.get("id") == "insights-token")
    token_body = json.loads(token_template["restBodyText"])

    with httpx.Client(timeout=120, follow_redirects=True) as client:
        token_response = client.post(token_template["endpoint"], data=token_body)
        token_response.raise_for_status()
        token = token_response.json()["access_token"]
        schema_response = client.post(
            GRAPHQL_ENDPOINT,
            json={"query": INTROSPECTION_QUERY},
            headers={"Authorization": f"Bearer {token}"},
        )
        schema_response.raise_for_status()
        schema = schema_response.json()["data"]["__schema"]
        root_fields = {field["name"]: field for field in schema["queryType"]["fields"]}
        types_by_name = {
            type_definition["name"]: type_definition
            for type_definition in schema["types"]
            if type_definition.get("name")
        }

        now = datetime.now(UTC)
        updated: list[dict[str, Any]] = []
        for saved_query in saved:
            query = dict(saved_query)
            if query.get("group") != "Insights" or query.get("apiMode") != "graphql":
                updated.append(query)
                continue

            root_field = root_field_from_query(query.get("query", ""))
            if root_field is None:
                raise RuntimeError(f"Could not identify root field for {query['id']}")
            if query["id"].startswith("insights-schema-"):
                field = root_fields[root_field]
                query_text, variables = build_operation(field, types_by_name)
                if "dateRange" in variables:
                    variables["dateRange"] = DATE_RANGE
                if "filters" in variables:
                    variables["filters"] = SAMPLE_FILTERS[root_field]
                query["query"] = query_text
                query["variablesText"] = json.dumps(variables, ensure_ascii=False, indent=2)
            else:
                query["query"] = update_curated_query(query["id"], query["query"])
            query["updatedAt"] = now.isoformat()
            updated.append(query)

    updated = [
        {**query, "updatedAt": (now + timedelta(seconds=1)).isoformat()}
        if query.get("id") == "insights-token"
        else query
        for query in updated
    ]
    save_saved_queries(updated)
    print("Populated 30 Insights GraphQL templates with verified tenant sample values.")


if __name__ == "__main__":
    main()
