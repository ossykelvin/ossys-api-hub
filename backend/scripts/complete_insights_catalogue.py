from __future__ import annotations

import json
import re
import sys
from copy import deepcopy
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Any

import httpx


BACKEND_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(BACKEND_ROOT))

from app.services.saved_queries import load_saved_queries, save_saved_queries  # noqa: E402


GRAPHQL_ENDPOINT = "https://insightsapi-uk.fmshosted.com/graphql"
GROUP = "Insights"
TYPE_REFERENCE = """
kind
name
ofType {
  kind
  name
  ofType {
    kind
    name
    ofType {
      kind
      name
      ofType {
        kind
        name
        ofType { kind name }
      }
    }
  }
}
"""
INTROSPECTION_QUERY = f"""
query InsightsCatalogueSchema {{
  __schema {{
    queryType {{
      fields(includeDeprecated: true) {{
        name
        description
        isDeprecated
        args {{
          name
          description
          defaultValue
          type {{ {TYPE_REFERENCE} }}
        }}
        type {{ {TYPE_REFERENCE} }}
      }}
    }}
    mutationType {{ fields {{ name }} }}
    types {{
      kind
      name
      description
      inputFields {{
        name
        description
        defaultValue
        type {{ {TYPE_REFERENCE} }}
      }}
      enumValues(includeDeprecated: false) {{ name }}
      fields(includeDeprecated: false) {{
        name
        args {{ name defaultValue type {{ {TYPE_REFERENCE} }} }}
        type {{ {TYPE_REFERENCE} }}
      }}
    }}
  }}
}}
"""


def type_string(type_reference: dict[str, Any]) -> str:
    kind = type_reference["kind"]
    if kind == "NON_NULL":
        return f"{type_string(type_reference['ofType'])}!"
    if kind == "LIST":
        return f"[{type_string(type_reference['ofType'])}]"
    return type_reference["name"]


def named_type(type_reference: dict[str, Any]) -> tuple[str, str]:
    current = type_reference
    while current["kind"] in {"NON_NULL", "LIST"}:
        current = current["ofType"]
    return current["kind"], current["name"]


def is_required(type_reference: dict[str, Any], default_value: str | None = None) -> bool:
    return type_reference["kind"] == "NON_NULL" and default_value is None


def sample_input(
    type_reference: dict[str, Any],
    types_by_name: dict[str, dict[str, Any]],
    seen: frozenset[str] = frozenset(),
) -> Any:
    kind = type_reference["kind"]
    if kind == "NON_NULL":
        return sample_input(type_reference["ofType"], types_by_name, seen)
    if kind == "LIST":
        return [sample_input(type_reference["ofType"], types_by_name, seen)]

    name = type_reference["name"]
    if kind == "ENUM":
        values = (types_by_name.get(name, {}).get("enumValues") or [])
        return values[0]["name"] if values else ""
    if kind == "INPUT_OBJECT":
        if name in seen:
            return {}
        input_fields = types_by_name.get(name, {}).get("inputFields") or []
        return {
            field["name"]: sample_input(field["type"], types_by_name, seen | {name})
            for field in input_fields
            if is_required(field["type"], field.get("defaultValue"))
        }
    if name in {"Int", "Long"}:
        return 1
    if name in {"Float", "Decimal"}:
        return 0
    if name == "Boolean":
        return False
    if name in {"Date", "DateTime", "DateTimeOffset", "Instant"}:
        return "2024-01-01T00:00:00Z"
    return ""


def selection_set(
    type_reference: dict[str, Any],
    types_by_name: dict[str, dict[str, Any]],
    depth: int = 0,
    seen: frozenset[str] = frozenset(),
) -> list[str]:
    kind, name = named_type(type_reference)
    if kind in {"SCALAR", "ENUM"}:
        return []
    if kind in {"INTERFACE", "UNION"} or name in seen or depth > 3:
        return ["__typename"]

    fields = types_by_name.get(name, {}).get("fields") or []
    selectable_fields = [
        field
        for field in fields
        if not any(is_required(arg["type"], arg.get("defaultValue")) for arg in field.get("args") or [])
    ]
    scalar_fields: list[str] = []
    object_fields: list[str] = []
    for field in selectable_fields:
        field_kind, _ = named_type(field["type"])
        if field_kind in {"SCALAR", "ENUM"}:
            scalar_fields.append(field["name"])
        elif depth < 1:
            children = selection_set(field["type"], types_by_name, depth + 1, seen | {name})
            if children:
                indented = "\n".join(f"  {line}" for line in children)
                object_fields.append(f"{field['name']} {{\n{indented}\n}}")
    return [*scalar_fields, *object_fields] or ["__typename"]


