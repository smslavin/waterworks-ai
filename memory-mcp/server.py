"""memory-mcp — thin FastMCP wrapper around fieldworks.memory.

Startup:
  python server.py

Environment:
  MEMORY_MCP_PORT       (default 8006)
  LADYBUG_DB_PATH       path to LadybugDB database directory
  DUCKDB_PATH           path to DuckDB file
  SPECIALIST_MEMORY_DIR directory for per-specialist markdown files
  DUCKDB_SYNC_INTERVAL  seconds between InfluxDB → DuckDB syncs (default 3600)
  INFLUXDB_URL / INFLUXDB_TOKEN / INFLUXDB_ORG / INFLUXDB_BUCKET
  TOPOLOGY_FILE         path to topology.yaml (default: repo root) — used to
                        auto-seed LadybugDB's static layer on first boot
"""

import asyncio
import json
import os
from contextlib import asynccontextmanager
from pathlib import Path
from typing import AsyncIterator

from dotenv import load_dotenv

load_dotenv(dotenv_path=Path(__file__).parent.parent / ".env")

from fastmcp import FastMCP

import topology as _topo_loader
from fieldworks.memory import (
    AnalyticalClient,
    AnalyticalConfig,
    GraphClient,
    GraphConfig,
    SpecialistMemory,
    aggregate_specialist_query,
)
from fieldworks.topology import seed_topology

PORT = int(os.environ.get("MEMORY_MCP_PORT", 8006))

graph = GraphClient(
    GraphConfig(db_path=os.environ.get("LADYBUG_DB_PATH", "../data/ladybugdb/fieldworks.db"))
)
analytical = AnalyticalClient(
    AnalyticalConfig(
        db_path=os.environ.get("DUCKDB_PATH", "../data/duckdb/analytical.duckdb"),
        process_table="wtp_process",
        fault_events_table="wtp_fault_events",
        influxdb_url=os.environ.get("INFLUXDB_URL", "http://localhost:8086"),
        influxdb_token=os.environ.get("INFLUXDB_TOKEN", ""),
        influxdb_org=os.environ.get("INFLUXDB_ORG", "waterworks"),
        influxdb_bucket=os.environ.get("INFLUXDB_BUCKET", "waterworks"),
        influxdb_measurement="wtp_process",
        sync_window_days=90,
        sync_interval_seconds=int(os.environ.get("DUCKDB_SYNC_INTERVAL", "3600")),
    )
)
specialist_mem = SpecialistMemory(
    os.environ.get("SPECIALIST_MEMORY_DIR", "../data/specialist-memory")
)


def _dump(obj) -> str:
    """json.dumps with fallback for datetime and other non-serializable types."""
    return json.dumps(
        obj, default=lambda x: x.isoformat() if hasattr(x, "isoformat") else str(x)
    )


def _maybe_seed_from_topology() -> None:
    """Bootstrap the static layer from topology.yaml on first boot (empty DB).
    Also warms the LadybugDB connection — query_graph() triggers lazy connect
    and schema creation.
    """
    rows = graph.query_graph("MATCH (f:Facility) RETURN count(f) AS c")
    if rows and rows[0]["c"] > 0:
        return
    topology = _topo_loader.load()
    counts = seed_topology(topology, graph)
    print(f"[memory-mcp] seeded from topology.yaml: {counts}")


@asynccontextmanager
async def _lifespan(server: FastMCP) -> AsyncIterator[None]:
    _maybe_seed_from_topology()
    asyncio.create_task(analytical.sync_loop())  # warms DuckDB on first iteration
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
    rows = graph.get_specialist_context(area_id)
    result = aggregate_specialist_query(rows)
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
def get_severity_for_attribute(type_id: str, attr_id: str, condition: str = "") -> str:
    """Runtime severity lookup for a (equipment type, attribute) pair, via FaultMode.severity
    on the graph — replaces static topology.yaml alarm config.
    condition: "below_min" | "above_max" | "" (considers both directions).
    """
    return _dump(graph.get_severity_for_attribute(type_id, attr_id, condition or None))


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
        session_id,
        equipment_id,
        diagnosis,
        confidence,
        status,
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
def link_incident_precedes(
    incident_a_id: str, incident_b_id: str, hours_apart: float
) -> str:
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
    result = graph.seed_discovered_topology(facility_id, facility_name, instances)
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
    return specialist_mem.get(specialist)


@mcp.tool()
def append_specialist_memory(specialist: str, content: str) -> str:
    """Append a timestamped entry to specialist memory. Call at session end with key findings."""
    specialist_mem.append(specialist, content)
    return _dump({"status": "ok"})


if __name__ == "__main__":
    mcp.run(transport="sse", port=PORT)
