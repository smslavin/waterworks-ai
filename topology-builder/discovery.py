"""MQTT and OPC-UA discovery via the fieldworks-adapters MCP tool contract.

Spawns mqtt-mcp/opcua-mcp directly as stdio subprocesses — not through the
mcp-aggregator's pool, since discovery is a rare, on-demand operation
(triggered by start_discovery), not something that benefits from a
persistent connection. See fieldworks.topology_builder.discovery for the
actual crawl/flatten logic; this module only owns the session lifecycle
(spawn, connect, crawl) that module expects its caller to provide.
"""

from __future__ import annotations

from mcp import ClientSession
from mcp.client.stdio import StdioServerParameters, stdio_client
from mcp.types import CallToolResult

from fieldworks.topology_builder.discovery import crawl_mqtt, crawl_opcua


class AdapterConnectError(RuntimeError):
    """Raised when an MQTT/OPC-UA adapter's connect tool call reports
    failure via the MCP result (isError / error content) rather than by
    raising — e.g. a refused broker connection. Without this check the
    caller has no way to distinguish "connected, crawled, found nothing"
    from "never actually connected" — both currently look identical."""


def _raise_if_connect_failed(result: CallToolResult, target: str) -> None:
    if not getattr(result, "isError", False):
        return
    detail = "; ".join(
        block.text for block in (result.content or []) if hasattr(block, "text")
    )
    raise AdapterConnectError(
        f"connect to {target} failed: {detail or '(no error detail returned)'}"
    )


def _parse_broker_url(url: str) -> tuple[str, int]:
    url = url.replace("mqtt://", "")
    parts = url.split(":")
    host = parts[0]
    port = int(parts[1]) if len(parts) > 1 else 1883
    return host, port


async def discover_mqtt_topics(broker_url: str) -> list[str]:
    """Spawn mqtt-mcp, connect to broker_url, crawl the full topic tree."""
    host, port = _parse_broker_url(broker_url)
    params = StdioServerParameters(command="mqtt-mcp", args=[])
    async with stdio_client(params) as (read, write):
        async with ClientSession(read, write) as session:
            await session.initialize()
            result = await session.call_tool("connect", {"host": host, "port": port})
            _raise_if_connect_failed(result, f"{host}:{port}")
            return await crawl_mqtt(session)


async def discover_opcua_nodes(opcua_url: str) -> list[str]:
    """Spawn opcua-mcp, connect to opcua_url, crawl the full node tree.

    opcua-mcp's connect accepts a full opc.tcp:// URL directly as `host`.
    """
    params = StdioServerParameters(command="opcua-mcp", args=[])
    async with stdio_client(params) as (read, write):
        async with ClientSession(read, write) as session:
            await session.initialize()
            result = await session.call_tool("connect", {"host": opcua_url})
            _raise_if_connect_failed(result, opcua_url)
            return await crawl_opcua(session)
