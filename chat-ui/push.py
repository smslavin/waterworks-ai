"""Web Push for the mobile page (gh-80).

A phone that installed the mobile page can ask to be woken for the events
an operator away from the desk needs: a critical alarm, a control action
waiting for approval, a review queued. broadcast_alert() hands every event
here; notify() picks those three and sends them to every subscribed device.

Needs a secure context: service workers and the Push API don't exist over
plain http on a LAN IP, and iOS (16.4+) also needs the page added to the
homescreen. CLAUDE.md describes putting Tailscale Serve in front of
chat-ui, with WATERWORKS_REQUIRE_TOKEN=1 so the token gate stays on.

VAPID keys are generated on first use and kept at VAPID_KEY_PATH (default:
next to metrics.db). Subscriptions live in metrics.db's push_subscriptions
table. pywebpush blocks, so sends run in the default executor; a device
whose subscription the push service reports gone (404/410) is dropped.
"""

from __future__ import annotations

import asyncio
import json
import logging
import os
import sqlite3
import threading
from datetime import datetime, timezone
from pathlib import Path

import session_store

logger = logging.getLogger(__name__)

SITE_NAME = os.environ.get("SITE_NAME", "Waterworks")
# Push services use the VAPID subject to reach whoever runs the sender, so
# it names this deployment's operator: a mailto: address or a bare
# https://host (no path; py_vapid and Apple both refuse anything else).
# There is no honest default, so push stays off until it is set.
SUBJECT = os.environ.get("VAPID_SUBJECT", "")
_lock = threading.Lock()


def configuration_problem() -> str | None:
    """Why push can't run, or None if it can."""
    from py_vapid import _check_sub

    if not SUBJECT:
        return (
            "set VAPID_SUBJECT in .env to a contact for this deployment: "
            "mailto:you@example.com or https://your.host"
        )
    if not _check_sub(SUBJECT):
        return f"VAPID_SUBJECT {SUBJECT!r} must be mailto:<address> or https://<host> with no path"
    return None


def _key_path() -> Path:
    default = Path(session_store._DB_PATH).with_name("vapid_private.pem")
    return Path(os.environ.get("VAPID_KEY_PATH", default))


def _vapid():
    """The VAPID key pair, generated and saved on first use."""
    from py_vapid import Vapid

    path = _key_path()
    with _lock:
        if path.exists():
            return Vapid.from_file(str(path))
        vapid = Vapid()
        vapid.generate_keys()
        vapid.save_key(str(path))
        os.chmod(path, 0o600)
        logger.info("Generated VAPID key for Web Push at %s", path)
        return vapid


def public_key() -> str:
    """The applicationServerKey a browser subscribes with: the raw P-256
    public point, base64url without padding."""
    from cryptography.hazmat.primitives import serialization
    from py_vapid import b64urlencode

    raw = _vapid().public_key.public_bytes(
        serialization.Encoding.X962, serialization.PublicFormat.UncompressedPoint
    )
    return b64urlencode(raw)


# ── Subscriptions ─────────────────────────────────────────────────────────────


def _conn() -> sqlite3.Connection:
    c = sqlite3.connect(session_store._DB_PATH)
    c.row_factory = sqlite3.Row
    c.execute("""CREATE TABLE IF NOT EXISTS push_subscriptions (
            endpoint    TEXT PRIMARY KEY,
            p256dh      TEXT NOT NULL,
            auth        TEXT NOT NULL,
            created_at  TEXT NOT NULL
        )""")
    return c


def subscribe(subscription: dict) -> None:
    """Store a browser PushSubscription (its toJSON() shape). Raises
    ValueError for anything that isn't one."""
    endpoint = subscription.get("endpoint")
    keys = subscription.get("keys") or {}
    if not isinstance(endpoint, str) or not endpoint.startswith("https://"):
        raise ValueError("endpoint must be an https:// URL")
    if not keys.get("p256dh") or not keys.get("auth"):
        raise ValueError("keys.p256dh and keys.auth are required")
    with _lock, _conn() as c:
        c.execute(
            """INSERT INTO push_subscriptions (endpoint, p256dh, auth, created_at)
               VALUES (?, ?, ?, ?)
               ON CONFLICT(endpoint) DO UPDATE
               SET p256dh = excluded.p256dh, auth = excluded.auth""",
            (
                endpoint,
                keys["p256dh"],
                keys["auth"],
                datetime.now(timezone.utc).isoformat(),
            ),
        )


