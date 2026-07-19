from __future__ import annotations

import hashlib
import json
import os
import sys
from collections import Counter
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Any

import httpx


BACKEND_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(BACKEND_ROOT))

from app.services.openapi_importer import templates_from_openapi  # noqa: E402
from app.services.saved_queries import load_saved_queries, save_saved_queries  # noqa: E402


REGIONS = {
    "UK": "clouduk",
    "US": "cloudus",
}


def fetch_spec(client: httpx.Client, host: str) -> dict[str, Any]:
    base = f"https://{host}.occupeye.com/OccupEye"
    token_response = client.post(
        f"{base}/token",
        data={
            "grant_type": "password",
            "username": os.environ["OCCUPEYE_USERNAME"],
            "password": os.environ["OCCUPEYE_PASSWORD"],
        },
    )
    token_response.raise_for_status()
    token = token_response.json()["access_token"]
    spec_response = client.get(
        f"{base}/swagger/docs/v4",
        headers={"Authorization": f"Bearer {token}"},
    )
    spec_response.raise_for_status()
    return json.loads(spec_response.text)


def catalogue_key(query: dict[str, Any]) -> tuple[str, str]:
    return str(query.get("restMethod", "GET")).upper(), str(query.get("endpoint", "")).rstrip("/")


def build_region_catalogue(
    region: str,
    host: str,
    spec: dict[str, Any],
    existing: list[dict[str, Any]],
    timestamp: datetime,
) -> list[dict[str, Any]]:
    group = f"OccupEye - {region}"
    base = f"https://{host}.occupeye.com/OccupEye"
    existing_region = [query for query in existing if query.get("group") == group]
    existing_by_key = {catalogue_key(query): query for query in existing_region}
    token = next(query for query in existing_region if query.get("id") == f"occupeye-{region.lower()}-token")
    token = {**token, "updatedAt": (timestamp + timedelta(seconds=1)).isoformat()}

    swagger_templates = templates_from_openapi(spec, f"{base}/swagger/docs/v4")
    completed: list[dict[str, Any]] = []
    for template in swagger_templates:
        key = catalogue_key(template)
        previous = existing_by_key.get(key)
        relative_path = template["endpoint"].removeprefix(base).lstrip("/")
        operation_path = "/" + relative_path
        operation = spec["paths"][operation_path][template["restMethod"].lower()]
        tag = (operation.get("tags") or ["API"])[0]
        digest = hashlib.sha1(f"{region}:{key[0]}:{relative_path}".encode()).hexdigest()[:16]
        template.update(
            {
                "id": previous["id"] if previous else f"occupeye-{region.lower()}-{digest}",
                "group": group,
                "name": f"OccupEye · {tag} · {key[0]} {relative_path}",
                "updatedAt": timestamp.isoformat(),
            }
        )
        completed.append(template)

    swagger_keys = {catalogue_key(query) for query in completed}
    api_help_only = [
        query
        for query in existing_region
        if query.get("restMethod") == "COPY" and catalogue_key(query) not in swagger_keys
    ]
    for query in api_help_only:
        query = {**query, "updatedAt": timestamp.isoformat()}
        completed.append(query)

    return [token, *completed]


def main() -> None:
    existing = load_saved_queries()
    with httpx.Client(timeout=120, follow_redirects=True) as client:
        specs = {region: fetch_spec(client, host) for region, host in REGIONS.items()}
        signatures = {
            region: {
                (method.upper(), path)
                for path, path_item in spec["paths"].items()
                for method, operation in path_item.items()
                if isinstance(operation, dict) and method in {"get", "post", "put", "patch", "delete", "copy"}
            }
            for region, spec in specs.items()
        }
        if signatures["UK"] != signatures["US"]:
            raise RuntimeError("UK and US Swagger operation sets differ; refusing to mirror an inconsistent catalogue")

        now = datetime.now(UTC)
        unchanged = [query for query in existing if query.get("group") not in {"OccupEye - UK", "OccupEye - US"}]
        regions = [
            query
            for region, host in REGIONS.items()
            for query in build_region_catalogue(region, host, specs[region], existing, now)
        ]
        merged = [*unchanged, *regions]

        for region in REGIONS:
            group = f"OccupEye - {region}"
            region_queries = [query for query in merged if query.get("group") == group]
            counts = Counter(query.get("restMethod") for query in region_queries)
            if len(region_queries) != 87 or counts != Counter({"GET": 52, "POST": 19, "DELETE": 8, "PUT": 6, "COPY": 2}):
                raise RuntimeError(f"Unexpected {group} catalogue: {len(region_queries)} {dict(counts)}")

    saved = save_saved_queries(merged)

    print(f"Saved {len(saved)} queries")
    for region in REGIONS:
        group = f"OccupEye - {region}"
        queries = [query for query in saved if query.get("group") == group]
        print(
            group,
            len(queries),
            dict(Counter(query.get("restMethod") for query in queries)),
            "largest body",
            max(len(query.get("restBodyText", "")) for query in queries),
        )


if __name__ == "__main__":
    main()
