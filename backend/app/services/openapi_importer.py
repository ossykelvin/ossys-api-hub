from __future__ import annotations

import hashlib
from datetime import UTC, datetime
from typing import Any
from urllib.parse import urljoin

import httpx

from app.models import PaginationConfig


SUPPORTED_METHODS = ("get", "post", "put", "patch", "delete", "copy")


def _sample_value(parameter: dict[str, Any]) -> Any:
    if "default" in parameter:
        return parameter["default"]
    if "example" in parameter:
        return parameter["example"]
    values = parameter.get("enum")
    if isinstance(values, list) and values:
        return values[0]
    value_type = parameter.get("type")
    if value_type == "integer" or value_type == "number":
        return 0
    if value_type == "boolean":
        return False
    if value_type == "array":
        return []
    return ""


def _sample_schema(
    schema: dict[str, Any],
    definitions: dict[str, Any],
    depth: int = 0,
    seen_references: frozenset[str] = frozenset(),
) -> Any:
    if "example" in schema:
        return schema["example"]
    if "default" in schema:
        return schema["default"]
    if depth > 4:
        return {}
    reference = schema.get("$ref")
    if isinstance(reference, str):
        name = reference.rsplit("/", 1)[-1]
        if name in seen_references:
            return {}
        return _sample_schema(
            definitions.get(name, {}),
            definitions,
            depth + 1,
            seen_references | {name},
        )
    schema_type = schema.get("type")
    if schema_type == "array":
        return [_sample_schema(schema.get("items", {}), definitions, depth + 1, seen_references)]
    if schema_type == "object" or "properties" in schema:
        properties = schema.get("properties", {})
        return {
            name: _sample_schema(value, definitions, depth + 1, seen_references)
            for name, value in properties.items()
        }
    return _sample_value(schema)


def templates_from_openapi(spec: dict[str, Any], source_url: str) -> list[dict[str, Any]]:
    scheme = (spec.get("schemes") or ["https"])[0]
    host = spec.get("host")
    base_path = str(spec.get("basePath") or "").rstrip("/")
    if host:
        api_root = f"{scheme}://{host}{base_path}/"
    else:
        api_root = urljoin(source_url, f"{base_path.lstrip('/')}/")
    definitions = spec.get("definitions", {})
    pagination = PaginationConfig(items_path="").model_dump(mode="json")
    updated_at = datetime.now(UTC).isoformat()
    templates: list[dict[str, Any]] = []

    for path, path_item in spec.get("paths", {}).items():
        for method in SUPPORTED_METHODS:
            operation = path_item.get(method)
            if not isinstance(operation, dict):
                continue
            parameters = [*path_item.get("parameters", []), *operation.get("parameters", [])]
            query_params: dict[str, Any] = {}
            body: Any = {}
            for parameter in parameters:
                if parameter.get("in") in {"path", "query"}:
                    query_params[parameter["name"]] = _sample_value(parameter)
                elif parameter.get("in") == "body":
                    body = _sample_schema(parameter.get("schema", {}), definitions)

            tags = operation.get("tags") or ["API"]
            summary = operation.get("summary") or operation.get("operationId") or path
            name = f"{tags[0]} · {' '.join(str(summary).split())}"
            digest = hashlib.sha1(f"{method}:{path}".encode()).hexdigest()[:16]
            consumes = operation.get("consumes") or spec.get("consumes") or []
            form_only = "application/x-www-form-urlencoded" in consumes and not any("json" in item for item in consumes)
            templates.append({
                "id": f"openapi-{digest}",
                "name": name,
                "endpoint": urljoin(api_root, path.lstrip("/")),
                "query": "",
                "variablesText": "{}",
                "headersText": _json_text({"Accept": "application/json"}),
                "pagination": pagination,
                "updatedAt": updated_at,
                "apiMode": "rest",
                "restMethod": method.upper(),
                "restParamsText": _json_text(query_params),
                "restBodyText": _json_text(body),
                "restBodyFormat": "form" if form_only else "json",
                "paginationLocation": "query",
            })
    return templates


def _json_text(value: Any) -> str:
    import json

    return json.dumps(value, ensure_ascii=False, indent=2)


async def fetch_openapi_templates(url: str) -> list[dict[str, Any]]:
    async with httpx.AsyncClient(timeout=30, follow_redirects=True) as client:
        response = await client.get(url, headers={"Accept": "application/json"})
        response.raise_for_status()
        spec = response.json()
    if not isinstance(spec, dict) or not isinstance(spec.get("paths"), dict):
        raise ValueError("The URL did not return a supported OpenAPI document")
    return templates_from_openapi(spec, url)
