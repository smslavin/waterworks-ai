"""memory-mcp — knowledge graph, analytical, and specialist memory tools.

Startup:
  python server.py

Environment:
  MEMORY_MCP_PORT      (default 8006)
  LADYBUG_DB_PATH      path to LadybugDB database directory
  DUCKDB_PATH          path to DuckDB file
  SPECIALIST_MEMORY_DIR  directory for per-specialist markdown files
  DUCKDB_SYNC_INTERVAL   seconds between InfluxDB → DuckDB syncs (default 3600)
"""

import asyncio
import json
import os
from contextlib import asynccontextmanager
from typing import AsyncIterator


def _dump(obj) -> str:
    """json.dumps with fallback for datetime and other non-serializable types."""
    return _dump(obj, default=lambda x: x.isoformat() if hasattr(x, "isoformat") else str(x))

from dotenv import load_dotenv
from fastmcp import FastMCP

import analytical
import graph
import specialist_mem

load_dotenv()

PORT = int(os.environ.get("MEMORY_MCP_PORT", 8006))


@asynccontextmanager
async def _lifespan(server: FastMCP) -> AsyncIterator[None]:
    graph.get_conn()           # warm LadybugDB — triggers auto-seed if empty
    analytical.get_conn()      # warm DuckDB
    asyncio.create_task(analytical.sync_loop())
    yield


mcp = FastMCP("memory-mcp", lifespan=_lifespan)


# ── Knowledge graph — read ────────────────────────────────────────────────────

@mcp.tool()
def get_topology() -> str:
    """Full area → equipment → type tree. Use for Cascade routing decisions."""
    return _dump(graph.get_topology())


@mcp.tool()
def get_specialist_context(area_id: str) -> str:
    """Structured specialist context for area_id: equipment, attributes, fault modes, tag bindings, and area notes."""
    rows   = graph.get_specialist_context(area_id)
    result = graph.aggregate_specialist_query(rows)
    return _dump(result)


@mcp.tool()
def get_equipment_history(equipment_id: str) -> str:
    """Past incidents, observations, and operator decision patterns for one equipment instance."""
    return _dump(graph.get_equipment_history(equipment_id))


@mcp.tool()
def get_writable_attributes() -> str:
    """All writable attributes with tag IDs, confirmation requirements, and write limits."""
    return _dump(graph.get_writable_attributes())


@mcp.tool()
def query_graph(cypher: str) -> str:
    """Read-only Cypher query against LadybugDB. Write keywords (CREATE/MERGE/SET/DELETE) are rejected."""
    return _dump(graph.query_graph(cypher))


# ── Knowledge graph — write ───────────────────────────────────────────────────

@mcp.tool()
def record_incident(
    session_id: str,
    equipment_id: str,
    diagnosis: str,
    confidence: float,
    status: str,
    fault_mode_id: str = "",
) -> str:
    """Write a diagnostic incident to LadybugDB.
    status: normal | anomaly_detected | fault_detected
    fault_mode_id: optional; links Incident to a FaultMode node.
    """
    incident_id = graph.record_incident(
        session_id, equipment_id, diagnosis, confidence, status,
        fault_mode_id or None,
    )
    return _dump({"incident_id": incident_id})


@mcp.tool()
def record_observation(
    session_id: str,
    equipment_id: str,
    text: str,
    confidence: float,
    specialist: str,
) -> str:
    """Write a specialist observation that should persist across sessions."""
    obs_id = graph.record_observation(session_id, equipment_id, text, confidence, specialist)
    return _dump({"observation_id": obs_id})


@mcp.tool()
def link_incident_precedes(incident_a_id: str, incident_b_id: str, hours_apart: float) -> str:
    """Create a PRECEDES relationship between two incidents for causality chain queries."""
    graph.link_incident_precedes(incident_a_id, incident_b_id, hours_apart)
    return _dump({"status": "ok"})


@mcp.tool()
def seed_discovered_topology(
    facility_id: str,
    facility_name: str,
    instances: list[dict],
) -> str:
    """Bulk-write a topology-builder discovered topology into LadybugDB.
    Called by topology-builder after discovery is confirmed by the operator.
    instances: list of instance dicts from topology-builder infer_topology().
    """
    conn = graph.get_conn()
    result = graph.seed_discovered_topology(conn, facility_id, facility_name, instances)
    return _dump(result)


# ── Analytical layer ──────────────────────────────────────────────────────────

@mcp.tool()
def run_correlation(sql: str) -> str:
    """SELECT query against DuckDB analytical layer. For long-horizon multi-equipment correlations."""
    return _dump(analytical.run_correlation(sql))


# ── Specialist memory ─────────────────────────────────────────────────────────

@mcp.tool()
def get_specialist_memory(specialist: str) -> str:
    """Read accumulated cross-session memory for a specialist. Call at session start."""
    return specialist_mem.get_specialist_memory(specialist)


@mcp.tool()
def append_specialist_memory(specialist: str, content: str) -> str:
    """Append a timestamped entry to specialist memory. Call at session end with key findings."""
    specialist_mem.append_specialist_memory(specialist, content)
    return _dump({"status": "ok"})


if __name__ == "__main__":
    mcp.run(transport="sse", port=PORT)
