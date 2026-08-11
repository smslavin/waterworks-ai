"""Periodic plant-status heartbeat — status_level and narrative always come
from the same real check, run only when there's reason to think something
may have changed (or a backstop interval has elapsed), not on a flat timer.

Why this exists: the enterprise orchestrator's diagnose_plant previously
triggered a full live multi-agent diagnosis for every overview-level
question, even "what's the overall status" — 1-3+ minutes, every time.
This module keeps a per-plant row (session_store.get_plant_status()) that
an enterprise-level question can read directly with a plain DB query
instead — see diagnose_plant_mcp's get_plant_status tool. diagnose_plant
itself is unchanged and remains the on-demand drill-down path.

status_level is NOT derived from monitor.current_status_level() directly —
an earlier version of this did that, on the assumption that the cheap
threshold check could stand in for a real status level between diagnoses.
It can't: monitor.py only tracks numeric attribute excursions, not
discrete equipment state (offline/running flags) — live testing showed it
report "Normal" while a full diagnosis in the same instant found real
offline equipment and said "Fault Detected". status_level is always
extracted from the narrative it's stored alongside, so the two can never
disagree; monitor.current_status_level() is used only as a cheap trigger
signal for deciding *when* to pay for a real check, with a max-staleness
backstop (STATUS_HEARTBEAT_MAX_STALE_TICKS) covering the cases it can't
see at all.
"""

import asyncio
import json
import logging
import os

import monitor as _monitor_mod
import session_store
from multi_agent_loop import run_multi_agent

logger = logging.getLogger(__name__)

INTERVAL_SECONDS = int(os.environ.get("STATUS_HEARTBEAT_INTERVAL", "900"))
# Force a real check at least this often even if the cheap trigger signal
# never changes — the backstop for what monitor.py's threshold tracking
# can't see at all (discrete equipment state). Default 4 * 900s = 1 hour.
MAX_STALE_TICKS = int(os.environ.get("STATUS_HEARTBEAT_MAX_STALE_TICKS", "4"))
# Same cheap model reactive escalation already uses for background diagnosis
# — this runs unattended on a timer, not in response to an operator waiting
# on it, so there's no reason to reach for a more expensive model.
_MODEL = os.environ.get("REACTIVE_MODEL", "claude-haiku-4-5-20251001")
_ANTHROPIC_API_KEY = os.environ.get("ANTHROPIC_API_KEY", "")

_task: asyncio.Task | None = None
# Cheap trigger-signal bookkeeping, not the displayed status_level (see
# module docstring) — in-memory, resets on restart, which just means the
# first tick after any restart always does a real check. That's correct:
# we don't know whether anything changed while this process was down.
_last_trigger_level: str | None = None
_ticks_since_check = 0


def is_running() -> bool:
    return _task is not None and not _task.done()


def stop() -> None:
    global _task
    if _task and not _task.done():
        _task.cancel()
    _task = None


async def _generate_narrative() -> str:
    """Full multi-agent diagnosis (all 4 specialists + Cascade synthesis) —
    same shape the interactive Plant panel triggers, just run on a timer
    instead of a click. Returns the synthesized text (the SUMMARY: block
    the model leads with, plus its detailed breakdown)."""
    messages = [
        {
            "role": "user",
            "content": (
                "Provide a brief status overview of the plant, covering all "
                "process areas. This is a periodic background check, not an "
                "operator question — be concise."
            ),
        }
    ]
    full_text = ""
    async for chunk in run_multi_agent(messages, _MODEL, api_key=_ANTHROPIC_API_KEY):
        try:
            event = json.loads(chunk)
        except (TypeError, ValueError):
            continue
        if event.get("type") == "text":
            full_text += event.get("text", "")
    return full_text


async def _tick() -> None:
    global _last_trigger_level, _ticks_since_check

    trigger_level = _monitor_mod.current_status_level()
    prev = session_store.get_plant_status()

    should_check = (
        prev is None
        or not prev.get("narrative")
        or trigger_level != _last_trigger_level
        or _ticks_since_check >= MAX_STALE_TICKS
    )
    if not should_check:
        _ticks_since_check += 1
        return

    try:
        narrative = await _generate_narrative()
    except Exception as exc:
        logger.warning("status_heartbeat check failed: %s", exc)
        return  # leave the last-known-good row untouched; retry next tick

    status_level, _confidence = session_store.extract_status_single(narrative)
    session_store.upsert_plant_status(status_level=status_level, narrative=narrative)
    _last_trigger_level = trigger_level
    _ticks_since_check = 0
    logger.info("status_heartbeat: checked (status_level=%s)", status_level)


async def _run() -> None:
    try:
        while True:
            try:
                await _tick()
            except Exception:
                logger.exception("status_heartbeat tick failed")
            await asyncio.sleep(INTERVAL_SECONDS)
    except asyncio.CancelledError:
        logger.info("status_heartbeat stopped")


def start(monitor: "_monitor_mod.AnomalyMonitor") -> asyncio.Task:
    """monitor param is unused directly (current_status_level() reads the
    module-level _window global) — accepted anyway so the caller's intent
    ("this heartbeat depends on the shared monitor already being started")
    is explicit at the call site, and so a future refactor away from a
    module global doesn't silently break this without a signature change
    forcing a look here too."""
    global _task
    if is_running():
        return _task
    _task = asyncio.create_task(_run())
    logger.info("status_heartbeat started (interval=%ds)", INTERVAL_SECONDS)
    return _task
