"""Tests for chat-ui/auth.py — the shared-secret gate on mutating/audit routes.

Fixes the fix for #12/#15's review: this module has real security behavior
(refuse unauthenticated access once BIND_HOST opts into exposure) that had
zero test coverage before this file.
"""

import sys
from pathlib import Path

import pytest
from starlette.applications import Starlette
from starlette.responses import JSONResponse
from starlette.routing import Route
from starlette.testclient import TestClient

root = Path(__file__).parent.parent
sys.path.insert(0, str(root / "chat-ui"))

import auth  # noqa: E402


@auth.require
async def _gated_endpoint(request):
    return JSONResponse({"ok": True})


@pytest.fixture()
def client():
    app = Starlette(routes=[Route("/gated", _gated_endpoint)])
    return TestClient(app)


@pytest.fixture(autouse=True)
def _reset_auth_state(monkeypatch):
    monkeypatch.setattr(auth, "_TOKEN", "test-secret")
    yield


def test_not_exposed_allows_requests_without_a_token(monkeypatch, client):
    monkeypatch.setattr(auth, "EXPOSED", False)
    resp = client.get("/gated")
    assert resp.status_code == 200


def test_exposed_rejects_requests_without_a_token(monkeypatch, client):
    monkeypatch.setattr(auth, "EXPOSED", True)
    resp = client.get("/gated")
    assert resp.status_code == 401


def test_exposed_accepts_a_correct_bearer_header(monkeypatch, client):
    monkeypatch.setattr(auth, "EXPOSED", True)
    resp = client.get("/gated", headers={"Authorization": "Bearer test-secret"})
    assert resp.status_code == 200


def test_exposed_accepts_a_correct_query_param(monkeypatch, client):
    monkeypatch.setattr(auth, "EXPOSED", True)
    resp = client.get("/gated", params={"token": "test-secret"})
    assert resp.status_code == 200


def test_exposed_rejects_a_wrong_bearer_header(monkeypatch, client):
    monkeypatch.setattr(auth, "EXPOSED", True)
    resp = client.get("/gated", headers={"Authorization": "Bearer wrong"})
    assert resp.status_code == 401


def test_exposed_rejects_a_wrong_query_param(monkeypatch, client):
    monkeypatch.setattr(auth, "EXPOSED", True)
    resp = client.get("/gated", params={"token": "wrong"})
    assert resp.status_code == 401


def test_presented_prefers_header_over_query_param():
    from starlette.requests import Request

    scope = {
        "type": "http",
        "method": "GET",
        "path": "/gated",
        "query_string": b"token=from-query",
        "headers": [(b"authorization", b"Bearer from-header")],
    }
    request = Request(scope)
    assert auth.presented(request) == "from-header"


# ── Token kept out of the access log ─────────────────────────────────────────

import logging  # noqa: E402


@pytest.mark.parametrize(
    "path,expected",
    [
        ("/mobile/?token=abc", "/mobile/?token=[redacted]"),
        ("/api/events?token=a-b_c&x=1", "/api/events?token=[redacted]&x=1"),
        ("/audit?x=1&token=abc", "/audit?x=1&token=[redacted]"),
        ("/api/health", "/api/health"),
        ("/api/x?mytoken=keep", "/api/x?mytoken=keep"),
    ],
)
def test_redact(path, expected):
    assert auth.redact(path) == expected


def test_access_log_record_is_redacted():
    record = logging.LogRecord(
        "uvicorn.access",
        logging.INFO,
        __file__,
        1,
        '%s - "%s %s HTTP/%s" %d',
        ("100.1.2.3:0", "GET", "/mobile/?token=secret", "1.1", 200),
        None,
    )
    assert auth.RedactTokenFilter().filter(record)
    assert "secret" not in record.getMessage()
    assert "token=[redacted]" in record.getMessage()


def test_redact_access_log_attaches_once():
    access = logging.getLogger("uvicorn.access")
    before = list(access.filters)
    try:
        auth.redact_access_log()
        auth.redact_access_log()
        added = [f for f in access.filters if isinstance(f, auth.RedactTokenFilter)]
        assert len(added) == 1
    finally:
        access.filters[:] = before
