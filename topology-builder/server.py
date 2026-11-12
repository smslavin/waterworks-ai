"""topology-builder — MCPServer :8007.

Tools:
  start_discovery          — begin async MQTT (+OPC-UA) crawl, returns discovery_id
  get_discovery_progress   — poll results for a discovery_id
  override_instance_type   — operator correction: reclassify an instance
  preview_discovered_topology — review document of a session's findings (not a loadable topology.yaml)

Committing a reviewed topology to LadybugDB does NOT go through this server —
chat-ui/backend.py's POST /api/topology/commit calls memory__seed_discovered_topology
directly via the aggregator (see fieldworks-core#19).
"""

import asyncio
import logging
import os
import time
import uuid
from pathlib import Path

import yaml
from dotenv import load_dotenv
from mcp.server import MCPServer
from mcp.types import ToolAnnotations

from discovery import discover_mqtt_topics, discover_opcua_nodes
from fieldworks.topology_builder.inference import infer_topology, load_template

load_dotenv(dotenv_path=Path(__file__).parent.parent / ".env")

from fieldworks.service_logging import setup_logging  # noqa: E402

setup_logging(__file__, "topology_builder")
logger = logging.getLogger(__name__)

_TEMPLATES_DIR = Path(__file__).parent / "templates"

mcp = MCPServer("topology-builder")

# Tool annotations (MCP spec hints), forwarded by mcp-aggregator. chat-ui's
# approval gate reads them: a destructive or unannotated tool is never offered
# to a model unless an operator approval can authorize it (chat-ui/control.py).
_READ = ToolAnnotations(read_only_hint=True)
_WRITE = ToolAnnotations(read_only_hint=False, destructive_hint=False)
_DESTRUCTIVE = ToolAnnotations(read_only_hint=False, destructive_hint=True)

_sessions: dict[str, dict] = {}
# Discovery tasks, held so the event loop's weak reference isn't the only one.
_tasks: set[asyncio.Task] = set()

# A finished session (complete or error) is dropped this long after it was
# last used; each holds a full instance list. Running sessions are kept.
_SESSION_TTL_S = float(os.environ.get("TOPOLOGY_SESSION_TTL", 3600))
# Also the cap on concurrent discoveries: each one spawns an adapter process.
_MAX_SESSIONS = int(os.environ.get("TOPOLOGY_MAX_SESSIONS", 20))


def _get_session(discovery_id: str) -> dict | None:
    session = _sessions.get(discovery_id)
    if session is not None:
        session["last_used"] = time.monotonic()
    return session


def _unknown(discovery_id: str) -> dict:
    return {"error": f"Unknown or expired discovery_id: {discovery_id}"}


def _make_room() -> bool:
    """Evict finished sessions past their TTL, then the least recently used
    finished ones until a new session fits. False if every slot is running."""
    now = time.monotonic()
    finished = sorted(
        (s["last_used"], sid)
        for sid, s in _sessions.items()
        if s["status"] != "running"
    )
    for last_used, sid in finished:
        if now - last_used > _SESSION_TTL_S or len(_sessions) >= _MAX_SESSIONS:
            del _sessions[sid]
    return len(_sessions) < _MAX_SESSIONS


@mcp.tool(annotations=_WRITE)
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
    if not _make_room():
        return {
            "error": f"{_MAX_SESSIONS} discoveries are already running; "
            "wait for one to finish and try again."
        }
    discovery_id = str(uuid.uuid4())[:8]
    _sessions[discovery_id] = {
        "status": "running",
        "broker_url": broker_url,
        "template": template,
        "opcua_url": opcua_url,
        "instances": [],
        "stats": {"topics_seen": 0, "instances_found": 0},
        "error": None,
        "last_used": time.monotonic(),
    }
    task = asyncio.create_task(
        _run_discovery(discovery_id, broker_url, opcua_url, template)
    )
    _tasks.add(task)
    task.add_done_callback(_tasks.discard)
    return {
        "discovery_id": discovery_id,
        "status": "running",
        "message": f"Discovery started. Call get_discovery_progress('{discovery_id}') to check results.",
    }


@mcp.tool(annotations=_READ)
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
    session = _get_session(discovery_id)
    if not session:
        return _unknown(discovery_id)
    return {
        "status": session["status"],
        "instances": session["instances"],
        "stats": session["stats"],
        "error": session.get("error"),
    }


@mcp.tool(annotations=_WRITE)
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
    session = _get_session(discovery_id)
    if not session:
        return _unknown(discovery_id)
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


_PREVIEW_HEADER = """\
# Topology discovery preview — a review document, NOT a loadable topology.yaml.
# fieldworks.topology.load() also needs facility, process area and equipment
# type definitions (units, fault modes, descriptions) that discovery can't
# observe. Commit the reviewed instances to LadybugDB instead (POST
# /api/topology/commit), or write topology.yaml by hand from this.
"""


@mcp.tool(annotations=_READ)
async def preview_discovered_topology(discovery_id: str) -> str:
    """Review document of a discovery session's findings, as YAML: each
    instance with its area, type, confidence and tag bindings. Not a
    loadable topology.yaml — see the header it starts with."""
    session = _get_session(discovery_id)
    if not session:
        return f"# Unknown or expired discovery_id: {discovery_id}"
    return _preview_yaml(discovery_id, session)


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
        if not mqtt_topics:
            # A refused connection now raises (see discovery.py's
            # AdapterConnectError) and is caught by the except below. Getting
            # here means the connect itself succeeded but the crawl saw
            # nothing — reachable but empty, or nothing publishing yet. That
            # is reported as an explicit error state, not folded into
            # "complete", since the two are otherwise indistinguishable from
            # a real successful discovery of an empty plant.
            session["status"] = "error"
            session["error"] = (
                f"Connected to MQTT broker at {broker_url} but discovered zero "
                "topics during the crawl window. The broker is reachable but "
                "appears to have no equipment publishing on it."
            )
            return

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


def _preview_yaml(discovery_id: str, session: dict) -> str:
    by_area: dict[str, list[dict]] = {}
    for inst in session["instances"]:
        by_area.setdefault(inst.get("area_id") or "unknown", []).append(
            {
                "id": inst["instance_id"],
                "equipment_type": inst.get("equipment_type"),
                "ladybug_type_id": inst.get("ladybug_type_id") or None,
                "confidence": inst.get("confidence_level"),
                "confidence_score": inst.get("confidence_score"),
                "tags": {
                    attr: info.get("tag")
                    for attr, info in (inst.get("attributes") or {}).items()
                },
            }
        )
    doc = {
        "discovery_id": discovery_id,
        "broker_url": session.get("broker_url"),
        "status": session.get("status"),
        "areas": by_area,
    }
    return _PREVIEW_HEADER + yaml.safe_dump(doc, sort_keys=False)


if __name__ == "__main__":
    mcp.run(transport="sse", port=int(os.environ.get("TOPOLOGY_BUILDER_PORT", 8007)))
