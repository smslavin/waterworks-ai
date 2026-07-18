"""Claude API chat loop with MCP tool calling. Yields SSE-ready JSON strings."""

import asyncio
import json
import logging
import os
import time
import uuid
from typing import AsyncIterator

import anthropic
from influxdb_client import InfluxDBClient

import audit
import control
import metrics
import session_store
from mcp_client import call_mcp_tool, list_mcp_tools
from topology import load as _load_topology

logger = logging.getLogger(__name__)

TOOL_RESULT_MAX_CHARS = 8_000
MAX_HISTORY_MESSAGES = 20  # ~10 conversation turns

CONTEXT_WINDOW_TOKENS = int(os.environ.get("CONTEXT_WINDOW_TOKENS", "200000"))
_CONTEXT_WARN_PCT = 0.70
_CONTEXT_COMPACT_PCT = 0.85

_INFLUXDB_URL = os.environ.get("INFLUXDB_URL", "http://localhost:8086")
_INFLUXDB_TOKEN = os.environ.get("INFLUXDB_TOKEN", "")
_INFLUXDB_ORG = os.environ.get("INFLUXDB_ORG", "waterworks")
_INFLUXDB_BUCKET = os.environ.get("INFLUXDB_BUCKET", "waterworks")

_process_state_cache: tuple[float, str] | None = None
_PROCESS_STATE_TTL = 60.0
_unit_running: dict[str, bool] = (
    {}
)  # populated by _fetch_process_state; keyed by unit name

_topo = _load_topology()
_TYPE_ORDER = [et.name for et in _topo.equipment_types]
_LABEL_OVERRIDES = {"UV": "UV", "Dosing": "Dosing", "StorageTank": "Storage Tanks"}
_TYPE_LABELS = {k: _LABEL_OVERRIDES.get(k, k + "s") for k in _TYPE_ORDER}

# Tool name as exposed by the aggregator (backend_name__tool_name)
_PROPOSE_ACTION_TOOL = "control__propose_action"
_ACTION_TIMEOUT = 300  # seconds to wait for operator decision


def _query_fault_history() -> str:
    """Synchronous InfluxDB query — run via asyncio.to_thread."""
    client = InfluxDBClient(url=_INFLUXDB_URL, token=_INFLUXDB_TOKEN, org=_INFLUXDB_ORG)
    try:
        flux = f"""
from(bucket: "{_INFLUXDB_BUCKET}")
  |> range(start: -30d)
  |> filter(fn: (r) => r._measurement == "wtp_fault_events" and r._field == "mode")
  |> sort(columns: ["_time"], desc: true)
  |> limit(n: 10)
"""
        tables = client.query_api().query(flux)
        events = []
        for table in tables:
            for record in table.records:
                ts = record.get_time().strftime("%Y-%m-%d %H:%M UTC")
                target = record.values.get("target", "?")
                mode = record.get_value()
                events.append(f"  {ts}  {target} → {mode}")
        if not events:
            return ""
        lines = "\n".join(events)
        return (
            "\n\n── Recent fault history (last 10 events) "
            "─────────────────────────────────────\n" + lines
        )
    finally:
        client.close()


async def _fetch_fault_history() -> str:
    try:
        return await asyncio.to_thread(_query_fault_history)
    except Exception as exc:
        logger.warning("Could not fetch fault history from InfluxDB: %s", exc)
        return ""


def _parse_topic_tree(raw: str) -> dict[str, dict[str, list[str]]]:
    """Parse get_full_topic_tree output into {type: {running: [...], stopped: [...]}}."""
    current_type: str | None = None
    current_instance: str | None = None
    units: dict[str, dict[str, list[str]]] = {}

    for line in raw.splitlines():
        stripped = line.lstrip()
        if not stripped or stripped.startswith("["):
            continue
        depth = (len(line) - len(stripped)) // 2
        key, _, val = stripped.partition(" = ")
        val = val.strip() if val else None

        if depth == 2:
            current_type = key
            current_instance = None
            if current_type not in units:
                units[current_type] = {"running": [], "stopped": []}
        elif depth == 3 and current_type:
            current_instance = key
        elif (
            depth == 4
            and current_type
            and current_instance
            and key == "Running"
            and val is not None
        ):
            bucket = "running" if val.lower() in ("true", "1") else "stopped"
            units[current_type][bucket].append(current_instance)

    return units


