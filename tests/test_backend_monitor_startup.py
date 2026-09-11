"""Regression test: _ensure_monitor_started must not block chat-ui startup
on monitor.py's _populate_severities (LadybugDB severity lookups via
memory-mcp). Previously AnomalyMonitor.start() awaited it directly, so a
slow/unreachable memory-mcp stalled backend.py's lifespan — and therefore
serving any request at all — before the MQTT client ever connected.
_populate_severities is now spawned as a tracked background task (the same
_spawn_tracked/_bg_tasks pattern used for _connect_mqtt_adapter) instead of
being awaited inline.
"""

import asyncio

import backend
import monitor as monitor_mod


class _FakeMonitor:
    """Stand-in for monitor.AnomalyMonitor — no real MQTT connection."""

    def __init__(self, **kwargs):
        self.kwargs = kwargs
        self.started = False

    async def start(self):
        self.started = True


def test_ensure_monitor_started_does_not_await_populate_severities(monkeypatch):
    backend._monitor = None
    backend._bg_tasks.clear()

    monkeypatch.setattr(monitor_mod, "AnomalyMonitor", _FakeMonitor)

    severities_started = asyncio.Event()
    severities_may_finish = asyncio.Event()

    async def slow_populate_severities(aggregator_url):
        severities_started.set()
        await severities_may_finish.wait()

    monkeypatch.setattr(monitor_mod, "_populate_severities", slow_populate_severities)

    async def body():
        # If _ensure_monitor_started still awaited _populate_severities
        # internally, this would hang until severities_may_finish is set —
        # which never happens until *after* this call returns below. The
        # outer wait_for is a hard backstop so a real regression fails fast
        # instead of hanging the test suite.
        monitor = await asyncio.wait_for(backend._ensure_monitor_started(), timeout=2.0)
        assert isinstance(monitor, _FakeMonitor)
        assert monitor.started is True

        # The background task should have started (or be about to) — but
        # the fact _ensure_monitor_started already returned above is the
        # actual proof of non-blocking; this just also checks the fetch is
        # genuinely still in flight in the background rather than having
        # been skipped entirely.
        await asyncio.wait_for(severities_started.wait(), timeout=2.0)
        assert not severities_may_finish.is_set()

        severities_may_finish.set()
        await asyncio.sleep(0.05)
        return monitor

    result = asyncio.run(body())
    assert backend._monitor is result
    backend._monitor = None


def test_ensure_monitor_started_survives_populate_severities_failure(monkeypatch):
    """A crashing background severities fetch must not crash startup or
    leave the tracked-task set in a bad state — _spawn_tracked already logs
    and discards on failure (see test_backend_mqtt_health.py); this just
    confirms _ensure_monitor_started actually routes through that path."""
    backend._monitor = None
    backend._bg_tasks.clear()

    monkeypatch.setattr(monitor_mod, "AnomalyMonitor", _FakeMonitor)

    async def failing_populate_severities(aggregator_url):
        raise RuntimeError("memory-mcp unreachable")

    monkeypatch.setattr(
        monitor_mod, "_populate_severities", failing_populate_severities
    )

    async def body():
        monitor = await asyncio.wait_for(backend._ensure_monitor_started(), timeout=2.0)
        await asyncio.sleep(0.05)  # let the background task crash and clean up
        return monitor

    result = asyncio.run(body())
    assert isinstance(result, _FakeMonitor)
    assert result.started is True
    assert len(backend._bg_tasks) == 0  # crashed task was cleaned up, not leaked
    backend._monitor = None
