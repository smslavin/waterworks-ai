"""Multi-agent diagnostic loop. Fan-out to 4 specialist Haiku agents in parallel,
then synthesize findings with a Sonnet orchestrator. Yields SSE-ready JSON strings."""

import asyncio
import json
import logging
import os
import re
import time
import uuid
from typing import AsyncIterator

import anthropic

import audit
import control
import metrics
import session_store
from claude_loop import _fetch_process_state, running_state_for
from mcp_client import call_mcp_tool, list_mcp_tools

logger = logging.getLogger(__name__)

TOOL_RESULT_MAX_CHARS = 8_000

SPECIALIST_MODEL    = "claude-haiku-4-5-20251001"
ORCHESTRATOR_MODEL  = "claude-sonnet-4-6"

# Tool name prefixes allowed per specialist. OPC-UA excluded from all specialists.
_MQTT_PREFIXES     = ("mqtt__",)
_INFLUXDB_PREFIXES = ("influxdb__",)

SPECIALISTS = [
    {
        "name": "intake",
        "label": "Intake",
        "unit_names": ["RawWater_01", "RawWater_02"],
        "tool_prefixes": _MQTT_PREFIXES + _INFLUXDB_PREFIXES,
        "system": """You are the Intake diagnostic specialist for a water treatment plant.

Your scope covers ONLY these process units:
  RawWater_01, RawWater_02  (raw water intake pumps)
  Attributes: Flow (L/min), Pressure (bar), Power (kW), Running (bool)

Tools available: MQTT (live reads) and InfluxDB (historical queries).
Do NOT use OPC-UA tools even if listed — they are redundant here.

MQTT topic root: Plant/WTP/Pump/<Instance>/<Attribute>
InfluxDB: call list_measurements first if unsure of available data.

Diagnostic approach:
1. Read current values for both raw water pumps via MQTT
2. Check for correlated anomalies:
   - Flow≈0 + Power≈0 + Running=True → run-status fault
   - Flow ramping to zero + erratic pressure + Running=True → suction starvation
   - High-frequency flow collapse + pressure spikes → cavitation
   - Pressure diverging from expected range → pressure drift
3. Query InfluxDB for recent trends if current readings are ambiguous
4. Compare RawWater_01 and RawWater_02 — single-pump fault vs both suggests different root causes

Always read actual values before making any assertions.""",
    },
    {
        "name": "treatment",
        "label": "Treatment",
        "unit_names": ["Clarifier_01", "Chlorine_01", "Fluoride_01", "UV_01", "UV_02"],
        "tool_prefixes": _MQTT_PREFIXES + _INFLUXDB_PREFIXES,
        "system": """You are the Treatment diagnostic specialist for a water treatment plant.

Your scope covers ONLY these process units:
  Clarifier_01         Level (%), Turbidity (NTU)
  Chlorine_01          FlowRate (L/h), Running (bool), TankLevel (%)
  Fluoride_01          FlowRate (L/h), Running (bool), TankLevel (%)
  UV_01, UV_02         Intensity (%), Running (bool), LampHours

Tools available: MQTT (live reads) and InfluxDB (historical queries).
Do NOT use OPC-UA tools even if listed.

MQTT topic root: Plant/WTP/<Type>/<Instance>/<Attribute>
  Types: Tank (Clarifier), Dosing (Chlorine/Fluoride), UV

Diagnostic approach:
1. Read current values for all treatment units via MQTT
2. Check for:
   - Clarifier turbidity out of normal range (concern > 10 NTU, alarm > 20 NTU)
   - Chemical dosing pumps not running or TankLevel low
   - UV intensity below threshold (< 80% warrants investigation)
   - LampHours exceeding service interval
3. Check correlations: turbidity spike + low chlorine dose is a compound risk
4. Query InfluxDB for trends if current readings are ambiguous

Always read actual values before making any assertions.""",
    },
    {
        "name": "distribution",
        "label": "Distribution",
        "unit_names": ["HighService_01", "HighService_02", "FinishedWater_01"],
        "tool_prefixes": _MQTT_PREFIXES + _INFLUXDB_PREFIXES,
        "system": """You are the Distribution diagnostic specialist for a water treatment plant.

Your scope covers ONLY these process units:
  HighService_01, HighService_02   treated water distribution pumps
    Attributes: Flow (L/min), Pressure (bar), Power (kW), Running (bool)
  FinishedWater_01                 finished water storage tank
    Attributes: Level (%), pH, Turbidity (NTU)

Tools available: MQTT (live reads) and InfluxDB (historical queries).
Do NOT use OPC-UA tools even if listed.

MQTT topic root:
  Plant/WTP/Pump/<Instance>/<Attribute>         (HighService pumps)
  Plant/WTP/Tank/FinishedWater_01/<Attribute>

Diagnostic approach:
1. Read current values for both distribution pumps and finished water tank via MQTT
2. Check for:
   - Pump faults: run-status, suction starvation, cavitation, pressure drift
   - Tank level outside normal range (low = distribution risk, high = intake overrun)
   - pH outside 6.5–8.5 range (treatment failure indicator)
   - Turbidity > 1 NTU in finished water (public health concern)
3. Query InfluxDB for trends if needed

Always read actual values before making any assertions.""",
    },
    {
        "name": "historian",
        "label": "Historian",
        "unit_names": [],
        "tool_prefixes": _INFLUXDB_PREFIXES,
        "system": """You are the Historian diagnostic specialist for a water treatment plant.

You provide HISTORICAL trend analysis only. Do NOT read live sensor data.

Tools available: InfluxDB only. Do NOT use MQTT tools even if listed.

Available measurements (do NOT call list_measurements — use these directly):
  wtp_process     tags: type, instance, attribute  field: value (float)
                  types: Pump, Tank, Dosing, UV
  wtp_fault_events  tags: target  field: mode (string)

Your role:
1. Query InfluxDB for trends relevant to the user's question
2. Look for patterns over the last 1–24 hours depending on the question
3. Identify: gradual drifts, repeated fault events, correlated multi-unit trends,
   or deviations from baseline that live readings alone cannot reveal

── Query efficiency ───────────────────────────────────────────────────────────
Write broad Flux queries that cover multiple units or attributes in one call.
Do NOT issue one query per unit or per attribute — that is wasteful and slow.
Filter by type or measurement to get a wide view, then narrow only if needed.
Aim for 2–3 queries total: one for process trends, one for fault events.

── Flux syntax rules (violations cause query errors) ─────────────────────────
- group() takes `columns:` not `by:` — correct: |> group(columns: ["instance"])
- Use `or` not `||` in filter functions — correct: r.type == "Pump" or r.type == "Tank"
- range() takes a single start: — do NOT write range(start: -24h, start: -1h)
- mean() requires a prior group() and will error on tagged data without it; prefer last() for current-state queries

Always cite specific time ranges and values. State clearly if no historical
anomaly is found.""",
    },
]