def _format_process_state(units: dict[str, dict[str, list[str]]]) -> str:
    """Format parsed unit states into a compact grouped running-state summary."""
    if not units:
        return "Process units: unavailable"

    lines = []
    ordered = [t for t in _TYPE_ORDER if t in units]
    ordered += sorted(t for t in units if t not in _TYPE_ORDER)
    for type_key in ordered:
        label = _TYPE_LABELS.get(type_key, type_key)
        data = units[type_key]
        run_s = ", ".join(data["running"]) or "none"
        stop_s = ", ".join(data["stopped"])
        row = f"{label:<10} Running: {run_s}"
        if stop_s:
            row += f"\n           Stopped: {stop_s}"
        lines.append(row)

    return "\n".join(lines)


def running_state_for(unit_names: list[str]) -> str:
    """Return a compact running-state string for a subset of units (for specialist prompts)."""
    if not _unit_running:
        return ""
    running = [u for u in unit_names if _unit_running.get(u, False)]
    stopped = [u for u in unit_names if not _unit_running.get(u, False)]
    parts = []
    if running:
        parts.append(f"Running: {', '.join(running)}")
    if stopped:
        parts.append(f"Stopped: {', '.join(stopped)}")
    return "  ".join(parts) if parts else ""


async def _fetch_process_state() -> str:
    global _process_state_cache, _unit_running
    if (
        _process_state_cache
        and (time.monotonic() - _process_state_cache[0]) < _PROCESS_STATE_TTL
    ):
        return _process_state_cache[1]
    try:
        raw = await asyncio.wait_for(
            call_mcp_tool("mqtt__get_full_topic_tree", {}),
            timeout=10.0,
        )
        parsed = _parse_topic_tree(raw)
        _unit_running = {
            name: True for data in parsed.values() for name in data["running"]
        }
        _unit_running.update(
            {name: False for data in parsed.values() for name in data["stopped"]}
        )
        state = _format_process_state(parsed)
    except Exception as exc:
        logger.warning("Could not fetch process state from MQTT: %s", exc)
        state = "Process units: unavailable (MQTT not reachable)"
    _process_state_cache = (time.monotonic(), state)
    return state


def build_system_prompt(process_units: str, alarm_history: str) -> str:
    return _SYSTEM_PROMPT_BASE.format(
        process_units=process_units,
        alarm_history=alarm_history,
    )


CLAUDE_MODELS = [
    "claude-sonnet-4-6",
    "claude-opus-4-7",
    "claude-haiku-4-5-20251001",
]

