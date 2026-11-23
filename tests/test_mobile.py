"""Read-only mobile PWA (gh-6): GET /api/reviews, the insight_review_created
broadcast it live-updates from, and the /mobile static shell."""

import asyncio
import json
import re
import sqlite3
from pathlib import Path

import pytest
from starlette.testclient import TestClient

import auth
import backend
from test_insights import CATEGORIES, REVIEWS_DDL, _Request

MOBILE = Path(backend.MOBILE_DIR)


def _insert(conn, review_id, created_at, resolved_at=None, note="bearing noise"):
    conn.execute(
        """INSERT INTO insight_reviews
           (id, node_id, category_id, category_label, target, note,
            created_at, resolved_at)
           VALUES (?, 'RawWater_01', 'maintenance_flag', 'Maintenance flag',
                   'work_item', ?, ?, ?)""",
        (review_id, note, created_at, resolved_at),
    )


@pytest.fixture()
def db(monkeypatch, tmp_path):
    path = tmp_path / "metrics.db"
    with sqlite3.connect(path) as conn:
        conn.execute(REVIEWS_DDL)
    monkeypatch.setattr(backend, "_METRICS_DB", str(path))
    return path


@pytest.fixture()
def client():
    return TestClient(backend.app)


# ── /api/reviews ──────────────────────────────────────────────────────────────


def test_reviews_lists_unresolved_newest_first(db, client):
    with sqlite3.connect(db) as conn:
        _insert(conn, "old", "2026-01-01T00:00:00+00:00")
        _insert(conn, "new", "2026-11-20T00:00:00+00:00")
        _insert(conn, "done", "2026-11-21T00:00:00+00:00", "2026-11-21T01:00:00+00:00")
    resp = client.get("/api/reviews")
    assert resp.status_code == 200
    reviews = resp.json()["reviews"]
    # No age window: a review from January is still waiting.
    assert [r["id"] for r in reviews] == ["new", "old"]
    assert reviews[0]["note"] == "bearing noise"
    assert reviews[0]["category_label"] == "Maintenance flag"


def test_reviews_empty_queue(db, client):
    assert client.get("/api/reviews").json() == {"reviews": []}


def test_reviews_missing_table_is_reported_not_a_crash(monkeypatch, tmp_path, client):
    monkeypatch.setattr(backend, "_METRICS_DB", str(tmp_path / "empty.db"))
    resp = client.get("/api/reviews")
    assert resp.status_code == 502
    assert resp.json()["error"] == "review queue unavailable"
    assert "insight_reviews" in resp.json()["detail"]


@pytest.fixture()
def exposed(monkeypatch):
    monkeypatch.setattr(auth, "EXPOSED", True)
    monkeypatch.setattr(auth, "_TOKEN", "test-secret")


def test_reviews_refused_without_token_when_exposed(db, exposed, client):
    assert client.get("/api/reviews").status_code == 401
    assert (
        client.get("/api/reviews", headers={"Authorization": "Bearer wrong"})
    ).status_code == 401


def test_reviews_accept_bearer_or_query_token_when_exposed(db, exposed, client):
    bearer = client.get("/api/reviews", headers={"Authorization": "Bearer test-secret"})
    query = client.get("/api/reviews?token=test-secret")
    assert bearer.status_code == query.status_code == 200


# ── insight_review_created broadcast ──────────────────────────────────────────


@pytest.fixture()
def subscriber(monkeypatch, db):
    monkeypatch.setattr(
        backend,
        "_topology_extensions",
        {"insight_categories": list(CATEGORIES.values())},
    )

    async def call(name, args, aggregator_url=None):
        return "ok"

    monkeypatch.setattr(backend.mcp_client, "call_mcp_tool", call)
    q: asyncio.Queue = asyncio.Queue()
    monkeypatch.setattr(backend, "_alert_subs", [q])
    return q


def _save(category):
    resp = asyncio.run(
        backend.insight_save_endpoint(
            _Request({"nodeId": "RawWater_01", "categoryId": category, "note": "noise"})
        )
    )
    return json.loads(resp.body)


def test_queued_review_is_broadcast(subscriber):
    body = _save("maintenance_flag")
    event = subscriber.get_nowait()
    assert event == {
        "type": "insight_review_created",
        "review_id": body["review_id"],
        "node_id": "RawWater_01",
        "category_label": "Maintenance flag",
    }
    # The desktop's alarm handling keys on instance_id; leaving it out is
    # what keeps this event from becoming a phantom alarm there.
    assert "instance_id" not in event