_ORCHESTRATOR_SYSTEM = """You are the orchestrator for a multi-agent water treatment plant diagnostic system.

You will receive the user's diagnostic question followed by findings from four
specialist agents: Intake, Treatment, Distribution, and Historian.

Your job is to synthesize these findings into a single coherent diagnostic response:
- Identify the most significant anomalies or faults across all subsystems
- Note cross-specialist correlations (e.g. low raw water flow + rising clarifier turbidity)
- State overall plant health clearly
- Prioritize actionable findings
- If a specialist reported Status: Error or Status: Unknown, note the gap in coverage

Do not make up data. Only synthesize what the specialists reported.
Respond in plain text with markdown formatting.

── Control actions ────────────────────────────────────────────────────────────
If the synthesis reveals a clear fault requiring immediate corrective action,
INVOKE the control__propose_action tool directly — do not describe it in text.
Only do this when the evidence is strong; do not propose actions for Normal status
or minor anomalies.

Tool parameters: description (str), action_type ("setpoint_adjustment"|"fault_clear"),
target (unit name), value (new value or empty string for fault_clear).

After the tool confirms operator approval, call control__set_setpoint or
control__clear_fault to execute. Never execute without prior approval."""

_FINDINGS_FORMAT = """
End your response with this block exactly:
FINDINGS:
Status: Normal | Anomaly Detected | Fault Detected
Confidence: 0.0–1.0
Key observations:
- [bullet points]"""

_SPECIALIST_TOOL_GUIDANCE = """
── Tool selection ─────────────────────────────────────────────────────────────
MQTT: For your initial read of all current values, call get_full_topic_tree once
— it returns the full plant snapshot in a single call. Do NOT call read_topic_value
repeatedly for an initial survey; use it only for targeted follow-up reads.

InfluxDB: Available measurements are wtp_process and wtp_fault_events.
Do NOT call list_measurements — use these directly."""

_ORCHESTRATOR_TOOL_PREFIXES = ("control__",)

