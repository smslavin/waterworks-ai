"""Control MCP server — write-back and action proposals for the WTP.

Tools
-----
propose_action   Signal intent to change a process parameter.
                 The waterworks-ai backend INTERCEPTS this call before it reaches
                 the aggregator — it blocks until the operator approves or denies.
set_setpoint     Write a new setpoint value to the simulator.
clear_fault      Clear an active fault condition on a process unit.

Environment variables
---------------------
SIMULATOR_CONTROL_URL  Simulator HTTP endpoint  (default: http://localhost:8090)
FASTMCP_PORT           Port to bind              (default: 8005)
"""

import json
import logging
import os
import sys
from pathlib import Path

import httpx
from dotenv import load_dotenv
from mcp.server import MCPServer
from mcp.server.mcpserver.exceptions import ToolError
from mcp.types import ToolAnnotations

load_dotenv()

sys.path.append(str(Path(__file__).resolve().parents[1]))  # repo root
from service_logging import setup_logging  # noqa: E402

setup_logging(__file__, "control_mcp")
logger = logging.getLogger(__name__)

SIMULATOR_URL = os.environ.get("SIMULATOR_CONTROL_URL", "http://localhost:8090")
mcp = MCPServer("control-mcp")

# Tool annotations (MCP spec hints), forwarded by mcp-aggregator. chat-ui's
# approval gate reads them: a destructive or unannotated tool is never offered
# to a model unless an operator approval can authorize it (chat-ui/control.py).
_READ = ToolAnnotations(read_only_hint=True)
_WRITE = ToolAnnotations(read_only_hint=False, destructive_hint=False)
_DESTRUCTIVE = ToolAnnotations(read_only_hint=False, destructive_hint=True)


def _post_to_simulator(path: str, params: dict) -> str:
    """POST to the simulator's control plane and return its JSON reply.

    Raises ToolError on a transport failure or a non-2xx reply, which
    MCPServer turns into an is_error result. The simulator answers a rejected
    write (unknown attribute, out of engineering limits) with 4xx and a JSON
    body; returned as plain text, that body read as success and the backend
    recorded the action's outcome as 'ok' for a write that never happened.
    ToolError, not a bare exception: from mcp 2.3 on, MCPServer replaces any
    other exception's message with "Error executing tool <name>", and the
    reason would never reach action_events.outcome.
    """
    try:
        resp = httpx.post(f"{SIMULATOR_URL}{path}", params=params, timeout=5.0)
    except httpx.HTTPError as exc:
        raise ToolError(f"simulator unreachable at {path}: {exc}") from exc
    if resp.is_error:
        raise ToolError(f"simulator rejected {path} ({resp.status_code}): {resp.text}")
    return json.dumps(resp.json(), indent=2)


@mcp.tool(annotations=_READ)
def propose_action(
    description: str,
    action_type: str,
    target: str,
    attribute: str = "",
    value: str = "",
) -> str:
    """Propose a control action requiring operator approval before execution.

    The backend intercepts this call and presents it to the operator via an
    approval dialog. This tool BLOCKS until the operator decides.
    After approval is returned, call the matching execution tool
    (set_setpoint or clear_fault) with the EXACT SAME target/attribute/value —
    the backend only executes calls that match what was approved.

    Args:
        description: Plain-language rationale, e.g. "Reduce chlorine dose from
                     3.5 to 2.8 L/h — current reading is elevated vs turbidity trend"
        action_type: "setpoint_adjustment" | "fault_clear"
        target:      Equipment ID (e.g. "Chlorine_01", "RawWater_01")
        attribute:   Attribute name for setpoint adjustments (e.g. "FlowRate");
                     omit for fault clears
        value:       New value for setpoint adjustments; omit for fault clears
    """
    # The backend intercepts this before routing through the aggregator.
    # This code only runs if the tool is called directly (not via waterworks-ai).
    return json.dumps(
        {
            "status": "not_intercepted",
            "message": "propose_action must be called through the waterworks-ai backend.",
        }
    )


@mcp.tool(annotations=_DESTRUCTIVE)
def set_setpoint(target: str, attribute: str, value: float) -> str:
    """Write a new setpoint value to a process unit in the simulator.

    IMPORTANT: Call propose_action first and receive 'approved' before calling this.

    Args:
        target:    Equipment ID (e.g. "Chlorine_01")
        attribute: Attribute name (e.g. "FlowRate", "Pressure")
        value:     New setpoint value (numeric)
    """
    return _post_to_simulator(
        "/setpoint", {"target": target, "attribute": attribute, "value": value}
    )


@mcp.tool(annotations=_DESTRUCTIVE)
def clear_fault(target: str) -> str:
    """Clear an active fault condition and restore a process unit to normal operation.

    IMPORTANT: Call propose_action first and receive 'approved' before calling this.

    Args:
        target: Equipment ID to clear (e.g. "RawWater_01")
    """
    return _post_to_simulator("/fault", {"target": target, "mode": "normal"})


if __name__ == "__main__":
    mcp.run(
        transport="sse",
        port=int(
            os.environ.get("CONTROL_MCP_PORT", os.environ.get("FASTMCP_PORT", 8005))
        ),
    )
