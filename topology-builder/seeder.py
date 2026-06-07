"""Persist discovered topology by calling memory-mcp via the MCP protocol."""

import json
import os

MEMORY_MCP_URL = os.environ.get("MEMORY_MCP_URL", "http://localhost:8006")


async def seed_topology(facility_id: str, facility_name: str, instances: list[dict]) -> dict:
    """Call memory-mcp's seed_discovered_topology tool over SSE."""
    from fastmcp import Client

    payload = {
        "facility_id": facility_id,
        "facility_name": facility_name,
        "instances": instances,
    }
    async with Client(f"{MEMORY_MCP_URL}/sse") as client:
        result = await client.call_tool("seed_discovered_topology", payload)

    if result and hasattr(result[0], "text"):
        return json.loads(result[0].text)
    return {"seeded_count": 0, "errors": 0}