def unsubscribe(endpoint: str) -> None:
    with _lock, _conn() as c:
        c.execute("DELETE FROM push_subscriptions WHERE endpoint = ?", (endpoint,))


def subscriptions() -> list[dict]:
    with _lock, _conn() as c:
        rows = c.execute("SELECT endpoint, p256dh, auth FROM push_subscriptions")
        return [
            {
                "endpoint": r["endpoint"],
                "keys": {"p256dh": r["p256dh"], "auth": r["auth"]},
            }
            for r in rows
        ]


# ── Messages ──────────────────────────────────────────────────────────────────


def message_for(event: dict) -> dict | None:
    """The notification for an event worth waking a phone for, or None.
    `tag` collapses repeats of the same alarm or proposal into one."""
    kind = event.get("type")
    if kind == "reactive_critical" and event.get("instance_id"):
        nr = event.get("normal_range")
        normal = "–".join(map(str, nr)) if isinstance(nr, list) else nr
        value = event.get("value")
        value = f"{value:.2f}" if isinstance(value, (int, float)) else value
        return {
            "title": f"{SITE_NAME}: critical on {event['instance_id']}",
            "body": f"{event.get('attribute', '?')} {value} (normal {normal})",
            "tag": f"critical-{event['instance_id']}-{event.get('attribute')}",
            "ttl": 3600,
        }
    if kind == "action_proposed" and event.get("action_id"):
        what = " · ".join(
            str(event[k])
            for k in ("action_type", "target", "attribute")
            if event.get(k)
        )
        value = event.get("value")
        return {
            "title": f"{SITE_NAME}: approval waiting",
            "body": (what or "Control action") + (f" → {value}" if value else ""),
            "tag": f"action-{event['action_id']}",
            # Unanswered proposals time out after 5 minutes; a later push
            # would point at something already settled.
            "ttl": 300,
        }
    if kind == "insight_review_created":
        return {
            "title": f"{SITE_NAME}: review queued",
            "body": f"{event.get('category_label', 'Insight')} on {event.get('node_id', '?')}",
            "tag": f"review-{event.get('review_id')}",
            "ttl": 86400,
        }
    return None


# ── Sending ───────────────────────────────────────────────────────────────────


def _send_all(message: dict) -> int:
    """Send to every subscriber; drop the ones the push service says are
    gone. Returns how many sends succeeded. Runs in an executor thread."""
    from pywebpush import WebPushException, webpush

    payload = json.dumps(
        {
            "title": message["title"],
            "body": message["body"],
            "tag": message["tag"],
            "url": "/mobile/",
        }
    )
    key = str(_key_path())
    _vapid()  # make sure the key file exists before pywebpush reads it
    sent = 0
    for sub in subscriptions():
        try:
            webpush(
                subscription_info=sub,
                data=payload,
                vapid_private_key=key,
                vapid_claims={"sub": SUBJECT},
                ttl=message["ttl"],
                timeout=10,
            )
            sent += 1
        except WebPushException as exc:
            status = getattr(exc.response, "status_code", None)
            if status in (404, 410):
                unsubscribe(sub["endpoint"])
                logger.info("Dropped expired push subscription (%s)", status)
            else:
                logger.warning("Web Push send failed (%s): %s", status, exc)
        except Exception as exc:  # network trouble must never reach callers
            logger.warning("Web Push send failed: %s", exc)
    return sent


def notify(event: dict) -> None:
    """Called for every broadcast event; sends only the ones message_for()
    picks, and only if any device subscribed. Never blocks or raises."""
    message = message_for(event)
    if message is None or configuration_problem():
        return
    try:
        if not subscriptions():
            return
    except sqlite3.Error as exc:
        logger.warning("push_subscriptions unreadable: %s", exc)
        return
    try:
        loop = asyncio.get_running_loop()
    except RuntimeError:
        threading.Thread(target=_send_all, args=(message,), daemon=True).start()
        return
    loop.run_in_executor(None, _send_all, message)
