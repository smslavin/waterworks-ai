"""The approval path end to end, through each loop that intercepts it (gh-13).

propose_action is intercepted in three places that don't share code:
single-agent (claude_loop.run_chat), the multi-agent orchestrator, and the
multi-agent follow-up path (_run_cascade_only). Every test here runs against
all three.

Real: control.py (futures and grants), session_store (action_events, in a
scratch metrics.db), audit.py (a scratch audit.jsonl). Faked: the Anthropic
client, which plays a script of tool calls, and the aggregator, which
records each call that reaches it. The operator answers the way the
/api/action/respond endpoint does: control.resolve() from outside the loop,
once the proposal is pending.
"""

import asyncio
import contextlib
import importlib
import json
from types import SimpleNamespace

import pytest

pytest.importorskip("anthropic")

import audit  # noqa: E402
import claude_loop  # noqa: E402
import control  # noqa: E402
import metrics  # noqa: E402
import multi_agent_loop  # noqa: E402
import session_store  # noqa: E402

PROPOSE = "control__propose_action"
SETPOINT = "control__set_setpoint"
CLEAR = "control__clear_fault"

PROPOSAL = {
    "description": "Reduce chlorine dose, residual is elevated",
    "action_type": "setpoint_adjustment",
    "target": "Chlorine_01",
    "attribute": "FlowRate",
    "value": "2.8",
}
EXACT = {"target": "Chlorine_01", "attribute": "FlowRate", "value": 2.8}

_READ = {"readOnlyHint": True, "destructiveHint": None}
_DESTRUCTIVE = {"readOnlyHint": False, "destructiveHint": True}
# What the aggregator lists, annotations included (gh-47). The two write
# tools must never reach a model.
_TOOLS = [
    {"name": n, "description": "", "inputSchema": {"type": "object"}, "annotations": a}
    for n, a in (
        (PROPOSE, _READ),
        (SETPOINT, _DESTRUCTIVE),
        (CLEAR, _DESTRUCTIVE),
        ("audit__list_incidents", _READ),
        ("mqtt__read_tag", None),
        ("mqtt__write_tag", None),
        ("influxdb__write_point", _DESTRUCTIVE),
    )
]


# ── fake Anthropic client ──────────────────────────────────────────────────


def _message(turn):
    usage = SimpleNamespace(
        input_tokens=1,
        output_tokens=1,
        cache_creation_input_tokens=0,
        cache_read_input_tokens=0,
    )
    if not turn:
        return SimpleNamespace(
            content=[SimpleNamespace(type="text", text="Done.")],
            stop_reason="end_turn",
            usage=usage,
        )
    blocks = [
        SimpleNamespace(type="tool_use", id=f"tu_{i}", name=name, input=dict(args))
        for i, (name, args) in enumerate(turn)
    ]
    return SimpleNamespace(content=blocks, stop_reason="tool_use", usage=usage)


class _Stream:
    def __init__(self, message):
        self._message = message

    async def __aenter__(self):
        return self

    async def __aexit__(self, *exc):
        return False

    @property
    def text_stream(self):
        async def gen():
            for block in self._message.content:
                if block.type == "text":
                    yield block.text

        return gen()

    async def get_final_message(self):
        return self._message


class _Model:
    """Plays `script`, a list of turns; each turn is a list of
    (tool_name, args). After the script, every turn is end_turn."""

    def __init__(self, script):
        self._turns = iter(script)
        self.messages = self
        self.offered: list[set[str]] = []  # tool names offered, per turn
        self.sent: list[list[dict]] = []  # messages sent, per turn

    def _next(self, kwargs):
        self.offered.append({t["name"] for t in kwargs.get("tools", [])})
        self.sent.append(kwargs.get("messages", []))
        return _message(next(self._turns, []))

    def stream(self, **kwargs):
        return _Stream(self._next(kwargs))

    async def create(self, **kwargs):
        return self._next(kwargs)


# ── the three loops ────────────────────────────────────────────────────────


async def _no_specialist(
    spec,
    user_message,
    client,
    all_tools,
    session_id,
    model,
    queue,
    tool_calls_all,
    **kwargs,
):
    await queue.put(None)


def _single(model):
    return claude_loop.run_chat(
        [{"role": "user", "content": "Lower the chlorine dose"}],
        "claude-test",
        base_url="http://unused",
    )


def _orchestrator(model):
    return multi_agent_loop.run_multi_agent(
        [{"role": "user", "content": "Lower the chlorine dose"}], "claude-test"
    )


def _cascade_only(model):
    return multi_agent_loop.run_multi_agent(
        [
            {"role": "user", "content": "How is chlorine?"},
            {"role": "assistant", "content": "Residual is elevated."},
            {"role": "user", "content": "Lower the chlorine dose"},
        ],
        "claude-test",
    )


@pytest.fixture(params=["single", "orchestrator", "cascade_only"])
def loop(request):
    return {
        "single": _single,
        "orchestrator": _orchestrator,
        "cascade_only": _cascade_only,
    }[request.param]