def test_insight_without_review_is_not_broadcast(subscriber):
    _save("fault_pattern")
    assert subscriber.empty()


# ── /mobile shell ─────────────────────────────────────────────────────────────


def test_mobile_index_is_served(client):
    resp = client.get("/mobile/")
    assert resp.status_code == 200
    assert 'src="app.js' in resp.text
    assert client.get("/mobile/app.js").status_code == 200


def test_manifest_icons_exist():
    manifest = json.loads((MOBILE / "manifest.json").read_text())
    for icon in manifest["icons"]:
        assert (MOBILE / icon["src"]).is_file(), icon["src"]


def test_service_worker_shell_files_exist():
    """sw.js's install step fails as a whole if any SHELL entry 404s, which
    silently leaves the page with no offline shell at all."""
    sw = (MOBILE / "sw.js").read_text()
    shell = re.search(r"const SHELL = \[(.*?)\];", sw, re.S).group(1)
    for entry in re.findall(r"'([^']+)'", shell):
        if entry == "./":
            entry = "index.html"
        assert (MOBILE / entry).is_file(), entry


# ── recent alerts buffer ──────────────────────────────────────────────────────

import recent_alerts  # noqa: E402


@pytest.fixture(autouse=True)
def _empty_buffer():
    recent_alerts.clear()
    yield
    recent_alerts.clear()


def _alarm(kind, instance="RawWater_01", attribute="Pressure", **extra):
    return {"type": kind, "instance_id": instance, "attribute": attribute, **extra}


def test_broadcast_records_alarms_newest_first(monkeypatch):
    monkeypatch.setattr(backend, "_alert_subs", [])
    backend.broadcast_alert(_alarm("reactive_warning", content=None))
    backend.broadcast_alert(_alarm("reactive_critical", instance="Fluoride_01"))
    backend.broadcast_alert({"type": "ping"})
    backend.broadcast_alert(_alarm("reactive_advisory", instance="UV_01"))
    alerts = recent_alerts.recent()
    assert [a["instance_id"] for a in alerts] == ["Fluoride_01", "RawWater_01"]
    assert all(a["ts"] for a in alerts)


def test_live_subscribers_get_the_same_ts_as_the_buffer(monkeypatch):
    q: asyncio.Queue = asyncio.Queue()
    monkeypatch.setattr(backend, "_alert_subs", [q])
    backend.broadcast_alert(_alarm("reactive_critical"))
    assert q.get_nowait()["ts"] == recent_alerts.recent()[0]["ts"]


def test_repeat_alarm_replaces_and_moves_to_front():
    recent_alerts.record(_alarm("reactive_warning"))
    recent_alerts.record(_alarm("reactive_critical", instance="Fluoride_01"))
    recent_alerts.record(_alarm("reactive_critical", value=12.0))
    alerts = recent_alerts.recent()
    assert [(a["instance_id"], a["type"]) for a in alerts] == [
        ("RawWater_01", "reactive_critical"),
        ("Fluoride_01", "reactive_critical"),
    ]


def test_warning_update_patches_its_diagnosis():
    recent_alerts.record(_alarm("reactive_warning", content=None))
    recent_alerts.record(_alarm("reactive_warning_update", content="Suction loss."))
    recent_alerts.record(
        _alarm("reactive_warning_update", instance="Nope_01", content="x")
    )
    alerts = recent_alerts.recent()
    assert len(alerts) == 1 and alerts[0]["content"] == "Suction loss."


def test_buffer_is_capped(monkeypatch):
    monkeypatch.setattr(recent_alerts, "MAX_ALERTS", 3)
    for i in range(5):
        recent_alerts.record(_alarm("reactive_critical", instance=f"Unit_{i}"))
    assert [a["instance_id"] for a in recent_alerts.recent()] == [
        "Unit_4",
        "Unit_3",
        "Unit_2",
    ]


def test_recent_returns_copies():
    recent_alerts.record(_alarm("reactive_critical"))
    recent_alerts.recent()[0]["content"] = "tampered"
    assert "content" not in recent_alerts.recent()[0]


def test_recent_alerts_endpoint(client):
    recent_alerts.record(_alarm("reactive_critical"))
    body = client.get("/api/alerts/recent").json()
    assert [a["instance_id"] for a in body["alerts"]] == ["RawWater_01"]


def test_recent_alerts_endpoint_gated_when_exposed(exposed, client):
    assert client.get("/api/alerts/recent").status_code == 401
    assert client.get("/api/alerts/recent?token=test-secret").status_code == 200


