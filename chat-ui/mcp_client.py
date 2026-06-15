"""MCP aggregator client — fetch tool list and call tools via the aggregator SSE endpoint."""

import logging
import os

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


async def list_mcp_tools(aggregator_url: str | None = None) -> list[dict]:
    url = aggregator_url or _DEFAULT_AGGREGATOR_URL
    if url in _tool_cache:
        return _tool_cache[url]
    try:
        async with sse_client(url, timeout=10) as (read, write):
            async with ClientSession(read, write) as session:
                await session.initialize()
                result = await session.list_tools()
                _tool_cache[url] = [
                    {
                        "name": t.name,
                        "description": t.description or "",
                        "inputSchema": t.inputSchema,
                    }
                    for t in result.tools
                ]
        logger.info("Loaded %d tools from %s", len(_tool_cache[url]), url)
        return _tool_cache[url]
    except Exception as exc:
        logger.warning("Could not load tools from %s: %s", url, exc)
        return []


async def call_mcp_tool(
    name: str, args: dict, aggregator_url: str | None = None
) -> str:
    url = aggregator_url or _DEFAULT_AGGREGATOR_URL
    try:
        async with sse_client(url, timeout=30) as (read, write):
            async with ClientSession(read, write) as session:
                await session.initialize()
                result = await session.call_tool(name, arguments=args)
                parts = [
                    block.text
                    for block in (result.content or [])
                    if hasattr(block, "text")
                ]
                return "\n".join(parts) if parts else "(no result)"
    except Exception as exc:
        logger.error("Tool call %s failed: %s", name, exc)
        return f"Error calling {name}: {exc}"


def clear_tool_cache(aggregator_url: str | None = None) -> None:
    if aggregator_url:
        _tool_cache.pop(aggregator_url, None)
    else:
        _tool_cache.clear()
