"""MCP aggregator client — fetch tool list and call tools via the aggregator SSE endpoint.

Session pooling
----------------
call_mcp_tool used to do sse_client() -> ClientSession() -> initialize() -> one
tool call -> full teardown, on *every single call*. That cost model forced
workarounds in three other places in this repo: monitor.py's
_populate_severities blocking chat-ui startup on ~50 sequential connections,
memory-mcp's _startup_done guard (working around the MCP SDK running
lifespan once per SSE session, i.e. once per call), and a TODO in
mcp-aggregator/server/server.py about pooling SSE backends.

This module now pools one long-lived ClientSession per distinct aggregator
URL (there can be more than one — enterprise/query_history_mcp/server.py
fans a call out across every plant's own aggregator_url). The shape mirrors
mcp-aggregator/server/server.py's own pooling for its streamable_http/stdio
backends: a background task per URL holds the session open
(_run_persistent_pool / _pools, vs. the aggregator's _run_persistent_pool /
_session_pool), reconnecting with backoff on drop. Naming intentionally
tracks the aggregator's. See _run_persistent_pool's own docstring for the
one place this deliberately doesn't copy the aggregator verbatim (no shared
shutdown-event signal — this module has no owning lifespan to fire one
from).

One deliberate difference from what the aggregator's own TODO comment
*proposes* (an asyncio.Queue + single consumer serializing every call onto
one connection): that was never actually implemented upstream for SSE, and
the aggregator's own *working* pooled code (streamable_http/stdio backends,
_proxy_call) does not use a queue either — it calls session.call_tool()
directly from concurrent callers with no extra locking. That's safe because
the MCP SDK's ClientSession/dispatcher already multiplexes concurrent
in-flight requests by request id (see mcp/shared/jsonrpc_dispatcher.py) —
the aggregator's pooled sessions already lean on exactly that. A
queue+single-consumer here would also have serialized multi_agent_loop.py's
four parallel specialists (asyncio.gather over the same default aggregator
URL) onto one call at a time, which would be a real regression. So this
pool follows the aggregator's *actual* running pattern: callers await
call_tool() directly on the shared session.

Reconnection: if a pooled call raises, the pool entry for that URL is
dropped (its background task cancelled) so the *next* call transparently
establishes a fresh session — a broken connection degrades one call, not
every subsequent one.
"""

import asyncio
import logging
import os
from dataclasses import dataclass, field

from dotenv import load_dotenv
from mcp import ClientSession
from mcp.client.sse import sse_client

load_dotenv()

_DEFAULT_AGGREGATOR_URL = os.environ.get(
    "MCP_AGGREGATOR_URL", "http://localhost:8100/sse"
)

logger = logging.getLogger(__name__)

# Per-url tool cache. Keyed by aggregator URL so multiple plants (each with their
# own aggregator) can coexist without one plant's tool list clobbering another's.
_tool_cache: dict[str, list[dict]] = {}

# Reconnect backoff between failed connection attempts, in seconds. Module-level
# (not a function default) so tests can shrink it instead of sleeping for real.
_RECONNECT_BACKOFF = 2.0

# First-connection-attempt timeout, in seconds — bounds how long a caller can
# be made to wait the very first time a URL is used, before falling back to
# the normal "return an Error string" behavior a caller already handles.
_CONNECT_TIMEOUT = 30.0


@dataclass
class _PoolEntry:
    """State for one pooled aggregator connection.

    `ready` is set exactly once per connection *attempt* (success or
    failure) and is never cleared again for this entry — after the first
    attempt settles, callers stop blocking on it and just read `session`/
    `error` directly, so a later background reconnect is picked up by the
    next call rather than making every call wait on it.
    """

    session: ClientSession | None = None
    error: Exception | None = None
    ready: asyncio.Event = field(default_factory=asyncio.Event)
    task: asyncio.Task | None = None


_pools: dict[str, _PoolEntry] = {}


async def _run_persistent_pool(url: str, entry: _PoolEntry) -> None:
    """Keep one persistent ClientSession open for `url`, reconnecting with
    backoff on drop. Mirrors mcp-aggregator/server/server.py's
    _run_persistent_pool for its own pooled (streamable_http/stdio)
    backends — same shape (a background task per connection, backoff then
    retry on failure), applied here to the SSE transport chat-ui actually
    talks to the aggregator over.

    One difference from the aggregator's version: it holds its pooled
    sessions open until a shared `_shutdown_event` (set once, from its own
    Starlette lifespan) fires, so every backend tears down together at app
    shutdown. mcp_client.py has no equivalent owning lifespan to wire a
    shared signal from — chat-ui's process shutdown simply cancels this
    task like any other background task, which the `except
    asyncio.CancelledError: raise` below already handles cleanly (closes
    the SSE stream and exits the ClientSession context via each `async
    with`'s teardown). A single shared Event here would also be a latent
    cross-event-loop bug in tests: an asyncio.Event created once at module
    import time binds to whichever loop first calls .wait() on it, then
    raises on every other loop that touches it — same reason it's an
    argument here and not a module global. Held open via an inner
    sleep-forever loop instead, cancellable at any point.
    """
    backoff = _RECONNECT_BACKOFF
    while True:
        try:
            async with sse_client(url, timeout=_CONNECT_TIMEOUT) as (read, write):
                async with ClientSession(read, write) as session:
                    await session.initialize()
                    entry.session = session
                    entry.error = None
                    entry.ready.set()
                    logger.info("MCP session pool ready for %s", url)
                    while True:
                        await asyncio.sleep(3600)
        except asyncio.CancelledError:
            raise
        except Exception as e:
            entry.session = None
            entry.error = e
            entry.ready.set()
            logger.warning(
                "MCP session pool for %s dropped, reconnecting in %.0fs: %s",
                url,
                backoff,
                e,
            )
            await asyncio.sleep(backoff)
            # loop back and retry the connection