def test_critical_update_patches_its_diagnosis():
    recent_alerts.record(_alarm("reactive_critical", content=None))
    recent_alerts.record(_alarm("reactive_critical_update", content="Clogged screen."))
    assert recent_alerts.recent()[0]["content"] == "Clogged screen."


@pytest.mark.parametrize("decision", ["approved", "denied", "timed_out"])
def test_pending_action_lives_until_its_decision(decision):
    recent_alerts.record(
        {"type": "action_proposed", "action_id": "a1", "target": "RawWater_01"}
    )
    recent_alerts.record({"type": "action_proposed", "action_id": "a2"})
    pending = recent_alerts.pending_actions()
    assert [p["action_id"] for p in pending] == ["a1", "a2"]
    assert pending[0]["ts"]
    recent_alerts.record(
        {"type": "action_decision", "action_id": "a1", "decision": decision}
    )
    assert [p["action_id"] for p in recent_alerts.pending_actions()] == ["a2"]


def test_recent_alerts_endpoint_includes_pending_actions(client):
    recent_alerts.record({"type": "action_proposed", "action_id": "a1"})
    body = client.get("/api/alerts/recent").json()
    assert [p["action_id"] for p in body["pending_actions"]] == ["a1"]


# ── reactive_loop: a critical alarm goes out before Cascade runs ──────────────

import reactive_loop  # noqa: E402


def test_critical_alarm_is_broadcast_before_cascade(monkeypatch):
    """Cascade can sit on a proposed action for up to 5 minutes; the alarm
    used to wait for it, which hid criticals from the read-only mobile page."""
    sent = []

    async def deadband(anomaly, aggregator_url, cascade_id=None):
        return True, "sustained"

    async def cascade(anomaly, reason, model, broadcast_fn=None, **kw):
        assert [e["type"] for e in sent] == ["reactive_critical"]
        return "Suction starvation; check the intake screen."

    monkeypatch.setattr(reactive_loop, "run_deadband", deadband)
    monkeypatch.setattr(reactive_loop, "_run_cascade", cascade)
    monkeypatch.setattr(reactive_loop.audit, "log", lambda *a, **kw: None)
    monkeypatch.setattr(reactive_loop, "_cooldown_until", {})

    anomaly = {
        "instance_id": "RawWater_01",
        "attribute": "Flow",
        "severity": "critical",
        "current_value": 0.0,
        "normal_range": [200, 450],
        "condition": "below",
    }
    asyncio.run(
        reactive_loop._handle_anomaly(anomaly, "http://agg", "model", sent.append)
    )
    assert [e["type"] for e in sent] == [
        "reactive_critical",
        "reactive_critical_update",
    ]
    assert sent[0]["content"] is None
    assert sent[1] == {
        "type": "reactive_critical_update",
        "instance_id": "RawWater_01",
        "attribute": "Flow",
        "content": "Suction starvation; check the intake screen.",
    }


@pytest.mark.parametrize("path", ["/mobile/", "/mobile/app.js", "/mobile/sw.js"])
def test_mobile_files_are_revalidated(client, path):
    """iOS Safari served a stale app.js across reloads without this."""
    assert client.get(path).headers["cache-control"] == "no-cache"


def test_mobile_unchanged_file_is_a_304(client):
    first = client.get("/mobile/app.js")
    again = client.get(
        "/mobile/app.js", headers={"If-None-Match": first.headers["etag"]}
    )
    assert again.status_code == 304


# ── /api/events gate (gh-78) ──────────────────────────────────────────────────


class _StreamRequest:
    def __init__(self, headers=None, query=None):
        self.headers = headers or {}
        self.query_params = query or {}


def _open_events(request):
    """Call the endpoint directly: TestClient would block reading an endless
    SSE stream. Unsubscribe whatever queue it registered."""
    before = list(backend._alert_subs)
    resp = asyncio.run(backend.events_endpoint(request))
    backend._alert_subs[:] = before
    return resp


def test_events_refused_without_token_when_exposed(exposed, client):
    assert client.get("/api/events").status_code == 401
    assert client.get("/api/events?token=wrong").status_code == 401


@pytest.mark.parametrize(
    "request_",
    [
        _StreamRequest(headers={"authorization": "Bearer test-secret"}),
        _StreamRequest(query={"token": "test-secret"}),
    ],
    ids=["bearer", "query"],
)
def test_events_accept_bearer_or_query_token_when_exposed(exposed, request_):
    assert _open_events(request_).status_code == 200


def test_events_open_without_token_on_loopback(monkeypatch):
    monkeypatch.setattr(auth, "EXPOSED", False)
    assert _open_events(_StreamRequest()).status_code == 200
