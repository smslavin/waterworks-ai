"""Regression tests for the mcp_client.py session-pooling fix.

Before this fix, call_mcp_tool opened a fresh sse_client() -> ClientSession()
-> initialize() -> one call -> full teardown on *every single call*. These
tests verify the replacement: one pooled ClientSession per distinct
aggregator URL, reused across sequential and concurrent calls, with
automatic reconnect on the next call after a dropped/errored connection —
without ever opening a real network connection (sse_client/ClientSession are
faked, following the same monkeypatch-the-module-attribute approach as
test_mcp_client_errors.py).
"""

import asyncio
import contextlib

import mcp_client


class _FakeBlock:
    def __init__(self, text):
        self.text = text


class _FakeResult:
    def __init__(self, *, is_error: bool = False, texts: list[str] | None = None):
        self.isError = is_error
        self.content = [_FakeBlock(t) for t in (texts or ["ok"])]


class _FakeSession:
    """Stand-in for mcp.ClientSession. Tracks every call_tool invocation
    made on *this* session instance, so a test can tell whether repeated
    calls landed on the same session object (pooled) or different ones
    (a fresh connection per call, the pre-fix behavior)."""

    def __init__(self, session_num: int, call_tool_fn=None):
        self.session_num = session_num
        self.initialized = False
        self.calls: list[tuple[str, dict]] = []
        self._call_tool_fn = call_tool_fn

    async def initialize(self):
        self.initialized = True

    async def call_tool(self, name, arguments=None):
        self.calls.append((name, arguments))
        if self._call_tool_fn is not None:
            outcome = self._call_tool_fn(self, name, arguments)
            if isinstance(outcome, Exception):
                raise outcome
            if outcome is not None:
                return outcome
        return _FakeResult(texts=["ok"])


class _ConnectionTracker:
    """Patches mcp_client.sse_client / mcp_client.ClientSession so every
    `async with sse_client(...): async with ClientSession(...) as session:`
    pair — i.e. every real connection the pool would establish — creates one
    new _FakeSession and is counted. `call_tool_fn(session, name, args)` may
    return a _FakeResult, an Exception (to raise, simulating a dropped
    connection), or None (default success)."""

    def __init__(self, call_tool_fn=None):
        self.connections: list[_FakeSession] = []
        self._call_tool_fn = call_tool_fn

    def install(self, monkeypatch):
        tracker = self

        @contextlib.asynccontextmanager
        async def fake_sse_client(url, timeout=30):
            yield (None, None)

        class _FakeClientSessionCM:
            def __init__(self, read, write):
                session = _FakeSession(
                    len(tracker.connections) + 1, tracker._call_tool_fn
                )
                tracker.connections.append(session)
                self._session = session

            async def __aenter__(self):
                return self._session

            async def __aexit__(self, *exc):
                return False

        monkeypatch.setattr(mcp_client, "sse_client", fake_sse_client)
        monkeypatch.setattr(mcp_client, "ClientSession", _FakeClientSessionCM)


def setup_function(_):
    # Pool state is module-global and would otherwise leak between tests
    # (and between the fresh event loop each asyncio.run() creates).
    mcp_client._reset_pools_for_tests()
    mcp_client.clear_tool_cache()


def teardown_function(_):
    mcp_client._reset_pools_for_tests()


# ── sequential calls reuse one pooled session ───────────────────────────────


def test_sequential_calls_reuse_the_same_pooled_session(monkeypatch):
    tracker = _ConnectionTracker()
    tracker.install(monkeypatch)

    async def body():
        results = []
        for i in range(5):
            results.append(await mcp_client.call_mcp_tool("mqtt__scan", {"i": i}))
        return results

    results = asyncio.run(body())

    assert all(r == "ok" for r in results)
    # Only one real connection was ever established...
    assert len(tracker.connections) == 1
    # ...and all five calls landed on that one session.
    assert len(tracker.connections[0].calls) == 5


# ── concurrent calls reuse one pooled session ───────────────────────────────


def test_concurrent_calls_reuse_the_same_pooled_session(monkeypatch):
    tracker = _ConnectionTracker()
    tracker.install(monkeypatch)

    async def body():
        return await asyncio.gather(
            *[mcp_client.call_mcp_tool("mqtt__scan", {"i": i}) for i in range(8)]
        )

    results = asyncio.run(body())

    assert all(r == "ok" for r in results)
    assert len(tracker.connections) == 1
    assert len(tracker.connections[0].calls) == 8


