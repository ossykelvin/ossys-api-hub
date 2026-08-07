from __future__ import annotations

import json
import os
import re
from copy import deepcopy
from datetime import UTC, datetime
from pathlib import Path
from tempfile import NamedTemporaryFile
from threading import Lock
from typing import Any
from urllib.parse import urlparse

import httpx

from app.services.state_store import database_enabled, load_json_state, save_json_state


_store_lock = Lock()
_sensitive_key = re.compile(r"password|secret|authorization|access[_-]?token|refresh[_-]?token", re.I)
_graphql_root_field = re.compile(r"\{\s*([_A-Za-z][_0-9A-Za-z]*)", re.S)

_TYPE_REFERENCE = """
kind
name
ofType { kind name ofType { kind name ofType { kind name ofType { kind name } } } }
"""

_INTROSPECTION_QUERY = f"""
query GraphQLHubDocumentation {{
  __schema {{
    queryType {{
      fields(includeDeprecated: true) {{
        name description isDeprecated deprecationReason
        args {{ name description defaultValue type {{ {_TYPE_REFERENCE} }} }}
        type {{ {_TYPE_REFERENCE} }}
      }}
    }}
    types {{
      kind name description
      fields(includeDeprecated: true) {{
        name description isDeprecated deprecationReason type {{ {_TYPE_REFERENCE} }}
      }}
      inputFields {{ name description defaultValue type {{ {_TYPE_REFERENCE} }} }}
      enumValues(includeDeprecated: true) {{ name description isDeprecated deprecationReason }}
    }}
  }}
}}
"""


def documentation_path() -> Path:
    configured_path = os.getenv("API_DOCUMENTATION_PATH")
    if configured_path:
        return Path(configured_path).expanduser().resolve()
    return Path(__file__).resolve().parents[2] / "data" / "api_documentation.json"


def load_documentation(path: Path | None = None) -> dict[str, dict[str, Any]]:
    if path is None and database_enabled():
        value = load_json_state("api_documentation")
        if value is None:
            return {}
        if not isinstance(value, dict):
            raise ValueError("API documentation store must contain a JSON object")
        return {
            str(query_id): record
            for query_id, record in value.items()
            if isinstance(record, dict)
        }

    store_path = path or documentation_path()
    with _store_lock:
        if not store_path.exists():
            return {}
        try:
            value = json.loads(store_path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError) as exc:
            raise ValueError(f"Could not read API documentation: {exc}") from exc
    if not isinstance(value, dict):
        raise ValueError("API documentation store must contain a JSON object")
    return {
        str(query_id): record
        for query_id, record in value.items()
        if isinstance(record, dict)
    }


def save_documentation(
    documentation: dict[str, dict[str, Any]],
    path: Path | None = None,
) -> dict[str, dict[str, Any]]:
    if path is None and database_enabled():
        save_json_state("api_documentation", documentation)
        return documentation

    store_path = path or documentation_path()
    store_path.parent.mkdir(parents=True, exist_ok=True)
    serialized = json.dumps(documentation, indent=2, ensure_ascii=False)
    with _store_lock:
        temporary_path: Path | None = None
        try:
            with NamedTemporaryFile(
                mode="w",
                encoding="utf-8",
                dir=store_path.parent,
                prefix=f".{store_path.name}.",
                suffix=".tmp",
                delete=False,
            ) as temporary_file:
                temporary_file.write(serialized)
                temporary_file.write("\n")
                temporary_path = Path(temporary_file.name)
            temporary_path.replace(store_path)
        finally:
            if temporary_path is not None:
                temporary_path.unlink(missing_ok=True)
    return documentation


def save_documentation_record(record: dict[str, Any], path: Path | None = None) -> dict[str, Any]:
    query_id = str(record.get("queryId", "")).strip()
    if not query_id:
        raise ValueError("Documentation record requires queryId")
    documentation = load_documentation(path)
    documentation[query_id] = record
    save_documentation(documentation, path)
    return record


