from __future__ import annotations

import os
from typing import Any

import psycopg
from psycopg.types.json import Jsonb


STATE_TABLE = "private.ossys_api_hub_state"


def database_enabled() -> bool:
    return bool(os.getenv("DATABASE_URL", "").strip())


def _connection() -> psycopg.Connection[Any]:
    database_url = os.getenv("DATABASE_URL", "").strip()
    if not database_url:
        raise RuntimeError("DATABASE_URL is not configured")
    return psycopg.connect(
        database_url,
        autocommit=True,
        connect_timeout=10,
        prepare_threshold=None,
    )


def load_json_state(key: str) -> Any | None:
    try:
        with _connection() as connection:
            row = connection.execute(
                f"SELECT value FROM {STATE_TABLE} WHERE key = %s",
                (key,),
            ).fetchone()
    except psycopg.Error as exc:
        raise ValueError(f"Could not read persisted application state: {exc}") from exc
    return None if row is None else row[0]


def save_json_state(key: str, value: Any) -> Any:
    try:
        with _connection() as connection:
            connection.execute(
                f"""
                INSERT INTO {STATE_TABLE} (key, value, updated_at)
                VALUES (%s, %s, now())
                ON CONFLICT (key) DO UPDATE
                SET value = EXCLUDED.value, updated_at = now()
                """,
                (key, Jsonb(value)),
            )
    except psycopg.Error as exc:
        raise OSError(f"Could not persist application state: {exc}") from exc
    return value
