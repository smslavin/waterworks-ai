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
from topology_prompts import build_specialists, build_orchestrator_system

logger = logging.getLogger(__name__)

TOOL_RESULT_MAX_CHARS = 8_000

SPECIALIST_MODEL    = "claude-haiku-4-5-20251001"
ORCHESTRATOR_MODEL  = "claude-sonnet-4-6"

# Tool name prefixes allowed per specialist. OPC-UA excluded from all specialists.
_MQTT_PREFIXES     = ("mqtt__",)
_INFLUXDB_PREFIXES = ("influxdb__",)

_topology            = _load_topology()
SPECIALISTS          = build_specialists(_topology)
_ORCHESTRATOR_SYSTEM = build_orchestrator_system(SPECIALISTS)

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
Do NOT call list_measurements — use these directly.

Flux syntax: boolean operators are lowercase — use `or`, `and`, `not`.
Never use uppercase OR / AND / NOT — they are parsed as identifiers and will cause a 400 error."""

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

    # ── Inject accumulated cross-session memory ───────────────────────────────
    try:
        mem_content = await call_mcp_tool("memory__get_specialist_memory", {"specialist": name})
        if mem_content and not mem_content.startswith("Error") and mem_content.strip():
            system_text = (
                "── Accumulated knowledge from prior sessions ──────────────────\n"
                + mem_content
                + "\n\n"
                + system_text
            )
    except Exception:
        pass  # memory-mcp unavailable — degrade gracefully

    conv    = [{"role": "user", "content": f"{query}\n\nEnd your response with the FINDINGS block as instructed."}]
    full_text       = ""
    input_tokens    = output_tokens = 0
    tool_call_count = error_count   = 0

    await queue.put({"type": "specialist_start", "specialist": name})

    try:
        while True:
            kwargs: dict = dict(
                model=SPECIALIST_MODEL,
                max_tokens=8192,
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
                            max_tokens=256,
                            messages=[
                                {"role": "user", "content": (
                                    f"Based on this diagnostic analysis, complete the FINDINGS block.\n"
                                    f"Required format:\nFINDINGS:\nStatus: <Normal|Anomaly Detected|Fault Detected>\n"
                                    f"Confidence: <0.0-1.0>\nKey observations:\n- <bullet>\n\n"
                                    f"Analysis:\n{full_text[-800:]}"
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

    # ── Record incident to LadybugDB ──────────────────────────────────────────
    if status not in ("Normal", "Unknown"):
        for unit_id in config.get("unit_names", []):
            try:
                await call_mcp_tool("memory__record_incident", {
                    "session_id":   session_id,
                    "equipment_id": unit_id,
                    "diagnosis":    full_text[-500:],
                    "confidence":   confidence,
                    "status":       status.lower().replace(" ", "_"),
                    "fault_mode_id": "",
                })
            except Exception:
                pass  # non-fatal

    # ── Append key finding to specialist memory ───────────────────────────────
    if status not in ("Normal", "Unknown") and confidence >= 0.7:
        try:
            unit_summary = ", ".join(config.get("unit_names", []))
            await call_mcp_tool("memory__append_specialist_memory", {
                "specialist": name,
                "content": (
                    f"Session {session_id[:8]}: {status} on {unit_summary}. "
                    f"Confidence {confidence}. "
                    f"Key finding: {full_text[-300:]}"
                ),
            })
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
    scope_instance_id: str | None = None,
    include_orchestrator: bool = True,
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
            _run_specialist(spec, user_message, client, all_tools, session_id,
                            SPECIALIST_MODEL, queue, tool_calls_all,
                            running_state=running_state_for(spec["unit_names"]))
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
            yield json.dumps({"type": "text", "text": text})
        yield json.dumps({
            "type": "done", "input_tokens": 0, "output_tokens": 0,
            "latency_ms": int((time.monotonic() - start_ts) * 1000),
        })
        return

    # ── Synthesis ──────────────────────────────────────────────────────────────
    yield json.dumps({"type": "synthesis_start"})

    findings_text = "\n\n".join(
        f"=== {spec['label']} Agent ===\n"
        + findings.get(spec["name"], {}).get("text", "[No findings received]")
        for spec in active_specialists
    )
    orchestrator_user = (
        f"User question: {user_message}\n\n"
        f"Specialist findings:\n\n{findings_text}"
    )

    orch_input_tokens = orch_output_tokens = 0
    orch_tool_call_count = 0
    orch_start = time.monotonic()

    orch_tools = _filter_tools(all_tools, _ORCHESTRATOR_TOOL_PREFIXES)
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
                _action_keywords = ("propose", "control action", "corrective action", "clear fault", "set_setpoint")
                if any(kw in orch_full_text.lower() for kw in _action_keywords):
                    logger.warning("Orchestrator end_turn with action language but no tool call — text tail: %r", orch_full_text[-200:])
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
