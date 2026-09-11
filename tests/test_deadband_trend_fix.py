"""Regression tests for the Deadband trend-calculation bug (design review,
2026-09-11): `deadband.py` used to compute trend slope by regex-scraping
numbers out of `influxdb-mcp`'s LLM-facing prose (`query` tool + its
`_format_tables()` formatter). For a query result of N records that prose
embeds N + 6*N extra numbers per record (record count once, then every
component of each ISO timestamp: year, month, day, hour, minute,
second.microsecond) ahead of/around the one real value per record. The
regex `\\b\\d+(?:\\.\\d+)?\\b` had no way to tell those apart from real
process values, so `_linear_slope()` was fed a vector dominated by
timestamp jitter rather than the actual signal — and that slope feeds
`_get_trend_direction`'s direction/confidence, which `check_confidence_threshold`
uses to decide ESCALATE vs SUPPRESS for real plant anomalies.

The fix adds `influxdb-mcp`'s `query_series` tool: a structured JSON read
path (`{"points": [{"t": ..., "v": ...}, ...]}`) that `deadband.py` now
parses directly via `json.loads(...)["points"]`, instead of regexing
`query`'s prose. This file proves three things end to end, using the real
production code on both sides (not hand-rolled stand-ins):

  1. `query_series` returns exactly the structured points a fake InfluxDB
     client produces (baseline correctness of the new tool).
  2. The *old* regex-based extraction, run against `_format_tables()`'s real
     prose output for a clean, known-linear signal, produces a polluted
     value vector and a slope that does NOT match the real signal — i.e.
     this fixture genuinely exercises the bug, not just a happy path.
  3. The *new* path — `deadband._get_trend_direction` calling the real
     `query_series` tool function via a monkeypatched `call_mcp_tool` —
     recovers the correct slope/direction for the same underlying data.

`verify_sustained`'s parallel fix (JSON point-counting instead of
`_extract_count` regex-scraping the first integer out of prose) is covered
too, since it went through the same `query_series` switch.
"""

import asyncio
import datetime
import importlib.util
import json
import re
import sys
from pathlib import Path

import pytest

root = Path(__file__).parent.parent

# influxdb-mcp/server.py is not on the pytest-collected `chat-ui`/`simulator`
# sys.path, and every MCP server in this repo is named server.py — a bare
# `import server` would collide with the other servers' own module-under-the-
# same-name imports elsewhere in the suite. Same fix test_m10_diagnose_plant.py
# already uses for enterprise/diagnose_plant_mcp/server.py.
_spec = importlib.util.spec_from_file_location(
    "_influxdb_mcp_server", root / "influxdb-mcp" / "server.py"
)
try:
    influxdb_server = importlib.util.module_from_spec(_spec)
    _spec.loader.exec_module(influxdb_server)
except Exception as exc:  # pragma: no cover - depends on local/CI env setup
    # influxdb-mcp/ has its own requirements.txt/venv (influxdb_client, mcp)
    # that CI's `pytest tests/` job does not install (see .github/workflows/
    # test.yml, which only installs topology-builder/chat-ui/simulator/
    # audit-mcp requirements). Skip cleanly rather than failing the whole
    # collection when those deps aren't present in this interpreter.
    pytest.skip(
        f"influxdb-mcp dependencies not importable in this environment: {exc}",
        allow_module_level=True,
    )

# conftest.py already does sys.path.insert(0, root / "chat-ui") for every test.
import deadband  # noqa: E402

# ── Fixture: a clean, known-linear "wtp_process" series ─────────────────────
#
# 7 samples, 5 minutes apart, value increasing by exactly 2.0 each step.
# _linear_slope() is index-based (x = 0..n-1), so the true slope of this
# series is exactly 2.0 regardless of the actual timestamp spacing.

_TRUE_VALUES = [100.0, 102.0, 104.0, 106.0, 108.0, 110.0, 112.0]
_TRUE_SLOPE = 2.0
_START = datetime.datetime(2026, 9, 10, 14, 30, 0, tzinfo=datetime.timezone.utc)


