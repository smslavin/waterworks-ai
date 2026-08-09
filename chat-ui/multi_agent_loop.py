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
from topology import load as _load_topology

from fieldworks.agents import (
    build_specialist_prompt,
    build_specialists as _fw_build_specialists,
    build_orchestrator_system as _fw_build_orchestrator_system,
    cache_system,
    cache_tools,
)

logger = logging.getLogger(__name__)

TOOL_RESULT_MAX_CHARS = 8_000

SPECIALIST_MODEL = "claude-haiku-4-5-20251001"
ORCHESTRATOR_MODEL = "claude-sonnet-4-6"

# Tool name prefixes allowed per specialist. OPC-UA excluded from all specialists.
_MQTT_PREFIXES = ("mqtt__",)
_INFLUXDB_PREFIXES = ("influxdb__",)

# Knowledge/RAG retrieval is equipment-scoped the same way specialists are
# equipment-scoped, so every specialist gets it — not just Historian.
_KNOWLEDGE_TOOL_PREFIXES = ("memory__query_knowledge",)

# Historian is a fixed cross-cutting agent, not generated from topology (it isn't
# scoped to a process area) — fieldworks.agents.build_specialists() only builds
# one specialist per process area, so Historian is defined here directly.
_MEMORY_READ_TOOLS = (
    "memory__run_correlation",
    "memory__get_equipment_history",
    "memory__query_graph",
    "memory__get_topology",
    "memory__get_specialist_context",
    "memory__get_writable_attributes",
    "memory__get_specialist_memory",
)
_HISTORIAN_TOOL_PREFIXES = (
    _INFLUXDB_PREFIXES + _MEMORY_READ_TOOLS + _KNOWLEDGE_TOOL_PREFIXES
)

_HISTORIAN_SYSTEM = """You are the Historian diagnostic specialist for a water treatment plant.

You provide HISTORICAL trend analysis only. Do NOT read live sensor data.

Tools available: InfluxDB only. Do NOT use MQTT tools even if listed.

Available measurements (do NOT call list_measurements — use these directly):
  wtp_process     tags: type, instance, attribute  field: value (float)
                  types: Pump, Clarifier, StorageTank, Dosing, UV
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

── Flux syntax rules — violations cause 400 errors ──────────────────────────
These are the most common mistakes. Use the VALID form exactly as shown.

  group():
    INVALID: |> group(by: ["instance"])        ← "by:" does not exist in Flux
    VALID:   |> group(columns: ["instance"])

  sort():
    INVALID: |> sort(by: ["_time"])            ← "by:" does not exist in Flux
    VALID:   |> sort(columns: ["_time"], desc: true)

  filter():
    INVALID: r.type == "Pump" || r.type == "Tank"   ← || not valid in Flux
    VALID:   r.type == "Pump" or r.type == "Tank"

  range():
    INVALID: range(start: -24h, stop: -1h)     ← use |> range(start:) then filter by time if needed
    VALID:   range(start: -24h)

  aggregates (mean, sum, etc.):
    Require group() first on tagged data or will error. Prefer last() for
    current-state queries where you just want the most recent value.

  count() / distinct() / schema.* (remove _time — causes parser error):
    INVALID: |> group(columns: ["target"]) |> count()
    INVALID: |> distinct(column: "instance")
    INVALID: schema.tagValues(bucket: "...", tag: "instance")
             — these drop _time; the client raises KeyError: '_time'
    VALID:   |> group(columns: ["target"]) |> last()
             — use last() to get one row per group with _time preserved
    VALID:   |> aggregateWindow(every: 1h, fn: count, createEmpty: false)
             — for time-series event counts with _time intact

Always cite specific time ranges and values. State clearly if no historical
anomaly is found.

── DuckDB (run_correlation) vs InfluxDB ──────────────────────────────────────
Use InfluxDB for: recent trends (≤ 7 days), single-unit queries, fault event history.
Use memory__run_correlation for: cross-equipment correlations, window functions,
queries spanning weeks or months.

Note: DuckDB is a materialized copy synced from InfluxDB on a schedule
(default 1 hour, set by DUCKDB_SYNC_INTERVAL). Do not use it for data from
the last hour — query InfluxDB directly for recent values.

Example queries:
  -- Correlation: pressure drops across all pumps vs turbidity spikes (90 days)
  SELECT date_trunc('day', time) AS day,
         AVG(CASE WHEN attribute = 'Pressure' THEN value END) AS avg_pressure,
         AVG(CASE WHEN attribute = 'Turbidity' THEN value END) AS avg_turbidity
  FROM wtp_process
  WHERE time > NOW() - INTERVAL '90 days'
    AND (instance LIKE '%Pump%' OR instance LIKE '%Clarifier%')
  GROUP BY day ORDER BY day

  -- Fault frequency by instance (30 days)
  SELECT target, COUNT(*) AS fault_count
  FROM wtp_fault_events
  WHERE time > NOW() - INTERVAL '30 days'
  GROUP BY target ORDER BY fault_count DESC

DuckDB schema:
  wtp_process(time TIMESTAMPTZ, type VARCHAR, instance VARCHAR, attribute VARCHAR, value DOUBLE)
  wtp_fault_events(time TIMESTAMPTZ, target VARCHAR, mode VARCHAR)"""


