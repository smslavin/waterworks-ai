"""Which chat-ui routes take the API token (gh-88).

A route added without @auth.require is open to the whole network once
BIND_HOST exposes chat-ui. The sweep below fails for any route that is
neither gated nor on the reviewed open list, so a new route needs a
decision either way.
"""

import pytest
from starlette.routing import Route
from starlette.testclient import TestClient

import auth
import backend
import pages.metrics

# Reviewed as safe to leave open: the SPA shell and the read-only plant
# description it boots from, plus the simulator's fault state. See auth.py.
OPEN = {
    "/",
    "/api/models",
    "/api/health",
    "/api/site",
    "/api/topology",
    "/api/sites",
    "/api/plant-status",
    "/api/fault/status",
    "/api/fault/modes",
    "/api/insight/categories",
    "/api/reactive",
}

GATED_POSTS = ["/api/chat", "/api/reactive/toggle", "/api/insight"]
GATED_GETS = ["/api/metrics", "/metrics"]


def _routes():
    return [r for r in backend.app.routes if isinstance(r, Route)]


def _is_gated(route) -> bool:
    return getattr(route.endpoint, "__wrapped__", None) is not None


def test_every_route_is_gated_or_reviewed_open():
    ungated = {r.path for r in _routes() if not _is_gated(r)}
    # New open routes: gate them, or add them to OPEN with a reason.
    assert ungated - OPEN == set()
    # Stale entries: an OPEN route that gained a gate or no longer exists.
    assert OPEN - ungated == set()


@pytest.fixture()
def exposed(monkeypatch):
    monkeypatch.setattr(auth, "EXPOSED", True)
    monkeypatch.setattr(auth, "_TOKEN", "test-secret")


@pytest.fixture()
def client():
    return TestClient(backend.app)


@pytest.mark.parametrize("path", GATED_POSTS)
def test_state_changing_routes_refused_without_token(exposed, client, path):
    assert client.post(path, json={}).status_code == 401
    assert client.post(f"{path}?token=wrong", json={}).status_code == 401


@pytest.mark.parametrize("path", GATED_GETS)
def test_metrics_refused_without_token(exposed, client, path):
    assert client.get(path).status_code == 401


def test_reactive_toggle_accepts_the_token(exposed, client, monkeypatch):
    monkeypatch.setattr(backend._reactive_loop, "is_running", lambda: False)
    resp = client.post(
        "/api/reactive/toggle",
        json={"enable": False},
        headers={"Authorization": "Bearer test-secret"},
    )
    assert resp.status_code == 200
    assert resp.json() == {"enabled": False, "changed": False}


def test_metrics_page_carries_the_token_into_its_links():
    page = pages.metrics.render({}, [], token="a b")
    assert 'href="/api/metrics?token=a%20b"' in page
    assert 'href="/audit?token=a%20b"' in page


def test_metrics_page_links_are_bare_without_a_token():
    page = pages.metrics.render({}, [])
    assert 'href="/api/metrics"' in page and 'href="/audit"' in page
