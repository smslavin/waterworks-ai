"""Shared state for the operator action-approval flow.

The claude_loop generator registers a Future when it intercepts propose_action,
then awaits it. The backend's /api/action/respond endpoint resolves the Future
with the operator's decision, unblocking the generator.

Approval alone does not execute anything: on approval, resolve() also stamps a
one-time grant binding the approved (session, execution tool, exact args). The
generator must present that grant via consume_grant() before dispatching
set_setpoint/clear_fault — a call whose args don't exactly match what the
operator approved is refused, not executed. This closes the gap where the
approval-dialog result was just prompt-visible text: nothing previously
stopped the model from calling the execution tools directly, or with
different args than it proposed.
"""

import asyncio
import hashlib
import json
import time

EXECUTION_TOOLS = {"control__set_setpoint", "control__clear_fault"}

# The fieldworks-adapters mqtt-mcp/opcua-mcp binaries declare no tool
# annotations yet. Until they do, these are the adapter tools known not to
# write to the plant. Anything else they expose (write_tag today, whatever
# ships next) counts as unannotated, so models never see it.
_ADAPTER_READ_ONLY = {
    f"{backend}__{tool}"
    for backend, tools in {
        "mqtt": (
            "discover_tags",
            "get_server_info",
            "get_topic_tree",
            "read_tag",
            "read_tag_history",
            "scan",
        ),
        "opcua": (
            "browse",
            "discover_tags",
            "get_node_tree",
            "get_server_info",
            "read_tag",
            "read_tag_history",
        ),
    }.items()
    for tool in tools
}
# Session bookkeeping on the adapter, not a plant write.
_ADAPTER_NON_DESTRUCTIVE = {
    "mqtt__connect",
    "mqtt__disconnect",
    "opcua__connect",
    "opcua__disconnect",
}


def requires_approval(tool: dict) -> bool:
    """True if a call to `tool` needs an operator approval to run.

    MCP's own defaults decide: a tool is destructive unless it declares
    readOnlyHint=true or destructiveHint=false, so a tool with no
    annotations requires approval. Only EXECUTION_TOOLS can ever be
    approved (build_execution_payload maps proposals to them), so for every
    other tool this means "never offered to a model".
    """
    name = tool["name"]
    if name in _ADAPTER_READ_ONLY or name in _ADAPTER_NON_DESTRUCTIVE:
        return False
    hints = tool.get("annotations") or {}
    if hints.get("readOnlyHint") is True:
        return False
    return hints.get("destructiveHint") is not False


def offered_to_models(tools: list[dict]) -> list[dict]:
    """The tools a model may be offered: everything that needs no
    approval, plus the execution tools an approval can unlock. Drops e.g.
    mqtt__write_tag and influxdb__write_point, which could otherwise inject
    fake readings with no operator in the loop."""
    return [
        t for t in tools if t["name"] in EXECUTION_TOOLS or not requires_approval(t)
    ]


_GRANT_TTL_SECONDS = 300

_pending: dict[str, "asyncio.Future[str]"] = {}
_proposals: dict[str, dict] = {}
_grants: dict[str, tuple[float, str]] = {}  # grant key -> (expiry, action_id)


def build_execution_payload(
    action_type: str, target: str, attribute: str, value: str
) -> tuple[str, dict] | None:
    """Map a propose_action payload to the (tool_name, args) it authorizes.

    Returns None if action_type is unrecognized or value doesn't parse for a
    setpoint adjustment — callers should treat that as "cannot be granted".
    """
    if action_type == "setpoint_adjustment":
        try:
            numeric_value = float(value)
        except (TypeError, ValueError):
            return None
        return "control__set_setpoint", {
            "target": target,
            "attribute": attribute,
            "value": numeric_value,
        }
    if action_type == "fault_clear":
        return "control__clear_fault", {"target": target}
    return None


def _grant_key(session_id: str, tool_name: str, args: dict) -> str:
    def _norm(v):
        return float(v) if isinstance(v, int) and not isinstance(v, bool) else v

    normalized = {k: _norm(v) for k, v in args.items()}
    digest = hashlib.sha256(json.dumps(normalized, sort_keys=True).encode()).hexdigest()
    return f"{session_id}:{tool_name}:{digest}"


def register(action_id: str, proposal: dict) -> "asyncio.Future[str]":
    """Create and store a Future for the given action_id. Returns the Future.

    proposal must contain 'session_id', 'action_type', 'target', 'attribute',
    'value' — the fields needed to compute the grant if approved.
    """
    loop = asyncio.get_event_loop()
    fut: asyncio.Future[str] = loop.create_future()
    _pending[action_id] = fut
    _proposals[action_id] = proposal

    # A timeout or a dropped client cancels the Future without resolve()
    # ever running; drop the entry then too, or it stays here for good.
    def _forget(_fut: "asyncio.Future[str]") -> None:
        _pending.pop(action_id, None)
        _proposals.pop(action_id, None)

    fut.add_done_callback(_forget)
    return fut


def resolve(action_id: str, decision: str) -> bool:
    """Resolve a pending action Future with 'approved' or 'denied'.

    On approval, also stamps a one-time execution grant for the exact payload
    that was proposed. Returns True if the action was found and resolved.
    """
    fut = _pending.pop(action_id, None)
    proposal = _proposals.pop(action_id, None)
    if not fut or fut.done():
        return False

    if decision == "approved" and proposal is not None:
        payload = build_execution_payload(
            proposal.get("action_type", ""),
            proposal.get("target", ""),
            proposal.get("attribute", ""),
            proposal.get("value", ""),
        )
        if payload is not None:
            tool_name, args = payload
            key = _grant_key(proposal["session_id"], tool_name, args)
            _grants[key] = (time.monotonic() + _GRANT_TTL_SECONDS, action_id)

    fut.set_result(decision)
    return True


def consume_grant(session_id: str, tool_name: str, args: dict) -> str | None:
    """Check for and consume a one-time grant matching this exact call.

    Returns the action_id it was granted for (and invalidates the grant) only
    if an unexpired grant exists for this session/tool/args combination, else
    None. The action_id lets the caller record the execution outcome against
    the same action_events row the proposal and decision were recorded on.
    """
    key = _grant_key(session_id, tool_name, args)
    entry = _grants.pop(key, None)
    if entry is None:
        return None
    expires, action_id = entry
    return action_id if time.monotonic() <= expires else None


def pending_ids() -> list[str]:
    return list(_pending.keys())
