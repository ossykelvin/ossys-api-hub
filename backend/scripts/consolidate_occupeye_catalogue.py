from __future__ import annotations

import argparse
import json
import re
from copy import deepcopy
from datetime import UTC, datetime
from pathlib import Path
from typing import Any


GROUPS = {"OccupEye - US", "OccupEye - UK"}
PATH_PARAMETER = re.compile(r"\{([^{}]+)\}")


def _json_object(value: str | None) -> dict[str, Any]:
    try:
        parsed = json.loads(value or "{}")
    except json.JSONDecodeError:
        return {}
    return parsed if isinstance(parsed, dict) else {}


def _relative_path(endpoint: str) -> str:
    return endpoint.split("/OccupEye/", 1)[-1].lstrip("/")


def logical_key(query: dict[str, Any]) -> tuple[str, str]:
    path = _relative_path(str(query.get("endpoint", "")))
    path = path.removeprefix("{deployment}/")
    return str(query.get("restMethod", "GET")).upper(), path.casefold()


def _operation_name(query: dict[str, Any]) -> str:
    path = _relative_path(str(query.get("endpoint", ""))).removeprefix("{deployment}/")
    api_path = path.split("api/", 1)[-1]
    controller = api_path.removeprefix("v2/").split("/", 1)[0]
    return f"OccupEye · {controller} · {str(query.get('restMethod', 'GET')).upper()} {path}"


def _sample_params(query: dict[str, Any], sample: dict[str, Any]) -> dict[str, Any]:
    endpoint = str(query.get("endpoint", ""))
    path = _relative_path(endpoint).casefold()
    params: dict[str, Any] = {}
    if "{deployment}" in endpoint or "deployment" in _json_object(query.get("restParamsText")):
        params["deployment"] = sample["deployment"]

    for placeholder in PATH_PARAMETER.findall(endpoint):
        if placeholder.casefold() == "deployment":
            continue
        params[placeholder] = sample["survey_id"]

    if "environmentdata" in path:
        params.update(
            {
                "SensorID": sample["sensor_id"],
                "triggerType": sample["trigger_type"],
                "triggerTypeID": sample["trigger_type_id"],
                "queryType": "SensorActivity",
                "startdate": sample["start_date"],
                "enddate": sample["end_date"],
                "StartTime": "00:00",
                "EndTime": "23:59",
                "surveyID": sample["survey_id"],
            }
        )
    elif "locationcounts" in path:
        params.update(
            {
                "parameters.startDate": sample["start_date"],
                "parameters.endDate": sample["end_date"],
                "parameters.startTime": "00:00",
                "parameters.endTime": "23:59",
            }
        )
    elif path.endswith("api/occupieddelay"):
        params["sensorid"] = sample["sensor_id"]
    elif path.endswith("api/sensorcounts"):
        params.update(
            {
                "id": sample["survey_id"],
                "parameters.startDate": sample["start_date"],
                "parameters.endDate": sample["end_date"],
                "parameters.startTime": "00:00",
                "parameters.endTime": "23:59",
            }
        )
    elif "sensorsusecondition" in path:
        params.update(
            {
                "date": sample["end_date"],
                "hostaddress": str(sample["host_address"]),
                "surveyID": sample["survey_id"],
            }
        )
    elif "/maps/" in path:
        params.update({"surveyid": sample["survey_id"], "request.size": 100, "request.index": 0})
    elif "surveysensorslatest" in path:
        params["query.surveyID"] = sample["survey_id"]
    elif "surveydevices" in path:
        params.update({"surveyid": sample["survey_id"], "apiv": 4})

    return params


def consolidate_region(
    queries: list[dict[str, Any]], group: str, sample: dict[str, Any], timestamp: str
) -> list[dict[str, Any]]:
    region = [query for query in queries if query.get("group") == group]
    token = next(query for query in region if str(query.get("endpoint", "")).endswith("/token"))
    operations: dict[tuple[str, str], dict[str, Any]] = {}
    for query in region:
        if query is token:
            continue
        key = logical_key(query)
        previous = operations.get(key)
        is_scoped = "/{deployment}/" in str(query.get("endpoint", ""))
        if previous is None or (is_scoped and "/{deployment}/" not in str(previous.get("endpoint", ""))):
            operations[key] = query

    cleaned: list[dict[str, Any]] = [{**deepcopy(token), "updatedAt": timestamp}]
    for key in sorted(operations):
        query = deepcopy(operations[key])
        query["name"] = _operation_name(query)
        query["restParamsText"] = json.dumps(_sample_params(query, sample), indent=2)
        query["updatedAt"] = timestamp
        pagination = deepcopy(query.get("pagination") or {})
        pagination["mode"] = "none"
        pagination["page_count"] = 1
        pagination["items_path"] = "Data" if "environmentdata" in key[1] else ""
        query["pagination"] = pagination
        cleaned.append(query)
    return cleaned


def consolidate_catalogue(
    queries: list[dict[str, Any]], samples: dict[str, dict[str, Any]], timestamp: str | None = None
) -> list[dict[str, Any]]:
    updated_at = timestamp or datetime.now(UTC).isoformat()
    untouched = [query for query in queries if query.get("group") not in GROUPS]
    occup_eye = [
        query
        for group in sorted(GROUPS)
        for query in consolidate_region(queries, group, samples[group], updated_at)
    ]
    return [*untouched, *occup_eye]


def main() -> None:
    parser = argparse.ArgumentParser(description="Consolidate duplicate OccupEye saved-query templates.")
    parser.add_argument("path", type=Path, help="Saved-query JSON file to update")
    parser.add_argument("--samples", type=Path, required=True, help="Private JSON file containing US/UK sample values")
    args = parser.parse_args()
    queries = json.loads(args.path.read_text(encoding="utf-8"))
    samples = json.loads(args.samples.read_text(encoding="utf-8"))
    cleaned = consolidate_catalogue(queries, samples)
    args.path.write_text(json.dumps(cleaned, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
    for group in sorted(GROUPS):
        rows = [query for query in cleaned if query.get("group") == group]
        print(f"{group}: {len(rows)} templates")


if __name__ == "__main__":
    main()