def _get_or_create_entry(url: str) -> _PoolEntry:
    entry = _pools.get(url)
    if entry is None or entry.task is None or entry.task.done():
        entry = _PoolEntry()
        entry.task = asyncio.create_task(
            _run_persistent_pool(url, entry), name=f"mcp_pool:{url}"
        )
        _pools[url] = entry
    return entry


def _invalidate(url: str) -> None:
    """Drop the pool entry for `url` so the next call reconnects from
    scratch. Fire-and-forget cancel — we don't await the old task's
    teardown here; it cleans up (closes the SSE stream, exits the
    ClientSession context) on its own once cancelled."""
    entry = _pools.pop(url, None)
    if entry is not None and entry.task is not None and not entry.task.done():
        entry.task.cancel()


async def _get_session(url: str) -> ClientSession:
    entry = _get_or_create_entry(url)
    await asyncio.wait_for(entry.ready.wait(), timeout=_CONNECT_TIMEOUT + 5)
    if entry.session is None:
        raise ConnectionError(
            f"MCP session pool for {url} is not connected: {entry.error}"
        )
    return entry.session


async def list_mcp_tools(aggregator_url: str | None = None) -> list[dict]:
    url = aggregator_url or _DEFAULT_AGGREGATOR_URL
    if url in _tool_cache:
        return _tool_cache[url]
    try:
        session = await _get_session(url)
        result = await session.list_tools()
        _tool_cache[url] = [
            {
                "name": t.name,
                "description": t.description or "",
                # Attribute name has drifted across mcp SDK versions
                # (inputSchema pre-2.0, input_schema from 2.0 on) —
                # this repo now pins its own mcp version via
                # chat-ui/uv.lock, so a single checkout no longer
                # drifts on its own. Kept as a fallback anyway: an
                # older .venv predating the lock, or a future
                # `uv lock --upgrade` across a major mcp bump, can
                # still land on either attribute name.
                "inputSchema": getattr(t, "inputSchema", None)
                or getattr(t, "input_schema", None),
            }
            for t in result.tools
        ]
        logger.info("Loaded %d tools from %s", len(_tool_cache[url]), url)
        return _tool_cache[url]
    except Exception as exc:
        logger.warning("Could not load tools from %s: %s", url, exc)
        _invalidate(url)
        return []


async def call_mcp_tool(
    name: str, args: dict, aggregator_url: str | None = None
) -> str:
    """Call an MCP tool via the aggregator's pooled session.

    MCP signals a tool-level failure two ways: by raising (transport error,
    aggregator unreachable) or, per the CallToolResult.isError convention, in
    the *result itself* with nothing raised at all — the fieldworks-adapters
    Rust tools use the latter for things like a refused broker connection.
    Both failure modes are normalized here to a return value that starts
    with the literal "Error" — callers must check for that prefix rather
    than assume success just because this coroutine didn't raise. A
    successful result never starts with "Error".

    Signature and behavior are unchanged from the pre-pooling version — this
    is a pure internal implementation change. On any failure (pool connect
    failure, or the call itself raising) the pool entry for `aggregator_url`
    is dropped so the next call reconnects instead of reusing a broken
    session.
    """
    url = aggregator_url or _DEFAULT_AGGREGATOR_URL
    try:
        session = await _get_session(url)
        result = await session.call_tool(name, arguments=args)
        parts = [
            block.text for block in (result.content or []) if hasattr(block, "text")
        ]
        text = "\n".join(parts) if parts else "(no result)"
        if getattr(result, "isError", False):
            logger.warning(
                "Tool call %s reported isError (args=%r): %s", name, args, text
            )
            return text if text.startswith("Error") else f"Error: {text}"
        return text
    except Exception as exc:
        logger.error("Tool call %s failed: %s", name, exc)
        _invalidate(url)
        return f"Error calling {name}: {exc}"


def clear_tool_cache(aggregator_url: str | None = None) -> None:
    if aggregator_url:
        _tool_cache.pop(aggregator_url, None)
    else:
        _tool_cache.clear()


def _reset_pools_for_tests() -> None:
    """Test-only helper: drop every pooled connection and cancel its
    background task. Module-level pool state otherwise persists across
    tests (and across the fresh event loop each `asyncio.run()` creates in
    a test), which would leave a later test observing a stale, dead-loop
    session. Not used by production code."""
    for url in list(_pools.keys()):
        _invalidate(url)