class _Aggregator:
    def __init__(self):
        self.calls = []
        self.reply = '{"ok": true}'

    async def call(self, name, args, aggregator_url=None):
        self.calls.append((name, dict(args)))
        return self.reply

    async def list_tools(self, aggregator_url=None):
        return _TOOLS


@pytest.fixture()
def aggregator(monkeypatch):
    return _Aggregator()


@pytest.fixture(autouse=True)
def _scratch_state(monkeypatch, tmp_path, aggregator):
    monkeypatch.setattr(session_store, "_DB_PATH", str(tmp_path / "metrics.db"))
    monkeypatch.setattr(session_store, "_SITE_ID", "wtp")
    session_store._init_db()

    monkeypatch.setenv("AUDIT_LOG_PATH", str(tmp_path / "audit.jsonl"))
    monkeypatch.delenv("AUDIT_KEY", raising=False)
    monkeypatch.setenv("AUDIT_REQUIRE_ENCRYPTION", "0")
    with pytest.warns(UserWarning, match="plaintext"):
        importlib.reload(audit)

    monkeypatch.setattr(metrics, "log_turn", lambda **kw: None)

    async def empty():
        return ""

    for mod in (claude_loop, multi_agent_loop):
        monkeypatch.setattr(mod, "call_mcp_tool", aggregator.call)
        monkeypatch.setattr(mod, "list_mcp_tools", aggregator.list_tools)
        monkeypatch.setattr(mod, "_fetch_process_state", empty)
        monkeypatch.setattr(mod, "_ACTION_TIMEOUT", 5)
    monkeypatch.setattr(claude_loop, "_fetch_fault_history", empty)
    monkeypatch.setattr(multi_agent_loop, "_run_specialist", _no_specialist)

    control._pending.clear()
    control._proposals.clear()
    control._grants.clear()
    yield
    control._pending.clear()
    control._proposals.clear()
    control._grants.clear()


def _run(monkeypatch, loop, script, decision=None, model=None):
    """Run one chat turn. When a proposal is pending, answer it with
    `decision` (None: never answer). Returns (events, row_while_pending)."""
    model = model or _Model(script)
    for mod in (claude_loop, multi_agent_loop):
        monkeypatch.setattr(mod.anthropic, "AsyncAnthropic", lambda **kw: model)

    seen_pending = []

    async def operator():
        while not control._pending:
            await asyncio.sleep(0.001)
        action_id = next(iter(control._pending))
        seen_pending.append(_event_row(action_id))
        if decision is not None:
            control.resolve(action_id, decision)

    async def body():
        answer = asyncio.create_task(operator())
        events = [json.loads(chunk) async for chunk in loop(model)]
        answer.cancel()
        with contextlib.suppress(asyncio.CancelledError):
            await answer
        return events

    return asyncio.run(body()), (seen_pending[0] if seen_pending else None)


def _event_row(action_id):
    return next(
        e for e in session_store.get_action_events() if e["action_id"] == action_id
    )


def _only_action():
    rows = session_store.get_action_events()
    assert len(rows) == 1, rows
    return rows[0]


def _audit(event):
    return [r for r in audit.read_log() if r.get("event") == event]


def _writes(aggregator):
    return [c for c in aggregator.calls if c[0] in control.EXECUTION_TOOLS]


# ── approve ────────────────────────────────────────────────────────────────


def test_approved_exact_call_executes_once_and_records_ok(
    monkeypatch, loop, aggregator
):
    events, pending_row = _run(
        monkeypatch, loop, [[(PROPOSE, PROPOSAL)], [(SETPOINT, EXACT)]], "approved"
    )

    # The proposal has a durable row before the operator answers.
    assert pending_row["decision"] == "pending"
    assert pending_row["outcome"] == "pending"

    assert _writes(aggregator) == [(SETPOINT, EXACT)]
    assert PROPOSE not in [c[0] for c in aggregator.calls]  # never forwarded
    row = _only_action()
    assert (row["decision"], row["outcome"]) == ("approved", "ok")
    assert row["target"] == "Chlorine_01"

    assert [r["decision"] for r in _audit("action_decision")] == ["approved"]
    assert not _audit("unapproved_execution_blocked")
    executed = [r for r in _audit("tool_result") if r["tool"] == SETPOINT]
    assert len(executed) == 1 and executed[0]["result"] == '{"ok": true}'
    assert any(e["type"] == "action_proposed" for e in events)


def test_grant_is_spent_by_the_first_execution(monkeypatch, loop, aggregator):
    _run(
        monkeypatch,
        loop,
        [[(PROPOSE, PROPOSAL)], [(SETPOINT, EXACT)], [(SETPOINT, EXACT)]],
        "approved",
    )

    assert _writes(aggregator) == [(SETPOINT, EXACT)]
    assert len(_audit("unapproved_execution_blocked")) == 1


