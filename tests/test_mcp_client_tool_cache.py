"""gh-45: chat-ui's tool cache follows the aggregator's tools/list_changed.

Aggregator v3 retries a backend that misses startup and adds its tools when
it answers, then notifies connected clients. Before gh-45, mcp_client cached
the first list_tools() answer per URL forever, so a late backend's tools
never reached the agents until chat-ui restarted.

The fakes stand in for sse_client/ClientSession; the notification passed to
the message_handler is a real mcp.types.ToolListChangedNotification.
"""

import asyncio
import contextlib
from types import SimpleNamespace

from mcp.types import ToolListChangedNotification

import mcp_client


def _tool(name):
    return SimpleNamespace(name=name, description="", input_schema={})


class _Aggregator:
    """One fake aggregator. `tools` is what list_tools() answers;
    `notify()` sends tools/list_changed to every open session, as the real
    one does. `on_list` runs inside list_tools(), between the request and
    the answer, to model a change that lands mid-listing."""

    def __init__(self, tools):
        self.tools = list(tools)
        self.handlers = []
        self.list_calls = 0
        self.connections = 0
        self.on_list = None

    async def notify(self):
        for handler in self.handlers:
            await handler(ToolListChangedNotification())

    def install(self, monkeypatch):
        agg = self

        @contextlib.asynccontextmanager
        async def fake_sse_client(url, timeout=30):
            yield (None, None)

        class _Session:
            async def initialize(self):
                pass

            async def list_tools(self):
                agg.list_calls += 1
                answer = [_tool(n) for n in agg.tools]
                if agg.on_list is not None:
                    hook, agg.on_list = agg.on_list, None
                    await hook()
                return SimpleNamespace(tools=answer)

        class _SessionCM:
            def __init__(self, read, write, message_handler=None):
                agg.connections += 1
                agg.handlers.append(message_handler)

            async def __aenter__(self):
                return _Session()

            async def __aexit__(self, *exc):
                return False

        monkeypatch.setattr(mcp_client, "sse_client", fake_sse_client)
        monkeypatch.setattr(mcp_client, "ClientSession", _SessionCM)


def _names(tools):
    return sorted(t["name"] for t in tools)


def setup_function(_):
    mcp_client._reset_pools_for_tests()
    mcp_client.clear_tool_cache()


def teardown_function(_):
    mcp_client._reset_pools_for_tests()


def test_list_changed_makes_the_next_listing_fresh(monkeypatch):
    agg = _Aggregator(["mqtt__scan"])
    agg.install(monkeypatch)

    async def body():
        first = await mcp_client.list_mcp_tools("http://agg/sse")
        cached = await mcp_client.list_mcp_tools("http://agg/sse")
        # influxdb missed aggregator startup and has just answered a retry.
        agg.tools.append("influxdb__query")
        await agg.notify()
        after = await mcp_client.list_mcp_tools("http://agg/sse")
        return first, cached, after

    first, cached, after = asyncio.run(body())

    assert _names(first) == _names(cached) == ["mqtt__scan"]
    assert _names(after) == ["influxdb__query", "mqtt__scan"]
    assert agg.list_calls == 2  # the cache still serves unchanged lists


def test_change_during_listing_is_not_cached_as_current(monkeypatch):
    """The notification lands while list_tools() is in flight: the answer is
    already stale, so it must be returned but not cached."""
    agg = _Aggregator(["mqtt__scan"])
    agg.install(monkeypatch)

    async def change():
        agg.tools.append("influxdb__query")
        await agg.notify()

    async def body():
        await mcp_client._get_session("http://agg/sse")  # pool up first
        agg.on_list = change
        stale = await mcp_client.list_mcp_tools("http://agg/sse")
        fresh = await mcp_client.list_mcp_tools("http://agg/sse")
        return stale, fresh

    stale, fresh = asyncio.run(body())

    assert _names(stale) == ["mqtt__scan"]
    assert _names(fresh) == ["influxdb__query", "mqtt__scan"]


def test_notification_for_one_plant_leaves_the_others_cached(monkeypatch):
    """M10: each plant has its own aggregator URL and its own cache entry."""
    agg = _Aggregator(["mqtt__scan"])
    agg.install(monkeypatch)

    async def body():
        await mcp_client.list_mcp_tools("http://plant-a/sse")
        await mcp_client.list_mcp_tools("http://plant-b/sse")
        handler_a = agg.handlers[0]
        await handler_a(ToolListChangedNotification())
        return set(mcp_client._tool_cache)

    assert asyncio.run(body()) == {"http://plant-b/sse"}


def test_reconnect_drops_the_cached_list(monkeypatch):
    """Notifications sent while disconnected are lost, and the aggregator
    may have restarted with different tools, so a new session starts
    from a fresh listing."""
    agg = _Aggregator(["mqtt__scan"])
    agg.install(monkeypatch)

    async def body():
        await mcp_client.list_mcp_tools("http://agg/sse")
        mcp_client._invalidate("http://agg/sse")  # what a failed call does
        agg.tools.append("influxdb__query")
        await mcp_client._get_session("http://agg/sse")
        return await mcp_client.list_mcp_tools("http://agg/sse")

    tools = asyncio.run(body())

    assert agg.connections == 2
    assert _names(tools) == ["influxdb__query", "mqtt__scan"]