def _json_object(value: Any) -> dict[str, Any]:
    if not isinstance(value, str):
        return {}
    try:
        parsed = json.loads(value)
    except json.JSONDecodeError:
        return {}
    return parsed if isinstance(parsed, dict) else {}


def redact(value: Any) -> Any:
    if isinstance(value, dict):
        return {
            str(key): "[redacted]" if _sensitive_key.search(str(key)) else redact(item)
            for key, item in value.items()
        }
    if isinstance(value, list):
        return [redact(item) for item in value]
    return value


def _display_summary(query: dict[str, Any]) -> str:
    name = str(query.get("name") or "API request")
    return re.sub(r"^.*?\s(?:·|Â·)\s", "", name, count=1).strip() or name


def _source_details(query: dict[str, Any]) -> tuple[str, str, str]:
    group = str(query.get("group") or "Employee")
    endpoint = str(query.get("endpoint") or "")
    if group == "Employee":
        return "openapi", "https://csat5.resourcescheduler.net/RSMCP/swagger/docs/v1", "Employee OpenAPI"
    if group == "OccupEye - US":
        if str(query.get("restMethod") or "").upper() == "COPY":
            return "manual", "https://cloudus.occupeye.com/OccupEye/APIHelp/", "OccupEye US APIHelp"
        return "openapi", "https://cloudus.occupeye.com/OccupEye/swagger/docs/v4", "OccupEye US Swagger"
    if group == "OccupEye - UK":
        if str(query.get("restMethod") or "").upper() == "COPY":
            return "manual", "https://clouduk.occupeye.com/OccupEye/APIHelp/", "OccupEye UK APIHelp"
        return "openapi", "https://clouduk.occupeye.com/OccupEye/swagger/docs/v4", "OccupEye UK Swagger"
    if group == "Insights" and endpoint.endswith("/graphql"):
        return "graphql", endpoint, "Insights GraphQL schema"
    return "manual", endpoint, "Saved request configuration"


def generated_documentation(query: dict[str, Any]) -> dict[str, Any]:
    source_type, source_url, source_label = _source_details(query)
    api_mode = str(query.get("apiMode") or "graphql")
    parameters = []
    for name, value in redact(_json_object(query.get("restParamsText"))).items():
        parameters.append({
            "name": name,
            "location": "path or query",
            "required": "{" + name + "}" in str(query.get("endpoint") or ""),
            "type": type(value).__name__,
            "example": value,
        })
    variables = redact(_json_object(query.get("variablesText")))
    for name, value in variables.items():
        parameters.append({
            "name": name,
            "location": "GraphQL variable",
            "required": False,
            "type": type(value).__name__,
            "example": value,
        })
    request_body = redact(_json_object(query.get("restBodyText")))
    pagination = query.get("pagination") if isinstance(query.get("pagination"), dict) else {}
    description = "Documentation generated from the saved request configuration."
    if "token" in str(query.get("name") or "").lower():
        description = "Generates an access token used by the other endpoints in this group. Credentials and tokens are always redacted."
    record: dict[str, Any] = {
        "queryId": str(query.get("id") or ""),
        "group": str(query.get("group") or "Employee"),
        "status": "generated",
        "sourceType": source_type,
        "sourceUrl": source_url,
        "sourceLabel": source_label,
        "fetchedAt": datetime.now(UTC).isoformat(),
        "summary": _display_summary(query),
        "description": description,
        "apiMode": api_mode,
        "method": "POST" if api_mode == "graphql" else str(query.get("restMethod") or "GET"),
        "endpoint": str(query.get("endpoint") or ""),
        "parameters": parameters,
        "requestBody": {
            "contentType": "application/graphql+json" if api_mode == "graphql" else (
                "application/x-www-form-urlencoded" if query.get("restBodyFormat") == "form" else "application/json"
            ),
            "example": request_body if api_mode == "rest" else {"variables": variables},
        },
        "responses": [],
        "pagination": {
            "mode": pagination.get("mode", "none"),
            "itemsPath": pagination.get("items_path", ""),
            "pageSize": pagination.get("page_size", 100),
            "maximumPages": pagination.get("max_pages", 500),
        },
    }
    if api_mode == "graphql":
        match = _graphql_root_field.search(str(query.get("query") or ""))
        record["graphql"] = {
            "rootField": match.group(1) if match else "",
            "arguments": [],
            "returnType": "",
            "fields": [],
        }
    return record


