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
import logging.handlers
import os

import httpx
from dotenv import load_dotenv
from mcp.server.fastmcp import FastMCP

load_dotenv()

_log_dir = os.path.join(os.path.dirname(__file__), "logs")
os.makedirs(_log_dir, exist_ok=True)
_fh = logging.handlers.RotatingFileHandler(
    os.path.join(_log_dir, "control_mcp.log"), maxBytes=5 * 1024 * 1024, backupCount=3
)
_fh.setFormatter(logging.Formatter("%(asctime)s %(levelname)s %(name)s: %(message)s",
                                   datefmt="%Y-%m-%d %H:%M:%S"))
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s %(levelname)s %(name)s: %(message)s",
    datefmt="%Y-%m-%d %H:%M:%S",
    handlers=[logging.StreamHandler(), _fh],
)
logger = logging.getLogger(__name__)

SIMULATOR_URL = os.environ.get("SIMULATOR_CONTROL_URL", "http://localhost:8090")
mcp = FastMCP("control-mcp", port=int(os.environ.get("FASTMCP_PORT", 8005)))


@mcp.tool()
def propose_action(
    description: str,
    action_type: str,
    target: str,
    value: str = "",
) -> str:
    """Propose a control action requiring operator approval before execution.

    The backend intercepts this call and presents it to the operator via an
    approval dialog. This tool BLOCKS until the operator decides.
    After approval is returned, call the appropriate execution tool
    (set_setpoint or clear_fault).

    Args:
        description: Plain-language rationale, e.g. "Reduce chlorine dose from
                     3.5 to 2.8 L/h — current reading is elevated vs turbidity trend"
        action_type: "setpoint_adjustment" | "fault_clear"
        target:      Equipment ID (e.g. "Chlorine_01", "RawWater_01")
        value:       New value for setpoint adjustments; omit for fault clears
    """
    # The backend intercepts this before routing through the aggregator.
    # This code only runs if the tool is called directly (not via waterworks-ai).
    return json.dumps({
        "status": "not_intercepted",
        "message": "propose_action must be called through the waterworks-ai backend.",
    })


@mcp.tool()
def set_setpoint(target: str, attribute: str, value: float) -> str:
    """Write a new setpoint value to a process unit in the simulator.

    IMPORTANT: Call propose_action first and receive 'approved' before calling this.

    Args:
        target:    Equipment ID (e.g. "Chlorine_01")
        attribute: Attribute name (e.g. "FlowRate", "Pressure")
        value:     New setpoint value (numeric)
    """
    try:
        resp = httpx.post(
            f"{SIMULATOR_URL}/setpoint",
            params={"target": target, "attribute": attribute, "value": value},
            timeout=5.0,
        )
        data = resp.json()
        return json.dumps(data, indent=2)
    except Exception as exc:
        return f"Error calling simulator /setpoint: {exc}"


@mcp.tool()
def clear_fault(target: str) -> str:
    """Clear an active fault condition and restore a process unit to normal operation.

    IMPORTANT: Call propose_action first and receive 'approved' before calling this.

    Args:
        target: Equipment ID to clear (e.g. "RawWater_01")
    """
    try:
        resp = httpx.post(
            f"{SIMULATOR_URL}/fault",
            params={"target": target, "mode": "normal"},
            timeout=5.0,
        )
        data = resp.json()
        return json.dumps(data, indent=2)
    except Exception as exc:
        return f"Error calling simulator /fault: {exc}"


if __name__ == "__main__":
    mcp.run(transport="sse")