_SYSTEM_PROMPT_BASE = """You are a process diagnostics assistant for a water treatment plant (WTP).

You have access to tools that read live sensor data via MQTT and OPC-UA, query
historical trends from InfluxDB, review past diagnostic sessions via audit tools,
and propose control actions for operator approval.

── Process units (live) ───────────────────────────────────────────────────────
{process_units}

Attributes by unit type:
  Pumps   Flow (L/min), Pressure (bar), Power (kW), Running (bool)
  Tanks   Level (%), Turbidity (NTU), pH (finished water only)
  Dosing  FlowRate (L/h), Running (bool), TankLevel (%)
  UV      Intensity (%), Running (bool), LampHours

── Data access ────────────────────────────────────────────────────────────────
MQTT topic root : Plant/WTP/<Type>/<Instance>/<Attribute>
OPC-UA endpoint : opc.tcp://localhost:4840/waterworks  (call connect_server first)
InfluxDB        : call list_measurements to discover available data

── Diagnostic approach ────────────────────────────────────────────────────────
1. Read current values via MQTT or OPC-UA to establish present state
2. Compare against expected ranges for the unit type
3. Look for correlated anomalies (e.g. Flow≈0 + Power≈0 + Running=True → run-status fault)
4. Query InfluxDB for historical context when current readings alone are ambiguous

── Tool selection ─────────────────────────────────────────────────────────────
For broad queries (health overview, all pumps, full plant): use get_full_topic_tree()
— it returns every live value in one call. Do NOT call read_topic_value repeatedly
for a plant-wide snapshot; that is wasteful and slow.

For targeted queries (one unit, one attribute): use read_topic_value(topic_path).

Always cite specific values and timestamps (e.g. "Flow is 12.4 L/min at 14:32:05").
Do not assert a value without first reading it from a tool.

── Control actions ────────────────────────────────────────────────────────────
You can propose and execute process control changes using control tools:
  propose_action(description, action_type, target, value)
    → Presents the action to the operator for explicit approval.
    → action_type: "setpoint_adjustment" | "fault_clear"
    → BLOCKS until the operator approves or denies — do not loop on this call.
  set_setpoint(target, attribute, value)   → Adjust a process setpoint
  clear_fault(target)                       → Restore a unit to normal

ALWAYS call propose_action first. Only proceed with set_setpoint or clear_fault
after the response confirms "Action approved by operator". Never execute a
control change without prior operator approval in the same session.

── Topology builder ───────────────────────────────────────────────────────────
The topology_builder__ tools discover plant equipment automatically from MQTT topics.
Workflow:
  1. Call start_discovery(broker_url) → returns a discovery_id immediately
  2. Poll get_discovery_progress(discovery_id) until status is 'complete'
  3. Present the discovered instances to the operator

IMPORTANT: Do NOT claim the topology has been committed or saved. Committing to
LadybugDB requires explicit operator action via the UI 'Commit to DB' button.
After presenting the results, tell the operator to review the graph and click that
button when satisfied. Your responsibility ends at presenting the discovery summary.
Topology builder only works in Single Agent mode.

── Audit history ──────────────────────────────────────────────────────────────
Use audit tools to answer questions about past incidents and decisions:
  list_incidents(date, hours_back)             → Recent fault/anomaly sessions
  get_session_summary(session_id)              → Full detail + actions for one session
  query_by_equipment(equipment_id, hours_back) → Sessions for a specific unit
  query_history(start, end, equipment)         → Narrative-ready time range query{alarm_history}

── Diagnostic output format ───────────────────────────────────────────────────
When diagnosing a specific piece of equipment, end your response with this block:
FINDINGS:
Status: Normal | Anomaly Detected | Fault Detected
Confidence: 0.0–1.0
Key observations:
- [bullet points]

Omit this block for general conversation, plant-wide overviews, or follow-up
questions that do not constitute a fresh equipment diagnosis."""


