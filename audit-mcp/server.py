"""Audit MCP server — query session summaries and action events.

Reads from the same metrics.db that chat-ui writes to.

Tools
-----
list_incidents       Fault/anomaly sessions in a date or recent window
get_session_summary  Full detail (diagnosis + actions) for one session
query_by_equipment   Sessions touching a specific equipment unit
query_history        Narrative-ready correlated records for a time range

Environment variables
---------------------
METRICS_DB_PATH  Absolute path to metrics.db
                 (default: ../chat-ui/metrics.db relative to this file)
FASTMCP_PORT     Port to bind (default: 8004)
"""

import json
import logging
import logging.handlers
import os
import sqlite3
from datetime import datetime, timedelta, timezone

from dotenv import load_dotenv
from mcp.server.fastmcp import FastMCP

load_dotenv()

_log_dir = os.path.join(os.path.dirname(__file__), "logs")
os.makedirs(_log_dir, exist_ok=True)
_fh = logging.handlers.RotatingFileHandler(
    os.path.join(_log_dir, "audit_mcp.log"), maxBytes=5 * 1024 * 1024, backupCount=3
)
_fh.setFormatter(logging.Formatter("%(asctime)s %(levelname)s %(name)s: %(message)s",
                                   datefmt="%Y-%m-%d %H:%M:%S"))
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s %(levelname)s %(name)s: %(message)s",
    datefmt="%Y-%m-%d %H:%M:%S",
    handlers=[logging.StreamHandler(), _fh],
)
logger = logging.getLogger(__name__)

_DB_PATH = os.environ.get(
    "METRICS_DB_PATH",
    os.path.abspath(os.path.join(os.path.dirname(__file__), "..", "chat-ui", "metrics.db")),
)
mcp = FastMCP("audit-mcp", port=int(os.environ.get("FASTMCP_PORT", 8004)))


def _conn() -> sqlite3.Connection:
    c = sqlite3.connect(_DB_PATH)
    c.row_factory = sqlite3.Row
    return c


# ── Tools ──────────────────────────────────────────────────────────────────────

@mcp.tool()
def list_incidents(date: str = "", hours_back: int = 24) -> str:
    """List diagnostic sessions that detected faults or anomalies.

    Args:
        date:       ISO date prefix to filter (e.g. "2026-05-30"). Omit for recent window.
        hours_back: Hours of history to scan when date is omitted (default 24).
    """
    try:
        c = _conn()
        if date:
            rows = c.execute(
                """SELECT session_id, ts, user_question, equipment, status, confidence, mode
                   FROM session_summaries
                   WHERE ts LIKE ? AND status NOT LIKE '%Normal%'
                   ORDER BY ts ASC""",
                (f"{date}%",),
            ).fetchall()
        else:
            cutoff = (datetime.now(timezone.utc) - timedelta(hours=hours_back)).isoformat()
            rows = c.execute(
                """SELECT session_id, ts, user_question, equipment, status, confidence, mode
                   FROM session_summaries
                   WHERE ts >= ? AND status NOT LIKE '%Normal%'
                   ORDER BY ts ASC""",
                (cutoff,),
            ).fetchall()
        incidents = [dict(r) for r in rows]
        if not incidents:
            return json.dumps({
                "incidents": [],
                "message": "No faults or anomalies found in the requested period.",
            })
        return json.dumps({"incidents": incidents}, indent=2, default=str)
    except Exception as exc:
        return f"Error: {exc}"


@mcp.tool()
def get_session_summary(session_id: str) -> str:
    """Get the full diagnostic summary for a single session, including actions taken.

    Args:
        session_id: Session UUID from list_incidents or query_by_equipment.
    """
    try:
        c = _conn()
        row = c.execute(
            "SELECT * FROM session_summaries WHERE session_id = ?", (session_id,)
        ).fetchone()
        if not row:
            return json.dumps({"error": f"Session '{session_id}' not found."})
        summary = dict(row)
        actions = c.execute(
            "SELECT * FROM action_events WHERE session_id = ? ORDER BY ts ASC",
            (session_id,),
        ).fetchall()
        summary["actions"] = [dict(a) for a in actions]
        return json.dumps(summary, indent=2, default=str)
    except Exception as exc:
        return f"Error: {exc}"


@mcp.tool()
def query_by_equipment(equipment_id: str, hours_back: int = 24) -> str:
    """List all diagnostic sessions involving a specific equipment unit.

    Args:
        equipment_id: Equipment instance ID, e.g. "RawWater_01" or "Chlorine_01".
        hours_back:   Hours of history to scan (default 24).
    """
    try:
        c = _conn()
        cutoff = (datetime.now(timezone.utc) - timedelta(hours=hours_back)).isoformat()
        rows = c.execute(
            """SELECT session_id, ts, user_question, equipment, status, confidence, mode
               FROM session_summaries
               WHERE equipment LIKE ? AND ts >= ?
               ORDER BY ts DESC""",
            (f"%{equipment_id}%", cutoff),
        ).fetchall()
        results = [dict(r) for r in rows]
        if not results:
            return json.dumps({
                "equipment_id": equipment_id,
                "sessions": [],
                "message": f"No sessions found for {equipment_id} in the last {hours_back} hours.",
            })
        return json.dumps(
            {"equipment_id": equipment_id, "sessions": results},
            indent=2, default=str,
        )
    except Exception as exc:
        return f"Error: {exc}"


@mcp.tool()
def query_history(start: str, end: str, equipment: str = "") -> str:
    """Return narrative-ready session history for a time range.

    Each session record includes its correlated action events in causal order:
      fault_detected → diagnosis (+ confidence) → action_proposed → operator_decision → outcome

    Args:
        start:     ISO datetime string for range start (e.g. "2026-05-30T00:00:00Z")
        end:       ISO datetime string for range end   (e.g. "2026-05-30T23:59:59Z")
        equipment: Optional equipment ID to filter (e.g. "RawWater_01"); omit for all.
    """
    try:
        c = _conn()
        if equipment:
            summaries = c.execute(
                """SELECT * FROM session_summaries
                   WHERE ts BETWEEN ? AND ? AND equipment LIKE ?
                   ORDER BY ts ASC""",
                (start, end, f"%{equipment}%"),
            ).fetchall()
        else:
            summaries = c.execute(
                """SELECT * FROM session_summaries
                   WHERE ts BETWEEN ? AND ?
                   ORDER BY ts ASC""",
                (start, end),
            ).fetchall()

        records = []
        for row in summaries:
            s = dict(row)
            actions = c.execute(
                "SELECT * FROM action_events WHERE session_id = ? ORDER BY ts ASC",
                (s["session_id"],),
            ).fetchall()
            s["actions"] = [dict(a) for a in actions]
            records.append(s)

        if not records:
            return json.dumps({
                "range": {"start": start, "end": end},
                "equipment": equipment or "all",
                "sessions": [],
                "message": "No sessions found for the requested range.",
            })
        return json.dumps(
            {"range": {"start": start, "end": end}, "equipment": equipment or "all",
             "sessions": records},
            indent=2, default=str,
        )
    except Exception as exc:
        return f"Error: {exc}"


if __name__ == "__main__":
    mcp.run(transport="sse")
