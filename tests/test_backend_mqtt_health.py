"""Regression tests for gh-21: chat-ui/backend.py's startup mqtt__connect
check inferred success from `not result.startswith("Error calling")`, which
only matches mcp_client.call_mcp_tool's client-side-exception wording — a
tool-level failure from the Rust adapter (e.g. "Error: connection refused")
didn't match and was logged as a successful connect. Also covers the
fire-and-forget task strong-reference fix and the new /api/health field
surfacing adapter connection state.
"""

import asyncio
import json
import logging

import backend
import mcp_client

# ── _connect_mqtt_adapter: must detect a tool-level failure, not just a
#    client-side exception ──────────────────────────────────────────────────


def test_connect_mqtt_adapter_detects_tool_level_error_and_exhausts_retries(
    monkeypatch,
):
    calls = []

    async def fake_call_mcp_tool(name, args, url):
        calls.append((name, args))
        # Tool-level failure per MCP's isError convention, normalized by
        # mcp_client.call_mcp_tool to start with "Error" — but NOT with the
        # narrower "Error calling" that only a client-side exception uses.
        return "Error: connection refused"

    async def no_sleep(_):
        return None

    monkeypatch.setattr(mcp_client, "call_mcp_tool", fake_call_mcp_tool)
    monkeypatch.setattr(backend.asyncio, "sleep", no_sleep)
    monkeypatch.setattr(backend, "_mqtt_adapter_connected", False)

    asyncio.run(backend._connect_mqtt_adapter())

    assert len(calls) == 5  # bounded retry exhausted
    assert backend._mqtt_adapter_connected is False


def test_connect_mqtt_adapter_succeeds_on_non_error_result(monkeypatch):
    calls = []

    async def fake_call_mcp_tool(name, args, url):
        calls.append((name, args))
        return "Connected to broker"

    monkeypatch.setattr(mcp_client, "call_mcp_tool", fake_call_mcp_tool)
    monkeypatch.setattr(backend, "_mqtt_adapter_connected", False)

    asyncio.run(backend._connect_mqtt_adapter())

    assert len(calls) == 1  # succeeded on first attempt, no retry needed
    assert backend._mqtt_adapter_connected is True


def test_connect_mqtt_adapter_would_have_false_positived_on_old_narrow_check(
    monkeypatch,
):
    """Documents the exact gh-21 bug: the old check `not result.startswith(
    "Error calling")` is True for a tool-level failure string — a false
    "succeeded" — while the fixed check `not result.startswith("Error")`
    correctly reports failure for the same string."""
    tool_level_failure = "Error: connection refused"
    assert not tool_level_failure.startswith(
        "Error calling"
    )  # old check: false positive
    assert tool_level_failure.startswith("Error")  # fixed check: correctly caught


# ── periodic health-check loop reconnects when mqtt__scan reports failure ──


def test_mqtt_health_check_loop_reconnects_on_unhealthy_scan(monkeypatch):
    scan_calls = []
    connect_calls = []

    async def fake_call_mcp_tool(name, args, url):
        if name == "mqtt__scan":
            scan_calls.append(1)
            return "Error: not connected"
        raise AssertionError(f"unexpected tool call {name}")

    async def fake_connect():
        connect_calls.append(1)
        backend._mqtt_adapter_connected = True

    sleep_calls = []

    async def fake_sleep(secs):
        sleep_calls.append(secs)
        if len(sleep_calls) >= 2:
            raise asyncio.CancelledError()  # stop the infinite loop after 2 ticks

    monkeypatch.setattr(mcp_client, "call_mcp_tool", fake_call_mcp_tool)
    monkeypatch.setattr(backend, "_connect_mqtt_adapter", fake_connect)
    monkeypatch.setattr(backend.asyncio, "sleep", fake_sleep)
    monkeypatch.setattr(backend, "_mqtt_adapter_connected", True)

    try:
        asyncio.run(backend._mqtt_health_check_loop())
    except asyncio.CancelledError:
        pass

    assert len(scan_calls) >= 1
    assert len(connect_calls) >= 1  # reconnect was attempted


def test_mqtt_health_check_loop_leaves_healthy_state_alone(monkeypatch):
    connect_calls = []

    async def fake_call_mcp_tool(name, args, url):
        return "entries: []"  # healthy, no "Error" prefix

    async def fake_connect():
        connect_calls.append(1)

    sleep_calls = []

    async def fake_sleep(secs):
        sleep_calls.append(secs)
        if len(sleep_calls) >= 2:
            raise asyncio.CancelledError()  # let one iteration run, then stop

    monkeypatch.setattr(mcp_client, "call_mcp_tool", fake_call_mcp_tool)
    monkeypatch.setattr(backend, "_connect_mqtt_adapter", fake_connect)
    monkeypatch.setattr(backend.asyncio, "sleep", fake_sleep)
    monkeypatch.setattr(backend, "_mqtt_adapter_connected", False)

    try:
        asyncio.run(backend._mqtt_health_check_loop())
    except asyncio.CancelledError:
        pass

    assert connect_calls == []  # healthy — no reconnect attempted
    assert backend._mqtt_adapter_connected is True


# ── fire-and-forget background tasks: strong ref + logged exception ────────


def test_spawn_tracked_retains_reference_while_running_and_cleans_up(caplog):
    backend._bg_tasks.clear()
    started = asyncio.Event()

    async def crash():
        started.set()
        await asyncio.sleep(0)
        raise RuntimeError("boom inside background task")

    async def body():
        task = backend._spawn_tracked(crash(), task_name="test_crash_task")
        assert task in backend._bg_tasks
        await started.wait()
        await asyncio.sleep(0.05)
        return task

    with caplog.at_level(logging.ERROR, logger="backend"):
        task = asyncio.run(body())

    assert task not in backend._bg_tasks
    assert any("crashed" in r.message and r.exc_info for r in caplog.records)


def test_spawn_tracked_cleans_up_on_success():
    backend._bg_tasks.clear()
    done = asyncio.Event()

    async def ok():
        done.set()

    async def body():
        task = backend._spawn_tracked(ok(), task_name="test_ok_task")
        assert task in backend._bg_tasks
        await done.wait()
        await asyncio.sleep(0.02)

    asyncio.run(body())
    assert len(backend._bg_tasks) == 0


# ── /api/health surfaces mqtt adapter connection state, additively ─────────


def test_health_endpoint_reports_mqtt_adapter_ok(monkeypatch):
    monkeypatch.setattr(backend, "_mqtt_adapter_connected", True)
    resp = asyncio.run(backend.health_endpoint(None))
    body = json.loads(resp.body)
    assert body["mqtt_adapter"] == "ok"
    # existing keys still present — additive, not restructured
    assert "aggregator" in body
    assert "mqtt" in body


def test_health_endpoint_reports_mqtt_adapter_error(monkeypatch):
    monkeypatch.setattr(backend, "_mqtt_adapter_connected", False)
    resp = asyncio.run(backend.health_endpoint(None))
    body = json.loads(resp.body)
    assert body["mqtt_adapter"] == "error"