_FINDINGS_RE = re.compile(
    r"FINDINGS:.*?Status:\s*([^\n]+)\n.*?Confidence:\s*([0-9.]+)",
    re.IGNORECASE | re.DOTALL,
)


def _parse_findings(text: str) -> tuple[str, float]:
    """Extract (status, confidence) from specialist text. Returns ('Unknown', 0.0) on failure."""
    m = _FINDINGS_RE.search(text)
    if not m:
        logger.warning("FINDINGS parse failed. tail: %r", text[-300:])
        return "Unknown", 0.0
    status     = m.group(1).strip().strip("*").strip()
    confidence = float(m.group(2))
    return status, confidence


def _filter_tools(all_tools: list[dict], prefixes: tuple[str, ...]) -> list[dict]:
    return [t for t in all_tools if any(t["name"].startswith(p) for p in prefixes)]


async def _run_specialist(
    config: dict,
    query: str,
    client: anthropic.AsyncAnthropic,
    all_tools: list[dict],
    session_id: str,
    model: str,
    queue: asyncio.Queue,
    tool_calls_all: list,
    running_state: str = "",
) -> None:
    name    = config["name"]
    start   = time.monotonic()
    tools   = _filter_tools(all_tools, config["tool_prefixes"])
    api_tools = [
        {**t, "cache_control": {"type": "ephemeral"}} if i == len(tools) - 1 else t
        for i, t in enumerate(
            {"name": t["name"], "description": t["description"], "input_schema": t["inputSchema"]}
            for t in tools
        )
    ]

    has_mqtt = any(p in config["tool_prefixes"] for p in _MQTT_PREFIXES)
    system_text = config["system"] + (_SPECIALIST_TOOL_GUIDANCE if has_mqtt else "")
    if running_state:
        system_text += f"\n\nCurrent running state: {running_state}"
    system_text += _FINDINGS_FORMAT

    conv    = [{"role": "user", "content": f"{query}\n\nEnd your response with the FINDINGS block as instructed."}]
    full_text       = ""
    input_tokens    = output_tokens = 0
    tool_call_count = error_count   = 0

    await queue.put({"type": "specialist_start", "specialist": name})

    try:
        while True:
            kwargs: dict = dict(
                model=SPECIALIST_MODEL,
                max_tokens=2048,
                system=[{"type": "text", "text": system_text, "cache_control": {"type": "ephemeral"}}],
                messages=conv,
            )
            if api_tools:
                kwargs["tools"] = api_tools

            async with client.messages.stream(**kwargs) as stream:
                async for text in stream.text_stream:
                    full_text += text

                final = await stream.get_final_message()

            input_tokens  += final.usage.input_tokens
            output_tokens += final.usage.output_tokens

            if final.stop_reason == "end_turn":
                if not _FINDINGS_RE.search(full_text):
                    try:
                        extr = await client.messages.create(
                            model=SPECIALIST_MODEL,
                            max_tokens=120,
                            messages=[
                                {"role": "user", "content": (
                                    f"Based on this diagnostic analysis, complete the FINDINGS block:\n\n"
                                    f"{full_text[-600:]}"
                                )},
                                {"role": "assistant", "content": "FINDINGS:\nStatus:"},
                            ],
                        )
                        if extr.content:
                            full_text += "\nFINDINGS:\nStatus:" + extr.content[0].text
                    except Exception as exc:
                        logger.warning("FINDINGS extraction failed for %s: %s", name, exc)
                break

            if final.stop_reason == "tool_use":
                assistant_content = []
                for block in final.content:
                    if block.type == "text":
                        assistant_content.append({"type": "text", "text": block.text})
                    elif block.type == "tool_use":
                        assistant_content.append({
                            "type": "tool_use",
                            "id": block.id,
                            "name": block.name,
                            "input": dict(block.input),
                        })

                tool_results = []
                for block in final.content:
                    if block.type != "tool_use":
                        continue
                    tool_call_count += 1
                    args = dict(block.input)
                    tool_calls_all.append((block.name, args))
                    audit.log("tool_call", session_id=session_id, tool=block.name, args=args, specialist=name)
                    await queue.put({"type": "tool_call", "tool": block.name, "args": args, "specialist": name})

                    result = await call_mcp_tool(block.name, args)
                    if result.startswith("Error"):
                        error_count += 1

                    audit.log("tool_result", session_id=session_id, tool=block.name, result=result, specialist=name)
                    await queue.put({"type": "tool_result", "tool": block.name, "result": result, "specialist": name})

                    stored = (
                        result if len(result) <= TOOL_RESULT_MAX_CHARS
                        else result[:TOOL_RESULT_MAX_CHARS] + "\n[truncated]"
                    )
                    tool_results.append({"type": "tool_result", "tool_use_id": block.id, "content": stored})

                conv = conv + [
                    {"role": "assistant", "content": assistant_content},
                    {"role": "user",      "content": tool_results},
                ]
                continue

            break

    except Exception as exc:
        error_count += 1
        logger.error("Specialist %s failed: %s", name, exc)
        full_text = f"Specialist encountered an error: {exc}"

    status, confidence = _parse_findings(full_text)
    if status == "Unknown" and full_text and "error" not in full_text.lower():
        logger.warning("Specialist %s: FINDINGS block missing or malformed", name)

    latency_ms = int((time.monotonic() - start) * 1000)
    metrics.log_turn(
        session_id=session_id,
        model=model,
        input_tokens=input_tokens,
        output_tokens=output_tokens,
        tool_call_count=tool_call_count,
        error_count=error_count,
        latency_ms=latency_ms,
        context_pressure=None,
        user_message=query,
        specialist=name,
        specialist_status=status,
        specialist_confidence=confidence,
    )

    await queue.put({
        "type":       "specialist_done",
        "specialist": name,
        "status":     status,
        "confidence": confidence,
        "text":       full_text,
    })
    await queue.put(None)  # sentinel — this specialist is done


