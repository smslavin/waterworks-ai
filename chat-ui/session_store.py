"""Session summary and action event storage for the compliance audit trail.

Both tables live in metrics.db alongside the existing turns table so all
persistent state stays in one place.
"""

import logging
import os
import re
import sqlite3
import threading
from datetime import datetime, timedelta, timezone

_DB_PATH = os.environ.get(
    "METRICS_DB_PATH",
    os.path.join(os.path.dirname(__file__), "metrics.db"),
)
# Each plant is a fully independent process group (see M10 Phase 0) — site_id is
# sourced from this env var at write time, not read from topology.yaml, so it
# stays correct even if topology.yaml is swapped without restarting the process.
_SITE_ID = os.environ.get("SITE_ID", "wtp")
_lock = threading.Lock()
logger = logging.getLogger(__name__)

_EQUIP_RE = re.compile(
    r"\b(RawWater_\d+|HighService_\d+|Clarifier_\d+|FinishedWater_\d+"
    r"|Chlorine_\d+|Fluoride_\d+|UV_\d+)\b"
)


# ── Equipment extraction ───────────────────────────────────────────────────────


def extract_equipment(tool_calls: list[tuple[str, dict]]) -> list[str]:
    """Scan tool call args for equipment instance IDs (e.g. RawWater_01)."""
    found: set[str] = set()
    for _name, args in tool_calls:
        for v in args.values():
            if isinstance(v, str):
                found.update(_EQUIP_RE.findall(v))
    return sorted(found)


def extract_status_single(text: str) -> tuple[str, float | None]:
    """Heuristic status/confidence extraction from a free-form response."""
    t = text.lower()
    if any(
        w in t
        for w in (
            "fault detected",
            "fault condition",
            "run-status fault",
            "cavitation",
            "suction starvation",
            "pressure drift",
        )
    ):
        return "Fault Detected", 0.7
    if any(
        w in t
        for w in (
            "anomaly",
            "abnormal",
            "irregular",
            "out of range",
            "concern",
            "elevated",
            "below threshold",
        )
    ):
        return "Anomaly Detected", 0.6
    return "Normal", 0.8


# ── DB helpers ─────────────────────────────────────────────────────────────────


def _conn() -> sqlite3.Connection:
    c = sqlite3.connect(_DB_PATH)
    c.row_factory = sqlite3.Row
    return c


def _add_column_if_missing(
    c: sqlite3.Connection, table: str, column: str, ddl: str
) -> None:
    """CREATE TABLE IF NOT EXISTS doesn't retroactively add columns to a table
    that already exists from before this column was introduced — ALTER TABLE
    is the only way to migrate a pre-existing metrics.db in place."""
    cols = {
        row["name"] for row in c.execute(f"PRAGMA table_info({table})")
    }  # nosec B608
    if column not in cols:
        c.execute(f"ALTER TABLE {table} ADD COLUMN {ddl}")  # nosec B608


def _init_db() -> None:
    with _lock, _conn() as c:
        c.executescript("""
            CREATE TABLE IF NOT EXISTS session_summaries (
                id            INTEGER PRIMARY KEY AUTOINCREMENT,
                ts            TEXT    NOT NULL,
                session_id    TEXT    NOT NULL UNIQUE,
                user_question TEXT,
                equipment     TEXT,
                diagnosis     TEXT,
                status        TEXT,
                confidence    REAL,
                mode          TEXT,
                site_id       TEXT    NOT NULL DEFAULT 'wtp'
            );
            CREATE TABLE IF NOT EXISTS action_events (
                id           INTEGER PRIMARY KEY AUTOINCREMENT,
                ts           TEXT    NOT NULL,
                session_id   TEXT    NOT NULL,
                action_type  TEXT,
                target       TEXT,
                value        TEXT,
                description  TEXT,
                operator_id  TEXT    NOT NULL DEFAULT 'operator_01',
                decision     TEXT,
                outcome      TEXT    DEFAULT 'pending',
                site_id      TEXT    NOT NULL DEFAULT 'wtp'
            );
            CREATE TABLE IF NOT EXISTS plant_status (
                site_id              TEXT PRIMARY KEY,
                status_level         TEXT,
                level_updated_at     TEXT,
                narrative            TEXT,
                narrative_updated_at TEXT
            );
        """)
        _add_column_if_missing(
            c, "session_summaries", "site_id", "site_id TEXT NOT NULL DEFAULT 'wtp'"
        )
        _add_column_if_missing(
            c, "action_events", "site_id", "site_id TEXT NOT NULL DEFAULT 'wtp'"
        )
        c.commit()


# ── Write functions ────────────────────────────────────────────────────────────


def log_session_summary(
    *,
    session_id: str,
    user_question: str,
    equipment: list[str],
    diagnosis: str,
    status: str,
    confidence: float | None,
    mode: str = "single",
) -> None:
    try:
        with _lock, _conn() as c:
            c.execute(
                """INSERT OR REPLACE INTO session_summaries
                   (ts, session_id, user_question, equipment, diagnosis, status, confidence, mode, site_id)
                   VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)""",
                (
                    datetime.now(timezone.utc).isoformat(),
                    session_id,
                    (user_question or "")[:500],
                    ",".join(equipment),
                    (diagnosis or "")[:2000],
                    status,
                    confidence,
                    mode,
                    _SITE_ID,
                ),
            )
            c.commit()
    except Exception as exc:
        logger.warning("session_summary write failed: %s", exc)