class _FakeRecord:
    """Duck-types influxdb_client's FluxRecord just enough for both
    `_format_tables()` (the old LLM-prose formatter) and `query_series`
    (the new structured-JSON tool) to work against it identically."""

    def __init__(self, t, value):
        self._t = t
        self._value = value
        self.values = {
            "_time": t,
            "_measurement": "wtp_process",
            "_field": "value",
            "_value": value,
            "instance": "RawWater_01",
            "attribute": "Flow",
            "type": "Pump",
        }

    def get_time(self):
        return self._t

    def get_measurement(self):
        return "wtp_process"

    def get_field(self):
        return "value"

    def get_value(self):
        return self._value


class _FakeTable:
    def __init__(self, records):
        self.records = records


class _FakeQueryApi:
    def __init__(self, tables):
        self._tables = tables

    def query(self, flux_query, org=None):
        return self._tables


class _FakeClient:
    def __init__(self, tables):
        self._tables = tables

    def query_api(self):
        return _FakeQueryApi(self._tables)


def _make_tables(values, start=_START, step_minutes=5):
    records = [
        _FakeRecord(start + datetime.timedelta(minutes=step_minutes * i), v)
        for i, v in enumerate(values)
    ]
    return [_FakeTable(records)]


def _old_extract_values(r) -> list[float]:
    """The pre-fix extraction logic from chat-ui/deadband.py, reproduced here
    only to prove the bug this test guards against — not imported from
    production, since the fix deletes it."""
    return [float(x) for x in re.findall(r"\b\d+(?:\.\d+)?\b", str(r))]


def _old_extract_count(r) -> int:
    """The pre-fix `_extract_count` logic, reproduced for the same reason."""
    m = re.search(r"\b(\d+)\b", str(r))
    return int(m.group(1)) if m else 0


# ── 1. query_series baseline correctness ─────────────────────────────────


def test_query_series_returns_structured_points(monkeypatch):
    tables = _make_tables(_TRUE_VALUES)
    monkeypatch.setattr(influxdb_server, "_get_client", lambda: _FakeClient(tables))

    raw = influxdb_server.query_series(
        measurement="wtp_process",
        instance="RawWater_01",
        attribute="Flow",
        start="-30m",
    )
    parsed = json.loads(raw)
    assert "error" not in parsed
    points = parsed["points"]
    assert len(points) == len(_TRUE_VALUES)
    assert [p["v"] for p in points] == _TRUE_VALUES
    # Timestamps round-trip as ISO-8601 strings, one per point, in order.
    assert all(isinstance(p["t"], str) for p in points)
    assert [p["t"] for p in points] == sorted(p["t"] for p in points)


def test_query_series_reports_error_without_raising(monkeypatch):
    def _boom():
        raise RuntimeError("influxdb unreachable")

    monkeypatch.setattr(influxdb_server, "_get_client", _boom)
    raw = influxdb_server.query_series(
        measurement="wtp_process", instance="x", attribute="y", start="-1m"
    )
    parsed = json.loads(raw)
    assert parsed["points"] == []
    assert "influxdb unreachable" in parsed["error"]


# ── 2. Old prose-regex path: proves the bug is real, not hypothetical ──────


def test_old_regex_extraction_is_polluted_by_timestamp_components():
    tables = _make_tables(_TRUE_VALUES)
    prose = influxdb_server._format_tables(tables)

    # Sanity: this really is the LLM-facing prose format described in the
    # bug report (record count first, ISO-formatted time= fields).
    assert prose.startswith(f"{len(_TRUE_VALUES)} record(s):")
    assert "time=2026-09-10T14:30:00" in prose

    old_values = _old_extract_values(prose)

    # The regex pulls out WAY more numbers than there are real values: the
    # leading record count, plus ~6 timestamp components per record (year,
    # month, day, hour, minute, second.microsecond).
    assert len(old_values) > len(_TRUE_VALUES) * 5

    old_slope = deadband._linear_slope(old_values)

    # This is the actual bug: the slope computed over the polluted vector
    # does not reflect the real, clean +2.0/step signal at all.
    assert old_slope != pytest.approx(_TRUE_SLOPE, abs=0.1)


