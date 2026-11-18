"""GET /api/sites says whether the enterprise layer answered (gh-68).

It used to return {} when the orchestrator was down, so SiteNav quietly
listed only this plant and nothing said why.
"""

import logging

import httpx
import pytest
from starlette.testclient import TestClient

import backend

SITES = {
    "wtp2": {
        "name": "Eastside",
        "region": "Metro Region",
        "chat_ui_url": "http://localhost:8010",
    }
}


class _Client:
    """httpx.AsyncClient stand-in: answers with SITES, or fails to connect."""

    up = True

    def __init__(self, *args, **kwargs):
        pass

    async def __aenter__(self):
        return self

    async def __aexit__(self, *exc):
        return False

    async def get(self, url, **kwargs):
        if not _Client.up:
            raise httpx.ConnectError("Connection refused")
        return httpx.Response(200, json=SITES, request=httpx.Request("GET", url))


@pytest.fixture()
def client(monkeypatch):
    monkeypatch.setattr(httpx, "AsyncClient", _Client)
    monkeypatch.setattr(backend, "_enterprise_reachable", None)
    _Client.up = True
    return TestClient(backend.app)


def test_reachable_orchestrator_returns_its_sites(client):
    body = client.get("/api/sites").json()
    assert body == {"enterprise": "ok", "sites": SITES}


def test_unreachable_orchestrator_is_reported_not_hidden(client):
    _Client.up = False
    resp = client.get("/api/sites")
    assert resp.status_code == 200
    assert resp.json() == {
        "enterprise": "unreachable",
        "url": backend.ENTERPRISE_ORCHESTRATOR_URL,
        "sites": {},
    }


def test_outage_is_logged_once_and_recovery_once(client, caplog):
    caplog.set_level(logging.INFO, logger=backend.logger.name)
    _Client.up = False
    for _ in range(3):
        client.get("/api/sites")
    _Client.up = True
    client.get("/api/sites")
    client.get("/api/sites")

    messages = [r.getMessage() for r in caplog.records]
    assert sum("not reachable" in m for m in messages) == 1
    assert sum("reachable again" in m for m in messages) == 1
