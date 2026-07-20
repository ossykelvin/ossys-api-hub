from scripts.consolidate_occupeye_catalogue import consolidate_catalogue


def _query(query_id: str, endpoint: str, method: str = "GET") -> dict:
    return {
        "id": query_id,
        "group": "OccupEye - US",
        "name": query_id,
        "endpoint": endpoint,
        "restMethod": method,
        "restParamsText": '{"deployment": "", "parameters.unused": [], "id": 0}',
        "pagination": {"mode": "page", "page_count": "all", "items_path": ""},
    }


def test_consolidates_duplicate_routes_and_prefers_deployment_scope():
    token = _query("token", "https://cloudus.occupeye.com/OccupEye/token", "POST")
    root = _query("root", "https://cloudus.occupeye.com/OccupEye/api/EnvironmentData")
    scoped = _query("scoped", "https://cloudus.occupeye.com/OccupEye/{deployment}/api/EnvironmentData")
    uk_token = {**token, "id": "uk-token", "group": "OccupEye - UK"}
    uk_scoped = {**scoped, "id": "uk-scoped", "group": "OccupEye - UK"}
    sample = {
        "deployment": "SampleDeployment",
        "survey_id": 2,
        "sensor_id": 20999002,
        "trigger_type": "Temperature",
        "trigger_type_id": 10,
        "start_date": "2025-07-15",
        "end_date": "2025-07-31",
        "host_address": 999,
    }

    result = consolidate_catalogue(
        [token, root, scoped, uk_token, uk_scoped],
        {"OccupEye - US": sample, "OccupEye - UK": sample},
        "2026-01-01T00:00:00+00:00",
    )

    us = [query for query in result if query["group"] == "OccupEye - US"]
    assert [query["id"] for query in us] == ["token", "scoped"]
    assert "{deployment}/api/EnvironmentData" in us[1]["endpoint"]
    assert '"SensorID": 20999002' in us[1]["restParamsText"]
    assert "parameters.unused" not in us[1]["restParamsText"]
    assert us[1]["pagination"]["items_path"] == "Data"
    assert us[1]["pagination"]["mode"] == "none"


def test_keeps_root_only_operation_and_populates_path_parameter():
    token = _query("token", "https://cloudus.occupeye.com/OccupEye/token", "POST")
    root_only = _query("hello", "https://cloudus.occupeye.com/OccupEye/api/v2/Hello/{id}")
    uk_token = {**token, "id": "uk-token", "group": "OccupEye - UK"}
    uk_root = {**root_only, "id": "uk-hello", "group": "OccupEye - UK"}
    sample = {
        "deployment": "SampleDeployment",
        "survey_id": 2,
        "sensor_id": 20999002,
        "trigger_type": "Temperature",
        "trigger_type_id": 10,
        "start_date": "2025-07-15",
        "end_date": "2025-07-31",
        "host_address": 999,
    }

    result = consolidate_catalogue(
        [token, root_only, uk_token, uk_root],
        {"OccupEye - US": sample, "OccupEye - UK": sample},
    )

    hello = next(query for query in result if query["id"] == "hello")
    assert '"id": 2' in hello["restParamsText"]