def _schema_value(schema: Any, definitions: dict[str, Any], depth: int = 0) -> Any:
    if not isinstance(schema, dict) or depth > 4:
        return schema if isinstance(schema, (str, int, float, bool)) else {}
    reference = schema.get("$ref")
    if isinstance(reference, str):
        name = reference.rsplit("/", 1)[-1]
        resolved = _schema_value(definitions.get(name, {}), definitions, depth + 1)
        if isinstance(resolved, dict):
            return {"title": name, **resolved}
        return resolved
    result = {
        key: deepcopy(value)
        for key, value in schema.items()
        if key in {"type", "format", "description", "required", "enum", "default", "example", "minimum", "maximum"}
    }
    if isinstance(schema.get("properties"), dict):
        result["properties"] = {
            name: _schema_value(value, definitions, depth + 1)
            for name, value in schema["properties"].items()
        }
    if "items" in schema:
        result["items"] = _schema_value(schema["items"], definitions, depth + 1)
    return result


def documentation_from_openapi(
    query: dict[str, Any],
    spec: dict[str, Any],
    source_url: str,
) -> dict[str, Any]:
    record = generated_documentation(query)
    endpoint_path = urlparse(str(query.get("endpoint") or "")).path.rstrip("/")
    base_path = str(spec.get("basePath") or "").rstrip("/")
    operation_path = endpoint_path[len(base_path):] if base_path and endpoint_path.startswith(base_path) else endpoint_path
    path_item = next(
        (
            value for path, value in spec.get("paths", {}).items()
            if str(path).rstrip("/") == operation_path.rstrip("/") and isinstance(value, dict)
        ),
        None,
    )
    method = str(query.get("restMethod") or "GET").lower()
    operation = path_item.get(method) if isinstance(path_item, dict) else None
    if not isinstance(operation, dict):
        raise ValueError(f"{method.upper()} {operation_path or endpoint_path} was not found in the OpenAPI document")
    definitions = spec.get("definitions", {}) if isinstance(spec.get("definitions"), dict) else {}
    parameters: list[dict[str, Any]] = []
    request_body: dict[str, Any] | None = None
    for parameter in [*(path_item.get("parameters") or []), *(operation.get("parameters") or [])]:
        if not isinstance(parameter, dict):
            continue
        if parameter.get("in") == "body":
            request_body = {
                "contentType": (operation.get("consumes") or spec.get("consumes") or ["application/json"])[0],
                "required": bool(parameter.get("required")),
                "description": parameter.get("description") or "",
                "schema": _schema_value(parameter.get("schema", {}), definitions),
                "example": record.get("requestBody", {}).get("example", {}),
            }
            continue
        parameters.append({
            "name": str(parameter.get("name") or ""),
            "location": str(parameter.get("in") or "query"),
            "required": bool(parameter.get("required")),
            "type": parameter.get("type") or parameter.get("schema", {}).get("type") or "object",
            "format": parameter.get("format") or "",
            "description": parameter.get("description") or "",
            "default": redact(parameter.get("default")),
            "example": redact(parameter.get("example")),
            "enum": parameter.get("enum") or [],
        })
    responses = []
    for status, response in (operation.get("responses") or {}).items():
        response = response if isinstance(response, dict) else {}
        responses.append({
            "status": str(status),
            "description": response.get("description") or "",
            "schema": _schema_value(response.get("schema", {}), definitions),
            "example": redact(next(iter((response.get("examples") or {}).values()), None)),
        })
    record.update({
        "status": "source",
        "sourceType": "openapi",
        "sourceUrl": source_url,
        "sourceLabel": str(spec.get("info", {}).get("title") or record["sourceLabel"]),
        "sourceVersion": str(spec.get("info", {}).get("version") or spec.get("swagger") or ""),
        "fetchedAt": datetime.now(UTC).isoformat(),
        "summary": operation.get("summary") or operation.get("operationId") or record["summary"],
        "description": operation.get("description") or operation.get("summary") or record["description"],
        "tags": operation.get("tags") or [],
        "operationId": operation.get("operationId") or "",
        "deprecated": bool(operation.get("deprecated")),
        "parameters": parameters,
        "requestBody": request_body or record["requestBody"],
        "responses": responses,
    })
    return record


