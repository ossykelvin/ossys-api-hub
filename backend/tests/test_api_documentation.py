from pathlib import Path

from app.services.api_documentation import (
    documentation_from_graphql,
    documentation_from_openapi,
    generated_documentation,
    load_documentation,
    save_documentation,
)


def sample_query() -> dict:
    return {
        "id": "query-1",
        "group": "Employee",
        "name": "Users · Get user",
        "endpoint": "https://example.com/api/users/{userId}",
        "apiMode": "rest",
        "restMethod": "GET",
        "restParamsText": '{"userId": 2954, "access_token": "unsafe"}',
        "restBodyText": '{"client_secret": "unsafe"}',
        "pagination": {"mode": "none", "page_size": 100, "max_pages": 500},
    }


def test_generated_documentation_redacts_secrets() -> None:
    documentation = generated_documentation(sample_query())

    assert documentation["parameters"][1]["example"] == "[redacted]"
    assert documentation["requestBody"]["example"]["client_secret"] == "[redacted]"


def test_openapi_documentation_includes_operation_details() -> None:
    spec = {
        "swagger": "2.0",
        "basePath": "/api",
        "info": {"title": "Example", "version": "1"},
        "paths": {
            "/users/{userId}": {
                "get": {
                    "summary": "Get a user",
                    "description": "Returns one user.",
                    "operationId": "Users_Get",
                    "tags": ["Users"],
                    "parameters": [{
                        "name": "userId", "in": "path", "required": True,
                        "type": "integer", "description": "User identifier",
                    }],
                    "responses": {"200": {"description": "Success", "schema": {"type": "object"}}},
                }
            }
        },
    }

    documentation = documentation_from_openapi(sample_query(), spec, "https://example.com/swagger.json")

    assert documentation["status"] == "source"
    assert documentation["operationId"] == "Users_Get"
    assert documentation["parameters"][0]["required"] is True
    assert documentation["responses"][0]["status"] == "200"


def test_documentation_store_round_trip(tmp_path: Path) -> None:
    path = tmp_path / "documentation.json"
    saved = {"query-1": generated_documentation(sample_query())}

    save_documentation(saved, path)

    assert load_documentation(path) == saved


def test_graphql_arguments_include_expandable_input_fields() -> None:
    query = {
        **sample_query(),
        "id": "graphql-1",
        "group": "Insights",
        "name": "Insights · Buildings",
        "endpoint": "https://example.com/graphql",
        "apiMode": "graphql",
        "query": "query Buildings($filters: BuildingFilters!) { buildings(filters: $filters) { total } }",
        "variablesText": '{"filters": {"name": "HQ"}}',
    }
    schema = {
        "queryType": {"fields": [{
            "name": "buildings",
            "description": "Gets buildings.",
            "args": [{
                "name": "filters", "description": "Building filters.", "defaultValue": None,
                "type": {"kind": "NON_NULL", "name": None, "ofType": {"kind": "INPUT_OBJECT", "name": "BuildingFilters"}},
            }],
            "type": {"kind": "OBJECT", "name": "BuildingPagedResult"},
        }]},
        "types": [
            {"kind": "INPUT_OBJECT", "name": "BuildingFilters", "inputFields": [{
                "name": "name", "description": "Building name.", "defaultValue": None,
                "type": {"kind": "SCALAR", "name": "String"},
            }]},
            {"kind": "OBJECT", "name": "BuildingPagedResult", "fields": [{
                "name": "total", "description": "Total buildings.", "isDeprecated": False,
                "type": {"kind": "SCALAR", "name": "Int"},
            }]},
        ],
    }

    documentation = documentation_from_graphql(query, schema)
    argument = documentation["graphql"]["arguments"][0]

    assert argument["required"] is True
    assert argument["inputFields"][0]["name"] == "name"
    assert argument["inputFields"][0]["description"] == "Building name."
    assert argument["example"] == {"name": ""}


def test_graphql_result_data_includes_expandable_nested_fields() -> None:
    query = {
        **sample_query(),
        "id": "graphql-results",
        "group": "Insights",
        "name": "Insights · Sensor assignments",
        "endpoint": "https://example.com/graphql",
        "apiMode": "graphql",
        "query": "query { sensorAssignments { data { id sensor { id name } } total } }",
    }
    schema = {
        "queryType": {"fields": [{
            "name": "sensorAssignments", "description": "Gets assignments.", "args": [],
            "type": {"kind": "OBJECT", "name": "SensorAssignmentPage"},
        }]},
        "types": [
            {"kind": "OBJECT", "name": "SensorAssignmentPage", "fields": [
                {"name": "data", "description": "Assignment rows.", "isDeprecated": False,
                 "type": {"kind": "LIST", "name": None, "ofType": {"kind": "OBJECT", "name": "SensorAssignment"}}},
                {"name": "total", "description": "Total rows.", "isDeprecated": False,
                 "type": {"kind": "SCALAR", "name": "Int"}},
            ]},
            {"kind": "OBJECT", "name": "SensorAssignment", "fields": [
                {"name": "id", "description": "Assignment ID.", "isDeprecated": False,
                 "type": {"kind": "SCALAR", "name": "ID"}},
                {"name": "sensor", "description": "Assigned sensor.", "isDeprecated": False,
                 "type": {"kind": "OBJECT", "name": "Sensor"}},
            ]},
            {"kind": "OBJECT", "name": "Sensor", "fields": [
                {"name": "id", "description": "Sensor ID.", "isDeprecated": False,
                 "type": {"kind": "SCALAR", "name": "ID"}},
                {"name": "name", "description": "Sensor name.", "isDeprecated": False,
                 "type": {"kind": "SCALAR", "name": "String"}},
                {"name": "assignment", "description": "Back reference.", "isDeprecated": False,
                 "type": {"kind": "OBJECT", "name": "SensorAssignment"}},
            ]},
        ],
    }

    graphql = documentation_from_graphql(query, schema)["graphql"]
    fields = graphql["fields"]
    data = next(field for field in fields if field["name"] == "data")
    sensor = next(field for field in data["fields"] if field["name"] == "sensor")

    assert [field["name"] for field in data["fields"]] == ["id", "sensor"]
    assert graphql["outputTreeVersion"] == 1
    assert [field["name"] for field in sensor["fields"]] == ["id", "name", "assignment"]
    assert next(field for field in sensor["fields"] if field["name"] == "assignment")["fields"] == []
