"""Which tools a model may be offered, decided by MCP tool annotations (gh-47).

control.requires_approval() applies the MCP spec's defaults: a tool is
destructive unless it declares readOnlyHint=true or destructiveHint=false.
Only control__set_setpoint/clear_fault can be approved, so every other tool
that requires approval is never offered to a model. Before gh-47, specialists
were offered every mqtt__* and influxdb__* tool, including mqtt__write_tag
and influxdb__write_point, which publish or store readings with no operator
in the loop.
"""

import ast
import asyncio
import importlib.util
from pathlib import Path

import pytest

import control
import multi_agent_loop

ROOT = Path(__file__).parent.parent
SERVERS = [
    "control-mcp/server.py",
    "influxdb-mcp/server.py",
    "audit-mcp/server.py",
    "memory-mcp/server.py",
    "topology-builder/server.py",
]

READ = {"readOnlyHint": True, "destructiveHint": None}
WRITE = {"readOnlyHint": False, "destructiveHint": False}
DESTRUCTIVE = {"readOnlyHint": False, "destructiveHint": True}


def _tool(name, annotations=None):
    return {
        "name": name,
        "description": "",
        "inputSchema": {},
        "annotations": annotations,
    }


@pytest.mark.parametrize(
    "tool,needs_approval",
    [
        (_tool("audit__list_incidents", READ), False),
        (_tool("audit__resolve_review", WRITE), False),
        (_tool("control__set_setpoint", DESTRUCTIVE), True),
        (_tool("influxdb__write_point", DESTRUCTIVE), True),
        # MCP defaults: no annotations, or readOnlyHint=false alone, is destructive.
        (_tool("newbackend__do_thing"), True),
        (
            _tool(
                "newbackend__do_thing", {"readOnlyHint": False, "destructiveHint": None}
            ),
            True,
        ),
        # fieldworks-adapters >= 1.0.5 declare their hints (adapters#15).
        (_tool("mqtt__read_tag", READ), False),
        (_tool("mqtt__scan", READ), False),
        (_tool("mqtt__connect", WRITE), False),
        (_tool("mqtt__write_tag", DESTRUCTIVE), True),
        (_tool("opcua__write_tag", DESTRUCTIVE), True),
        # An older adapter binary declares nothing, so its reads are hidden too.
        (_tool("mqtt__read_tag"), True),
    ],
    ids=lambda v: v["name"] if isinstance(v, dict) else str(v),
)
def test_requires_approval(tool, needs_approval):
    assert control.requires_approval(tool) is needs_approval


def test_offered_keeps_approvable_writes_and_drops_the_rest():
    tools = [
        _tool("control__propose_action", READ),
        _tool("control__set_setpoint", DESTRUCTIVE),
        _tool("control__clear_fault", DESTRUCTIVE),
        _tool("mqtt__read_tag", READ),
        _tool("mqtt__write_tag", DESTRUCTIVE),
        _tool("influxdb__write_point", DESTRUCTIVE),
        _tool("memory__seed_discovered_topology", DESTRUCTIVE),
    ]
    offered = {t["name"] for t in control.offered_to_models(tools)}
    assert offered == {
        "control__propose_action",
        "control__set_setpoint",
        "control__clear_fault",
        "mqtt__read_tag",
    }


def test_specialists_lose_the_raw_write_tools():
    """The specialist prefixes (mqtt__, influxdb__) used to pass these through."""
    tools = [
        _tool("mqtt__read_tag", READ),
        _tool("mqtt__write_tag", DESTRUCTIVE),
        _tool("influxdb__query", READ),
        _tool("influxdb__write_point", DESTRUCTIVE),
    ]
    prefixes = multi_agent_loop._MQTT_PREFIXES + multi_agent_loop._INFLUXDB_PREFIXES
    names = {t["name"] for t in multi_agent_loop._filter_tools(tools, prefixes)}
    assert names == {"mqtt__read_tag", "influxdb__query"}


# ── every tool this repo serves declares its annotations ───────────────────


def _tool_decorators(path):
    """(function name, has annotations=) for each @mcp.tool(...) in a file.
    Parsed, not imported: importing memory-mcp's server writes real data."""
    tree = ast.parse((ROOT / path).read_text())
    for node in ast.walk(tree):
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
            for dec in node.decorator_list:
                if (
                    isinstance(dec, ast.Call)
                    and isinstance(dec.func, ast.Attribute)
                    and dec.func.attr == "tool"
                ):
                    yield node.name, any(k.arg == "annotations" for k in dec.keywords)


@pytest.mark.parametrize("path", SERVERS)
def test_every_served_tool_declares_annotations(path):
    tools = list(_tool_decorators(path))
    assert tools, f"no @mcp.tool found in {path}"
    missing = [name for name, annotated in tools if not annotated]
    assert missing == [], f"{path}: unannotated tools {missing}"


def test_control_mcp_annotations_match_the_execution_tools():
    """What control-mcp declares, read back over MCP, must agree with
    control.EXECUTION_TOOLS: the approvable tools are exactly its
    destructive ones, and propose_action stays visible."""
    pytest.importorskip("mcp.client")
    from mcp.client import Client

    spec = importlib.util.spec_from_file_location(
        "control_mcp_server_annotations", ROOT / "control-mcp" / "server.py"
    )
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)

    async def listed():
        async with Client(mod.mcp) as client:
            return (await client.list_tools()).tools

    tools = [
        _tool(
            f"control__{t.name}",
            {
                "readOnlyHint": t.annotations.read_only_hint,
                "destructiveHint": t.annotations.destructive_hint,
            },
        )
        for t in asyncio.run(listed())
    ]
    gated = {t["name"] for t in tools if control.requires_approval(t)}
    assert gated == control.EXECUTION_TOOLS
    assert "control__propose_action" in {
        t["name"] for t in control.offered_to_models(tools)
    }
