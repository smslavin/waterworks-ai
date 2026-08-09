"""Tests for M10 Phase 3: query_enterprise_history's fan-out/merge/filter
logic. call_mcp_tool is monkeypatched — no live plants needed. Live
cross-plant behavior is covered by verification against the running Phase 0
stacks, not here."""

import asyncio
import importlib.util
import json
import sys
from pathlib import Path

import pytest
import yaml

root = Path(__file__).parent.parent
sys.path.insert(0, str(root / "enterprise"))

import plant_registry  # noqa: E402

# Not a plain `import server` — see tests/test_m10_diagnose_plant.py for why
# (every MCP server in this repo is named server.py; pytest collects every
# test file in one process, so bare imports collide in sys.modules).
_spec = importlib.util.spec_from_file_location(
    "_query_history_server", root / "enterprise" / "query_history_mcp" / "server.py"
)
qh_server = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(qh_server)


@pytest.fixture()
def enterprise_file(tmp_path):
    path = tmp_path / "enterprise.yaml"
    path.write_text(
        yaml.dump(
            {
                "regions": [
                    {
                        "id": "metro",
                        "sites": [
                            {
                                "site_id": "wtp",
                                "name": "Waterworks",
                                "chat_ui_url": "http://localhost:8080",
                                "aggregator_url": "http://localhost:8100/sse",
                            },
                            {
                                "site_id": "wtp2",
                                "name": "Eastside",
                                "chat_ui_url": "http://localhost:8010",
                                "aggregator_url": "http://localhost:8110/sse",
                            },
                        ],
                    },
                ],
            }
        )
    )
    return path


def _fake_call_mcp_tool(responses: dict[str, str]):
    """Build a fake call_mcp_tool that dispatches by aggregator_url."""

    async def _fake(name, args, aggregator_url):
        return responses.get(aggregator_url, json.dumps({"sessions": []}))

    return _fake


def test_merges_sessions_from_both_plants(enterprise_file, monkeypatch):
    monkeypatch.setenv("ENTERPRISE_FILE", str(enterprise_file))
    monkeypatch.setattr(
        qh_server,
        "call_mcp_tool",
        _fake_call_mcp_tool(
            {
                "http://localhost:8100/sse": json.dumps(
                    {
                        "sessions": [
                            {
                                "session_id": "s1",
                                "ts": "2026-08-09T10:00:00Z",
                                "site_id": "wtp",
                            }
                        ]
                    }
                ),
                "http://localhost:8110/sse": json.dumps(
                    {
                        "sessions": [
                            {
                                "session_id": "s2",
                                "ts": "2026-08-09T11:00:00Z",
                                "site_id": "wtp2",
                            }
                        ]
                    }
                ),
            }
        ),
    )
    result = json.loads(
        asyncio.run(
            qh_server.query_enterprise_history(
                "2026-08-09T00:00:00Z", "2026-08-09T23:59:59Z"
            )
        )
    )
    site_ids = {s["site_id"] for s in result["sessions"]}
    assert site_ids == {"wtp", "wtp2"}
    assert len(result["sessions"]) == 2


def test_sessions_sorted_by_timestamp_across_plants(enterprise_file, monkeypatch):
    monkeypatch.setenv("ENTERPRISE_FILE", str(enterprise_file))
    monkeypatch.setattr(
        qh_server,
        "call_mcp_tool",
        _fake_call_mcp_tool(
            {
                "http://localhost:8100/sse": json.dumps(
                    {
                        "sessions": [
                            {
                                "session_id": "late",
                                "ts": "2026-08-09T15:00:00Z",
                                "site_id": "wtp",
                            }
                        ]
                    }
                ),
                "http://localhost:8110/sse": json.dumps(
                    {
                        "sessions": [
                            {
                                "session_id": "early",
                                "ts": "2026-08-09T05:00:00Z",
                                "site_id": "wtp2",
                            }
                        ]
                    }
                ),
            }
        ),
    )
    result = json.loads(
        asyncio.run(
            qh_server.query_enterprise_history(
                "2026-08-09T00:00:00Z", "2026-08-09T23:59:59Z"
            )
        )
    )
    assert [s["session_id"] for s in result["sessions"]] == ["early", "late"]


def test_site_id_filter_returns_only_that_plant(enterprise_file, monkeypatch):
    monkeypatch.setenv("ENTERPRISE_FILE", str(enterprise_file))
    calls = []

    async def _fake(name, args, aggregator_url):
        calls.append(aggregator_url)
        return json.dumps(
            {
                "sessions": [
                    {"session_id": "x", "ts": "2026-08-09T10:00:00Z", "site_id": "wtp2"}
                ]
            }
        )

    monkeypatch.setattr(qh_server, "call_mcp_tool", _fake)
    result = json.loads(
        asyncio.run(
            qh_server.query_enterprise_history(
                "2026-08-09T00:00:00Z", "2026-08-09T23:59:59Z", site_id="wtp2"
            )
        )
    )
    # Proves the fan-out isn't silently single-DB: only wtp2's aggregator was
    # ever called, and every returned row is tagged wtp2.
    assert calls == ["http://localhost:8110/sse"]
    assert all(s["site_id"] == "wtp2" for s in result["sessions"])


def test_unknown_site_id_returns_clean_error(enterprise_file, monkeypatch):
    monkeypatch.setenv("ENTERPRISE_FILE", str(enterprise_file))
    result = json.loads(
        asyncio.run(
            qh_server.query_enterprise_history(
                "2026-08-09T00:00:00Z", "2026-08-09T23:59:59Z", site_id="bogus"
            )
        )
    )
    assert "unknown site_id" in result["error"].lower()


def test_one_plant_failing_does_not_break_the_other(enterprise_file, monkeypatch):
    monkeypatch.setenv("ENTERPRISE_FILE", str(enterprise_file))

    async def _fake(name, args, aggregator_url):
        if aggregator_url == "http://localhost:8100/sse":
            raise ConnectionError("plant unreachable")
        return json.dumps(
            {
                "sessions": [
                    {
                        "session_id": "ok",
                        "ts": "2026-08-09T10:00:00Z",
                        "site_id": "wtp2",
                    }
                ]
            }
        )

    monkeypatch.setattr(qh_server, "call_mcp_tool", _fake)
    result = json.loads(
        asyncio.run(
            qh_server.query_enterprise_history(
                "2026-08-09T00:00:00Z", "2026-08-09T23:59:59Z"
            )
        )
    )
    assert len(result["sessions"]) == 1
    assert result["sessions"][0]["site_id"] == "wtp2"


def test_malformed_plant_response_is_skipped_not_fatal(enterprise_file, monkeypatch):
    monkeypatch.setenv("ENTERPRISE_FILE", str(enterprise_file))
    monkeypatch.setattr(
        qh_server,
        "call_mcp_tool",
        _fake_call_mcp_tool(
            {
                "http://localhost:8100/sse": "not valid json",
                "http://localhost:8110/sse": json.dumps(
                    {
                        "sessions": [
                            {
                                "session_id": "ok",
                                "ts": "2026-08-09T10:00:00Z",
                                "site_id": "wtp2",
                            }
                        ]
                    }
                ),
            }
        ),
    )
    result = json.loads(
        asyncio.run(
            qh_server.query_enterprise_history(
                "2026-08-09T00:00:00Z", "2026-08-09T23:59:59Z"
            )
        )
    )
    assert len(result["sessions"]) == 1
    assert result["sessions"][0]["session_id"] == "ok"
