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


def _cols(db_path):
    conn = sqlite3.connect(db_path)
    return [row[1] for row in conn.execute("PRAGMA table_info(action_events)")]


def _propose(action_id="a1"):
    session_store.log_action_proposed(
        action_id=action_id,
        session_id="s1",
        action_type="setpoint_adjustment",
        target="Chlorine_01",
        value="2.8",
        description="Reduce chlorine dose",
    )


# ── operator_id and auth_method (gh-82, spec Part I/III) ─────────────────────


def test_a_pending_row_names_no_one(store):
    _propose()
    row = _row(store, "a1")
    assert (row["operator_id"], row["auth_method"]) == (None, None)


def test_the_decision_records_who_decided(store):
    _propose()
    session_store.log_action_decision(
        action_id="a1",
        decision="approved",
        operator_id="shared-token",
        auth_method="shared_credential",
    )
    row = _row(store, "a1")
    assert (row["decision"], row["operator_id"], row["auth_method"]) == (
        "approved",
        "shared-token",
        "shared_credential",
    )


@pytest.mark.parametrize(
    "operator_id,auth_method",
    [
        ("operator_01", "password"),  # not an auth method the spec knows
        ("trust-mode:supervised", "shared_credential"),  # claims trust mode
        ("", "shared_credential"),  # names no one
    ],
)
def test_a_dishonest_approver_is_refused_before_writing(
    store, operator_id, auth_method
):
    _propose()
    with pytest.raises(ValueError):
        session_store.log_action_decision(
            action_id="a1",
            decision="approved",
            operator_id=operator_id,
            auth_method=auth_method,
        )
    assert _row(store, "a1")["decision"] == "pending"


def test_fresh_db_has_nullable_operator_columns(store):
    conn = sqlite3.connect(store)
    info = {r[1]: r for r in conn.execute("PRAGMA table_info(action_events)")}
    for col in ("operator_id", "auth_method"):
        _, _, _, notnull, default, _ = info[col]
        assert (notnull, default) == (0, None)


def test_placeholder_operator_column_is_replaced_in_a_pre_existing_db(
    tmp_path, monkeypatch
):
    """A metrics.db from before the first fix has operator_id TEXT NOT NULL
    DEFAULT 'operator_01', a placeholder person on every row. _init_db()
    drops that column, fake values and all, and adds the honest one."""
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
        INSERT INTO action_events (ts, session_id, decision)
            VALUES ('2026-01-01', 's0', 'approved');
    """)
    conn.commit()
    conn.close()

    monkeypatch.setattr(session_store, "_DB_PATH", db_path)
    monkeypatch.setattr(session_store, "_SITE_ID", "wtp")
    session_store._init_db()

    assert {"operator_id", "auth_method", "action_id"} <= set(_cols(db_path))
    (old,) = session_store.get_action_events()
    assert old["operator_id"] is None  # the fake 'operator_01' is gone


def test_recorded_operators_survive_a_restart(store):
    _propose()
    session_store.log_action_decision(
        action_id="a1",
        decision="denied",
        operator_id="local-console",
        auth_method="shared_credential",
    )
    session_store._init_db()
    assert _row(store, "a1")["operator_id"] == "local-console"


def test_column_migrations_are_idempotent(store):
    session_store._init_db()
    session_store._init_db()
    cols = _cols(store)
    for col in ("action_id", "operator_id", "auth_method"):
        assert cols.count(col) == 1
