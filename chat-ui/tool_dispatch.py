"""One model tool call, dispatched: the approval intercept, gated control
writes, and plain MCP calls, with their audit records and UI events.

Single-agent mode and both Cascade paths in multi-agent mode used to carry
their own copy of this (gh-24). The copies had already drifted: the denial
message read differently by mode, and single-agent wrote no audit record of
what an executed control write returned (fixed in gh-13 before this module
existed). The approval path moves an actuator and writes the compliance
record, so it lives in one place.

    call = ToolCall(name, args, session_id=..., call_tool=call_mcp_tool,
                    action_timeout=_ACTION_TIMEOUT)
    async for event in call.events():
        yield json.dumps(event)
    tool_results.append({..., "content": call.for_history()})
"""

from __future__ import annotations

import asyncio
import uuid
from collections.abc import AsyncIterator, Awaitable, Callable

import audit
import control
import session_store

PROPOSE_ACTION = "control__propose_action"

# Tool results are capped at this length in conversation history, so one
# large InfluxDB payload can't crowd out the context window. The UI event
# and the audit record keep the full text.
TOOL_RESULT_MAX_CHARS = 8_000


class ToolCall:
    """One tool_use block. Iterate events() to run it; afterwards `result`
    holds what goes back to the model and `is_error` whether it failed."""

    def __init__(
        self,
        name: str,
        args: dict,
        *,
        session_id: str,
        call_tool: Callable[[str, dict], Awaitable[str]],
        action_timeout: float,
        audit_fields: dict | None = None,
    ):
        self.name = name
        self.args = dict(args)
        self.session_id = session_id
        self._call_tool = call_tool
        self._timeout = action_timeout
        self._audit_fields = audit_fields or {}
        self.result = ""
        self.is_error = False

    def _audit(self, event: str, **fields) -> None:
        audit.log(event, session_id=self.session_id, **fields, **self._audit_fields)

    async def events(self) -> AsyncIterator[dict]:
        self._audit("tool_call", tool=self.name, args=self.args)
        yield {"type": "tool_call", "tool": self.name, "args": self.args}

        if self.name == PROPOSE_ACTION:
            async for event in self._propose():
                yield event
        elif self.name in control.EXECUTION_TOOLS:
            await self._execute_if_granted()
        else:
            self.result = await self._call_tool(self.name, self.args)
            self.is_error = self.result.startswith("Error")

        self._audit("tool_result", tool=self.name, result=self.result)
        yield {"type": "tool_result", "tool": self.name, "result": self.result}

    def for_history(self) -> str:
        if len(self.result) <= TOOL_RESULT_MAX_CHARS:
            return self.result
        return self.result[:TOOL_RESULT_MAX_CHARS] + "\n[truncated]"

    async def _propose(self) -> AsyncIterator[dict]:
        """Hold the turn until the operator answers. Approval stamps a
        one-time grant for exactly this payload (control.resolve); it
        executes nothing by itself."""
        args = self.args
        proposal = {
            "action_type": args.get("action_type", ""),
            "target": args.get("target", ""),
            "attribute": args.get("attribute", ""),
            "value": args.get("value", ""),
        }
        action_id = str(uuid.uuid4())
        yield {
            "type": "action_proposed",
            "action_id": action_id,
            "description": args.get("description", ""),
            **proposal,
        }
        fut = control.register(action_id, {"session_id": self.session_id, **proposal})
        # Recorded before waiting: a restart or a dropped client while the
        # operator decides must not leave the proposal with no row at all.
        session_store.log_action_proposed(
            action_id=action_id,
            session_id=self.session_id,
            action_type=proposal["action_type"],
            target=proposal["target"],
            value=str(proposal["value"]),
            description=args.get("description", ""),
        )
        try:
            decision = await asyncio.wait_for(fut, timeout=self._timeout)
        except asyncio.TimeoutError:
            decision = "timed_out"

        session_store.log_action_decision(action_id=action_id, decision=decision)
        self._audit("action_decision", action_id=action_id, decision=decision)
        yield {"type": "action_decision", "action_id": action_id, "decision": decision}

        if decision == "approved":
            self.result = (
                f"Action approved by operator. Proceed with "
                f"{proposal['action_type'] or 'action'} on "
                f"{proposal['target'] or 'target'}."
            )
        else:
            self.result = (
                f"Action denied by operator ({decision}). "
                f"No changes will be made to {proposal['target'] or 'target'}."
            )

    async def _execute_if_granted(self) -> None:
        """Run a control write only against a grant for exactly these args."""
        action_id = control.consume_grant(self.session_id, self.name, self.args)
        if action_id is None:
            self.result = (
                "Refused: no matching operator approval for this exact action. "
                "Call propose_action again and use the exact same "
                "target/attribute/value to execute."
            )
            self._audit("unapproved_execution_blocked", tool=self.name, args=self.args)
            return
        self.result = await self._call_tool(self.name, self.args)
        self.is_error = self.result.startswith("Error")
        session_store.log_action_outcome(
            action_id=action_id,
            outcome=f"failed: {self.result[:200]}" if self.is_error else "ok",
        )
