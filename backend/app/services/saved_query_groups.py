from __future__ import annotations

import json
import os
from pathlib import Path
from tempfile import NamedTemporaryFile
from threading import Lock


_store_lock = Lock()


def saved_query_groups_path() -> Path:
    configured_path = os.getenv("SAVED_QUERY_GROUPS_PATH")
    if configured_path:
        return Path(configured_path).expanduser().resolve()
    return Path(__file__).resolve().parents[2] / "data" / "saved_query_groups.json"


def normalize_groups(groups: list[str]) -> list[str]:
    normalized: list[str] = []
    seen: set[str] = set()
    for group in groups:
        name = group.strip()
        key = name.casefold()
        if name and key not in seen:
            seen.add(key)
            normalized.append(name)
    return normalized


def load_saved_query_groups(path: Path | None = None) -> list[str]:
    store_path = path or saved_query_groups_path()
    if path is None and not store_path.exists():
        example_path = store_path.with_name("saved_query_groups.example.json")
        if example_path.exists():
            store_path = example_path
    with _store_lock:
        if not store_path.exists():
            return []
        try:
            value = json.loads(store_path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError) as exc:
            raise ValueError(f"Could not read saved query groups: {exc}") from exc
    if not isinstance(value, list) or not all(isinstance(item, str) for item in value):
        raise ValueError("Saved query group store must contain a JSON string array")
    return normalize_groups(value)


def save_saved_query_groups(groups: list[str], path: Path | None = None) -> list[str]:
    store_path = path or saved_query_groups_path()
    store_path.parent.mkdir(parents=True, exist_ok=True)
    normalized = normalize_groups(groups)
    serialized = json.dumps(normalized, indent=2, ensure_ascii=False)

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
    return normalized