def _type_name(reference: dict[str, Any] | None) -> str:
    if not isinstance(reference, dict):
        return ""
    if reference.get("kind") == "NON_NULL":
        return f"{_type_name(reference.get('ofType'))}!"
    if reference.get("kind") == "LIST":
        return f"[{_type_name(reference.get('ofType'))}]"
    return str(reference.get("name") or "")


def _named_type(reference: dict[str, Any] | None) -> str:
    current = reference or {}
    while isinstance(current, dict) and current.get("ofType"):
        current = current["ofType"]
    return str(current.get("name") or "") if isinstance(current, dict) else ""


def _input_example(
    reference: dict[str, Any] | None,
    types_by_name: dict[str, dict[str, Any]],
    depth: int = 0,
    seen: frozenset[str] = frozenset(),
) -> Any:
    if not isinstance(reference, dict) or depth > 4:
        return None
    kind = reference.get("kind")
    if kind == "NON_NULL":
        return _input_example(reference.get("ofType"), types_by_name, depth, seen)
    if kind == "LIST":
        return [_input_example(reference.get("ofType"), types_by_name, depth + 1, seen)]
    name = str(reference.get("name") or "")
    if name in seen:
        return None
    type_definition = types_by_name.get(name, {})
    if kind == "ENUM" or type_definition.get("kind") == "ENUM":
        values = type_definition.get("enumValues") or []
        return values[0].get("name") if values else ""
    if kind == "INPUT_OBJECT" or type_definition.get("kind") == "INPUT_OBJECT":
        return {
            field.get("name", ""): _input_example(
                field.get("type"), types_by_name, depth + 1, seen | {name}
            )
            for field in type_definition.get("inputFields") or []
        }
    return {"Int": 0, "Long": 0, "Float": 0.0, "Decimal": 0.0, "Boolean": False}.get(name, "")


def _input_fields(
    reference: dict[str, Any] | None,
    types_by_name: dict[str, dict[str, Any]],
    depth: int = 0,
    seen: frozenset[str] = frozenset(),
) -> list[dict[str, Any]]:
    name = _named_type(reference)
    if not name or name in seen or depth > 4:
        return []
    type_definition = types_by_name.get(name, {})
    fields = []
    for field in type_definition.get("inputFields") or []:
        field_reference = field.get("type")
        field_type = _type_name(field_reference)
        nested_name = _named_type(field_reference)
        nested_definition = types_by_name.get(nested_name, {})
        fields.append({
            "name": field.get("name") or "",
            "type": field_type,
            "required": field_type.endswith("!"),
            "description": field.get("description") or "",
            "default": field.get("defaultValue"),
            "enumValues": [value.get("name") for value in nested_definition.get("enumValues") or []],
            "example": _input_example(field_reference, types_by_name, depth + 1, seen | {name}),
            "inputFields": _input_fields(field_reference, types_by_name, depth + 1, seen | {name}),
        })
    return fields


