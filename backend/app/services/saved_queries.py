from __future__ import annotations

import json
import os
from pathlib import Path
from tempfile import NamedTemporaryFile
from threading import Lock
from typing import Any

from app.services.state_store import database_enabled, load_json_state, save_json_state


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
