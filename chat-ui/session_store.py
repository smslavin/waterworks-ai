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
                mode          TEXT
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
                outcome      TEXT    DEFAULT 'pending'
            );
        """)
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
                   (ts, session_id, user_question, equipment, diagnosis, status, confidence, mode)
                   VALUES (?, ?, ?, ?, ?, ?, ?, ?)""",
                (
                    datetime.now(timezone.utc).isoformat(),
                    session_id,
                    (user_question or "")[:500],
                    ",".join(equipment),
                    (diagnosis or "")[:2000],
                    status,
                    confidence,
                    mode,
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
                    operator_id, decision, outcome)
                   VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)""",
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
                ),
            )
            c.commit()
    except Exception as exc:
        logger.warning("action_event write failed: %s", exc)


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
            f"SELECT * FROM session_summaries {where} ORDER BY id DESC LIMIT ?",
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
