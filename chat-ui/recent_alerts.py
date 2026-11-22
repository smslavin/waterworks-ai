"""The last few reactive alerts, and actions still awaiting approval, for pages
that weren't listening when they fired.

/api/events only reaches whoever is subscribed at that moment. A phone
drops that connection constantly (sleep, app switch, reload), so the mobile
page (gh-6) loads this on open and on every reconnect, the same way it
reloads the review queue.

Alerts: one entry per instance/attribute, as on the desktop's alarm list. A
repeat alarm replaces the old one and moves to the front. The diagnosis
arrives later, in reactive_warning_update / reactive_critical_update, and is
patched onto its entry.

Pending actions: an action_proposed stays here until its action_decision
(approved, denied or timed_out — tool_dispatch always sends one). Approving
happens on the desktop; the mobile page only shows that one is waiting.

In memory only; a chat-ui restart starts empty, which is also right for
pending actions, since their approval Futures die with the process.
"""

from __future__ import annotations

from collections import OrderedDict
from datetime import datetime, timezone

MAX_ALERTS = 50
_ALARM_TYPES = {"reactive_critical", "reactive_warning"}
_UPDATE_TYPES = {"reactive_warning_update", "reactive_critical_update"}

_alerts: OrderedDict[str, dict] = OrderedDict()
_pending: OrderedDict[str, dict] = OrderedDict()


def _key(event: dict) -> str:
    return f"{event.get('instance_id', '')}_{event.get('attribute') or 'unknown'}"


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


def record(event: dict) -> None:
    """Keep alarms and pending actions, apply their follow-ups, ignore the rest.

    Stamps a "ts" on alarm and proposal events (in place, so live
    subscribers see the same time the buffer stores).
    """
    kind = event.get("type")
    if kind in _ALARM_TYPES and event.get("instance_id"):
        event.setdefault("ts", _now())
        key = _key(event)
        _alerts.pop(key, None)
        _alerts[key] = dict(event)
        while len(_alerts) > MAX_ALERTS:
            _alerts.popitem(last=False)
    elif kind in _UPDATE_TYPES:
        stored = _alerts.get(_key(event))
        if stored is not None and event.get("content"):
            stored["content"] = event["content"]
    elif kind == "action_proposed" and event.get("action_id"):
        event.setdefault("ts", _now())
        _pending[event["action_id"]] = dict(event)
    elif kind == "action_decision":
        _pending.pop(event.get("action_id"), None)


def recent() -> list[dict]:
    """Alerts, newest first."""
    return [dict(e) for e in reversed(_alerts.values())]


def pending_actions() -> list[dict]:
    """Proposals still awaiting an answer, oldest first."""
    return [dict(e) for e in _pending.values()]


def clear() -> None:
    _alerts.clear()
    _pending.clear()