async def run_multi_agent(
    messages: list[dict],
    model: str,
    *,
    api_key: str | None = None,
    **kwargs,
) -> AsyncIterator[str]:
    session_id = str(uuid.uuid4())
    start_ts   = time.monotonic()

    user_message = next(
        (m["content"] for m in reversed(messages) if m["role"] == "user"), ""
    )
    audit.log("session_start", session_id=session_id, model=f"multi/{model}", user_message=user_message)

    client    = anthropic.AsyncAnthropic(api_key=api_key)
    all_tools = await list_mcp_tools()

    await _fetch_process_state()  # warm the cache and populate _unit_running before fan-out

    # ── Fan-out: all specialists run in parallel ───────────────────────────────
    queue = asyncio.Queue()
    tool_calls_all: list = []  # shared; list.append is GIL-safe across tasks

    tasks = [
        asyncio.create_task(
            _run_specialist(spec, user_message, client, all_tools, session_id,
                            SPECIALIST_MODEL, queue, tool_calls_all,
                            running_state=running_state_for(spec["unit_names"]))
        )
        for spec in SPECIALISTS
    ]

    findings: dict[str, dict] = {}
    done_count = 0

    while done_count < len(SPECIALISTS):
        event = await queue.get()
        if event is None:
            done_count += 1
            continue
        if event["type"] == "specialist_done":
            findings[event["specialist"]] = event
        yield json.dumps(event)

    await asyncio.gather(*tasks, return_exceptions=True)

    # ── Synthesis ──────────────────────────────────────────────────────────────
    yield json.dumps({"type": "synthesis_start"})

    findings_text = "\n\n".join(
        f"=== {spec['label']} Agent ===\n"
        + findings.get(spec["name"], {}).get("text", "[No findings received]")
        for spec in SPECIALISTS
    )
    orchestrator_user = (
        f"User question: {user_message}\n\n"
        f"Specialist findings:\n\n{findings_text}"
    )

    orch_input_tokens = orch_output_tokens = 0
    orch_tool_call_count = 0
    orch_start = time.monotonic()

    orch_tools = _filter_tools(all_tools, _ORCHESTRATOR_TOOL_PREFIXES)
    logger.info("Orchestrator tools: %s", [t["name"] for t in orch_tools])
    orch_api_tools = [
        {
            **({"cache_control": {"type": "ephemeral"}} if i == len(orch_tools) - 1 else {}),
            "name": t["name"],
            "description": t["description"],
            "input_schema": t["inputSchema"],
        }
        for i, t in enumerate(orch_tools)
    ]
    orch_conv = [{"role": "user", "content": orchestrator_user}]
    orch_full_text = ""

    try:
        while True:
            orch_kwargs: dict = dict(
                model=ORCHESTRATOR_MODEL,
                max_tokens=2048,
                system=[{"type": "text", "text": _ORCHESTRATOR_SYSTEM,
                          "cache_control": {"type": "ephemeral"}}],
                messages=orch_conv,
            )
            if orch_api_tools:
                orch_kwargs["tools"] = orch_api_tools

            async with client.messages.stream(**orch_kwargs) as stream:
                async for text in stream.text_stream:
                    orch_full_text += text
                    yield json.dumps({"type": "text", "text": text})
                final = await stream.get_final_message()

            orch_input_tokens  += final.usage.input_tokens
            orch_output_tokens += final.usage.output_tokens

            if final.stop_reason == "end_turn":
                break

            if final.stop_reason == "tool_use":
                assistant_content = []
                for block in final.content:
                    if block.type == "text":
                        assistant_content.append({"type": "text", "text": block.text})
                    elif block.type == "tool_use":
                        assistant_content.append({
                            "type": "tool_use", "id": block.id,
                            "name": block.name, "input": dict(block.input),
                        })

                tool_results = []
                for block in final.content:
                    if block.type != "tool_use":
                        continue
                    orch_tool_call_count += 1
                    args = dict(block.input)
                    audit.log("tool_call", session_id=session_id, tool=block.name,
                              args=args, specialist="orchestrator")
                    yield json.dumps({"type": "tool_call", "tool": block.name, "args": args})

                    if block.name == "control__propose_action":
                        action_id = str(uuid.uuid4())[:8]
                        yield json.dumps({
                            "type":        "action_proposed",
                            "action_id":   action_id,
                            "description": args.get("description", ""),
                            "action_type": args.get("action_type", ""),
                            "target":      args.get("target", ""),
                            "value":       args.get("value", ""),
                        })
                        fut = control.register(action_id)
                        try:
                            decision = await asyncio.wait_for(fut, timeout=300)
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
                        audit.log("action_decision", session_id=session_id,
                                  action_id=action_id, decision=decision)
                        yield json.dumps({"type": "action_decision",
                                          "action_id": action_id, "decision": decision})
                        if decision == "approved":
                            result = (f"Action approved by operator. Proceed with "
                                      f"{args.get('action_type', '')} on {args.get('target', '')}.")
                        else:
                            result = (f"Action denied by operator ({decision}). "
                                      f"No changes to {args.get('target', '')}.")
                    else:
                        result = await call_mcp_tool(block.name, args)

                    audit.log("tool_result", session_id=session_id,
                              tool=block.name, result=result, specialist="orchestrator")
                    yield json.dumps({"type": "tool_result", "tool": block.name, "result": result})

                    stored = (result if len(result) <= TOOL_RESULT_MAX_CHARS
                              else result[:TOOL_RESULT_MAX_CHARS] + "\n[truncated]")
                    tool_results.append({"type": "tool_result",
                                         "tool_use_id": block.id, "content": stored})

                orch_conv = orch_conv + [
                    {"role": "assistant", "content": assistant_content},
                    {"role": "user",      "content": tool_results},
                ]
                continue

            break

        text_content = orch_full_text
        audit.log("response", session_id=session_id, text=text_content)

        # Write session summary for compliance audit trail
        _statuses = [
            f.get("status", "Unknown") for f in findings.values()
            if f.get("status") not in ("Unknown", "Error", None)
        ]
        _confs = [
            f.get("confidence", 0.0) for f in findings.values()
            if isinstance(f.get("confidence"), (int, float)) and f.get("confidence", 0) > 0
        ]
        overall_status = (
            "Fault Detected"   if any("Fault"   in s for s in _statuses) else
            "Anomaly Detected" if any("Anomaly" in s for s in _statuses) else
            "Normal"           if _statuses else "Unknown"
        )
        avg_confidence = round(sum(_confs) / len(_confs), 3) if _confs else None
        session_store.log_session_summary(
            session_id=session_id,
            user_question=user_message,
            equipment=session_store.extract_equipment(tool_calls_all),
            diagnosis=text_content,
            status=overall_status,
            confidence=avg_confidence,
            mode="multi",
        )

    except Exception as exc:
        logger.exception("Orchestrator failed")
        yield json.dumps({"type": "error", "error": str(exc)})

    metrics.log_turn(
        session_id=session_id,
        model=ORCHESTRATOR_MODEL,
        input_tokens=orch_input_tokens,
        output_tokens=orch_output_tokens,
        tool_call_count=orch_tool_call_count,
        error_count=0,
        latency_ms=int((time.monotonic() - orch_start) * 1000),
        context_pressure=None,
        user_message=user_message,
        specialist="orchestrator",
    )

    total_latency_ms = int((time.monotonic() - start_ts) * 1000)
    yield json.dumps({
        "type":          "done",
        "input_tokens":  orch_input_tokens,
        "output_tokens": orch_output_tokens,
        "latency_ms":    total_latency_ms,
    })
