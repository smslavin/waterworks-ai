"""Regression tests for gh-21: topology-builder/discovery.py dropped the
return value of `session.call_tool("connect", ...)` on the MQTT path — MCP
signals a tool-level failure in the *result* (isError/error content), not
by raising, so a refused broker connection proceeded straight into
crawl_mqtt (which just returns []), and server.py's _run_discovery reported
`topics_seen=0, instances_found=0, status="complete"` — indistinguishable
from "there really is nothing in this plant". The OPC-UA path already
wrapped its call in a try/except in server.py; the MQTT one didn't.

topology-builder/ has its own requirements.txt/uv.lock separate from the
root chat-ui test environment (see CLAUDE.md), so this file adds its
directory to sys.path itself rather than relying on tests/conftest.py.
mcp and fieldworks-core happen to be importable in the ambient environment
here too (verified before writing this), so these run as real unit tests
rather than being skipped.

Every MCP server in this repo is named server.py, and pytest collects all
test files into one process — test_phase13_audit_reviews.py already does
its own `import server as audit_server` for audit-mcp's server.py, so a
plain `import server` here would silently bind to whichever one happened
to load first (see test_m10_diagnose_plant.py's comment, which hit the same
problem for enterprise/diagnose_plant_mcp/server.py and fixed it the same
way this file does below).
"""

import importlib.util
import sys
from pathlib import Path

import pytest

_TB_DIR = Path(__file__).parent.parent / "topology-builder"
if str(_TB_DIR) not in sys.path:
    sys.path.insert(0, str(_TB_DIR))

# discovery.py's own module name is unique repo-wide (verified: no other
# top-level "discovery.py" exists), so a plain import is safe — and it must
# land in sys.modules under the literal name "discovery" anyway, since
# server.py itself does `from discovery import ...` and needs to resolve
# that same instance.
discovery = pytest.importorskip(
    "discovery", reason="topology-builder deps (mcp, fieldworks-core) not installed"
)

try:
    _spec = importlib.util.spec_from_file_location(
        "_topology_builder_server", _TB_DIR / "server.py"
    )
    server = importlib.util.module_from_spec(_spec)
    _spec.loader.exec_module(server)
except ImportError as exc:  # pragma: no cover - env without topology-builder deps
    pytest.skip(f"topology-builder deps not installed: {exc}")

import asyncio


class _FakeBlock:
    def __init__(self, text):
        self.text = text


class _FakeConnectResult:
    def __init__(self, *, is_error: bool, texts: list[str] = ()):
        self.isError = is_error
        self.content = [_FakeBlock(t) for t in texts]


# ── discovery.py: _raise_if_connect_failed is the core of the fix ──────────


def test_raise_if_connect_failed_raises_on_is_error():
    result = _FakeConnectResult(is_error=True, texts=["connection refused"])
    with pytest.raises(discovery.AdapterConnectError, match="connection refused"):
        discovery._raise_if_connect_failed(result, "localhost:1883")


def test_raise_if_connect_failed_noop_on_success():
    result = _FakeConnectResult(is_error=False, texts=["ok"])
    discovery._raise_if_connect_failed(result, "localhost:1883")  # must not raise


def test_raise_if_connect_failed_handles_empty_error_content():
    result = _FakeConnectResult(is_error=True, texts=[])
    with pytest.raises(discovery.AdapterConnectError, match="no error detail"):
        discovery._raise_if_connect_failed(result, "localhost:1883")


# ── server.py's _run_discovery: the operator-visible consequence ───────────


def _fresh_session(discovery_id="d1"):
    server._sessions[discovery_id] = {
        "status": "running",
        "broker_url": "localhost:1883",
        "template": "water-treatment-municipal",
        "opcua_url": None,
        "instances": [],
        "stats": {"topics_seen": 0, "instances_found": 0},
        "error": None,
    }
    return discovery_id


def test_run_discovery_reports_error_status_on_refused_connection(monkeypatch):
    """A refused connection (discover_mqtt_topics now raises
    AdapterConnectError instead of silently proceeding) must not be
    reported as a successful empty discovery."""
    discovery_id = _fresh_session()

    async def fake_discover_mqtt_topics(broker_url):
        raise discovery.AdapterConnectError(
            f"connect to {broker_url} failed: connection refused"
        )

    monkeypatch.setattr(server, "discover_mqtt_topics", fake_discover_mqtt_topics)

    asyncio.run(
        server._run_discovery(
            discovery_id, "localhost:1883", None, "water-treatment-municipal"
        )
    )

    session = server._sessions[discovery_id]
    assert session["status"] == "error"
    assert session["error"] is not None
    assert "connection refused" in session["error"]


def test_run_discovery_reports_error_status_on_zero_topics_after_connect(
    monkeypatch,
):
    """Connect succeeds, crawl finds nothing — a "reachable but empty"
    state that must not be folded into the same status="complete" a real
    successful discovery gets."""
    discovery_id = _fresh_session()

    async def fake_discover_mqtt_topics(broker_url):
        return []  # connected fine, crawl saw nothing

    monkeypatch.setattr(server, "discover_mqtt_topics", fake_discover_mqtt_topics)

    asyncio.run(
        server._run_discovery(
            discovery_id, "localhost:1883", None, "water-treatment-municipal"
        )
    )

    session = server._sessions[discovery_id]
    assert session["stats"]["topics_seen"] == 0
    assert session["status"] == "error"
    assert session["error"] is not None


def test_run_discovery_still_reports_complete_on_real_success(monkeypatch):
    """Regression guard: a genuine successful discovery (topics found) must
    still report status='complete', not get caught by the new empty-crawl
    check."""
    discovery_id = _fresh_session()

    async def fake_discover_mqtt_topics(broker_url):
        return ["Plant/WTP/Pump/RawWater_01/Running"]

    monkeypatch.setattr(server, "discover_mqtt_topics", fake_discover_mqtt_topics)

    asyncio.run(
        server._run_discovery(
            discovery_id, "localhost:1883", None, "water-treatment-municipal"
        )
    )

    session = server._sessions[discovery_id]
    assert session["stats"]["topics_seen"] == 1
    assert session["status"] == "complete"
    assert session["error"] is None
