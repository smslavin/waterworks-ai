"""POST /api/insight (gh-29): each category's target, and failures reported.

Before: the dispatch lived in the route, a failed memory-mcp write still
answered {"status": "ok"}, and a missing insight_reviews table (created by
audit-mcp at its startup) surfaced as an unhandled 500.
"""

import asyncio
import json
import sqlite3

import pytest

import audit
import backend

CATEGORIES = {
    "fault_pattern": {
        "id": "fault_pattern",
        "label": "Fault pattern",
        "target": "graph_observation",
    },
    "maintenance_flag": {
        "id": "maintenance_flag",
        "label": "Maintenance flag",
        "target": "work_item",
        "requires_review": True,
    },
    "false_positive": {
        "id": "false_positive",
        "label": "False positive",
        "target": "confidence_feedback",
    },
    "operator_note": {
        "id": "operator_note",
        "label": "Operator note",
        "target": "specialist_memory",
    },
}

REVIEWS_DDL = """CREATE TABLE insight_reviews (
    id TEXT PRIMARY KEY, node_id TEXT NOT NULL, category_id TEXT NOT NULL,
    category_label TEXT NOT NULL, target TEXT NOT NULL, note TEXT,
    created_at TEXT NOT NULL, resolved_at TEXT, resolution TEXT, resolver_note TEXT)"""


class _Request:
    def __init__(self, body):
        self._body = body

    async def json(self):
        return self._body


@pytest.fixture()
def env(monkeypatch, tmp_path):
    db = tmp_path / "metrics.db"
    with sqlite3.connect(db) as conn:
        conn.execute(REVIEWS_DDL)
    monkeypatch.setattr(backend, "_METRICS_DB", str(db))
    monkeypatch.setattr(
        backend,
        "_topology_extensions",
        {"insight_categories": list(CATEGORIES.values())},
    )
    calls, reply, logged = [], {"text": "ok"}, []

    async def call(name, args, aggregator_url=None):
        calls.append((name, args))
        return reply["text"]

    monkeypatch.setattr(backend.mcp_client, "call_mcp_tool", call)
    monkeypatch.setattr(audit, "log", lambda event, **kw: logged.append((event, kw)))
    return {"db": db, "calls": calls, "reply": reply, "logged": logged}


def _post(category, node="RawWater_01", note="bearing noise"):
    resp = asyncio.run(
        backend.insight_save_endpoint(
            _Request({"nodeId": node, "categoryId": category, "note": note})
        )
    )
    return resp.status_code, json.loads(resp.body)


def test_graph_observation_records_with_the_nodes_specialist(env):
    status, body = _post("fault_pattern")
    assert (status, body) == (200, {"status": "ok"})
    name, args = env["calls"][0]
    assert name == "memory__record_observation"
    assert args["equipment_id"] == "RawWater_01"
    assert args["specialist"] == "Intake"
    assert args["text"] == "bearing noise"
    assert args["session_id"]


def test_specialist_memory_appends(env):
    status, _ = _post("operator_note")
    assert status == 200
    assert env["calls"][0] == (
        "memory__append_specialist_memory",
        {"specialist": "Intake", "content": "bearing noise"},
    )


def test_other_targets_go_to_the_audit_log(env):
    status, _ = _post("false_positive")
    assert status == 200 and env["calls"] == []
    event, fields = env["logged"][0]
    assert event == "insight_saved" and fields["target"] == "confidence_feedback"


def test_review_category_is_queued_not_dispatched(env):
    status, body = _post("maintenance_flag")
    assert status == 200 and body["status"] == "queued"
    assert env["calls"] == []
    with sqlite3.connect(env["db"]) as conn:
        row = conn.execute(
            "SELECT id, node_id, category_label, note FROM insight_reviews"
        ).fetchone()
    assert row == (
        body["review_id"],
        "RawWater_01",
        "Maintenance flag",
        "bearing noise",
    )


@pytest.mark.parametrize("category", ["fault_pattern", "operator_note"])
def test_failed_memory_write_is_reported_not_ok(env, category):
    env["reply"][
        "text"
    ] = "Error calling memory__record_observation: connection refused"
    status, body = _post(category)
    assert status == 502
    assert body["error"] == "insight not saved"
    assert "connection refused" in body["detail"]


def test_missing_review_table_is_reported_not_a_crash(env):
    with sqlite3.connect(env["db"]) as conn:
        conn.execute("DROP TABLE insight_reviews")
    status, body = _post("maintenance_flag")
    assert status == 502
    assert "no such table" in body["detail"]


def test_unknown_node_has_no_specialist(env):
    status, _ = _post("fault_pattern", node="Nowhere_99")
    assert status == 200
    assert env["calls"][0][1]["specialist"] == "operator"