def test_approved_but_drifted_value_is_refused(monkeypatch, loop, aggregator):
    drifted = {**EXACT, "value": 3.0}
    _run(monkeypatch, loop, [[(PROPOSE, PROPOSAL)], [(SETPOINT, drifted)]], "approved")

    assert _writes(aggregator) == []
    blocked = _audit("unapproved_execution_blocked")
    assert [b["args"] for b in blocked] == [drifted]
    # Approved but never executed: outcome stays pending, for
    # recover_abandoned_actions to settle, never 'ok'.
    row = _only_action()
    assert (row["decision"], row["outcome"]) == ("approved", "pending")


def test_failed_execution_records_the_failure(monkeypatch, loop, aggregator):
    # What control-mcp's ToolError reaches chat-ui as (mcp 2.0 through 2.3).
    aggregator.reply = (
        "Error executing tool set_setpoint: simulator rejected /setpoint (400): "
        '{"error":"99.0 outside engineering limits [0, 10] for Chlorine_01.FlowRate"}'
    )
    _run(monkeypatch, loop, [[(PROPOSE, PROPOSAL)], [(SETPOINT, EXACT)]], "approved")

    row = _only_action()
    assert row["decision"] == "approved"
    assert row["outcome"].startswith("failed: ")
    assert "outside engineering limits" in row["outcome"]


# ── deny / timeout / no proposal ───────────────────────────────────────────


def test_denied_action_cannot_execute(monkeypatch, loop, aggregator):
    _run(monkeypatch, loop, [[(PROPOSE, PROPOSAL)], [(SETPOINT, EXACT)]], "denied")

    assert _writes(aggregator) == []
    row = _only_action()
    assert (row["decision"], row["outcome"]) == ("denied", "not_executed")
    assert [r["decision"] for r in _audit("action_decision")] == ["denied"]
    assert len(_audit("unapproved_execution_blocked")) == 1


def test_unanswered_proposal_times_out_and_cannot_execute(
    monkeypatch, loop, aggregator
):
    for mod in (claude_loop, multi_agent_loop):
        monkeypatch.setattr(mod, "_ACTION_TIMEOUT", 0.05)

    _run(monkeypatch, loop, [[(PROPOSE, PROPOSAL)], [(SETPOINT, EXACT)]], None)

    assert _writes(aggregator) == []
    row = _only_action()
    assert (row["decision"], row["outcome"]) == ("timed_out", "not_executed")
    assert [r["decision"] for r in _audit("action_decision")] == ["timed_out"]
    assert control._pending == {}  # nothing left for a late answer to approve


@pytest.mark.parametrize(
    "tool,args", [(SETPOINT, EXACT), (CLEAR, {"target": "RawWater_01"})]
)
def test_execution_without_a_proposal_is_refused(
    monkeypatch, loop, aggregator, tool, args
):
    events, pending_row = _run(monkeypatch, loop, [[(tool, args)]])

    assert pending_row is None
    assert _writes(aggregator) == []
    assert session_store.get_action_events() == []
    blocked = _audit("unapproved_execution_blocked")
    assert [(b["tool"], b["args"]) for b in blocked] == [(tool, args)]
    refused = [r for r in _audit("tool_result") if r["tool"] == tool]
    assert len(refused) == 1 and refused[0]["result"].startswith("Refused")
    assert any(
        e["type"] == "tool_result" and e["result"].startswith("Refused") for e in events
    )


# ── what a model is offered (gh-47) ────────────────────────────────────────


def test_models_are_offered_the_approval_tools_but_no_raw_writes(
    monkeypatch, loop, aggregator
):
    model = _Model([])
    _run(monkeypatch, loop, [], model=model)

    offered = model.offered[0]
    assert {PROPOSE, SETPOINT, CLEAR, "audit__list_incidents"} <= offered
    assert "mqtt__write_tag" not in offered
    assert "influxdb__write_point" not in offered


# ── one dispatcher for all three loops (gh-24) ─────────────────────────────


def test_denial_reads_the_same_in_every_loop(monkeypatch, loop, aggregator):
    """The copies had drifted: multi-agent said "No changes to X"."""
    events, _ = _run(monkeypatch, loop, [[(PROPOSE, PROPOSAL)]], "denied")
    results = [e["result"] for e in events if e["type"] == "tool_result"]
    assert results == [
        "Action denied by operator (denied). No changes will be made to Chlorine_01."
    ]


def test_long_tool_results_are_truncated_in_history(monkeypatch, loop, aggregator):
    """Cascade's follow-up path used to send whole tool results back."""
    aggregator.reply = "x" * 20_000
    model = _Model([[("audit__list_incidents", {})]])
    events, _ = _run(monkeypatch, loop, [], model=model)

    history_result = model.sent[1][-1]["content"][-1]["content"]
    assert history_result == "x" * 8_000 + "\n[truncated]"
    # The UI event and the audit record keep the full result.
    shown = [e for e in events if e["type"] == "tool_result"]
    assert shown[0]["result"] == "x" * 20_000
    assert [r["result"] for r in _audit("tool_result")] == ["x" * 20_000]