def _output_fields(
    reference: dict[str, Any] | None,
    types_by_name: dict[str, dict[str, Any]],
    depth: int = 0,
    seen: frozenset[str] = frozenset(),
) -> list[dict[str, Any]]:
    """Build a navigable output tree while stopping recursive GraphQL type cycles."""
    name = _named_type(reference)
    if not name or name in seen or depth > 8:
        return []
    type_definition = types_by_name.get(name, {})
    next_seen = seen | {name}
    return [
        {
            "name": field.get("name") or "",
            "type": _type_name(field.get("type")),
            "description": field.get("description") or "",
            "deprecated": bool(field.get("isDeprecated")),
            "deprecationReason": field.get("deprecationReason") or "",
            "fields": _output_fields(field.get("type"), types_by_name, depth + 1, next_seen),
        }
        for field in (type_definition.get("fields") or [])
    ]


def documentation_from_graphql(query: dict[str, Any], schema: dict[str, Any]) -> dict[str, Any]:
    record = generated_documentation(query)
    graphql = record.get("graphql", {})
    root_name = str(graphql.get("rootField") or "")
    root_field = next(
        (field for field in schema.get("queryType", {}).get("fields", []) if field.get("name") == root_name),
        None,
    )
    if not isinstance(root_field, dict):
        raise ValueError(f"GraphQL query field {root_name or '(unknown)'} was not found in the schema")
    types_by_name = {
        item["name"]: item for item in schema.get("types", [])
        if isinstance(item, dict) and item.get("name")
    }
    fields = _output_fields(root_field.get("type"), types_by_name)
    record.update({
        "status": "source",
        "sourceType": "graphql",
        "sourceLabel": "Insights GraphQL schema",
        "fetchedAt": datetime.now(UTC).isoformat(),
        "summary": root_name,
        "description": root_field.get("description") or record["description"],
        "deprecated": bool(root_field.get("isDeprecated")),
        "graphql": {
            "outputTreeVersion": 1,
            "rootField": root_name,
            "arguments": [
                {
                    "name": argument.get("name") or "",
                    "type": _type_name(argument.get("type")),
                    "required": _type_name(argument.get("type")).endswith("!"),
                    "description": argument.get("description") or "",
                    "default": argument.get("defaultValue"),
                    "enumValues": [
                        value.get("name")
                        for value in types_by_name.get(_named_type(argument.get("type")), {}).get("enumValues") or []
                    ],
                    "example": _input_example(argument.get("type"), types_by_name),
                    "inputFields": _input_fields(argument.get("type"), types_by_name),
                }
                for argument in root_field.get("args", [])
            ],
            "returnType": _type_name(root_field.get("type")),
            "fields": fields,
        },
    })
    return record


async def refresh_documentation(
    query: dict[str, Any],
    bearer_token: str | None = None,
    timeout_seconds: float = 60,
    verify_ssl: bool = True,
) -> dict[str, Any]:
    source_type, source_url, _ = _source_details(query)
    if source_type == "manual" or "token" in str(query.get("name") or "").lower():
        record = generated_documentation(query)
        return save_documentation_record(record)
    headers = {"Accept": "application/json"}
    if bearer_token:
        headers["Authorization"] = f"Bearer {bearer_token}"
    if str(query.get("group") or "").startswith("OccupEye") and not bearer_token:
        raise ValueError("A group bearer token is required to refresh OccupEye Swagger documentation")
    async with httpx.AsyncClient(
        timeout=httpx.Timeout(timeout_seconds),
        verify=verify_ssl,
        follow_redirects=True,
    ) as client:
        if source_type == "openapi":
            response = await client.get(source_url, headers=headers)
            response.raise_for_status()
            payload = response.json()
            record = documentation_from_openapi(query, payload, source_url)
        else:
            if not bearer_token:
                raise ValueError("A group bearer token is required to refresh GraphQL documentation")
            response = await client.post(
                source_url,
                headers=headers,
                json={"query": _INTROSPECTION_QUERY, "variables": {}},
            )
            response.raise_for_status()
            payload = response.json()
            if payload.get("errors"):
                raise ValueError(f"GraphQL introspection failed: {payload['errors']}")
            record = documentation_from_graphql(query, payload["data"]["__schema"])
    return save_documentation_record(record)
