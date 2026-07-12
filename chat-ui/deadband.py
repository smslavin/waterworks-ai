"""Deadband agent — validates anomaly is real and sustained before escalation."""

import asyncio
import json
import logging
import os
import re
import time

import anthropic

import metrics
from mcp_client import call_mcp_tool
from topology import load as _load_topology

from fieldworks.agents.deadband import (
    DEADBAND_TOOLS,
    build_deadband_system,
    check_confidence_threshold,
    parse_decision,
)

logger = logging.getLogger(__name__)
DEADBAND_MODEL = os.environ.get("REACTIVE_MODEL", "claude-haiku-4-5-20251001")
INFLUXDB_BUCKET = os.environ.get("INFLUXDB_BUCKET", "waterworks")

DEADBAND_SYSTEM = build_deadband_system(_load_topology().facility.name)


async def _verify_sustained(
    instance_id,
    attribute,
    condition,
    duration_minutes,
    normal_lo,
    normal_hi,
    aggregator_url,
):
    comp = "<" if condition == "below_min" else ">"
    limit = normal_lo if condition == "below_min" else normal_hi
    # Use seconds for sub-minute precision. Clamp to 30s minimum.
    window_s = max(30, int(duration_minutes * 60))
    flux_viol = (
        f'from(bucket:"{INFLUXDB_BUCKET}") |> range(start: -{window_s}s) '
        f'|> filter(fn: (r) => r._measurement == "wtp_process" '
        f'and r.instance == "{instance_id}" and r.attribute == "{attribute}") '
        f"|> filter(fn: (r) => r._value {comp} {limit}) |> last()"
    )
    flux_total = flux_viol.replace(
        f"|> filter(fn: (r) => r._value {comp} {limit}) ", ""
    )
    try:
        raw_viol = await call_mcp_tool(
            "influxdb__query", {"flux_query": flux_viol}, aggregator_url
        )
        raw_total = await call_mcp_tool(
            "influxdb__query", {"flux_query": flux_total}, aggregator_url
        )
        logger.debug("deadband raw_viol=%r raw_total=%r", raw_viol, raw_total)
        v = _extract_count(raw_viol)
        t = _extract_count(raw_total)
        fraction = v / t if t > 0 else 0.0
        logger.info(
            "deadband verify_sustained %s/%s v=%d t=%d fraction=%.2f",
            instance_id,
            attribute,
            v,
            t,
            fraction,
        )
        return {
            "sustained": fraction >= 0.5,
            "fraction_in_violation": round(fraction, 2),
            "sample_count": t,
        }
    except Exception as e:
        return {"sustained": False, "error": str(e)}


async def _get_trend_direction(
    instance_id, attribute, time_window_minutes, aggregator_url
):
    flux = (
        f'from(bucket:"{INFLUXDB_BUCKET}") |> range(start: -{int(time_window_minutes)}m) '
        f'|> filter(fn: (r) => r._measurement == "wtp_process" '
        f'and r.instance == "{instance_id}" and r.attribute == "{attribute}") '
        f'|> sort(columns: ["_time"])'
    )
    try:
        values = _extract_values(
            await call_mcp_tool(
                "influxdb__query",
                {"flux_query": flux},
                aggregator_url,
            )
        )
        if len(values) < 4:
            return {"direction": "stable", "slope": 0.0, "confidence": 0.3}
        slope = _linear_slope(values)
        direction = (
            "stable"
            if abs(slope) < 0.5
            else ("worsening" if slope < 0 else "improving")
        )
        # Confidence reflects how actionable the trend is, not how steep the slope is:
        # stable   = system is stuck in a bad state — high confidence it won't self-correct
        # worsening = actively deteriorating — highest confidence
        # improving = may self-correct — lower confidence
        confidence = {"stable": 0.80, "worsening": 0.95, "improving": 0.35}[direction]
        return {
            "direction": direction,
            "slope": round(slope, 3),
            "confidence": confidence,
        }
    except Exception as e:
        return {"direction": "stable", "slope": 0.0, "confidence": 0.0, "error": str(e)}