def _build_specialists(topology) -> list[dict]:
    """Adapt fieldworks.agents' framework-shaped specialists (area_id/area_name/
    instance_ids/system_prompt) into the shape this fan-out loop needs at
    runtime: tool_prefixes for MQTT/InfluxDB routing, and unit_names using the
    *original* instance display names (e.g. "RawWater_01") rather than
    topology.yaml ids — MQTT/InfluxDB data is keyed by the former.
    """
    specialists = []
    for area in topology.process_areas:
        instances = topology.instances_in_area(area.id)
        specialists.append(
            {
                "name": area.id,
                "label": area.name,
                "unit_names": [i.name for i in instances],
                "tool_prefixes": (
                    _MQTT_PREFIXES + _INFLUXDB_PREFIXES + _KNOWLEDGE_TOOL_PREFIXES
                ),
                "system": build_specialist_prompt(area.id, topology),
            }
        )
    specialists.append(
        {
            "name": "historian",
            "label": "Historian",
            "unit_names": [],
            "tool_prefixes": _HISTORIAN_TOOL_PREFIXES,
            "system": _HISTORIAN_SYSTEM,
        }
    )
    return specialists


_HISTORIAN_MENTION = (
    "\n\nYou also have a Historian agent available for historical trend analysis"
    " (InfluxDB + DuckDB correlation queries). Historian is not scoped to a"
    " process area — route cross-cutting or long-horizon questions to it."
)

# control-mcp/audit-mcp are app-specific tools fieldworks.agents.
# build_orchestrator_system() has no knowledge of (by design — the framework
# builder only knows about topology-derived specialists). Their usage
# guidance is appended here rather than lost.
_CONTROL_ACTION_GUIDANCE = """

── Control actions ────────────────────────────────────────────────────────────
If the synthesis reveals a clear fault requiring immediate corrective action,
call the control__propose_action tool. Do this SILENTLY — do not write "I am
proposing an action" or any similar text before the tool call. Just call it.

Writing about a proposed action in text without calling the tool is a protocol
violation. The tool IS the proposal — text is not.

Only propose when evidence is strong; do not propose for Normal status or minor
anomalies.

Tool parameters: description (str), action_type ("setpoint_adjustment"|"fault_clear"),
target (unit name), value (new value or empty string for fault_clear).

After the tool confirms operator approval, call control__set_setpoint or
control__clear_fault to execute. Never execute without prior approval.

── Insight review queue ───────────────────────────────────────────────────────
Operators save insights during node diagnostics. Those flagged requires_review=true
are queued for engineering approval in the insight_reviews table.

audit__list_pending_reviews(hours_back=168) — list unresolved operator insight reviews.
audit__resolve_review(review_id, resolution, resolver_note?) — approve, reject, or defer.
  resolution values: "approved" | "rejected" | "deferred"

Use these when the operator asks about pending reviews, saved insights, or the insight
queue. Do NOT use audit__list_incidents or audit__query_history for this — those query
diagnostic sessions, not the insight review queue."""

