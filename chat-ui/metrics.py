"""AI_Metrics writer — logs per-turn telemetry to InfluxDB (for Grafana)
and a local SQLite store (for the /metrics display page)."""

import logging
import os
import sqlite3
import threading
from datetime import datetime, timezone

from dotenv import load_dotenv
from influxdb_client import InfluxDBClient, Point
from influxdb_client.client.write_api import SYNCHRONOUS

load_dotenv()

INFLUXDB_URL    = os.environ.get("INFLUXDB_URL",    "http://localhost:8086")
INFLUXDB_TOKEN  = os.environ.get("INFLUXDB_TOKEN",  "")
INFLUXDB_ORG    = os.environ.get("INFLUXDB_ORG",    "waterworks")
INFLUXDB_BUCKET = os.environ.get("INFLUXDB_BUCKET", "waterworks")

logger = logging.getLogger(__name__)

_influx_client: InfluxDBClient | None = None
_DB_PATH = os.path.join(os.path.dirname(__file__), "metrics.db")
_lock = threading.Lock()


def _get_influx_client() -> InfluxDBClient:
    global _influx_client
    if _influx_client is None:
        _influx_client = InfluxDBClient(
            url=INFLUXDB_URL, token=INFLUXDB_TOKEN, org=INFLUXDB_ORG
        )
    return _influx_client


def _conn() -> sqlite3.Connection:
    c = sqlite3.connect(_DB_PATH)
    c.row_factory = sqlite3.Row
    return c


def _init_db() -> None:
    with _lock, _conn() as c:
        c.execute("""
            CREATE TABLE IF NOT EXISTS turns (
                id               INTEGER PRIMARY KEY AUTOINCREMENT,
                ts               TEXT    NOT NULL,
                session_id       TEXT    NOT NULL,
                model            TEXT    NOT NULL,
                input_tokens     INTEGER,
                output_tokens    INTEGER,
                tool_call_count  INTEGER NOT NULL DEFAULT 0,
                error_count      INTEGER NOT NULL DEFAULT 0,
                latency_ms       INTEGER,
                context_pressure REAL,
                user_message     TEXT
            )
        """)
        try:
            c.execute("ALTER TABLE turns ADD COLUMN context_pressure REAL")
        except Exception:
            pass  # column already exists on existing databases
        c.commit()


def log_turn(
    *,
    session_id: str,
    model: str,
    input_tokens: int | None,
    output_tokens: int | None,
    tool_call_count: int,
    error_count: int,
    latency_ms: int,
    context_pressure: float | None,
    user_message: str,
) -> None:
    # Write to InfluxDB — best-effort, for Grafana dashboards
    try:
        point = (
            Point("ai_metrics")
            .tag("model", model)
            .tag("session_id", session_id)
            .field("input_tokens",    int(input_tokens  or 0))
            .field("output_tokens",   int(output_tokens or 0))
            .field("tool_call_count", int(tool_call_count))
            .field("error_count",     int(error_count))
            .field("latency_ms",      int(latency_ms))
            .field("context_pressure", float(context_pressure or 0.0))
            .field("user_message",    (user_message or "")[:200])
        )
        _get_influx_client().write_api(write_options=SYNCHRONOUS).write(
            bucket=INFLUXDB_BUCKET, record=point
        )
    except Exception as exc:
        logger.warning("InfluxDB metrics write failed: %s", exc)

    # Write to SQLite — for the /metrics display page
    try:
        with _lock, _conn() as c:
            c.execute(
                """INSERT INTO turns
                   (ts, session_id, model, input_tokens, output_tokens,
                    tool_call_count, error_count, latency_ms, context_pressure, user_message)
                   VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
                (
                    datetime.now(timezone.utc).isoformat(),
                    session_id, model,
                    input_tokens, output_tokens,
                    tool_call_count, error_count, latency_ms,
                    context_pressure,
                    (user_message or "")[:200],
                ),
            )
            c.commit()
    except Exception as exc:
        logger.warning("SQLite metrics write failed: %s", exc)


def get_recent_turns(limit: int = 100) -> list[dict]:
    with _lock, _conn() as c:
        rows = c.execute(
            "SELECT * FROM turns ORDER BY id DESC LIMIT ?", (limit,)
        ).fetchall()
        return [dict(r) for r in rows]


def get_summary() -> dict:
    with _lock, _conn() as c:
        row = c.execute("""
            SELECT
                COUNT(*)                   AS total_turns,
                COUNT(DISTINCT session_id) AS total_sessions,
                SUM(input_tokens)          AS total_input_tokens,
                SUM(output_tokens)         AS total_output_tokens,
                SUM(tool_call_count)       AS total_tool_calls,
                SUM(error_count)           AS total_errors,
                ROUND(AVG(latency_ms))     AS avg_latency_ms
            FROM turns
        """).fetchone()
        return dict(row) if row else {}


_init_db()