def operation_name(field_name: str) -> str:
    return field_name[:1].upper() + field_name[1:]


def display_name(field_name: str) -> str:
    words = re.sub(r"(?<!^)(?=[A-Z])", " ", field_name).replace("wifi", "WiFi")
    return words[:1].upper() + words[1:]


def root_field_from_query(query: str) -> str | None:
    match = re.search(r"\bquery\s+\w+(?:\s*\([^)]*\))?\s*\{\s*(\w+)", query, re.DOTALL)
    return match.group(1) if match else None


def page_input(field: dict[str, Any], types_by_name: dict[str, dict[str, Any]]) -> tuple[list[str], dict[str, Any], str] | None:
    page_argument = next((arg for arg in field["args"] if arg["name"] == "page"), None)
    if page_argument is None:
        return None
    _, page_type_name = named_type(page_argument["type"])
    page_fields = {
        item["name"]: item
        for item in types_by_name.get(page_type_name, {}).get("inputFields") or []
    }
    if "number" not in page_fields or "size" not in page_fields:
        return None
    definitions = [
        f"$pageNumber: {type_string(page_fields['number']['type'])}",
        f"$pageSize: {type_string(page_fields['size']['type'])}",
    ]
    variables = {"pageNumber": 1, "pageSize": 100}
    argument = "page: { number: $pageNumber, size: $pageSize }"
    return definitions, variables, argument


def build_operation(
    field: dict[str, Any],
    types_by_name: dict[str, dict[str, Any]],
    skip_resolver: bool = False,
) -> tuple[str, dict[str, Any]]:
    variable_definitions: list[str] = []
    variables: dict[str, Any] = {}
    arguments: list[str] = []
    page = page_input(field, types_by_name)
    if page is not None:
        page_definitions, page_variables, page_argument = page
        variable_definitions.extend(page_definitions)
        variables.update(page_variables)
        arguments.append(page_argument)

    for argument in field["args"]:
        if argument["name"] == "page" and page is not None:
            continue
        variable_definitions.append(f"${argument['name']}: {type_string(argument['type'])}")
        variables[argument["name"]] = sample_input(argument["type"], types_by_name)
        arguments.append(f"{argument['name']}: ${argument['name']}")

    definitions_text = f"({', '.join(variable_definitions)})" if variable_definitions else ""
    arguments_text = f"({', '.join(arguments)})" if arguments else ""
    directive = " @skip(if: true)" if skip_resolver else ""
    selections = selection_set(field["type"], types_by_name)
    if selections:
        selection_text = "\n".join(f"    {line}" for line in selections)
        field_text = f"{field['name']}{arguments_text}{directive} {{\n{selection_text}\n  }}"
    else:
        field_text = f"{field['name']}{arguments_text}{directive}"
    query = (
        f"query {operation_name(field['name'])}{definitions_text} {{\n"
        f"  {field_text}\n"
        "}"
    )
    return query, variables


def schema_has_data_collection(field: dict[str, Any], types_by_name: dict[str, dict[str, Any]]) -> bool:
    _, return_type_name = named_type(field["type"])
    return any(
        child["name"] == "data" and named_type(child["type"])[0] == "OBJECT"
        for child in types_by_name.get(return_type_name, {}).get("fields") or []
    )