_SUMMARY_FORMAT = """

── Synthesis output format ─────────────────────────────────────────────────────
START your synthesis with this block, before any detailed breakdown — the
specialist findings are already in front of you, so lead with the conclusion
rather than building up to it:
SUMMARY:
Status: Normal | Anomaly Detected | Fault Detected
Overview: [one or two plain-language sentences]
Key points:
- [bullet points — omit the list entirely if there is nothing notable]

Detailed reasoning, tables, and recommendations belong after this block, not
before it — the block must never be pushed to the end where it risks being cut
off by the response length limit.

Omit this block for a simple conversational follow-up that isn't really a status
overview of the area or plant."""

_topology = _load_topology()
SPECIALISTS = _build_specialists(_topology)
_ORCHESTRATOR_SYSTEM = (
    _fw_build_orchestrator_system(_fw_build_specialists(_topology), _topology)
    + _HISTORIAN_MENTION
    + _CONTROL_ACTION_GUIDANCE
    + _SUMMARY_FORMAT
)

_FINDINGS_FORMAT = """
End your response with this block exactly:
FINDINGS:
Status: Normal | Anomaly Detected | Fault Detected
Confidence: 0.0–1.0
Key observations:
- [bullet points]"""

_SPECIALIST_TOOL_GUIDANCE = """
── Tool selection ─────────────────────────────────────────────────────────────
MQTT: For your initial read of current values, call mqtt__scan once with no
arguments (default pattern "#") — it returns every live topic and its current
value in a single call. Do NOT guess a tag_id and call mqtt__read_tag first —
topic paths are full MQTT paths, not "<Instance>/<Attribute>", so a guessed
tag_id will time out. Use mqtt__read_tag only for a cheap targeted follow-up
once you already have the exact topic string from a scan or discover_tags
call. Do NOT call mqtt__get_topic_tree — it's for topology onboarding, not
runtime queries, and is intentionally expensive.

InfluxDB: Available measurements are wtp_process and wtp_fault_events.
Do NOT call list_measurements — use these directly.

Flux syntax: boolean operators are lowercase — use `or`, `and`, `not`.
Never use uppercase OR / AND / NOT — they are parsed as identifiers and will cause a 400 error."""

_ORCHESTRATOR_TOOL_PREFIXES = ("control__", "audit__")

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
    status = m.group(1).strip().strip("*").strip()
    confidence = float(m.group(2))
    return status, confidence


def _filter_tools(all_tools: list[dict], prefixes: tuple[str, ...]) -> list[dict]:
    return [t for t in all_tools if any(t["name"].startswith(p) for p in prefixes)]


