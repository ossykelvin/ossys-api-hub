from __future__ import annotations

import json
import sys
from collections import Counter
from pathlib import Path
from typing import Any

import httpx


BACKEND_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(BACKEND_ROOT))

from app.services.api_documentation import (  # noqa: E402
    _INTROSPECTION_QUERY,
    documentation_from_graphql,
    documentation_from_openapi,
    generated_documentation,
    save_documentation,
)
from app.services.saved_queries import load_saved_queries  # noqa: E402


def json_object(text: Any) -> dict[str, Any]:
    if not isinstance(text, str):
        return {}
    value = json.loads(text)
    return value if isinstance(value, dict) else {}


def token(client: httpx.Client, query: dict[str, Any]) -> str:
    response = client.post(
        query["endpoint"],
        data=json_object(query.get("restBodyText")),
        headers={"Accept": "application/json"},
    )
    response.raise_for_status()
    return response.json()["access_token"]


def main() -> None:
    queries = load_saved_queries()
    records = {str(query["id"]): generated_documentation(query) for query in queries}
    source_counts: Counter[str] = Counter(record["status"] for record in records.values())

    with httpx.Client(timeout=120, follow_redirects=True) as client:
        employee_spec_response = client.get(
            "https://csat5.resourcescheduler.net/RSMCP/swagger/docs/v1",
            headers={"Accept": "application/json"},
        )
        employee_spec_response.raise_for_status()
        employee_spec = employee_spec_response.json()
        for query in queries:
            if query.get("group") != "Employee" or not str(query.get("id", "")).startswith("openapi-"):
                continue
            records[str(query["id"])] = documentation_from_openapi(
                query,
                employee_spec,
                "https://csat5.resourcescheduler.net/RSMCP/swagger/docs/v1",
            )

        for region, host in (("UK", "clouduk"), ("US", "cloudus")):
            group = f"OccupEye - {region}"
            group_queries = [query for query in queries if query.get("group") == group]
            token_query = next(query for query in group_queries if "token" in str(query.get("name", "")).lower())
            access_token = token(client, token_query)
            source_url = f"https://{host}.occupeye.com/OccupEye/swagger/docs/v4"
            spec_response = client.get(
                source_url,
                headers={"Accept": "application/json", "Authorization": f"Bearer {access_token}"},
            )
            spec_response.raise_for_status()
            spec = spec_response.json()
            for query in group_queries:
                if query.get("restMethod") == "COPY" or query is token_query:
                    continue
                records[str(query["id"])] = documentation_from_openapi(query, spec, source_url)

        insights_queries = [query for query in queries if query.get("group") == "Insights"]
        insights_token_query = next(query for query in insights_queries if query.get("apiMode") == "rest")
        insights_token = token(client, insights_token_query)
        graphql_query = next(query for query in insights_queries if query.get("apiMode") == "graphql")
        schema_response = client.post(
            graphql_query["endpoint"],
            headers={"Accept": "application/json", "Authorization": f"Bearer {insights_token}"},
            json={"query": _INTROSPECTION_QUERY, "variables": {}},
        )
        schema_response.raise_for_status()
        schema_payload = schema_response.json()
        if schema_payload.get("errors"):
            raise RuntimeError(f"GraphQL introspection failed: {schema_payload['errors']}")
        schema = schema_payload["data"]["__schema"]
        for query in insights_queries:
            if query.get("apiMode") == "graphql":
                records[str(query["id"])] = documentation_from_graphql(query, schema)

    save_documentation(records)
    source_counts = Counter(record["status"] for record in records.values())
    print(f"Saved documentation for {len(records)} queries")
    print("Status counts:", dict(sorted(source_counts.items())))


if __name__ == "__main__":
    main()
