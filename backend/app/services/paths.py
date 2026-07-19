from __future__ import annotations

from typing import Any


_MISSING = object()


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
        if value is None:
            continue
        if isinstance(value, dict):
            records.append(value)
        else:
            records.append({"value": value})
    return records
