"""Tests for the action_events proposal/decision/outcome parity fix
(chat-ui/session_store.py) — a proposed action now has a durable row from
the moment it's proposed, not only once a decision is made, and outcome
reflects what actually happened rather than always sitting on the caller's
optimistic default.
"""

import sqlite3

import pytest

import session_store


@pytest.fixture()
def store(tmp_path, monkeypatch):
    db_path = str(tmp_path / "metrics.db")
    monkeypatch.setattr(session_store, "_DB_PATH", db_path)
    monkeypatch.setattr(session_store, "_SITE_ID", "wtp")
    session_store._init_db()
    return db_path


def _row(store, action_id):
    events = session_store.get_action_events()
    return next(e for e in events if e["action_id"] == action_id)


def test_proposal_alone_creates_a_pending_row(store):
    session_store.log_action_proposed(
        action_id="a1",
        session_id="s1",
        action_type="setpoint_adjustment",
        target="Chlorine_01",
        value="2.8",
        description="Reduce chlorine dose",
    )
    row = _row(store, "a1")
    assert row["decision"] == "pending"
    assert row["outcome"] == "pending"


def test_approval_updates_decision_and_leaves_outcome_pending(store):
    session_store.log_action_proposed(
        action_id="a1",
        session_id="s1",
        action_type="setpoint_adjustment",
        target="Chlorine_01",
        value="2.8",
        description="",
    )
    session_store.log_action_decision(action_id="a1", decision="approved")
    row = _row(store, "a1")
    assert row["decision"] == "approved"
    assert row["outcome"] == "pending"


def test_denial_settles_outcome_as_not_executed(store):
    session_store.log_action_proposed(
        action_id="a1",
        session_id="s1",
        action_type="setpoint_adjustment",
        target="Chlorine_01",
        value="2.8",
        description="",
    )
    session_store.log_action_decision(action_id="a1", decision="denied")
    row = _row(store, "a1")
    assert row["decision"] == "denied"
    assert row["outcome"] == "not_executed"


def test_outcome_records_a_real_execution_result(store):
    session_store.log_action_proposed(
        action_id="a1",
        session_id="s1",
        action_type="setpoint_adjustment",
        target="Chlorine_01",
        value="2.8",
        description="",
    )
    session_store.log_action_decision(action_id="a1", decision="approved")
    session_store.log_action_outcome(action_id="a1", outcome="ok")
    row = _row(store, "a1")
    assert row["outcome"] == "ok"


def test_outcome_records_a_failure_message(store):
    session_store.log_action_proposed(
        action_id="a1",
        session_id="s1",
        action_type="setpoint_adjustment",
        target="Chlorine_01",
        value="2.8",
        description="",
    )
    session_store.log_action_decision(action_id="a1", decision="approved")
    session_store.log_action_outcome(
        action_id="a1", outcome="failed: simulator unreachable"
    )
    row = _row(store, "a1")
    assert row["outcome"] == "failed: simulator unreachable"


def test_recover_abandoned_actions_sweeps_rows_still_pending(store):
    session_store.log_action_proposed(
        action_id="a1",
        session_id="s1",
        action_type="setpoint_adjustment",
        target="Chlorine_01",
        value="2.8",
        description="",
    )
    # No decision ever arrives — simulates the process restarting while a
    # propose_action Future was still being awaited.
    recovered = session_store.recover_abandoned_actions()
    assert recovered == 1
    row = _row(store, "a1")
    assert row["decision"] == "abandoned_restart"
    assert row["outcome"] == "abandoned_restart"


def test_recover_abandoned_actions_leaves_resolved_rows_alone(store):
    session_store.log_action_proposed(
        action_id="a1",
        session_id="s1",
        action_type="setpoint_adjustment",
        target="Chlorine_01",
        value="2.8",
        description="",
    )
    session_store.log_action_decision(action_id="a1", decision="approved")
    session_store.log_action_outcome(action_id="a1", outcome="ok")

    recovered = session_store.recover_abandoned_actions()
    assert recovered == 0
    row = _row(store, "a1")
    assert row["decision"] == "approved"
    assert row["outcome"] == "ok"


def test_operator_id_column_is_gone_on_a_fresh_db(store):
    conn = sqlite3.connect(store)
    cols = {row[1] for row in conn.execute("PRAGMA table_info(action_events)")}
    assert "operator_id" not in cols


def test_operator_id_column_is_dropped_from_a_pre_existing_db(tmp_path, monkeypatch):
    """A metrics.db created before this fix has operator_id TEXT NOT NULL
    DEFAULT 'operator_01' — a hardcoded fake identity in a compliance table.
    _init_db() must drop it, not just stop writing to it (leaving the fake
    default silently applied to every future row would be worse than
    dropping the column outright)."""
    db_path = str(tmp_path / "metrics.db")
    conn = sqlite3.connect(db_path)
    conn.executescript("""
        CREATE TABLE action_events (
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
    conn.commit()
    conn.close()

    monkeypatch.setattr(session_store, "_DB_PATH", db_path)
    monkeypatch.setattr(session_store, "_SITE_ID", "wtp")
    session_store._init_db()

    conn = sqlite3.connect(db_path)
    cols = {row[1] for row in conn.execute("PRAGMA table_info(action_events)")}
    assert "operator_id" not in cols
    assert "action_id" in cols


def test_add_and_drop_column_migrations_are_idempotent(store):
    session_store._init_db()
    session_store._init_db()
    conn = sqlite3.connect(store)
    cols = [row[1] for row in conn.execute("PRAGMA table_info(action_events)")]
    assert cols.count("action_id") == 1
    assert "operator_id" not in cols
