from __future__ import annotations

import json
from typing import Any


_MISSING = object()


def decode_json_container(value: Any) -> Any:
    """Decode a JSON object or array that an API returned inside a string."""
    if not isinstance(value, str):
        return value
    stripped = value.strip()
    if not stripped or stripped[0] not in "[{":
        return value
    try:
        decoded = json.loads(stripped)
    except (TypeError, ValueError):
        return value
    return decoded if isinstance(decoded, (dict, list)) else value


def get_path(data: Any, path: str | None, default: Any = None) -> Any:
    """Resolve a dotted path across dictionaries and list indices."""
    if path is None or path.strip() == "":
        return data

    current = data
    for raw_part in path.split("."):
        part = raw_part.strip()
        if not part:
            continue
        if isinstance(current, dict):
            current = current.get(part, _MISSING)
        elif isinstance(current, list) and part.isdigit():
            index = int(part)
            current = current[index] if 0 <= index < len(current) else _MISSING
        else:
            current = _MISSING

        if current is _MISSING:
            return default
    return current


def normalize_records(items: Any, record_path: str | None = None) -> list[dict[str, Any]]:
    items = decode_json_container(items)
    if items is None:
        return []
    if isinstance(items, dict):
        iterable = [items]
    elif isinstance(items, list):
        iterable = items
    else:
        return [{"value": items}]

    records: list[dict[str, Any]] = []
    for item in iterable:
        value = get_path(item, record_path) if record_path else item
        value = decode_json_container(value)
        if value is None:
            continue
        if isinstance(value, dict):
            records.append(value)
        elif isinstance(value, list):
            records.extend(normalize_records(value))
        else:
            records.append({"value": value})
    return records