def _find_specialist_for_instance(instance_id: str) -> dict | None:
    """Return the specialist config whose unit_names contains instance_id, or None."""
    for spec in SPECIALISTS:
        if instance_id in spec.get("unit_names", []):
            return spec
    return None


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
    cascade_id: str | None = None,
) -> None:
    name = config["name"]
    start = time.monotonic()
    tools = _filter_tools(all_tools, config["tool_prefixes"])
    api_tools = cache_tools(tools)

    has_mqtt = any(p in config["tool_prefixes"] for p in _MQTT_PREFIXES)
    system_text = config["system"] + (_SPECIALIST_TOOL_GUIDANCE if has_mqtt else "")
    if running_state:
        system_text += f"\n\nCurrent running state: {running_state}"
    system_text += _FINDINGS_FORMAT

    # ── Inject accumulated cross-session memory ───────────────────────────────
    try:
        mem_content = await call_mcp_tool(
            "memory__get_specialist_memory", {"specialist": name}
        )
        if mem_content and not mem_content.startswith("Error") and mem_content.strip():
            system_text = (
                "── Accumulated knowledge from prior sessions ──────────────────\n"
                + mem_content
                + "\n\n"
                + system_text
            )
    except Exception:
        pass  # memory-mcp unavailable — degrade gracefully

    conv = [
        {
            "role": "user",
            "content": f"{query}\n\nEnd your response with the FINDINGS block as instructed.",
        }
    ]
    full_text = ""
    input_tokens = output_tokens = 0
    cache_creation_input_tokens = cache_read_input_tokens = 0
    tool_call_count = error_count = 0
    after_tool_call = False  # track turns so paragraph breaks are inserted

    await queue.put({"type": "specialist_start", "specialist": name})

    try:
        while True:
            kwargs: dict = dict(
                model=SPECIALIST_MODEL,
                max_tokens=8192,
                system=cache_system(system_text),
                messages=conv,
            )
            if api_tools:
                kwargs["tools"] = api_tools

            async with client.messages.stream(**kwargs) as stream:
                first_chunk = True
                async for text in stream.text_stream:
                    if first_chunk and after_tool_call and text.strip():
                        full_text += "\n\n"
                        after_tool_call = False
                    full_text += text
                    if first_chunk and text.strip():
                        first_chunk = False

                final = await stream.get_final_message()

            input_tokens += final.usage.input_tokens
            output_tokens += final.usage.output_tokens
            cache_creation_input_tokens += final.usage.cache_creation_input_tokens or 0
            cache_read_input_tokens += final.usage.cache_read_input_tokens or 0

            if final.stop_reason == "end_turn":
                if not _FINDINGS_RE.search(full_text):
                    try:
                        extr = await client.messages.create(
                            model=SPECIALIST_MODEL,
                            max_tokens=256,
                            messages=[
                                {
                                    "role": "user",
                                    "content": (
                                        f"Based on this diagnostic analysis, complete the FINDINGS block.\n"
                                        f"Required format:\nFINDINGS:\nStatus: <Normal|Anomaly Detected|Fault Detected>\n"
                                        f"Confidence: <0.0-1.0>\nKey observations:\n- <bullet>\n\n"
                                        f"Analysis:\n{full_text[-800:]}"
                                    ),
                                },
                                {"role": "assistant", "content": "FINDINGS:\nStatus:"},
                            ],
                        )
                        if extr.content:
                            full_text += "\nFINDINGS:\nStatus:" + extr.content[0].text
                    except Exception as exc:
                        logger.warning(
                            "FINDINGS extraction failed for %s: %s", name, exc
                        )
                break

            if final.stop_reason == "tool_use":
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
                    tool_calls_all.append((block.name, args))
                    audit.log(
                        "tool_call",
                        session_id=session_id,
                        tool=block.name,
                        args=args,
                        specialist=name,
                    )
                    await queue.put(
                        {
                            "type": "tool_call",
                            "tool": block.name,
                            "args": args,
                            "specialist": name,
                        }
                    )

                    result = await call_mcp_tool(block.name, args)
                    if result.startswith("Error"):
                        error_count += 1

                    audit.log(
                        "tool_result",
                        session_id=session_id,
                        tool=block.name,
                        result=result,
                        specialist=name,
                    )
                    await queue.put(
                        {
                            "type": "tool_result",
                            "tool": block.name,
                            "result": result,
                            "specialist": name,
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

                conv = conv + [
                    {"role": "assistant", "content": assistant_content},
                    {"role": "user", "content": tool_results},
                ]
                after_tool_call = True
                continue

            break

    except Exception as exc:
        error_count += 1
        logger.error("Specialist %s failed: %s", name, exc)
        full_text = f"Specialist encountered an error: {exc}"

    status, confidence = _parse_findings(full_text)
    if status == "Unknown" and full_text and "error" not in full_text.lower():
        logger.warning("Specialist %s: FINDINGS block missing or malformed", name)

    # ── Record incident to LadybugDB ──────────────────────────────────────────
    if status not in ("Normal", "Unknown"):
        for unit_id in config.get("unit_names", []):
            try:
                await call_mcp_tool(
                    "memory__record_incident",
                    {
                        "session_id": session_id,
                        "equipment_id": unit_id,
                        "diagnosis": full_text[-500:],
                        "confidence": confidence,
                        "status": status.lower().replace(" ", "_"),
                        "fault_mode_id": "",
                    },
                )
            except Exception:
                pass  # non-fatal

    # ── Append key finding to specialist memory ───────────────────────────────
    if status not in ("Normal", "Unknown") and confidence >= 0.7:
        try:
            unit_summary = ", ".join(config.get("unit_names", []))
            await call_mcp_tool(
                "memory__append_specialist_memory",
                {
                    "specialist": name,
                    "content": (
                        f"Session {session_id[:8]}: {status} on {unit_summary}. "
                        f"Confidence {confidence}. "
                        f"Key finding: {full_text[-300:]}"
                    ),
                },
            )
        except Exception:
            pass  # non-fatal

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
        cascade_id=cascade_id,
        cache_creation_input_tokens=cache_creation_input_tokens,
        cache_read_input_tokens=cache_read_input_tokens,
    )

    await queue.put(
        {
            "type": "specialist_done",
            "specialist": name,
            "status": status,
            "confidence": confidence,
            "text": full_text,
        }
    )
    await queue.put(None)  # sentinel — this specialist is done


async def _run_cascade_only(
    messages: list[dict],
    user_message: str,
    all_tools: list[dict],
    client,
    session_id: str,
    start_ts: float,
    cascade_id: str | None,
) -> AsyncIterator[str]:
    """Run Cascade alone on a follow-up question, without specialist fan-out."""
    yield json.dumps({"type": "synthesis_start"})

    orch_tools = _filter_tools(all_tools, _ORCHESTRATOR_TOOL_PREFIXES)
    orch_api_tools = cache_tools(orch_tools)
    # Full conversation history — Cascade sees all prior turns and the new message
    orch_conv = [
        {"role": m["role"], "content": m["content"]}
        for m in messages
        if m["role"] in ("user", "assistant")
    ]

    orch_input_tokens = orch_output_tokens = 0
    orch_cache_creation_input_tokens = orch_cache_read_input_tokens = 0
    orch_tool_call_count = 0
    orch_full_text = ""

    try:
        while True:
            orch_kwargs: dict = dict(
                model=ORCHESTRATOR_MODEL,
                max_tokens=4096,
                system=cache_system(_ORCHESTRATOR_SYSTEM),
                messages=orch_conv,
            )
            if orch_api_tools:
                orch_kwargs["tools"] = orch_api_tools
            response = await client.messages.create(**orch_kwargs)
            orch_input_tokens += response.usage.input_tokens
            orch_output_tokens += response.usage.output_tokens
            orch_cache_creation_input_tokens += (
                response.usage.cache_creation_input_tokens or 0
            )
            orch_cache_read_input_tokens += response.usage.cache_read_input_tokens or 0

            tool_uses, text_blocks = [], []
            for block in response.content:
                if block.type == "tool_use":
                    tool_uses.append(block)
                elif block.type == "text":
                    text_blocks.append(block)
                    orch_full_text += block.text
                    yield json.dumps({"type": "text", "text": block.text})

            if response.stop_reason == "end_turn" or not tool_uses:
                break

            tool_results = []
            for tu in tool_uses:
                orch_tool_call_count += 1
                result = await call_mcp_tool(tu.name, dict(tu.input))
                tool_results.append(
                    {"type": "tool_result", "tool_use_id": tu.id, "content": result}
                )

            orch_conv = orch_conv + [
                {"role": "assistant", "content": response.content},
                {"role": "user", "content": tool_results},
            ]
    except Exception as exc:
        logger.exception("Cascade-only stream error: %s", exc)
        yield json.dumps({"type": "error", "error": str(exc)})

    latency = int((time.monotonic() - start_ts) * 1000)
    metrics.log_turn(
        session_id=session_id,
        model=ORCHESTRATOR_MODEL,
        input_tokens=orch_input_tokens,
        output_tokens=orch_output_tokens,
        tool_call_count=orch_tool_call_count,
        error_count=0,
        latency_ms=latency,
        context_pressure=None,
        user_message=user_message,
        specialist="orchestrator",
        cascade_id=cascade_id,
        cache_creation_input_tokens=orch_cache_creation_input_tokens,
        cache_read_input_tokens=orch_cache_read_input_tokens,
    )
    session_store.log_session_summary(
        session_id=session_id,
        user_question=user_message,
        equipment=[],
        diagnosis=orch_full_text,
        status="Normal",
        confidence=None,
        mode="multi-followup",
    )
    yield json.dumps(
        {
            "type": "done",
            "input_tokens": orch_input_tokens,
            "output_tokens": orch_output_tokens,
            "latency_ms": latency,
        }
    )


async def run_multi_agent(
    messages: list[dict],
    model: str,
    *,
    api_key: str | None = None,
    scope_instance_id: str | None = None,
    include_orchestrator: bool = True,
    cascade_id: str | None = None,
    **kwargs,
) -> AsyncIterator[str]:
    session_id = str(uuid.uuid4())
    start_ts = time.monotonic()

    user_message = next(
        (m["content"] for m in reversed(messages) if m["role"] == "user"), ""
    )
    audit.log(
        "session_start",
        session_id=session_id,
        model=f"multi/{model}",
        user_message=user_message,
    )

    client = anthropic.AsyncAnthropic(api_key=api_key)
    all_tools = await list_mcp_tools()

    await _fetch_process_state()  # warm the cache and populate _unit_running before fan-out

    # ── Follow-up detection: skip specialist fan-out, route straight to Cascade ──
    is_followup = any(m["role"] == "assistant" for m in messages[:-1])
    if is_followup and include_orchestrator:
        async for chunk in _run_cascade_only(
            messages, user_message, all_tools, client, session_id, start_ts, cascade_id
        ):
            yield chunk
        return

    # ── Scope specialists (reactive uses one; interactive uses all) ────────────
    if scope_instance_id:
        scoped = _find_specialist_for_instance(scope_instance_id)
        active_specialists = [scoped] if scoped else SPECIALISTS
    else:
        active_specialists = SPECIALISTS

    # ── Fan-out: specialists run in parallel ───────────────────────────────────
    queue = asyncio.Queue()
    tool_calls_all: list = []  # shared; list.append is GIL-safe across tasks

    tasks = [
        asyncio.create_task(
            _run_specialist(
                spec,
                user_message,
                client,
                all_tools,
                session_id,
                SPECIALIST_MODEL,
                queue,
                tool_calls_all,
                running_state=running_state_for(spec["unit_names"]),
                cascade_id=cascade_id,
            )
        )
        for spec in active_specialists
    ]

    findings: dict[str, dict] = {}
    done_count = 0

    while done_count < len(active_specialists):
        event = await queue.get()
        if event is None:
            done_count += 1
            continue
        if event["type"] == "specialist_done":
            findings[event["specialist"]] = event
        yield json.dumps(event)

    await asyncio.gather(*tasks, return_exceptions=True)

    # ── Warning tier: return specialist text directly, skip orchestrator ───────
    if not include_orchestrator:
        text = "\n\n".join(
            findings.get(s["name"], {}).get("text", "")
            for s in active_specialists
            if findings.get(s["name"], {}).get("text")
        )
        if text:
            # Deduplicate FINDINGS blocks — keep only the last one
            findings_positions = [m.start() for m in re.finditer(r"\nFINDINGS:", text)]
            if len(findings_positions) > 1:
                text = text[: findings_positions[0]] + text[findings_positions[-1] :]
            yield json.dumps({"type": "text", "text": text})
        yield json.dumps(
            {
                "type": "done",
                "input_tokens": 0,
                "output_tokens": 0,
                "latency_ms": int((time.monotonic() - start_ts) * 1000),
            }
        )
        return

    # ── Synthesis ──────────────────────────────────────────────────────────────
    yield json.dumps({"type": "synthesis_start"})

    findings_text = "\n\n".join(
        f"=== {spec['label']} Agent ===\n"
        + findings.get(spec["name"], {}).get("text", "[No findings received]")
        for spec in active_specialists
    )
    orchestrator_user = (
        f"User question: {user_message}\n\n" f"Specialist findings:\n\n{findings_text}"
    )

    orch_input_tokens = orch_output_tokens = 0
    orch_cache_creation_input_tokens = orch_cache_read_input_tokens = 0
    orch_tool_call_count = 0
    orch_start = time.monotonic()

    orch_tools = _filter_tools(all_tools, _ORCHESTRATOR_TOOL_PREFIXES)
    orch_api_tools = cache_tools(orch_tools)
    # Thread prior conversation history into Cascade so follow-up questions
    # have full context. On a fresh open, messages[:-1] is empty and this is
    # equivalent to the old single-turn start.
    prior_turns = [
        {"role": m["role"], "content": m["content"]}
        for m in messages[:-1]
        if m["role"] in ("user", "assistant")
    ]
    orch_conv = prior_turns + [{"role": "user", "content": orchestrator_user}]
    orch_full_text = ""

    try:
        while True:
            orch_kwargs: dict = dict(
                model=ORCHESTRATOR_MODEL,
                max_tokens=4096,
                system=cache_system(_ORCHESTRATOR_SYSTEM),
                messages=orch_conv,
            )
            if orch_api_tools:
                orch_kwargs["tools"] = orch_api_tools

            async with client.messages.stream(**orch_kwargs) as stream:
                async for text in stream.text_stream:
                    orch_full_text += text
                    yield json.dumps({"type": "text", "text": text})
                final = await stream.get_final_message()

            orch_input_tokens += final.usage.input_tokens
            orch_output_tokens += final.usage.output_tokens
            orch_cache_creation_input_tokens += (
                final.usage.cache_creation_input_tokens or 0
            )
            orch_cache_read_input_tokens += final.usage.cache_read_input_tokens or 0

            if final.stop_reason == "end_turn":
                _action_keywords = (
                    "propose",
                    "control action",
                    "corrective action",
                    "clear fault",
                    "set_setpoint",
                )
                if any(kw in orch_full_text.lower() for kw in _action_keywords):
                    logger.warning(
                        "Orchestrator end_turn with action language but no tool call — text tail: %r",
                        orch_full_text[-200:],
                    )
                break

            if final.stop_reason == "tool_use":
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
                    orch_tool_call_count += 1
                    args = dict(block.input)
                    audit.log(
                        "tool_call",
                        session_id=session_id,
                        tool=block.name,
                        args=args,
                        specialist="orchestrator",
                    )
                    yield json.dumps(
                        {"type": "tool_call", "tool": block.name, "args": args}
                    )

                    if block.name == "control__propose_action":
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
                                f"Action approved by operator. Proceed with "
                                f"{args.get('action_type', '')} on {args.get('target', '')}."
                            )
                        else:
                            result = (
                                f"Action denied by operator ({decision}). "
                                f"No changes to {args.get('target', '')}."
                            )
                    else:
                        result = await call_mcp_tool(block.name, args)

                    audit.log(
                        "tool_result",
                        session_id=session_id,
                        tool=block.name,
                        result=result,
                        specialist="orchestrator",
                    )
                    yield json.dumps(
                        {"type": "tool_result", "tool": block.name, "result": result}
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

                orch_conv = orch_conv + [
                    {"role": "assistant", "content": assistant_content},
                    {"role": "user", "content": tool_results},
                ]
                continue

            break

        text_content = orch_full_text
        audit.log("response", session_id=session_id, text=text_content)

        # Write session summary for compliance audit trail
        _statuses = [
            f.get("status", "Unknown")
            for f in findings.values()
            if f.get("status") not in ("Unknown", "Error", None)
        ]
        _confs = [
            f.get("confidence", 0.0)
            for f in findings.values()
            if isinstance(f.get("confidence"), (int, float))
            and f.get("confidence", 0) > 0
        ]
        overall_status = (
            "Fault Detected"
            if any("Fault" in s for s in _statuses)
            else (
                "Anomaly Detected"
                if any("Anomaly" in s for s in _statuses)
                else "Normal" if _statuses else "Unknown"
            )
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
        cascade_id=cascade_id,
        cache_creation_input_tokens=orch_cache_creation_input_tokens,
        cache_read_input_tokens=orch_cache_read_input_tokens,
    )

    total_latency_ms = int((time.monotonic() - start_ts) * 1000)
    yield json.dumps(
        {
            "type": "done",
            "input_tokens": orch_input_tokens,
            "output_tokens": orch_output_tokens,
            "latency_ms": total_latency_ms,
        }
    )
