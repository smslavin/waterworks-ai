"""Tests for audit-mcp insight review tools (Phase 13)."""
import json
import sqlite3
import sys
import uuid
from datetime import datetime, timedelta, timezone
from pathlib import Path

import pytest

root = Path(__file__).parent.parent
sys.path.insert(0, str(root / "audit-mcp"))

import server as audit_server  # noqa: E402


@pytest.fixture()
def review_db(tmp_path, monkeypatch):
    """Isolated metrics.db with insight_reviews table seeded."""
    db_path = str(tmp_path / "metrics.db")
    monkeypatch.setattr(audit_server, "_DB_PATH", db_path)
    audit_server._ensure_tables()
    return db_path


def _insert_review(db_path: str, **kwargs) -> str:
    review_id = str(uuid.uuid4())
    now = datetime.now(timezone.utc).isoformat()
    conn = sqlite3.connect(db_path)
    conn.execute(
        """INSERT INTO insight_reviews
           (id, node_id, category_id, category_label, target, note, created_at)
           VALUES (?, ?, ?, ?, ?, ?, ?)""",
        (
            kwargs.get("id", review_id),
            kwargs.get("node_id", "RawWater_01"),
            kwargs.get("category_id", "fault_pattern"),
            kwargs.get("category_label", "Fault pattern"),
            kwargs.get("target", "graph_observation"),
            kwargs.get("note"),
            kwargs.get("created_at", now),
        ),
    )
    conn.commit()
    conn.close()
    return kwargs.get("id", review_id)


# ── list_pending_reviews ───────────────────────────────────────────────────────


def test_list_pending_reviews_empty(review_db):
    result = json.loads(audit_server.list_pending_reviews())
    assert result["reviews"] == []
    assert "message" in result


def test_list_pending_reviews_returns_unresolved(review_db):
    rid = _insert_review(review_db)
    result = json.loads(audit_server.list_pending_reviews())
    ids = [r["id"] for r in result["reviews"]]
    assert rid in ids


def test_list_pending_reviews_excludes_resolved(review_db):
    rid = _insert_review(review_db)
    audit_server.resolve_review(rid, "approved")
    result = json.loads(audit_server.list_pending_reviews())
    ids = [r["id"] for r in result["reviews"]]
    assert rid not in ids


def test_list_pending_reviews_respects_hours_back(review_db):
    old_ts = (datetime.now(timezone.utc) - timedelta(hours=200)).isoformat()
    rid = _insert_review(review_db, created_at=old_ts)
    result = json.loads(audit_server.list_pending_reviews(hours_back=168))
    ids = [r["id"] for r in result["reviews"]]
    assert rid not in ids


def test_list_pending_reviews_fields(review_db):
    _insert_review(review_db, node_id="Clarifier_01", category_id="maintenance_flag")
    result = json.loads(audit_server.list_pending_reviews())
    row = result["reviews"][0]
    assert {"id", "node_id", "category_id", "category_label", "target", "created_at"}.issubset(row.keys())


# ── resolve_review ─────────────────────────────────────────────────────────────


def test_resolve_review_approved(review_db):
    rid = _insert_review(review_db)
    result = json.loads(audit_server.resolve_review(rid, "approved"))
    assert result["status"] == "ok"
    assert result["resolution"] == "approved"


def test_resolve_review_rejected(review_db):
    rid = _insert_review(review_db)
    result = json.loads(audit_server.resolve_review(rid, "rejected", "not a real fault"))
    assert result["status"] == "ok"


def test_resolve_review_deferred(review_db):
    rid = _insert_review(review_db)
    result = json.loads(audit_server.resolve_review(rid, "deferred"))
    assert result["status"] == "ok"


def test_resolve_review_invalid_resolution(review_db):
    rid = _insert_review(review_db)
    result = json.loads(audit_server.resolve_review(rid, "maybe"))
    assert "error" in result


def test_resolve_review_not_found(review_db):
    result = json.loads(audit_server.resolve_review("nonexistent-id", "approved"))
    assert "error" in result


def test_resolve_review_idempotent(review_db):
    rid = _insert_review(review_db)
    audit_server.resolve_review(rid, "approved")
    result = json.loads(audit_server.resolve_review(rid, "rejected"))
    assert "error" in result


def test_resolve_review_sets_resolved_at(review_db):
    rid = _insert_review(review_db)
    audit_server.resolve_review(rid, "approved", "looks good")
    conn = sqlite3.connect(review_db)
    row = conn.execute(
        "SELECT resolved_at, resolution, resolver_note FROM insight_reviews WHERE id = ?",
        (rid,),
    ).fetchone()
    conn.close()
    assert row[0] is not None
    assert row[1] == "approved"
    assert row[2] == "looks good"