def log_action_event(
    *,
    session_id: str,
    action_type: str,
    target: str,
    value: str,
    description: str,
    decision: str,
    outcome: str = "pending",
    operator_id: str = "operator_01",
) -> None:
    try:
        with _lock, _conn() as c:
            c.execute(
                """INSERT INTO action_events
                   (ts, session_id, action_type, target, value, description,
                    operator_id, decision, outcome, site_id)
                   VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
                (
                    datetime.now(timezone.utc).isoformat(),
                    session_id,
                    action_type,
                    target,
                    value,
                    description,
                    operator_id,
                    decision,
                    outcome,
                    _SITE_ID,
                ),
            )
            c.commit()
    except Exception as exc:
        logger.warning("action_event write failed: %s", exc)


# ── Plant status (status_heartbeat.py's persisted rollup) ─────────────────────


def upsert_plant_status(*, status_level: str, narrative: str) -> None:
    """status_level and narrative always move together — status_heartbeat.py
    only calls this when a real check (full diagnosis) just ran, never on a
    tick that skipped checking. Deliberately not split into a
    faster-moving "level" update and a slower "narrative" update: monitor.py
    only tracks numeric threshold excursions, not discrete equipment state
    (offline/running flags), so a level derived from it alone can say
    Normal while a full diagnosis's narrative says Fault Detected — an
    earlier version of this function had exactly that split and produced
    that mismatch. status_level here is always extracted from the same
    narrative it's stored with, so the two can never disagree."""
    try:
        with _lock, _conn() as c:
            now = datetime.now(timezone.utc).isoformat()
            c.execute(
                """INSERT INTO plant_status
                   (site_id, status_level, level_updated_at, narrative, narrative_updated_at)
                   VALUES (?, ?, ?, ?, ?)
                   ON CONFLICT(site_id) DO UPDATE SET
                     status_level = excluded.status_level,
                     level_updated_at = excluded.level_updated_at,
                     narrative = excluded.narrative,
                     narrative_updated_at = excluded.narrative_updated_at""",
                (_SITE_ID, status_level, now, narrative, now),
            )
            c.commit()
    except Exception as exc:
        logger.warning("plant_status write failed: %s", exc)


def get_plant_status() -> dict | None:
    with _lock, _conn() as c:
        row = c.execute(
            "SELECT * FROM plant_status WHERE site_id = ?", (_SITE_ID,)
        ).fetchone()
        return dict(row) if row else None


# ── Read functions (used by audit page + audit-mcp) ───────────────────────────


def get_session_summaries(
    limit: int = 50,
    status_filter: str | None = None,
    hours_back: int | None = None,
) -> list[dict]:
    with _lock, _conn() as c:
        clauses, params = [], []
        if status_filter:
            clauses.append("status LIKE ?")
            params.append(f"%{status_filter}%")
        if hours_back is not None:
            cutoff = (
                datetime.now(timezone.utc) - timedelta(hours=hours_back)
            ).isoformat()
            clauses.append("ts >= ?")
            params.append(cutoff)
        where = ("WHERE " + " AND ".join(clauses)) if clauses else ""
        params.append(limit)
        rows = c.execute(
            f"SELECT * FROM session_summaries {where} ORDER BY id DESC LIMIT ?",  # nosec B608
            params,
        ).fetchall()
        return [dict(r) for r in rows]


def get_session_summary(session_id: str) -> dict | None:
    with _lock, _conn() as c:
        row = c.execute(
            "SELECT * FROM session_summaries WHERE session_id = ?", (session_id,)
        ).fetchone()
        return dict(row) if row else None


def get_summaries_by_equipment(equipment: str, hours_back: int = 24) -> list[dict]:
    cutoff = (datetime.now(timezone.utc) - timedelta(hours=hours_back)).isoformat()
    with _lock, _conn() as c:
        rows = c.execute(
            """SELECT * FROM session_summaries
               WHERE equipment LIKE ? AND ts >= ?
               ORDER BY id DESC""",
            (f"%{equipment}%", cutoff),
        ).fetchall()
        return [dict(r) for r in rows]


def get_action_events(session_id: str | None = None, limit: int = 50) -> list[dict]:
    with _lock, _conn() as c:
        if session_id:
            rows = c.execute(
                """SELECT * FROM action_events
                   WHERE session_id = ? ORDER BY id DESC LIMIT ?""",
                (session_id, limit),
            ).fetchall()
        else:
            rows = c.execute(
                "SELECT * FROM action_events ORDER BY id DESC LIMIT ?", (limit,)
            ).fetchall()
        return [dict(r) for r in rows]


def get_history(start: str, end: str, equipment: str | None = None) -> list[dict]:
    """Return session summaries + their action events in causal order (for narrative)."""
    with _lock, _conn() as c:
        if equipment:
            summaries = c.execute(
                """SELECT * FROM session_summaries
                   WHERE ts BETWEEN ? AND ? AND equipment LIKE ?
                   ORDER BY ts ASC""",
                (start, end, f"%{equipment}%"),
            ).fetchall()
        else:
            summaries = c.execute(
                "SELECT * FROM session_summaries WHERE ts BETWEEN ? AND ? ORDER BY ts ASC",
                (start, end),
            ).fetchall()
        result = []
        for row in summaries:
            s = dict(row)
            actions = c.execute(
                "SELECT * FROM action_events WHERE session_id = ? ORDER BY ts ASC",
                (s["session_id"],),
            ).fetchall()
            s["actions"] = [dict(a) for a in actions]
            result.append(s)
        return result


_init_db()
