"""Regression tests for gh-21: MCP tools can signal failure in the *result*
(CallToolResult.isError / error content) rather than by raising — a refused
broker connection from the fieldworks-adapters Rust tools looks like this.
mcp_client.call_mcp_tool previously joined result.content into a plain
string regardless of isError, so a caller checking `result.startswith(
"Error calling")` (client-side-exception-only) or even the broader
`result.startswith("Error")` had no reliable signal for a tool-level
failure unless the tool's own error text happened to start with "Error".

The fix centralizes this: call_mcp_tool now normalizes both failure paths
(client-side exception, and isError=True result) to a string starting with
"Error", and never returns such a string on success.
"""

import asyncio
import contextlib
import logging

import mcp_client


class _FakeBlock:
    def __init__(self, text):
        self.text = text


class _FakeResult:
    def __init__(self, *, is_error: bool, texts: list[str]):
        self.isError = is_error
        self.content = [_FakeBlock(t) for t in texts]


class _FakeSession:
    def __init__(self, result):
        self._result = result

    async def initialize(self):
        pass

    async def call_tool(self, name, arguments=None):
        return self._result


class _FakeClientSessionCM:
    """Stands in for `async with ClientSession(read, write) as session:`."""

    def __init__(self, read, write):
        self._session = _pending_session

    async def __aenter__(self):
        return self._session

    async def __aexit__(self, *exc):
        return False


_pending_session = None


def _patch_transport(monkeypatch, result):
    global _pending_session
    _pending_session = _FakeSession(result)

    @contextlib.asynccontextmanager
    async def fake_sse_client(url, timeout=30):
        yield (None, None)

    monkeypatch.setattr(mcp_client, "sse_client", fake_sse_client)
    monkeypatch.setattr(mcp_client, "ClientSession", _FakeClientSessionCM)


# ── tool-level failure (isError=True, nothing raised) must be detected ─────


def test_call_mcp_tool_detects_tool_level_is_error_result(monkeypatch, caplog):
    _patch_transport(
        monkeypatch, _FakeResult(is_error=True, texts=["connection refused"])
    )
    with caplog.at_level(logging.WARNING, logger="mcp_client"):
        result = asyncio.run(mcp_client.call_mcp_tool("mqtt__connect", {"host": "x"}))
    assert result.startswith("Error")
    assert "connection refused" in result
    assert any("isError" in r.message for r in caplog.records)


def test_call_mcp_tool_does_not_double_prefix_error_text(monkeypatch):
    """If the tool's own error text already starts with "Error", it must
    not become "Error: Error: ..."."""
    _patch_transport(monkeypatch, _FakeResult(is_error=True, texts=["Error: refused"]))
    result = asyncio.run(mcp_client.call_mcp_tool("mqtt__connect", {}))
    assert result == "Error: refused"


def test_call_mcp_tool_success_never_starts_with_error(monkeypatch):
    _patch_transport(monkeypatch, _FakeResult(is_error=False, texts=["Connected OK"]))
    result = asyncio.run(mcp_client.call_mcp_tool("mqtt__connect", {"host": "x"}))
    assert result == "Connected OK"
    assert not result.startswith("Error")


# ── client-side exception path is unaffected (still "Error calling ...") ───


def test_call_mcp_tool_client_exception_still_reported(monkeypatch):
    @contextlib.asynccontextmanager
    async def raising_sse_client(url, timeout=30):
        raise ConnectionRefusedError("no aggregator")
        yield  # pragma: no cover - unreachable, makes this a generator

    monkeypatch.setattr(mcp_client, "sse_client", raising_sse_client)
    result = asyncio.run(mcp_client.call_mcp_tool("mqtt__connect", {}))
    assert result.startswith("Error calling mqtt__connect")


# ── the exact false-negative from gh-21: a narrow "Error calling" prefix
#    check misses a tool-level failure, but the broader "Error" check
#    (used consistently once centralized here) catches both ─────────────────


def test_narrow_error_calling_prefix_check_would_miss_tool_level_failure(
    monkeypatch,
):
    _patch_transport(
        monkeypatch, _FakeResult(is_error=True, texts=["connection refused"])
    )
    result = asyncio.run(mcp_client.call_mcp_tool("mqtt__connect", {}))
    # This documents exactly the bug: the old startup check in backend.py
    # was `if not result.startswith("Error calling")`, which is True here
    # (a false "success") even though the call failed.
    assert not result.startswith("Error calling")
    # The broader, now-consistently-applied check catches it correctly.
    assert result.startswith("Error")
