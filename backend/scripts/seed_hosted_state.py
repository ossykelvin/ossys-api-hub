from __future__ import annotations

import json
import re
import sys
from pathlib import Path
from typing import Any


BACKEND_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(BACKEND_ROOT))

from app.services.api_documentation import redact  # noqa: E402
from app.services.state_store import save_json_state  # noqa: E402


_sensitive_key = re.compile(
    r"password|secret|authorization|access[_-]?token|refresh[_-]?token",
    re.I,
)
_safe_placeholders = {"", "REPLACE_LOCALLY", "[redacted]"}


def _read_json(name: str) -> Any:
    return json.loads((BACKEND_ROOT / "data" / name).read_text(encoding="utf-8"))


def _assert_sanitized(value: Any, path: str = "root") -> None:
    if isinstance(value, dict):
        for key, item in value.items():
            item_path = f"{path}.{key}"
            if (
                _sensitive_key.search(str(key))
                and isinstance(item, str)
                and item.strip() not in _safe_placeholders
            ):
                raise ValueError(f"Refusing to seed a credential at {item_path}")
            _assert_sanitized(item, item_path)
        return
    if isinstance(value, list):
        for index, item in enumerate(value):
            _assert_sanitized(item, f"{path}[{index}]")
        return
    if isinstance(value, str):
        try:
            embedded = json.loads(value)
        except (json.JSONDecodeError, TypeError):
            return
        _assert_sanitized(embedded, f"{path}<json>")


def main() -> None:
    queries = _read_json("saved_queries.example.json")
    groups = _read_json("saved_query_groups.example.json")
    documentation_path = BACKEND_ROOT / "data" / "api_documentation.json"
    documentation = (
        redact(json.loads(documentation_path.read_text(encoding="utf-8")))
        if documentation_path.exists()
        else {}
    )

    _assert_sanitized(queries)
    _assert_sanitized(documentation)
    save_json_state("saved_queries", queries)
    save_json_state("saved_query_groups", groups)
    save_json_state("api_documentation", documentation)
    print(
        f"Seeded {len(queries)} queries, {len(groups)} groups, "
        f"and {len(documentation)} documentation records."
    )


if __name__ == "__main__":
    main()
