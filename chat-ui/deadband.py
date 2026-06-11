"""Deadband agent — validates anomaly is real and sustained before escalation."""

import asyncio
import json
import logging
import os
import re

import anthropic

from mcp_client import call_mcp_tool

logger = logging.getLogger(__name__)
DEADBAND_MODEL = os.environ.get("REACTIVE_MODEL", "claude-haiku-4-5-20251001")

DEADBAND_SYSTEM = """You are Deadband, a signal validation agent for an industrial water treatment plant.

Your only job is to determine whether a detected anomaly is real, sustained, and worth escalating.
You are the filter between sensor noise and a full diagnostic cycle.

You have three tools:
- verify_sustained: confirms the condition has persisted in InfluxDB history
- get_trend_direction: determines if the condition is worsening, improving, or stable
- check_confidence_threshold: gates the escalation decision on composite confidence

Call all three. For check_confidence_threshold, pass the confidence from get_trend_direction
directly — do not invent a different number or override the threshold parameter.

A sustained violation (fraction_in_violation >= 0.5) that is stable or worsening is almost
always worth escalating. Only suppress if the violation is not sustained OR is clearly improving.

Then respond with exactly one of:
ESCALATE: <one sentence reason>
SUPPRESS: <one sentence reason>

Do not diagnose. Do not recommend actions. Decide only: escalate or suppress."""

DEADBAND_TOOLS = [
    {
        "name": "verify_sustained",
        "description": "Check InfluxDB: has this attribute been outside its normal range for the given duration? Returns {sustained, fraction_in_violation, sample_count}.",
        "input_schema": {
            "type": "object",
            "properties": {
                "instance_id":       {"type": "string"},
                "attribute":         {"type": "string"},
                "condition":         {"type": "string", "enum": ["below_min", "above_max"]},
                "duration_minutes":  {"type": "number"},
                "normal_lo":         {"type": "number"},
                "normal_hi":         {"type": "number"},
            },
            "required": ["instance_id", "attribute", "condition", "duration_minutes", "normal_lo", "normal_hi"],
        },
    },
    {
        "name": "get_trend_direction",
        "description": "Query InfluxDB and compute whether the value is trending worsening, improving, or stable. Returns {direction, slope, confidence}.",
        "input_schema": {
            "type": "object",
            "properties": {
                "instance_id":        {"type": "string"},
                "attribute":          {"type": "string"},
                "time_window_minutes": {"type": "number"},
            },
            "required": ["instance_id", "attribute", "time_window_minutes"],
        },
    },
    {
        "name": "check_confidence_threshold",
        "description": "Gate: is this confidence score high enough to escalate? Returns {escalate, confidence, threshold}.",
        "input_schema": {
            "type": "object",
            "properties": {
                "confidence": {"type": "number"},
                "threshold":  {"type": "number"},
            },
            "required": ["confidence"],
        },
    },
]


async def _verify_sustained(instance_id, attribute, condition, duration_minutes, normal_lo, normal_hi, aggregator_url):
    comp = "<" if condition == "below_min" else ">"
    limit = normal_lo if condition == "below_min" else normal_hi
    # Use seconds for sub-minute precision. Clamp to 30s minimum.
    window_s = max(30, int(duration_minutes * 60))
    flux_viol = (
        f'from(bucket:"wtp") |> range(start: -{window_s}s) '
        f'|> filter(fn: (r) => r._measurement == "wtp_process" '
        f'and r.instance == "{instance_id}" and r._field == "{attribute}") '
        f'|> filter(fn: (r) => r._value {comp} {limit}) |> count()'
    )
    flux_total = flux_viol.replace(f'|> filter(fn: (r) => r._value {comp} {limit}) ', "")
    try:
        v = _extract_count(await call_mcp_tool("influxdb__query", {"bucket": "wtp", "flux_query": flux_viol}, aggregator_url))
        t = _extract_count(await call_mcp_tool("influxdb__query", {"bucket": "wtp", "flux_query": flux_total}, aggregator_url))
        fraction = v / t if t > 0 else 0.0
        return {"sustained": fraction >= 0.5, "fraction_in_violation": round(fraction, 2), "sample_count": t}
    except Exception as e:
        return {"sustained": False, "error": str(e)}


async def _get_trend_direction(instance_id, attribute, time_window_minutes, aggregator_url):
    flux = (
        f'from(bucket:"wtp") |> range(start: -{int(time_window_minutes)}m) '
        f'|> filter(fn: (r) => r._measurement == "wtp_process" '
        f'and r.instance == "{instance_id}" and r._field == "{attribute}") '
        f'|> sort(columns: ["_time"])'
    )
    try:
        values = _extract_values(await call_mcp_tool("influxdb__query", {"bucket": "wtp", "flux_query": flux}, aggregator_url))
        if len(values) < 4:
            return {"direction": "stable", "slope": 0.0, "confidence": 0.3}
        slope = _linear_slope(values)
        direction = "stable" if abs(slope) < 0.5 else ("worsening" if slope < 0 else "improving")
        # Confidence reflects how actionable the trend is, not how steep the slope is:
        # stable   = system is stuck in a bad state — high confidence it won't self-correct
        # worsening = actively deteriorating — highest confidence
        # improving = may self-correct — lower confidence
        confidence = {"stable": 0.80, "worsening": 0.95, "improving": 0.35}[direction]
        return {"direction": direction, "slope": round(slope, 3), "confidence": confidence}
    except Exception as e:
        return {"direction": "stable", "slope": 0.0, "confidence": 0.0, "error": str(e)}


def _check_confidence_threshold(confidence, threshold=0.7):
    return {"escalate": confidence >= threshold, "confidence": confidence, "threshold": threshold}


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
        return _check_confidence_threshold(**inputs)
    return {"error": f"unknown tool: {name}"}


async def run_deadband(anomaly: dict, aggregator_url: str) -> tuple[bool, str]:
    """Returns (should_escalate, reason). Severity is not re-derived here — it's in anomaly dict."""
    client = anthropic.AsyncAnthropic()
    lo, hi = anomaly["normal_range"]
    dur_min = max(1, round(anomaly['duration_seconds'] / 60, 1))
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

    for _ in range(8):
        resp = await client.messages.create(
            model=DEADBAND_MODEL, max_tokens=512,
            system=DEADBAND_SYSTEM, tools=DEADBAND_TOOLS, messages=messages,
        )
        if resp.stop_reason == "end_turn":
            text = next((b.text for b in resp.content if hasattr(b, "text")), "")
            escalate = "ESCALATE" in text
            reason = text.split("ESCALATE:", 1)[-1].strip() if escalate else text.split("SUPPRESS:", 1)[-1].strip()
            return escalate, reason
        tool_results = []
        for block in resp.content:
            if block.type == "tool_use":
                result = await _dispatch(block.name, block.input, aggregator_url)
                tool_results.append({"type": "tool_result", "tool_use_id": block.id, "content": json.dumps(result)})
        messages.append({"role": "assistant", "content": resp.content})
        messages.append({"role": "user", "content": tool_results})

    return False, "max_rounds exceeded"