def _extract_count(r) -> int:
    m = re.search(r"\b(\d+)\b", str(r))
    return int(m.group(1)) if m else 0


def _extract_values(r) -> list[float]:
    return [float(x) for x in re.findall(r"\b\d+(?:\.\d+)?\b", str(r))]


def _linear_slope(values: list[float]) -> float:
    n = len(values)
    xs = list(range(n))
    x_mean = sum(xs) / n
    y_mean = sum(values) / n
    num = sum((x - x_mean) * (y - y_mean) for x, y in zip(xs, values))
    den = sum((x - x_mean) ** 2 for x in xs)
    return num / den if den else 0.0


async def _dispatch(name, inputs, aggregator_url):
    if name == "verify_sustained":
        return await _verify_sustained(aggregator_url=aggregator_url, **inputs)
    if name == "get_trend_direction":
        return await _get_trend_direction(aggregator_url=aggregator_url, **inputs)
    if name == "check_confidence_threshold":
        return check_confidence_threshold(**inputs)
    return {"error": f"unknown tool: {name}"}


async def run_deadband(
    anomaly: dict, aggregator_url: str, cascade_id: str | None = None
) -> tuple[bool, str]:
    """Returns (should_escalate, reason). Severity is not re-derived here — it's in anomaly dict."""
    client = anthropic.AsyncAnthropic()
    lo, hi = anomaly["normal_range"]
    dur_min = max(1, round(anomaly["duration_seconds"] / 60, 1))
    prompt = (
        f"Anomaly detected:\n"
        f"  Equipment: {anomaly['instance_id']} ({anomaly['equipment_type']})\n"
        f"  Attribute: {anomaly['attribute']} = {anomaly['current_value']:.2f} (normal: {lo}–{hi})\n"
        f"  Condition: {anomaly['condition']} | Severity tier: {anomaly['severity']}\n"
        f"  Confirmed duration: {anomaly['duration_seconds']:.0f}s\n"
        f"  → Call verify_sustained with duration_minutes={dur_min} to match the known fault window.\n\n"
        "Use your three tools to validate, then return ESCALATE or SUPPRESS."
    )
    messages = [{"role": "user", "content": prompt}]
    start = time.monotonic()
    total_input = total_output = tool_call_count = 0

    for _ in range(8):
        resp = await client.messages.create(
            model=DEADBAND_MODEL,
            max_tokens=512,
            system=DEADBAND_SYSTEM,
            tools=DEADBAND_TOOLS,
            messages=messages,
        )
        total_input += resp.usage.input_tokens
        total_output += resp.usage.output_tokens
        if resp.stop_reason == "end_turn":
            text = next((b.text for b in resp.content if hasattr(b, "text")), "")
            escalate, reason = parse_decision(text)
            metrics.log_turn(
                session_id=cascade_id or "reactive",
                model=DEADBAND_MODEL,
                input_tokens=total_input,
                output_tokens=total_output,
                tool_call_count=tool_call_count,
                error_count=0,
                latency_ms=int((time.monotonic() - start) * 1000),
                context_pressure=None,
                user_message=f"{anomaly['instance_id']}/{anomaly['attribute']}",
                specialist="deadband",
                cascade_id=cascade_id,
            )
            return escalate, reason
        tool_results = []
        for block in resp.content:
            if block.type == "tool_use":
                tool_call_count += 1
                result = await _dispatch(block.name, block.input, aggregator_url)
                tool_results.append(
                    {
                        "type": "tool_result",
                        "tool_use_id": block.id,
                        "content": json.dumps(result),
                    }
                )
        messages.append({"role": "assistant", "content": resp.content})
        messages.append({"role": "user", "content": tool_results})

    metrics.log_turn(
        session_id=cascade_id or "reactive",
        model=DEADBAND_MODEL,
        input_tokens=total_input,
        output_tokens=total_output,
        tool_call_count=tool_call_count,
        error_count=1,
        latency_ms=int((time.monotonic() - start) * 1000),
        context_pressure=None,
        user_message=f"{anomaly['instance_id']}/{anomaly['attribute']}",
        specialist="deadband",
        cascade_id=cascade_id,
    )
    return False, "max_rounds exceeded"
