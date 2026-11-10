import json
from app.db import db


def get_value(key: str, default=None):
    with db() as conn:
        row = conn.execute("SELECT value FROM kv_store WHERE key = ?", (key,)).fetchone()
    return json.loads(row["value"]) if row else default


def set_value(key: str, value) -> None:
    with db() as conn:
        conn.execute(
            "INSERT INTO kv_store(key, value, updated_at) VALUES(?, ?, CURRENT_TIMESTAMP) "
            "ON CONFLICT(key) DO UPDATE SET value=excluded.value, updated_at=CURRENT_TIMESTAMP",
            (key, json.dumps(value, separators=(",", ":"))),
        )
