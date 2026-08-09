"""Tests for M10 Phase 1: per-plant site_id tagging in session_store.py."""

import sqlite3

import pytest

import session_store


@pytest.fixture()
def store(tmp_path, monkeypatch):
    """Isolated metrics.db, freshly initialized (site_id column present from the start)."""
    db_path = str(tmp_path / "metrics.db")
    monkeypatch.setattr(session_store, "_DB_PATH", db_path)
    monkeypatch.setattr(session_store, "_SITE_ID", "wtp")
    session_store._init_db()
    return db_path


def test_fresh_db_has_site_id_column_with_default(store):
    conn = sqlite3.connect(store)
    cols = {row[1] for row in conn.execute("PRAGMA table_info(session_summaries)")}
    assert "site_id" in cols
    cols = {row[1] for row in conn.execute("PRAGMA table_info(action_events)")}
    assert "site_id" in cols


def test_log_session_summary_tags_current_site_id(store):
    session_store.log_session_summary(
        session_id="s1",
        user_question="why is RawWater_01 low flow?",
        equipment=["RawWater_01"],
        diagnosis="suction starvation",
        status="Fault Detected",
        confidence=0.7,
    )
    summary = session_store.get_session_summary("s1")
    assert summary["site_id"] == "wtp"


def test_log_action_event_tags_current_site_id(store):
    session_store.log_action_event(
        session_id="s1",
        action_type="setpoint_adjustment",
        target="Chlorine_01",
        value="2.8",
        description="Reduce chlorine dose",
        decision="approved",
    )
    events = session_store.get_action_events(session_id="s1")
    assert len(events) == 1
    assert events[0]["site_id"] == "wtp"


def test_second_plant_site_id_is_independent(store, monkeypatch):
    monkeypatch.setattr(session_store, "_SITE_ID", "wtp2")
    session_store.log_session_summary(
        session_id="s2",
        user_question="q",
        equipment=[],
        diagnosis="normal",
        status="Normal",
        confidence=0.8,
    )
    summary = session_store.get_session_summary("s2")
    assert summary["site_id"] == "wtp2"


def test_alter_table_migrates_pre_existing_db_without_site_id(tmp_path, monkeypatch):
    """A metrics.db created before this column existed must gain it (defaulted to
    'wtp') via ALTER TABLE, not silently keep missing it — CREATE TABLE IF NOT
    EXISTS alone would never touch an already-existing table."""
    db_path = str(tmp_path / "metrics.db")
    conn = sqlite3.connect(db_path)
    conn.executescript("""
        CREATE TABLE session_summaries (
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
    conn.execute(
        """INSERT INTO session_summaries
           (ts, session_id, user_question, equipment, diagnosis, status, confidence, mode)
           VALUES ('2026-01-01T00:00:00Z', 'pre-existing', '', '', '', 'Normal', 0.8, 'single')"""
    )
    conn.commit()
    conn.close()

    monkeypatch.setattr(session_store, "_DB_PATH", db_path)
    monkeypatch.setattr(session_store, "_SITE_ID", "wtp")
    session_store._init_db()

    summary = session_store.get_session_summary("pre-existing")
    assert summary["site_id"] == "wtp"


def test_add_column_if_missing_is_idempotent(store):
    """Calling _init_db() again (e.g. on every process restart) must not error
    on a column that's already there."""
    session_store._init_db()
    session_store._init_db()
    conn = sqlite3.connect(store)
    cols = [row[1] for row in conn.execute("PRAGMA table_info(session_summaries)")]
    assert cols.count("site_id") == 1
