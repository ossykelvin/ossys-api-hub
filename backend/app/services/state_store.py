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


def ping_database() -> None:
    """Open a database connection and execute a minimal read-only query."""
    try:
        with _connection() as connection:
            row = connection.execute("SELECT 1").fetchone()
    except psycopg.Error as exc:
        raise ConnectionError(f"Could not reach the application database: {exc}") from exc
    if row != (1,):
        raise RuntimeError("Application database heartbeat returned an unexpected result")


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


def upsert_json_array_item(key: str, item: dict[str, Any], id_field: str = "id") -> list[Any]:
    """Atomically replace one object in a JSON-array state value, or append it."""
    item_id = str(item.get(id_field, ""))
    if not item_id:
        raise ValueError(f"Persisted item must have a non-empty {id_field}")
    try:
        with _connection() as connection:
            row = connection.execute(
                f"""
                INSERT INTO {STATE_TABLE} AS state (key, value, updated_at)
                VALUES (%s, jsonb_build_array(%s::jsonb), now())
                ON CONFLICT (key) DO UPDATE
                SET value = (
                    COALESCE((
                        SELECT jsonb_agg(element)
                        FROM jsonb_array_elements(
                            CASE WHEN jsonb_typeof(state.value) = 'array'
                                THEN state.value ELSE '[]'::jsonb END
                        ) AS element
                        WHERE element ->> %s IS DISTINCT FROM %s
                    ), '[]'::jsonb) || EXCLUDED.value
                ), updated_at = now()
                RETURNING value
                """,
                (key, Jsonb(item), id_field, item_id),
            ).fetchone()
    except psycopg.Error as exc:
        raise OSError(f"Could not persist application state item: {exc}") from exc
    return list(row[0]) if row else []


def delete_json_array_item(key: str, item_id: str, id_field: str = "id") -> list[Any]:
    """Atomically remove one object from a JSON-array state value."""
    try:
        with _connection() as connection:
            row = connection.execute(
                f"""
                UPDATE {STATE_TABLE}
                SET value = COALESCE((
                    SELECT jsonb_agg(element)
                    FROM jsonb_array_elements(
                        CASE WHEN jsonb_typeof(value) = 'array'
                            THEN value ELSE '[]'::jsonb END
                    ) AS element
                    WHERE element ->> %s IS DISTINCT FROM %s
                ), '[]'::jsonb), updated_at = now()
                WHERE key = %s
                RETURNING value
                """,
                (id_field, item_id, key),
            ).fetchone()
    except psycopg.Error as exc:
        raise OSError(f"Could not delete persisted application state item: {exc}") from exc
    return list(row[0]) if row else []
