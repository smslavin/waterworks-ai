"""MCP aggregator client — fetch tool list and call tools via the aggregator SSE endpoint."""

import logging
import os

from dotenv import load_dotenv
from mcp import ClientSession
from mcp.client.sse import sse_client

load_dotenv()

MCP_AGGREGATOR_URL = os.environ.get("MCP_AGGREGATOR_URL", "http://localhost:8100/sse")

logger = logging.getLogger(__name__)

# Tool list is cached after first fetch. Cleared on server restart.
_tool_cache: list[dict] | None = None


async def list_mcp_tools() -> list[dict]:
    global _tool_cache
    if _tool_cache is not None:
        return _tool_cache
    try:
        async with sse_client(MCP_AGGREGATOR_URL, timeout=10) as (read, write):
            async with ClientSession(read, write) as session:
                await session.initialize()
                result = await session.list_tools()
                _tool_cache = [
                    {
                        "name": t.name,
                        "description": t.description or "",
                        "inputSchema": t.inputSchema,
                    }
                    for t in result.tools
                ]
        logger.info("Loaded %d tools from aggregator", len(_tool_cache))
        return _tool_cache
    except Exception as exc:
        logger.warning("Could not load tools from aggregator: %s", exc)
        return []


async def call_mcp_tool(name: str, args: dict) -> str:
    try:
        async with sse_client(MCP_AGGREGATOR_URL, timeout=30) as (read, write):
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


def clear_tool_cache() -> None:
    global _tool_cache
    _tool_cache = None
