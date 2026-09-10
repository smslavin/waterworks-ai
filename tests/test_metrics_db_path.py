"""Tests for metrics.py's SQLite DB path resolution.

Regression coverage for a live bug: metrics.py resolved its DB path as
dirname(__file__)/metrics.db, ignoring METRICS_DB_PATH — unlike its sibling
session_store.py, which respects the env var. In an M10 multi-plant
deployment this meant a second plant's checkout kept writing the `turns`
table to the first plant's database while session_store.py's tables moved
correctly, so /metrics and /audit silently read two different databases.
"""

import importlib
import sqlite3

import pytest


@pytest.fixture()
def reload_metrics(monkeypatch):
    """Reload metrics.py after tweaking env vars so its module-level
    _DB_PATH is recomputed, then restore the original module afterward so
    later tests importing `metrics` don't see a stale reloaded state."""
    import metrics as metrics_module

    def _reload():
        return importlib.reload(metrics_module)

    yield _reload

    # Restore to the un-overridden default for any other test in the suite.
    monkeypatch.delenv("METRICS_DB_PATH", raising=False)
    importlib.reload(metrics_module)


def test_respects_metrics_db_path_env_var(tmp_path, monkeypatch, reload_metrics):
    scratch_db = str(tmp_path / "scratch_metrics.db")
    monkeypatch.setenv("METRICS_DB_PATH", scratch_db)

    metrics = reload_metrics()

    assert metrics._DB_PATH == scratch_db


def test_falls_back_to_local_default_when_unset(monkeypatch, reload_metrics):
    monkeypatch.delenv("METRICS_DB_PATH", raising=False)

    metrics = reload_metrics()

    assert metrics._DB_PATH.endswith("metrics.db")
    # Falls back to the module-local default, not an arbitrary path.
    import os

    expected = os.path.join(os.path.dirname(metrics.__file__), "metrics.db")
    assert metrics._DB_PATH == expected


def test_log_turn_actually_opens_db_at_env_var_path(tmp_path, monkeypatch, reload_metrics):
    """End-to-end: with METRICS_DB_PATH set, a real log_turn() call must
    create/write the `turns` table at that path, not the hardcoded default."""
    scratch_db = tmp_path / "plant2_metrics.db"
    monkeypatch.setenv("METRICS_DB_PATH", str(scratch_db))

    metrics = reload_metrics()
    metrics._init_db()
    metrics.log_turn(
        session_id="s1",
        model="claude-haiku",
        input_tokens=10,
        output_tokens=5,
        tool_call_count=1,
        error_count=0,
        latency_ms=123,
        context_pressure=0.1,
        user_message="test",
    )

    assert scratch_db.exists()
    conn = sqlite3.connect(str(scratch_db))
    rows = conn.execute("SELECT session_id, model FROM turns").fetchall()
    conn.close()
    assert rows == [("s1", "claude-haiku")]