# ── distinct aggregator URLs get distinct pools ─────────────────────────────


def test_distinct_aggregator_urls_get_distinct_pooled_sessions(monkeypatch):
    tracker = _ConnectionTracker()
    tracker.install(monkeypatch)

    async def body():
        await mcp_client.call_mcp_tool("mqtt__scan", {}, "http://plant-a/sse")
        await mcp_client.call_mcp_tool("mqtt__scan", {}, "http://plant-a/sse")
        await mcp_client.call_mcp_tool("mqtt__scan", {}, "http://plant-b/sse")

    asyncio.run(body())

    # Two distinct URLs -> two distinct pooled connections, not three (the
    # repeated plant-a call reused its pool) and not one (plant-b isn't
    # forced to share plant-a's session).
    assert len(tracker.connections) == 2


# ── isError normalization still works through the pooled session ──────────


def test_pooled_call_still_normalizes_is_error_result(monkeypatch):
    def call_tool_fn(session, name, args):
        return _FakeResult(is_error=True, texts=["connection refused"])

    tracker = _ConnectionTracker(call_tool_fn=call_tool_fn)
    tracker.install(monkeypatch)

    result = asyncio.run(mcp_client.call_mcp_tool("mqtt__connect", {}))
    assert result == "Error: connection refused"


# ── dropped/errored connection: next call reconnects, doesn't stay broken ──


def test_dropped_connection_reconnects_on_next_call(monkeypatch):
    call_count = 0

    def call_tool_fn(session, name, args):
        nonlocal call_count
        call_count += 1
        if call_count == 2:
            # Simulate the connection dying mid-call.
            return ConnectionResetError("connection dropped")
        return _FakeResult(texts=[f"ok-{call_count}"])

    tracker = _ConnectionTracker(call_tool_fn=call_tool_fn)
    tracker.install(monkeypatch)

    async def body():
        first = await mcp_client.call_mcp_tool("mqtt__scan", {})
        second = await mcp_client.call_mcp_tool("mqtt__scan", {})
        third = await mcp_client.call_mcp_tool("mqtt__scan", {})
        return first, second, third

    first, second, third = asyncio.run(body())

    assert first == "ok-1"
    assert second.startswith("Error calling mqtt__scan")
    assert third == "ok-3"

    # The drop forced a reconnect: two distinct connections were
    # established (one for calls 1-2, a fresh one for call 3), not one
    # permanently broken pool and not a fresh connection for every call.
    assert len(tracker.connections) == 2


def test_pool_survives_many_calls_after_a_reconnect(monkeypatch):
    """A drop should degrade exactly one call, not the pool going forward —
    calls after the reconnect keep reusing the new session."""
    call_count = 0

    def call_tool_fn(session, name, args):
        nonlocal call_count
        call_count += 1
        if call_count == 1:
            return ConnectionResetError("dropped immediately")
        return _FakeResult(texts=["ok"])

    tracker = _ConnectionTracker(call_tool_fn=call_tool_fn)
    tracker.install(monkeypatch)

    async def body():
        results = []
        for _ in range(6):
            results.append(await mcp_client.call_mcp_tool("mqtt__scan", {}))
        return results

    results = asyncio.run(body())

    assert results[0].startswith("Error calling mqtt__scan")
    assert all(r == "ok" for r in results[1:])
    # One failed connection (call 1) + one good, reused connection (calls 2-6).
    assert len(tracker.connections) == 2
    assert len(tracker.connections[1].calls) == 5


# ── call_mcp_tool's signature/behavior contract is unchanged by pooling ────


def test_call_mcp_tool_signature_accepts_positional_and_keyword_aggregator_url(
    monkeypatch,
):
    tracker = _ConnectionTracker()
    tracker.install(monkeypatch)

    async def body():
        a = await mcp_client.call_mcp_tool("mqtt__scan", {})
        b = await mcp_client.call_mcp_tool("mqtt__scan", {}, None)
        c = await mcp_client.call_mcp_tool("mqtt__scan", {}, aggregator_url=None)
        return a, b, c

    a, b, c = asyncio.run(body())
    assert a == b == c == "ok"
