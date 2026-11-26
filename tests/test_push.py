"""Web Push for the mobile page (gh-80): which events wake a phone, the
subscription store, sending and dropping dead subscriptions, the gated
routes, and WATERWORKS_REQUIRE_TOKEN for chat-ui behind a proxy."""

import asyncio
import json
import os
import stat
import subprocess
import sys
from pathlib import Path
from types import SimpleNamespace

import pytest
from starlette.testclient import TestClient

import auth
import backend
import push
import session_store

SUB = {
    "endpoint": "https://web.push.apple.com/abc",
    "keys": {"p256dh": "BPk", "auth": "xyz"},
}


@pytest.fixture(autouse=True)
def isolated(tmp_path, monkeypatch):
    monkeypatch.setattr(session_store, "_DB_PATH", str(tmp_path / "metrics.db"))
    monkeypatch.delenv("VAPID_KEY_PATH", raising=False)
    monkeypatch.setattr(push, "SUBJECT", "mailto:ops@example.com")


@pytest.fixture()
def client():
    return TestClient(backend.app)


# ── Which events ──────────────────────────────────────────────────────────────


def test_critical_alarm_wakes_the_phone():
    msg = push.message_for(
        {
            "type": "reactive_critical",
            "instance_id": "RawWater_01",
            "attribute": "Flow",
            "value": 12.345,
            "normal_range": [40, 60],
        }
    )
    assert msg["title"].endswith("critical on RawWater_01")
    assert msg["body"] == "Flow 12.35 (normal 40–60)"
    assert msg["tag"] == "critical-RawWater_01-Flow"


def test_waiting_approval_expires_with_its_timeout():
    msg = push.message_for(
        {
            "type": "action_proposed",
            "action_id": "a1",
            "action_type": "fault_clear",
            "target": "RawWater_01",
            "value": "",
        }
    )
    assert msg["body"] == "fault_clear · RawWater_01"
    assert msg["ttl"] == 300


def test_queued_review_wakes_the_phone():
    msg = push.message_for(
        {
            "type": "insight_review_created",
            "review_id": "r1",
            "node_id": "RawWater_01",
            "category_label": "Maintenance flag",
        }
    )
    assert msg["body"] == "Maintenance flag on RawWater_01"


@pytest.mark.parametrize(
    "event",
    [
        {"type": "reactive_warning", "instance_id": "X"},
        {"type": "reactive_critical_update", "instance_id": "X"},
        {"type": "action_decision", "action_id": "a1"},
        {"type": "ping"},
    ],
)
def test_other_events_stay_quiet(event):
    assert push.message_for(event) is None


# ── Subscriptions ─────────────────────────────────────────────────────────────


def test_subscribe_is_idempotent_and_unsubscribe_removes():
    push.subscribe(SUB)
    push.subscribe({**SUB, "keys": {"p256dh": "new", "auth": "xyz"}})
    assert push.subscriptions() == [{**SUB, "keys": {"p256dh": "new", "auth": "xyz"}}]
    push.unsubscribe(SUB["endpoint"])
    assert push.subscriptions() == []


@pytest.mark.parametrize(
    "bad",
    [
        {**SUB, "endpoint": "http://insecure.example/x"},
        {**SUB, "keys": {"p256dh": "BPk"}},
        {"keys": SUB["keys"]},
    ],
)
def test_subscribe_refuses_what_isnt_a_push_subscription(bad):
    with pytest.raises(ValueError):
        push.subscribe(bad)


# ── Sending ───────────────────────────────────────────────────────────────────


@pytest.fixture()
def fake_webpush(monkeypatch):
    import pywebpush

    sent, fail = [], {}

    def webpush(
        *, subscription_info, data, vapid_private_key, vapid_claims, ttl, timeout
    ):
        assert timeout == 10
        if subscription_info["endpoint"] in fail:
            raise pywebpush.WebPushException(
                "push failed", response=fail[subscription_info["endpoint"]]
            )
        sent.append(
            (subscription_info["endpoint"], json.loads(data), ttl, vapid_claims)
        )

    monkeypatch.setattr(pywebpush, "webpush", webpush)
    return sent, fail


def test_send_reaches_every_subscriber_and_drops_dead_ones(fake_webpush):
    sent, fail = fake_webpush
    push.subscribe(SUB)
    push.subscribe({**SUB, "endpoint": "https://gone.example/1"})
    push.subscribe({**SUB, "endpoint": "https://flaky.example/1"})
    fail["https://gone.example/1"] = SimpleNamespace(status_code=410)
    fail["https://flaky.example/1"] = SimpleNamespace(status_code=503)

    msg = push.message_for({"type": "action_proposed", "action_id": "a1"})
    assert push._send_all(msg) == 1

    ((endpoint, payload, ttl, claims),) = sent
    assert endpoint == SUB["endpoint"]
    assert payload["url"] == "/mobile/" and payload["tag"] == "action-a1"
    assert ttl == 300 and claims["sub"].startswith(("https://", "mailto:"))
    # Gone (410) is dropped; a temporary failure (503) is kept for next time.
    assert {s["endpoint"] for s in push.subscriptions()} == {
        SUB["endpoint"],
        "https://flaky.example/1",
    }


def test_notify_sends_off_the_event_loop(fake_webpush, monkeypatch):
    sent, _ = fake_webpush
    push.subscribe(SUB)

    async def fire():
        push.notify({"type": "insight_review_created", "review_id": "r1"})
        await asyncio.sleep(0.2)  # the executor thread finishes the send

    asyncio.run(fire())
    assert len(sent) == 1


