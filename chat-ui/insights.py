"""Saving an operator insight: the dispatch behind POST /api/insight.

Each insight category in topology.yaml names a target. A category that
requires review is queued in insight_reviews for an engineer; otherwise the
insight goes straight to its target: an Observation in the knowledge graph,
a line in the specialist's memory file, or the audit log.

Moved out of backend.py's route (gh-29), where a failed memory-mcp write
still answered {"status": "ok"}, and `specialist`/`session_id` were only
assigned inside one branch.
"""

from __future__ import annotations

import sqlite3
import uuid
from collections.abc import Awaitable, Callable
from contextlib import closing
from datetime import datetime, timezone

import audit


class SaveFailed(Exception):
    """The insight was not stored; the message says why."""


async def save(
    *,
    node_id: str,
    category: dict,
    note: str,
    specialist: str | None,
    call_tool: Callable[[str, dict], Awaitable[str]],
    db_path: str,
) -> dict:
    target = category["target"]
    label = category["label"]

    if category.get("requires_review", False):
        review_id = str(uuid.uuid4())
        try:
            # insight_reviews is created by audit-mcp at its startup.
            with closing(sqlite3.connect(db_path)) as conn, conn:
                conn.execute(
                    """INSERT INTO insight_reviews
                       (id, node_id, category_id, category_label, target, note, created_at)
                       VALUES (?, ?, ?, ?, ?, ?, ?)""",
                    (
                        review_id,
                        node_id,
                        category["id"],
                        label,
                        target,
                        note or None,
                        datetime.now(timezone.utc).isoformat(),
                    ),
                )
        except sqlite3.Error as exc:
            raise SaveFailed(f"could not queue the review: {exc}") from exc
        return {"status": "queued", "review_id": review_id}

    if target == "graph_observation":
        await _call(
            call_tool,
            "memory__record_observation",
            {
                "session_id": str(uuid.uuid4()),
                "equipment_id": node_id,
                "text": note or f"Operator insight: {label}",
                "confidence": 1.0,
                "specialist": specialist or "operator",
            },
        )
    elif target == "specialist_memory":
        await _call(
            call_tool,
            "memory__append_specialist_memory",
            {
                "specialist": specialist or node_id,
                "content": note or f"Operator insight ({label}) on {node_id}",
            },
        )
    else:
        audit.log(
            "insight_saved",
            node_id=node_id,
            category_id=category["id"],
            category_label=label,
            target=target,
            note=note or None,
        )
    return {"status": "ok"}


async def _call(call_tool, name: str, args: dict) -> None:
    # call_mcp_tool reports every failure as text starting with "Error".
    result = await call_tool(name, args)
    if result.startswith("Error"):
        raise SaveFailed(result)
