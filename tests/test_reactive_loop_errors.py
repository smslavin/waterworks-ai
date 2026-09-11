"""Regression tests for gh-18: reactive_loop.py silently swallowed exceptions
around action_proposed/action_decision broadcasting, and fire-and-forget
_handle_anomaly tasks had no strong reference (CPython's documented
weak-reference GC caveat could drop one mid-execution with nothing logged).

Policy under test:
  - _collect_text narrows its except to json.JSONDecodeError for the parse;
    a broadcast_fn failure is logged via logger.exception, not swallowed.
  - action_proposed broadcast to zero subscribers logs a warning (the
    operator approval dialog silently never appearing is otherwise
    invisible).
  - _run's fire-and-forget tasks are held in a module-level set and any
    exception raised inside one is logged via a done-callback.
"""

import asyncio
import json
import logging

import reactive_loop


def _agen(lines):
    async def gen():
        for line in lines:
            yield line

    return gen()


# ── _collect_text: malformed JSON is expected/recoverable ──────────────────


def test_collect_text_skips_malformed_json_but_keeps_collecting(caplog):
    lines = [
        "not json",
        json.dumps({"type": "text", "text": "hello "}),
        json.dumps({"type": "text", "text": "world"}),
    ]
    with caplog.at_level(logging.WARNING, logger="reactive_loop"):
        result = asyncio.run(reactive_loop._collect_text(_agen(lines)))
    assert result == "hello world"
    assert any(
        "could not parse cascade event line" in r.message for r in caplog.records
    )


# ── _collect_text: a broadcast_fn failure must never be silently swallowed ─


def test_collect_text_logs_exception_when_broadcast_fn_raises(caplog):
    lines = [json.dumps({"type": "action_proposed", "instance_id": "Pump_01"})]

    def bad_broadcast(evt):
        raise RuntimeError("subscriber removed mid-iteration")

    with caplog.at_level(logging.ERROR, logger="reactive_loop"):
        result = asyncio.run(reactive_loop._collect_text(_agen(lines), bad_broadcast))
    assert result == ""
    records = [r for r in caplog.records if r.levelno >= logging.ERROR]
    assert any("broadcast_fn raised" in r.message for r in records)
    assert any(r.exc_info for r in records)  # logger.exception, not just .error


def test_collect_text_does_not_raise_when_broadcast_fn_raises():
    """A broadcast failure must not blow up the whole cascade collection —
    the highest-consequence outcome (silently dropping the rest of the
    diagnosis) would be worse than logging and continuing."""
    lines = [
        json.dumps({"type": "action_proposed", "instance_id": "Pump_01"}),
        json.dumps({"type": "text", "text": "diagnosis continues"}),
    ]

    def bad_broadcast(evt):
        raise RuntimeError("boom")

    result = asyncio.run(reactive_loop._collect_text(_agen(lines), bad_broadcast))
    assert result == "diagnosis continues"


# ── action_proposed to zero subscribers: must be observable in logs ────────


def test_collect_text_warns_when_action_proposed_has_zero_subscribers(caplog):
    lines = [
        json.dumps(
            {"type": "action_proposed", "instance_id": "Pump_01", "attribute": "flow"}
        )
    ]

    def broadcast_zero_subs(evt):
        return 0

    with caplog.at_level(logging.WARNING, logger="reactive_loop"):
        asyncio.run(reactive_loop._collect_text(_agen(lines), broadcast_zero_subs))
    assert any(
        "zero subscribers" in r.message and r.levelno == logging.WARNING
        for r in caplog.records
    )


def test_collect_text_no_warning_when_subscribers_present(caplog):
    lines = [json.dumps({"type": "action_proposed", "instance_id": "Pump_01"})]

    def broadcast_one_sub(evt):
        return 1

    with caplog.at_level(logging.WARNING, logger="reactive_loop"):
        asyncio.run(reactive_loop._collect_text(_agen(lines), broadcast_one_sub))
    assert not any("zero subscribers" in r.message for r in caplog.records)


def test_collect_text_action_decision_zero_subs_does_not_warn():
    """Only action_proposed (the approval-dialog trigger) is the
    highest-consequence case called out for this warning — action_decision
    with zero subscribers isn't the same failure mode (nobody's waiting on
    a decision echo)."""
    lines = [json.dumps({"type": "action_decision", "instance_id": "Pump_01"})]

    def broadcast_zero(evt):
        return 0

    # Should not raise and should not require a warning assertion — this
    # just documents the intentionally narrower scope of the warning.
    asyncio.run(reactive_loop._collect_text(_agen(lines), broadcast_zero))


# ── fire-and-forget _handle_anomaly tasks: strong ref + logged exception ───


class _FakeMonitor:
    def __init__(self, anomalies):
        self._anomalies = anomalies

    async def events(self):
        for a in self._anomalies:
            yield a


def test_run_retains_strong_reference_to_bg_task_and_logs_its_exception(
    monkeypatch, caplog
):
    reactive_loop._active.clear()
    reactive_loop._cooldown_until.clear()
    reactive_loop._bg_tasks.clear()

    started = asyncio.Event()

    async def failing_handle_anomaly(anomaly, aggregator_url, model, broadcast_fn):
        started.set()
        raise RuntimeError("crash inside handler")

    monkeypatch.setattr(reactive_loop, "_handle_anomaly", failing_handle_anomaly)

    async def body():
        monitor = _FakeMonitor([{"instance_id": "TestPump_99"}])
        await reactive_loop._run(monitor, "http://agg", "model", lambda e: 0)
        # _run's async-for has completed (FakeMonitor.events() is finite);
        # the spawned task is created but may not have run yet — it should
        # still be tracked.
        assert len(reactive_loop._bg_tasks) == 1
        await started.wait()
        # let the event loop run the task to completion and fire the
        # done-callback
        await asyncio.sleep(0.05)

    with caplog.at_level(logging.ERROR, logger="reactive_loop"):
        asyncio.run(body())

    # Cleaned up after completion — no leaked strong reference.
    assert len(reactive_loop._bg_tasks) == 0
    assert any(
        "_handle_anomaly task crashed" in r.message and r.exc_info
        for r in caplog.records
    )


def test_run_bg_task_cleanup_on_success(monkeypatch):
    reactive_loop._active.clear()
    reactive_loop._cooldown_until.clear()
    reactive_loop._bg_tasks.clear()

    finished = asyncio.Event()

    async def ok_handle_anomaly(anomaly, aggregator_url, model, broadcast_fn):
        finished.set()

    monkeypatch.setattr(reactive_loop, "_handle_anomaly", ok_handle_anomaly)

    async def body():
        monitor = _FakeMonitor([{"instance_id": "TestPump_98"}])
        await reactive_loop._run(monitor, "http://agg", "model", lambda e: 0)
        await finished.wait()
        await asyncio.sleep(0.02)

    asyncio.run(body())
    assert len(reactive_loop._bg_tasks) == 0
