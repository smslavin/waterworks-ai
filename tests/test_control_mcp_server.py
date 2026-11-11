"""control-mcp/server.py through the real MCP stack (gh-13).

The tools are called over mcp's in-memory Client, so a test sees exactly
what the aggregator and chat-ui would: content text plus is_error. Only the
HTTP hop to the simulator is faked.

The case that matters: the simulator answers a rejected write (out of
engineering limits, unknown attribute) with a 4xx and a JSON body. Returned
as plain text, that body read as success, and the backend recorded the
approved action's outcome as 'ok' for a write that never happened.
"""

import asyncio
import importlib.util
from pathlib import Path

import httpx
import pytest

pytest.importorskip("mcp.client")
from mcp.client import Client  # noqa: E402

_SERVER = Path(__file__).parent.parent / "control-mcp" / "server.py"


@pytest.fixture()
def control_mcp(monkeypatch, tmp_path):
    # Several services have a top-level server.py; load this one by path so
    # it can't bind to whichever was imported first.
    spec = importlib.util.spec_from_file_location("control_mcp_server", _SERVER)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


class _Simulator:
    """Records each POST and answers with a canned httpx.Response."""

    def __init__(self, status=200, body=None, raises=None):
        self.status = status
        self.body = body if body is not None else {"ok": True}
        self.raises = raises
        self.posts = []

    def post(self, url, params=None, timeout=None):
        self.posts.append((url, params))
        if self.raises is not None:
            raise self.raises
        return httpx.Response(
            self.status, json=self.body, request=httpx.Request("POST", url)
        )


def _call(mod, tool, args):
    async def run():
        async with Client(mod.mcp) as client:
            return await client.call_tool(tool, args)

    return asyncio.run(run())


def _text(result):
    return "\n".join(b.text for b in result.content if hasattr(b, "text"))


def test_set_setpoint_success_returns_the_simulator_reply(control_mcp, monkeypatch):
    sim = _Simulator(body={"target": "Chlorine_01", "FlowRate": 2.8})
    monkeypatch.setattr(control_mcp.httpx, "post", sim.post)

    result = _call(
        control_mcp,
        "set_setpoint",
        {"target": "Chlorine_01", "attribute": "FlowRate", "value": 2.8},
    )

    assert not result.is_error
    assert '"FlowRate": 2.8' in _text(result)
    url, params = sim.posts[0]
    assert url.endswith("/setpoint")
    assert params == {"target": "Chlorine_01", "attribute": "FlowRate", "value": 2.8}


def test_set_setpoint_rejected_by_simulator_is_a_tool_error(control_mcp, monkeypatch):
    sim = _Simulator(
        status=400,
        body={
            "error": "99.0 outside engineering limits [0, 10] for Chlorine_01.FlowRate"
        },
    )
    monkeypatch.setattr(control_mcp.httpx, "post", sim.post)

    result = _call(
        control_mcp,
        "set_setpoint",
        {"target": "Chlorine_01", "attribute": "FlowRate", "value": 99.0},
    )

    assert result.is_error
    assert "400" in _text(result)
    assert "outside engineering limits" in _text(result)


def test_set_setpoint_unreachable_simulator_is_a_tool_error(control_mcp, monkeypatch):
    sim = _Simulator(raises=httpx.ConnectError("connection refused"))
    monkeypatch.setattr(control_mcp.httpx, "post", sim.post)

    result = _call(
        control_mcp,
        "set_setpoint",
        {"target": "Chlorine_01", "attribute": "FlowRate", "value": 2.8},
    )

    assert result.is_error
    assert "connection refused" in _text(result)


def test_clear_fault_posts_mode_normal(control_mcp, monkeypatch):
    sim = _Simulator(body={"target": "RawWater_01", "mode": "normal"})
    monkeypatch.setattr(control_mcp.httpx, "post", sim.post)

    result = _call(control_mcp, "clear_fault", {"target": "RawWater_01"})

    assert not result.is_error
    url, params = sim.posts[0]
    assert url.endswith("/fault")
    assert params == {"target": "RawWater_01", "mode": "normal"}


def test_clear_fault_unknown_target_is_a_tool_error(control_mcp, monkeypatch):
    sim = _Simulator(status=404, body={"error": "Unknown instance 'Nope_01'"})
    monkeypatch.setattr(control_mcp.httpx, "post", sim.post)

    result = _call(control_mcp, "clear_fault", {"target": "Nope_01"})

    assert result.is_error
    assert "Unknown instance" in _text(result)


def test_propose_action_reached_directly_is_not_an_approval(control_mcp):
    """The backend intercepts propose_action; if a call ever reaches the
    server itself, the reply must not read as an operator approval."""
    result = _call(
        control_mcp,
        "propose_action",
        {
            "description": "test",
            "action_type": "setpoint_adjustment",
            "target": "Chlorine_01",
            "attribute": "FlowRate",
            "value": "2.8",
        },
    )

    assert "not_intercepted" in _text(result)
    assert "approved" not in _text(result).lower()
