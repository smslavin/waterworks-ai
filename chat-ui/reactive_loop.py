"""Reactive loop: monitor → deadband → tiered routing by severity."""

import asyncio
import json
import logging
import os
import time
import uuid

import audit
from deadband import run_deadband
from monitor import AnomalyMonitor
from multi_agent_loop import run_multi_agent as _cascade

logger = logging.getLogger(__name__)

COOLDOWN     = int(os.environ.get("REACTIVE_COOLDOWN",      "60"))
MIN_DURATION = float(os.environ.get("REACTIVE_MIN_DURATION", "30"))

_MAX_CONCURRENT = 2   # max simultaneous Deadband+Cascade runs

_active:          set[str]          = set()
_cooldown_until:  dict[str, float]  = {}
_task:            asyncio.Task | None = None
_monitor:         AnomalyMonitor | None = None


def is_running() -> bool:
    return _task is not None and not _task.done()


def stop() -> None:
    global _task, _monitor
    if _task and not _task.done():
        _task.cancel()
    _task = None
    if _monitor:
        try:
            _monitor._client.loop_stop()
            _monitor._client.disconnect()
        except Exception:
            pass
    _monitor = None


def _can_trigger(instance_id: str) -> bool:
    return (
        instance_id not in _active
        and time.time() >= _cooldown_until.get(instance_id, 0)
        and len(_active) < _MAX_CONCURRENT
    )


def _trigger_message(anomaly: dict, deadband_reason: str) -> str:
    lo, hi = anomaly["normal_range"]
    return (
        f"REACTIVE DIAGNOSTIC — system-initiated, not an operator query.\n\n"
        f"Anomaly confirmed by Deadband:\n"
        f"  Equipment: {anomaly['instance_id']} ({anomaly['equipment_type']})\n"
        f"  Attribute: {anomaly['attribute']} = {anomaly['current_value']:.2f} (normal: {lo}–{hi})\n"
        f"  Sustained: {anomaly['duration_seconds']:.0f}s | Severity: {anomaly['severity']}\n"
        f"  Deadband: {deadband_reason}\n\n"
        "Investigate and diagnose the root cause. Assess severity.\n\n"
        "CRITICAL: If a corrective action is warranted, you MUST call the control__propose_action "
        "tool immediately — do NOT describe the action in text. Describing an action without "
        "calling the tool is a protocol violation."
    )


async def _collect_text(gen, broadcast_fn=None) -> str:
    """Collect 'text' events from run_multi_agent. Forward action_proposed/action_decision via broadcast_fn."""
    chunks = []
    async for line in gen:
        try:
            evt = json.loads(line)
            t = evt.get("type")
            if t == "text":
                chunks.append(evt["text"])
            elif t in ("action_proposed", "action_decision") and broadcast_fn:
                broadcast_fn(evt)
        except Exception:
            pass
    return "".join(chunks)


async def _run_cascade(anomaly: dict, deadband_reason: str, model: str, broadcast_fn=None, *, include_orchestrator: bool = True, cascade_id: str | None = None) -> str:
    messages = [{"role": "user", "content": _trigger_message(anomaly, deadband_reason)}]
    return await _collect_text(
        _cascade(messages, model, scope_instance_id=anomaly["instance_id"], include_orchestrator=include_orchestrator, cascade_id=cascade_id),
        broadcast_fn,
    )


async def _handle_anomaly(anomaly: dict, aggregator_url: str, model: str, broadcast_fn):
    instance_id = anomaly["instance_id"]
    severity    = anomaly["severity"]
    cascade_id  = str(uuid.uuid4())
    _active.add(instance_id)
    escalated = False
    try:
        audit.log("reactive_anomaly_detected", cascade_id=cascade_id, **anomaly)
        escalate, reason = await run_deadband(anomaly, aggregator_url, cascade_id=cascade_id)
        audit.log("reactive_deadband_verdict", instance_id=instance_id, escalate=escalate,
                  severity=severity, reason=reason)

        if not escalate:
            logger.info("Deadband suppressed %s/%s: %s", instance_id, anomaly["attribute"], reason)
            return

        escalated = True

        logger.info("Deadband escalated %s/%s [%s] → routing", instance_id, anomaly["attribute"], severity)

        if severity == "advisory":
            broadcast_fn({
                "type":         "reactive_advisory",
                "instance_id":  instance_id,
                "attribute":    anomaly["attribute"],
                "value":        anomaly["current_value"],
                "normal_range": anomaly["normal_range"],
                "condition":    anomaly["condition"],
                "reason":       reason,
            })
            audit.log("reactive_advisory_surfaced", instance_id=instance_id)

        elif severity == "warning":
            broadcast_fn({
                "type":         "reactive_warning",
                "instance_id":  instance_id,
                "attribute":    anomaly["attribute"],
                "value":        anomaly["current_value"],
                "normal_range": anomaly["normal_range"],
                "reason":       reason,
                "content":      None,
            })
            content = await _run_cascade(anomaly, reason, model, broadcast_fn, include_orchestrator=False, cascade_id=cascade_id)
            broadcast_fn({
                "type":        "reactive_warning_update",
                "instance_id": instance_id,
                "attribute":   anomaly["attribute"],
                "content":     content,
            })
            audit.log("reactive_warning_complete", instance_id=instance_id)

        else:  # critical
            content = await _run_cascade(anomaly, reason, model, broadcast_fn, cascade_id=cascade_id)
            broadcast_fn({
                "type":         "reactive_critical",
                "instance_id":  instance_id,
                "attribute":    anomaly["attribute"],
                "value":        anomaly["current_value"],
                "normal_range": anomaly["normal_range"],
                "reason":       reason,
                "content":      content,
            })
            audit.log("reactive_critical_complete", instance_id=instance_id)

    except Exception as e:
        logger.error("reactive handler error for %s: %s", instance_id, e)
        audit.log("reactive_error", instance_id=instance_id, error=str(e))
    finally:
        _active.discard(instance_id)
        # Full cooldown after a cascade runs; short retry if Deadband suppressed so
        # the monitor can re-check once more InfluxDB history has accumulated.
        _cooldown_until[instance_id] = time.time() + (COOLDOWN if escalated else MIN_DURATION)


async def _run(broker_url: str, aggregator_url: str, model: str, broadcast_fn):
    global _monitor
    try:
        _monitor = AnomalyMonitor(broker_url=broker_url, min_duration=MIN_DURATION)
        await _monitor.start()
        logger.info("Reactive loop started (broker=%s min_duration=%.0fs)", broker_url, MIN_DURATION)
        async for anomaly in _monitor.events():
            if _can_trigger(anomaly["instance_id"]):
                asyncio.create_task(_handle_anomaly(anomaly, aggregator_url, model, broadcast_fn))
    except asyncio.CancelledError:
        logger.info("Reactive loop stopped")
    except Exception:
        logger.exception("Reactive loop crashed — restart via UI toggle")


def start(broker_url: str, aggregator_url: str, model: str, broadcast_fn) -> asyncio.Task:
    """Create and register the reactive loop task. Returns the task."""
    global _task
    if is_running():
        return _task
    _task = asyncio.create_task(_run(broker_url, aggregator_url, model, broadcast_fn))
    return _task