def test_old_extract_count_first_match_is_record_count_but_fragile():
    """_extract_count "worked" only by the accident that record count is
    always the first integer in the prose — demonstrated here, not asserted
    as reliable, since the fix removes the dependency on this ordering
    entirely."""
    tables = _make_tables(_TRUE_VALUES)
    prose = influxdb_server._format_tables(tables)
    assert _old_extract_count(prose) == len(_TRUE_VALUES)


# ── 3. New JSON path: the real query_series tool, called the way ──────────
#    deadband.py now calls it, recovers the true signal.


def test_get_trend_direction_uses_query_series_and_recovers_true_slope(monkeypatch):
    tables = _make_tables(_TRUE_VALUES)
    monkeypatch.setattr(influxdb_server, "_get_client", lambda: _FakeClient(tables))

    async def _fake_call_mcp_tool(name, args, aggregator_url=None):
        assert name == "influxdb__query_series"
        # Exercises the real production query_series() implementation, not
        # a hand-rolled stand-in — only the transport (aggregator SSE call)
        # is faked, matching this repo's existing "call MCP tool functions
        # directly" testing convention (see tests/conftest.py).
        return influxdb_server.query_series(**args)

    monkeypatch.setattr(deadband, "call_mcp_tool", _fake_call_mcp_tool)

    result = asyncio.run(
        deadband._get_trend_direction(
            instance_id="RawWater_01",
            attribute="Flow",
            time_window_minutes=30,
            aggregator_url="http://fake-aggregator",
        )
    )

    assert "error" not in result
    assert result["slope"] == pytest.approx(_TRUE_SLOPE, abs=1e-6)
    assert result["direction"] == "improving"  # slope > 0.5 threshold
    assert result["confidence"] == pytest.approx(0.35)


def test_get_trend_direction_worsening_signal(monkeypatch):
    declining = list(reversed(_TRUE_VALUES))  # -2.0/step
    tables = _make_tables(declining)
    monkeypatch.setattr(influxdb_server, "_get_client", lambda: _FakeClient(tables))

    async def _fake_call_mcp_tool(name, args, aggregator_url=None):
        return influxdb_server.query_series(**args)

    monkeypatch.setattr(deadband, "call_mcp_tool", _fake_call_mcp_tool)

    result = asyncio.run(
        deadband._get_trend_direction(
            instance_id="RawWater_01",
            attribute="Flow",
            time_window_minutes=30,
            aggregator_url="http://fake-aggregator",
        )
    )
    assert result["slope"] == pytest.approx(-_TRUE_SLOPE, abs=1e-6)
    assert result["direction"] == "worsening"
    assert result["confidence"] == pytest.approx(0.95)


def test_verify_sustained_uses_query_series_and_counts_points_directly(monkeypatch):
    # normal_hi=105: values > 105 are violations -> 106, 108, 110, 112 = 4/7
    tables = _make_tables(_TRUE_VALUES)
    monkeypatch.setattr(influxdb_server, "_get_client", lambda: _FakeClient(tables))

    async def _fake_call_mcp_tool(name, args, aggregator_url=None):
        assert name == "influxdb__query_series"
        return influxdb_server.query_series(**args)

    monkeypatch.setattr(deadband, "call_mcp_tool", _fake_call_mcp_tool)

    result = asyncio.run(
        deadband._verify_sustained(
            instance_id="RawWater_01",
            attribute="Flow",
            condition="above_max",
            duration_minutes=5,
            normal_lo=90,
            normal_hi=105,
            aggregator_url="http://fake-aggregator",
        )
    )
    assert result["sample_count"] == 7
    assert result["fraction_in_violation"] == pytest.approx(4 / 7, abs=0.01)
    assert result["sustained"] is True
