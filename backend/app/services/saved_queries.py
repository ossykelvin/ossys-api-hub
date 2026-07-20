from __future__ import annotations

import json
import os
from pathlib import Path
from tempfile import NamedTemporaryFile
from threading import Lock
from typing import Any

from app.services.state_store import (
    database_enabled,
    delete_json_array_item,
    load_json_state,
    save_json_state,
    upsert_json_array_item,
)


_store_lock = Lock()


def saved_queries_path() -> Path:
    configured_path = os.getenv("SAVED_QUERIES_PATH")
    if configured_path:
        return Path(configured_path).expanduser().resolve()
    return Path(__file__).resolve().parents[2] / "data" / "saved_queries.json"


def load_saved_queries(path: Path | None = None) -> list[dict[str, Any]]:
    if path is None and database_enabled():
        value = load_json_state("saved_queries")
        if value is None:
            example_path = saved_queries_path().with_name("saved_queries.example.json")
            value = _load_queries_file(example_path) if example_path.exists() else []
            save_json_state("saved_queries", value)
        if not isinstance(value, list):
            raise ValueError("Saved query store must contain a JSON array")
        return [item for item in value if isinstance(item, dict)]

    store_path = path or saved_queries_path()
    if path is None and not store_path.exists():
        example_path = store_path.with_name("saved_queries.example.json")
        if example_path.exists():
            store_path = example_path
    value = _load_queries_file(store_path)

    if not isinstance(value, list):
        raise ValueError("Saved query store must contain a JSON array")
    return [item for item in value if isinstance(item, dict)]


def _load_queries_file(store_path: Path) -> Any:
    with _store_lock:
        if not store_path.exists():
            return []
        try:
            return json.loads(store_path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError) as exc:
            raise ValueError(f"Could not read saved queries: {exc}") from exc


def save_saved_queries(
    queries: list[dict[str, Any]],
    path: Path | None = None,
) -> list[dict[str, Any]]:
    if path is None and database_enabled():
        save_json_state("saved_queries", queries)
        return queries

    store_path = path or saved_queries_path()
    store_path.parent.mkdir(parents=True, exist_ok=True)
    serialized = json.dumps(queries, indent=2, ensure_ascii=False)

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

    return queries


def merge_saved_queries(
    existing: list[dict[str, Any]],
    incoming: list[dict[str, Any]],
) -> list[dict[str, Any]]:
    """Merge an imported catalogue without allowing a stale client to delete records."""
    merged = {str(item.get("id")): item for item in existing if item.get("id")}
    for item in incoming:
        item_id = str(item.get("id", ""))
        if not item_id:
            continue
        current = merged.get(item_id)
        if current is None or str(item.get("updatedAt", "")) >= str(current.get("updatedAt", "")):
            merged[item_id] = item
    return sorted(merged.values(), key=lambda item: str(item.get("updatedAt", "")), reverse=True)


def upsert_saved_query(query: dict[str, Any], path: Path | None = None) -> dict[str, Any]:
    query_id = str(query.get("id", ""))
    if not query_id:
        raise ValueError("Saved query must have a non-empty id")
    if path is None and database_enabled():
        upsert_json_array_item("saved_queries", query)
        return query

    store_path = path or saved_queries_path()
    with _store_lock:
        existing = _load_queries_file_unlocked(store_path) if store_path.exists() else []
        updated = [query, *(item for item in existing if str(item.get("id")) != query_id)]
        _save_queries_file_unlocked(store_path, updated)
    return query


def delete_saved_query(query_id: str, path: Path | None = None) -> None:
    if path is None and database_enabled():
        delete_json_array_item("saved_queries", query_id)
        return

    store_path = path or saved_queries_path()
    with _store_lock:
        existing = _load_queries_file_unlocked(store_path) if store_path.exists() else []
        updated = [item for item in existing if str(item.get("id")) != query_id]
        _save_queries_file_unlocked(store_path, updated)


def _load_queries_file_unlocked(store_path: Path) -> list[dict[str, Any]]:
    try:
        value = json.loads(store_path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise ValueError(f"Could not read saved queries: {exc}") from exc
    if not isinstance(value, list):
        raise ValueError("Saved query store must contain a JSON array")
    return [item for item in value if isinstance(item, dict)]


def _save_queries_file_unlocked(store_path: Path, queries: list[dict[str, Any]]) -> None:
    store_path.parent.mkdir(parents=True, exist_ok=True)
    serialized = json.dumps(queries, indent=2, ensure_ascii=False)
    temporary_path: Path | None = None
    try:
        with NamedTemporaryFile(
            mode="w", encoding="utf-8", dir=store_path.parent,
            prefix=f".{store_path.name}.", suffix=".tmp", delete=False,
        ) as temporary_file:
            temporary_file.write(serialized)
            temporary_file.write("\n")
            temporary_path = Path(temporary_file.name)
        temporary_path.replace(store_path)
    finally:
        if temporary_path is not None:
            temporary_path.unlink(missing_ok=True)