def test_notify_without_subscribers_does_nothing(fake_webpush):
    sent, _ = fake_webpush
    push.notify({"type": "reactive_critical", "instance_id": "X"})
    assert sent == []


def test_broadcast_hands_every_event_to_push(monkeypatch):
    seen = []
    monkeypatch.setattr(backend.push, "notify", seen.append)
    backend.broadcast_alert({"type": "ping"})
    assert seen == [{"type": "ping"}]


# ── VAPID key and routes ──────────────────────────────────────────────────────


def test_vapid_key_is_generated_once_and_private(tmp_path):
    first = push.public_key()
    assert push.public_key() == first
    assert len(first) == 87  # 65-byte uncompressed P-256 point, base64url
    mode = stat.S_IMODE(os.stat(tmp_path / "vapid_private.pem").st_mode)
    assert mode == 0o600


def test_push_routes(client):
    key = client.get("/api/push/key").json()["public_key"]
    assert key == push.public_key()
    assert client.post("/api/push/subscribe", json=SUB).json() == {"ok": True}
    assert client.post("/api/push/subscribe", json={"endpoint": 1}).status_code == 400
    client.post("/api/push/unsubscribe", json={"endpoint": SUB["endpoint"]})
    assert push.subscriptions() == []


@pytest.mark.parametrize(
    "method,path",
    [
        ("get", "/api/push/key"),
        ("post", "/api/push/subscribe"),
        ("post", "/api/push/unsubscribe"),
    ],
)
def test_push_routes_need_the_token_when_exposed(monkeypatch, client, method, path):
    monkeypatch.setattr(auth, "EXPOSED", True)
    monkeypatch.setattr(auth, "_TOKEN", "test-secret")
    assert getattr(client, method)(path).status_code == 401


def test_require_token_keeps_the_gate_on_behind_a_proxy():
    """Tailscale Serve reaches chat-ui on loopback; without this setting the
    gate would switch off for everyone the proxy lets in. auth reads the
    environment at import, so check it in a fresh interpreter."""
    chat_ui = Path(__file__).parent.parent / "chat-ui"
    code = f"import sys; sys.path.insert(0, {str(chat_ui)!r}); import auth; print(auth.EXPOSED)"
    env = {k: v for k, v in os.environ.items() if k not in ("BIND_HOST",)}

    def run(**extra):
        return subprocess.run(
            [sys.executable, "-c", code],
            env={**env, **extra},
            capture_output=True,
            text=True,
            check=True,
        ).stdout.strip()

    assert run(WATERWORKS_REQUIRE_TOKEN="0") == "False"
    assert run(WATERWORKS_REQUIRE_TOKEN="1") == "True"


def test_a_real_send_is_encrypted_and_vapid_signed(monkeypatch):
    """Runs pywebpush for real against a generated subscriber key pair, and
    stops only at the HTTP call: proves the key file, the claims and the
    payload encryption all work together, which the faked sends can't."""
    import base64

    import requests
    from cryptography.hazmat.primitives import serialization
    from cryptography.hazmat.primitives.asymmetric import ec

    def b64(raw):
        return base64.urlsafe_b64encode(raw).rstrip(b"=").decode()

    subscriber = ec.generate_private_key(ec.SECP256R1())
    p256dh = subscriber.public_key().public_bytes(
        serialization.Encoding.X962, serialization.PublicFormat.UncompressedPoint
    )
    push.subscribe(
        {
            "endpoint": SUB["endpoint"],
            "keys": {"p256dh": b64(p256dh), "auth": b64(os.urandom(16))},
        }
    )

    posted = []

    def fake_post(url, data=None, headers=None, timeout=None, **kw):
        posted.append((url, data, headers))
        return SimpleNamespace(status_code=201, text="", headers={})

    monkeypatch.setattr(requests, "post", fake_post)
    msg = push.message_for({"type": "insight_review_created", "review_id": "r1"})
    assert push._send_all(msg) == 1

    ((url, body, headers),) = posted
    assert url == SUB["endpoint"]
    assert headers["content-encoding"] == "aes128gcm"
    assert headers["authorization"].startswith("vapid t=")
    assert f"k={push.public_key()}" in headers["authorization"]
    assert b"review queued" not in body  # encrypted, not plain JSON


@pytest.mark.parametrize(
    "subject,ok",
    [
        ("", False),
        ("https://github.com/smslavin/waterworks-ai", False),  # a path is refused
        ("ops@example.com", False),
        ("mailto:ops@example.com", True),
        ("https://plant.example.ts.net", True),
    ],
)
def test_push_needs_an_honest_vapid_subject(monkeypatch, subject, ok):
    monkeypatch.setattr(push, "SUBJECT", subject)
    assert (push.configuration_problem() is None) is ok


def test_unconfigured_push_says_what_to_set_and_sends_nothing(
    monkeypatch, client, fake_webpush
):
    sent, _ = fake_webpush
    monkeypatch.setattr(push, "SUBJECT", "")
    resp = client.get("/api/push/key")
    assert resp.status_code == 503
    assert "VAPID_SUBJECT" in resp.json()["error"]
    push.subscribe(SUB)
    push.notify({"type": "insight_review_created", "review_id": "r1"})
    assert sent == []
