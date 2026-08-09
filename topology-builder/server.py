"""topology-builder — MCPServer :8007.

Tools:
  start_discovery          — begin async MQTT (+OPC-UA) crawl, returns discovery_id
  get_discovery_progress   — poll results for a discovery_id
  override_instance_type   — operator correction: reclassify an instance
  generate_topology_yaml   — preview topology.yaml without committing

Committing a reviewed topology to LadybugDB does NOT go through this server —
chat-ui/backend.py's POST /api/topology/commit calls memory__seed_discovered_topology
directly via the aggregator (see fieldworks-core#19).
"""

import asyncio
import os
import uuid
from pathlib import Path

from dotenv import load_dotenv
from mcp.server import MCPServer

from discovery import discover_mqtt_topics, discover_opcua_nodes
from fieldworks.topology_builder.inference import infer_topology, load_template

load_dotenv(dotenv_path=Path(__file__).parent.parent / ".env")

_TEMPLATES_DIR = Path(__file__).parent / "templates"

mcp = MCPServer("topology-builder")

_sessions: dict[str, dict] = {}


@mcp.tool()
async def start_discovery(
    broker_url: str,
    template: str = "water-treatment-municipal",
    opcua_url: str | None = None,
    crawl_duration: float = 10.0,
) -> dict:
    """
    Begin async topology discovery from MQTT (and optionally OPC-UA).
    Returns immediately with a discovery_id. Poll get_discovery_progress for results.
    broker_url: MQTT broker URL, e.g. 'localhost:1883' or 'mqtt://192.168.1.10:1883'
    template: equipment type library name (default 'water-treatment-municipal')
    opcua_url: optional OPC-UA endpoint, e.g. 'opc.tcp://localhost:4840'
    crawl_duration: unused — retained for API compatibility. mqtt-mcp's
        get_topic_tree (fieldworks-core#22) manages its own fixed scan
        window internally; the adapter doesn't expose a way to configure it.
    """
    discovery_id = str(uuid.uuid4())[:8]
    _sessions[discovery_id] = {
        "status": "running",
        "broker_url": broker_url,
        "template": template,
        "opcua_url": opcua_url,
        "instances": [],
        "stats": {"topics_seen": 0, "instances_found": 0},
        "error": None,
    }
    asyncio.create_task(_run_discovery(discovery_id, broker_url, opcua_url, template))
    return {
        "discovery_id": discovery_id,
        "status": "running",
        "message": f"Discovery started. Call get_discovery_progress('{discovery_id}') to check results.",
    }


@mcp.tool()
async def get_discovery_progress(discovery_id: str) -> dict:
    """
    Returns current discovery results for a given discovery_id.
    status: 'running' | 'complete' | 'error'
    instances: list of discovered equipment instances with confidence levels.
    When status is 'complete', present the topology summary to the operator and
    tell them to review the graph and click 'Commit to DB' when satisfied.
    Do NOT claim that the topology has been committed or saved — only the operator
    can commit via the UI button. Your job ends at presenting the discovery results.
    """
    session = _sessions.get(discovery_id)
    if not session:
        return {"error": f"Unknown discovery_id: {discovery_id}"}
    return {
        "status": session["status"],
        "instances": session["instances"],
        "stats": session["stats"],
        "error": session.get("error"),
    }


@mcp.tool()
async def override_instance_type(
    discovery_id: str,
    instance_id: str,
    equipment_type: str,
    ladybug_type_id: str = "",
    confidence: float = 1.0,
) -> dict:
    """
    Operator-guided correction: reclassify a discovered instance.
    Sets confidence_level to 'verified' and confidence_score to the supplied value.
    ladybug_type_id: the LadybugDB EquipmentType id (e.g. 'centrifugal_pump').
    """
    session = _sessions.get(discovery_id)
    if not session:
        return {"error": f"Unknown discovery_id: {discovery_id}"}
    for inst in session["instances"]:
        if inst["instance_id"] == instance_id:
            inst["equipment_type"] = equipment_type
            if ladybug_type_id:
                inst["ladybug_type_id"] = ladybug_type_id
            inst["confidence_score"] = confidence
            inst["confidence_level"] = "verified"
            return {"ok": True, "instance_id": instance_id, "new_type": equipment_type}
    return {
        "error": f"instance_id '{instance_id}' not found in session '{discovery_id}'"
    }


@mcp.tool()
async def generate_topology_yaml(discovery_id: str) -> str:
    """Generate a topology.yaml preview from the current session without committing."""
    session = _sessions.get(discovery_id)
    if not session:
        return f"# Unknown discovery_id: {discovery_id}"
    return _generate_yaml("plant", "Plant", session["instances"])


async def _run_discovery(
    discovery_id: str,
    broker_url: str,
    opcua_url: str | None,
    template_name: str,
) -> None:
    session = _sessions[discovery_id]
    try:
        tmpl = load_template(_TEMPLATES_DIR / f"{template_name}.yaml")

        mqtt_topics = await discover_mqtt_topics(broker_url)
        session["stats"]["topics_seen"] = len(mqtt_topics)

        opcua_nodes: list[str] = []
        if opcua_url:
            try:
                opcua_nodes = await discover_opcua_nodes(opcua_url)
            except Exception as e:
                session["stats"]["opcua_error"] = str(e)

        instances = infer_topology(mqtt_topics, opcua_nodes, tmpl)
        session["instances"] = instances
        session["stats"]["instances_found"] = len(instances)
        session["status"] = "complete"
    except Exception as e:
        session["status"] = "error"
        session["error"] = str(e)


def _generate_yaml(facility_id: str, facility_name: str, instances: list[dict]) -> str:
    from collections import defaultdict

    by_type: dict[str, list[str]] = defaultdict(list)
    for inst in instances:
        by_type[inst["equipment_type"]].append(inst["instance_id"])

    lines = [f"site: Plant", f"facility: {facility_id}", ""]
    lines.append("instances:")
    for eq_type, inst_ids in by_type.items():
        lines.append(f"  {eq_type}:")
        for inst_id in inst_ids:
            lines.append(f"    - id: {inst_id}")
    return "\n".join(lines)


if __name__ == "__main__":
    mcp.run(transport="sse", port=int(os.environ.get("TOPOLOGY_BUILDER_PORT", 8007)))