async def run_chat(
    messages: list[dict],
    model: str,
    *,
    base_url: str,
    api_key: str | None = None,
    thinking_enabled: bool = False,
    **kwargs,
) -> AsyncIterator[str]:
    session_id = str(uuid.uuid4())
    start_ts = time.monotonic()
    input_tokens = output_tokens = 0
    tool_call_count = error_count = 0
    last_input_tokens = 0
    cache_creation_input_tokens = cache_read_input_tokens = 0
    _warn_triggered = False
    _compact_triggered = False
    user_message = next(
        (m["content"] for m in reversed(messages) if m["role"] == "user"), ""
    )

    audit.log(
        "session_start", session_id=session_id, model=model, user_message=user_message
    )

    effective_model = "claude-opus-4-7" if thinking_enabled else model
    client = anthropic.AsyncAnthropic(api_key=api_key, base_url=base_url)

    mcp_tools = await list_mcp_tools()
    tools = [
        {
            "name": t["name"],
            "description": t["description"],
            "input_schema": t["inputSchema"],
        }
        for t in mcp_tools
    ]

    conv_messages = list(messages)
    if len(conv_messages) > MAX_HISTORY_MESSAGES:
        conv_messages = conv_messages[-MAX_HISTORY_MESSAGES:]
        while conv_messages and conv_messages[0]["role"] != "user":
            conv_messages = conv_messages[1:]

    if len(conv_messages) == 1:
        process_units, alarm_history = await asyncio.gather(
            _fetch_process_state(),
            _fetch_fault_history(),
        )
    else:
        process_units = await _fetch_process_state()
        alarm_history = ""
    cached_system = [
        {
            "type": "text",
            "text": build_system_prompt(process_units, alarm_history),
            "cache_control": {"type": "ephemeral"},
        }
    ]

    # Track all tool calls for equipment extraction at session end
    _tool_calls_made: list[tuple[str, dict]] = []
    _final_response_text = ""

    try:
        while True:
            stream_kwargs: dict = dict(
                model=effective_model,
                max_tokens=8192,
                system=cached_system,
                messages=conv_messages,
            )
            if tools:
                cached_tools = list(tools)
                cached_tools[-1] = {
                    **cached_tools[-1],
                    "cache_control": {"type": "ephemeral"},
                }
                stream_kwargs["tools"] = cached_tools
            if thinking_enabled:
                stream_kwargs["thinking"] = {"type": "adaptive"}
                stream_kwargs["output_config"] = {"effort": "high"}

            async with client.messages.stream(**stream_kwargs) as stream:
                if thinking_enabled:
                    _in_thinking = False
                    _thinking_streamed = False
                    async for event in stream:
                        if event.type == "content_block_start":
                            cb = getattr(event, "content_block", None)
                            if cb and getattr(cb, "type", None) == "thinking":
                                _in_thinking = True
                        elif event.type == "content_block_stop":
                            if _in_thinking:
                                _in_thinking = False
                                _thinking_streamed = True
                                yield json.dumps({"type": "thinking_stop"})
                        elif event.type == "content_block_delta":
                            delta = event.delta
                            if _in_thinking and hasattr(delta, "thinking"):
                                yield json.dumps(
                                    {"type": "thinking_delta", "text": delta.thinking}
                                )
                            elif not _in_thinking and hasattr(delta, "text"):
                                yield json.dumps({"type": "text", "text": delta.text})
                else:
                    async for text in stream.text_stream:
                        yield json.dumps({"type": "text", "text": text})

                final = await stream.get_final_message()

                if thinking_enabled and not _thinking_streamed:
                    for block in final.content:
                        if hasattr(block, "thinking") and block.thinking:
                            yield json.dumps(
                                {"type": "thinking_delta", "text": block.thinking}
                            )
                            yield json.dumps({"type": "thinking_stop"})
                            break

            last_input_tokens = final.usage.input_tokens
            input_tokens += last_input_tokens
            output_tokens += final.usage.output_tokens
            cache_creation_input_tokens += final.usage.cache_creation_input_tokens or 0
            cache_read_input_tokens += final.usage.cache_read_input_tokens or 0

            if final.stop_reason == "end_turn":
                text_content = " ".join(
                    b.text for b in final.content if hasattr(b, "text")
                )
                _final_response_text = text_content
                audit.log("response", session_id=session_id, text=text_content)
                break

            if final.stop_reason == "tool_use":
                # Build assistant message for conversation history
                assistant_content = []
                for block in final.content:
                    if block.type == "text":
                        assistant_content.append({"type": "text", "text": block.text})
                    elif block.type == "tool_use":
                        assistant_content.append(
                            {
                                "type": "tool_use",
                                "id": block.id,
                                "name": block.name,
                                "input": dict(block.input),
                            }
                        )

                tool_results = []
                for block in final.content:
                    if block.type != "tool_use":
                        continue
                    tool_call_count += 1
                    args = dict(block.input)
                    _tool_calls_made.append((block.name, args))

                    audit.log(
                        "tool_call", session_id=session_id, tool=block.name, args=args
                    )
                    yield json.dumps(
                        {"type": "tool_call", "tool": block.name, "args": args}
                    )

                    # ── propose_action intercept ───────────────────────────────
                    if block.name == _PROPOSE_ACTION_TOOL:
                        action_id = str(uuid.uuid4())[:8]
                        yield json.dumps(
                            {
                                "type": "action_proposed",
                                "action_id": action_id,
                                "description": args.get("description", ""),
                                "action_type": args.get("action_type", ""),
                                "target": args.get("target", ""),
                                "value": args.get("value", ""),
                            }
                        )
                        fut = control.register(action_id)
                        try:
                            decision = await asyncio.wait_for(
                                fut, timeout=_ACTION_TIMEOUT
                            )
                        except asyncio.TimeoutError:
                            decision = "timed_out"

                        session_store.log_action_event(
                            session_id=session_id,
                            action_type=args.get("action_type", ""),
                            target=args.get("target", ""),
                            value=str(args.get("value", "")),
                            description=args.get("description", ""),
                            decision=decision,
                        )
                        audit.log(
                            "action_decision",
                            session_id=session_id,
                            action_id=action_id,
                            decision=decision,
                        )
                        yield json.dumps(
                            {
                                "type": "action_decision",
                                "action_id": action_id,
                                "decision": decision,
                            }
                        )

                        if decision == "approved":
                            result = (
                                f"Action approved by operator. "
                                f"Proceed with {args.get('action_type', 'action')} "
                                f"on {args.get('target', 'target')}."
                            )
                        else:
                            result = (
                                f"Action denied by operator ({decision}). "
                                f"No changes will be made to {args.get('target', 'target')}."
                            )
                        audit.log(
                            "tool_result",
                            session_id=session_id,
                            tool=block.name,
                            result=result,
                        )
                        yield json.dumps(
                            {
                                "type": "tool_result",
                                "tool": block.name,
                                "result": result,
                            }
                        )

                    # ── Normal MCP tool call ────────────────────────────────────
                    else:
                        result = await call_mcp_tool(block.name, args)
                        if result.startswith("Error"):
                            error_count += 1
                        audit.log(
                            "tool_result",
                            session_id=session_id,
                            tool=block.name,
                            result=result,
                        )
                        yield json.dumps(
                            {
                                "type": "tool_result",
                                "tool": block.name,
                                "result": result,
                            }
                        )

                    stored = (
                        result
                        if len(result) <= TOOL_RESULT_MAX_CHARS
                        else result[:TOOL_RESULT_MAX_CHARS] + "\n[truncated]"
                    )
                    tool_results.append(
                        {
                            "type": "tool_result",
                            "tool_use_id": block.id,
                            "content": stored,
                        }
                    )

                context_pct = last_input_tokens / CONTEXT_WINDOW_TOKENS
                context_prefix: list[dict] = []
                if context_pct >= _CONTEXT_COMPACT_PCT and not _compact_triggered:
                    _compact_triggered = True
                    yield json.dumps(
                        {
                            "type": "context_warning",
                            "pct": round(context_pct, 2),
                            "level": "compact",
                        }
                    )
                    context_prefix = [
                        {
                            "type": "text",
                            "text": (
                                f"[System: context window at {context_pct:.0%} of limit. "
                                "Summarize key findings from this session and stop making tool calls "
                                "unless the user explicitly requests another query.]"
                            ),
                        }
                    ]
                elif context_pct >= _CONTEXT_WARN_PCT and not _warn_triggered:
                    _warn_triggered = True
                    yield json.dumps(
                        {
                            "type": "context_warning",
                            "pct": round(context_pct, 2),
                            "level": "warn",
                        }
                    )
                    context_prefix = [
                        {
                            "type": "text",
                            "text": (
                                f"[System: context window at {context_pct:.0%} of limit. "
                                "Be concise in remaining responses and avoid unnecessary tool calls.]"
                            ),
                        }
                    ]

                conv_messages = conv_messages + [
                    {"role": "assistant", "content": assistant_content},
                    {"role": "user", "content": context_prefix + tool_results},
                ]
                continue

            # Unexpected stop reason — exit cleanly
            break

    except Exception as exc:
        error_count += 1
        audit.log("error", session_id=session_id, error=str(exc))
        yield json.dumps({"type": "error", "error": str(exc)})

    finally:
        latency_ms = int((time.monotonic() - start_ts) * 1000)
        context_pressure = (
            round(last_input_tokens / CONTEXT_WINDOW_TOKENS, 4)
            if last_input_tokens
            else None
        )
        metrics.log_turn(
            session_id=session_id,
            model=model,
            input_tokens=input_tokens,
            output_tokens=output_tokens,
            tool_call_count=tool_call_count,
            error_count=error_count,
            latency_ms=latency_ms,
            context_pressure=context_pressure,
            user_message=user_message,
            cache_creation_input_tokens=cache_creation_input_tokens,
            cache_read_input_tokens=cache_read_input_tokens,
        )

        # Write session summary for compliance audit trail
        if _final_response_text or _tool_calls_made:
            equipment = session_store.extract_equipment(_tool_calls_made)
            status, confidence = session_store.extract_status_single(
                _final_response_text
            )
            session_store.log_session_summary(
                session_id=session_id,
                user_question=user_message,
                equipment=equipment,
                diagnosis=_final_response_text,
                status=status,
                confidence=confidence,
                mode="single",
            )

        yield json.dumps(
            {
                "type": "done",
                "input_tokens": input_tokens,
                "output_tokens": output_tokens,
                "context_pressure": context_pressure,
            }
        )
