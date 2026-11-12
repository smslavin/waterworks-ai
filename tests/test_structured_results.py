"""Typed tool results through MCP output schemas (gh-52).

influxdb-mcp's query_series declares an output schema and returns its points
as structured content; a failed query is a tool error. mcp_client's
call_mcp_tool_structured hands code the structured content and raises on any
failure, so Deadband can't read an InfluxDB outage as "zero samples" (which
reported fraction_in_violation 0.0 with no error) the way it could before.
"""

import asyncio
import contextlib
import importlib.util
from pathlib import Path

import pytest
from mcp.types import CallToolResult, TextContent

import deadband
import mcp_client

ROOT = Path(__file__).parent.parent


def _influxdb_server():
    spec = importlib.util.spec_from_file_location(
        "_influxdb_mcp_structured", ROOT / "influxdb-mcp" / "server.py"
    )
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


# ── the server side, over MCP ──────────────────────────────────────────────


def test_query_series_declares_an_output_schema_and_returns_structured_points(
    monkeypatch,
):
    from mcp.client import Client

    server = _influxdb_server()

    class _Record:
        def __init__(self, t, v):
            self._t, self._v = t, v

        def get_time(self):
            return self._t

        def get_value(self):
            return self._v

    import datetime

    t0 = datetime.datetime(2026, 11, 11, 10, 0, tzinfo=datetime.timezone.utc)
    table = type("T", (), {"records": [_Record(t0, 3), _Record(t0, None)]})()
    client = type(
        "C",
        (),
        {
            "query_api": lambda self: type(
                "Q", (), {"query": lambda s, f, org: [table]}
            )()
        },
    )()
    monkeypatch.setattr(server, "_get_client", lambda: client)

    async def run():
        async with Client(server.mcp) as c:
            tool = next(
                t for t in (await c.list_tools()).tools if t.name == "query_series"
            )
            result = await c.call_tool(
                "query_series",
                {
                    "measurement": "wtp_process",
                    "instance": "RawWater_01",
                    "attribute": "Flow",
                    "start": "-5m",
                },
            )
            return tool, result

    tool, result = asyncio.run(run())
    assert "points" in tool.output_schema["properties"]
    assert not result.is_error
    assert result.structured_content == {
        "points": [{"t": "2026-11-11T10:00:00+00:00", "v": 3.0}]
    }


def test_query_series_failure_reaches_the_client_as_an_error(monkeypatch):
    from mcp.client import Client

    server = _influxdb_server()

    def _boom():
        raise RuntimeError("connection refused")

    monkeypatch.setattr(server, "_get_client", _boom)

    async def run():
        async with Client(server.mcp) as c:
            return await c.call_tool(
                "query_series",
                {"measurement": "m", "instance": "i", "attribute": "a", "start": "-1m"},
            )

    result = asyncio.run(run())
    assert result.is_error
    assert "InfluxDB query failed: connection refused" in result.content[0].text


# ── mcp_client.call_mcp_tool_structured ────────────────────────────────────


def _patch_session(monkeypatch, result=None, raises=None):
    class _Session:
        async def initialize(self):
            pass

        async def call_tool(self, name, arguments=None):
            if raises:
                raise raises
            return result

    class _CM:
        def __init__(self, read, write, message_handler=None):
            pass

        async def __aenter__(self):
            return _Session()

        async def __aexit__(self, *exc):
            return False

    @contextlib.asynccontextmanager
    async def fake_sse(url, timeout=30):
        yield (None, None)

    monkeypatch.setattr(mcp_client, "sse_client", fake_sse)
    monkeypatch.setattr(mcp_client, "ClientSession", _CM)
    mcp_client._reset_pools_for_tests()


def _call():
    async def run():
        try:
            return await mcp_client.call_mcp_tool_structured(
                "influxdb__query_series", {}
            )
        finally:
            mcp_client._reset_pools_for_tests()

    return asyncio.run(run())


def test_structured_call_returns_structured_content(monkeypatch):
    _patch_session(
        monkeypatch,
        CallToolResult(
            content=[TextContent(type="text", text="{}")],
            structured_content={"points": []},
        ),
    )
    assert _call() == {"points": []}


@pytest.mark.parametrize(
    "result,raises,message",
    [
        (
            CallToolResult(
                content=[TextContent(type="text", text="InfluxDB query failed: x")],
                is_error=True,
            ),
            None,
            "Error: InfluxDB query failed: x",
        ),
        (
            CallToolResult(content=[TextContent(type="text", text='{"points": []}')]),
            None,
            "returned no structured content",
        ),
        (
            None,
            ConnectionError("aggregator down"),
            "Error calling influxdb__query_series: aggregator down",
        ),
    ],
    ids=["is_error", "no-structured-content", "transport"],
)
def test_structured_call_raises_on_every_failure(monkeypatch, result, raises, message):
    _patch_session(monkeypatch, result, raises)
    with pytest.raises(mcp_client.ToolCallError, match=message):
        _call()


def test_text_call_keeps_its_error_string_contract(monkeypatch):
    _patch_session(monkeypatch, raises=ConnectionError("aggregator down"))

    async def run():
        try:
            return await mcp_client.call_mcp_tool("x__y", {})
        finally:
            mcp_client._reset_pools_for_tests()

    assert asyncio.run(run()) == "Error calling x__y: aggregator down"


# ── Deadband surfaces an outage instead of reading zero samples ────────────


def test_deadband_reports_an_influxdb_outage_as_an_error(monkeypatch):
    async def failing(name, args, aggregator_url=None):
        raise mcp_client.ToolCallError(
            "Error: InfluxDB query failed: connection refused"
        )

    monkeypatch.setattr(deadband, "call_mcp_tool_structured", failing)
    sustained = asyncio.run(
        deadband._verify_sustained(
            "RawWater_01", "Flow", "above_max", 5, 90, 105, "http://agg"
        )
    )
    trend = asyncio.run(
        deadband._get_trend_direction("RawWater_01", "Flow", 30, "http://agg")
    )
    assert sustained["sustained"] is False
    assert "connection refused" in sustained["error"]
    assert "fraction_in_violation" not in sustained  # not a fake 0.0
    assert "connection refused" in trend["error"]