def validate_without_resolving(
    client: httpx.Client,
    token: str,
    field: dict[str, Any],
    types_by_name: dict[str, dict[str, Any]],
) -> None:
    query, variables = build_operation(field, types_by_name, skip_resolver=True)
    response = client.post(
        GRAPHQL_ENDPOINT,
        json={"query": query, "variables": variables},
        headers={"Authorization": f"Bearer {token}", "Accept": "application/json"},
    )
    response.raise_for_status()
    errors = response.json().get("errors")
    if errors:
        raise RuntimeError(f"Generated {field['name']} template failed validation: {errors}")


def main() -> None:
    saved = load_saved_queries()
    token_template = next(query for query in saved if query.get("id") == "insights-token")
    token_body = json.loads(token_template["restBodyText"])

    with httpx.Client(timeout=120, follow_redirects=True) as client:
        token_response = client.post(
            token_template["endpoint"],
            data=token_body,
            headers={"Accept": "application/json"},
        )
        token_response.raise_for_status()
        token = token_response.json()["access_token"]
        schema_response = client.post(
            GRAPHQL_ENDPOINT,
            json={"query": INTROSPECTION_QUERY},
            headers={"Authorization": f"Bearer {token}", "Accept": "application/json"},
        )
        schema_response.raise_for_status()
        schema_payload = schema_response.json()
        if schema_payload.get("errors"):
            raise RuntimeError(f"Schema introspection failed: {schema_payload['errors']}")

        schema = schema_payload["data"]["__schema"]
        mutation_fields = (schema.get("mutationType") or {}).get("fields") or []
        if mutation_fields:
            raise RuntimeError("Insights unexpectedly exposed mutations; refusing to auto-generate them")
        root_fields = [
            field
            for field in schema["queryType"]["fields"]
            if not field.get("isDeprecated")
        ]
        types_by_name = {
            type_definition["name"]: type_definition
            for type_definition in schema["types"]
            if type_definition.get("name")
        }

        existing_insights = [query for query in saved if query.get("group") == GROUP]
        covered_fields = {
            root_field
            for query in existing_insights
            if query.get("apiMode") == "graphql"
            if (root_field := root_field_from_query(query.get("query", "")))
        }
        missing_fields = [field for field in root_fields if field["name"] not in covered_fields]

        pagination_template = deepcopy(
            next(query for query in existing_insights if query.get("apiMode") == "graphql")["pagination"]
        )
        now = datetime.now(UTC)
        generated: list[dict[str, Any]] = []
        for field in missing_fields:
            validate_without_resolving(client, token, field, types_by_name)
            query_text, variables = build_operation(field, types_by_name)
            pagination = deepcopy(pagination_template)
            if page_input(field, types_by_name) and schema_has_data_collection(field, types_by_name):
                pagination.update({
                    "mode": "page",
                    "items_path": f"data.{field['name']}.data",
                    "record_path": "",
                    "page_variable": "pageNumber",
                    "page_size_variable": "pageSize",
                    "page_size": 100,
                    "starting_page": 1,
                    "page_count": 1,
                })
            else:
                pagination.update({
                    "mode": "none",
                    "items_path": f"data.{field['name']}",
                    "record_path": "",
                    "page_count": 1,
                })
            generated.append({
                "id": f"insights-schema-{re.sub(r'(?<!^)(?=[A-Z])', '-', field['name']).lower()}",
                "group": GROUP,
                "name": f"Insights · {display_name(field['name'])}",
                "endpoint": GRAPHQL_ENDPOINT,
                "query": query_text,
                "variablesText": json.dumps(variables, ensure_ascii=False, indent=2),
                "headersText": "{}",
                "pagination": pagination,
                "updatedAt": now.isoformat(),
                "apiMode": "graphql",
            })

    updated_saved = [
        {
            **query,
            "updatedAt": (now + timedelta(seconds=1)).isoformat(),
        }
        if query.get("id") == "insights-token"
        else query
        for query in saved
    ]
    updated_saved.extend(generated)
    save_saved_queries(updated_saved)
    print(
        f"Saved {len(generated)} new Insights templates; "
        f"{len(covered_fields | {field['name'] for field in missing_fields})}/{len(root_fields)} root fields covered."
    )
    for query in generated:
        print(query["name"])


if __name__ == "__main__":
    main()
