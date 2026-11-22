"""Tests for M10 Phase 2: plant_registry.py and diagnose_plant_mcp's SUMMARY
extraction. Network-calling paths (diagnose_plant's httpx round-trip to a
plant's real chat-ui) are covered by live verification against the running
Phase 0 stacks, not mocked here."""

import asyncio
import importlib.util
import sys
from pathlib import Path

import pytest
import yaml

root = Path(__file__).parent.parent
sys.path.insert(0, str(root / "enterprise"))

import plant_registry  # noqa: E402

# Not a plain `import server` — every MCP server in this repo is named
# server.py, and pytest collects all test files in one process, so a bare
# `import server` here would collide with test_phase13_audit_reviews.py's
# own `import server as audit_server` in sys.modules (whichever loads first
# wins, silently breaking the other). Same fix simulator/topology.py already
# uses for its own name collision.
_spec = importlib.util.spec_from_file_location(
    "_diagnose_plant_server", root / "enterprise" / "diagnose_plant_mcp" / "server.py"
)
diagnose_server = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(diagnose_server)


@pytest.fixture()
def enterprise_file(tmp_path):
    path = tmp_path / "enterprise.yaml"
    path.write_text(
        yaml.dump(
            {
                "enterprise": {"name": "Test Utility"},
                "regions": [
                    {
                        "id": "metro",
                        "name": "Metro Region",
                        "sites": [
                            {
                                "site_id": "wtp",
                                "name": "Waterworks",
                                "topology_file": "topology.yaml",
                                "chat_ui_url": "http://localhost:8080",
                            },
                            {
                                "site_id": "wtp2",
                                "name": "Eastside",
                                "topology_file": "topology-wtp2.yaml",
                                "chat_ui_url": "http://localhost:8010",
                            },
                        ],
                    },
                    {"id": "valley", "name": "Valley Region", "sites": []},
                ],
            }
        )
    )
    return path


# ── plant_registry ──────────────────────────────────────────────────────────


def test_load_sites_flattens_across_regions(enterprise_file):
    sites = plant_registry.load_sites(enterprise_file)
    assert set(sites.keys()) == {"wtp", "wtp2"}


def test_load_sites_captures_region_name(enterprise_file):
    sites = plant_registry.load_sites(enterprise_file)
    assert sites["wtp"].region_name == "Metro Region"
    assert sites["wtp"].chat_ui_url == "http://localhost:8080"


def test_get_site_returns_none_for_unknown_site(enterprise_file):
    assert plant_registry.get_site("nope", enterprise_file) is None


def test_get_site_returns_metadata_for_known_site(enterprise_file):
    site = plant_registry.get_site("wtp2", enterprise_file)
    assert site.name == "Eastside"
    assert site.chat_ui_url == "http://localhost:8010"


def test_site_missing_chat_ui_url_is_an_error_not_skipped(tmp_path):
    """Part V (gh-83): the old loader silently dropped this site, leaving
    every cross-plant answer quietly incomplete."""
    path = tmp_path / "enterprise.yaml"
    path.write_text(
        yaml.dump(
            {
                "enterprise": {"name": "Test Utility"},
                "regions": [
                    {
                        "id": "metro",
                        "name": "Metro Region",
                        "sites": [
                            {
                                "site_id": "wtp",
                                "name": "Waterworks",
                                "topology_file": "topology.yaml",
                            }
                        ],
                    }
                ],
            }
        )
    )
    with pytest.raises(ValueError, match="chat_ui_url"):
        plant_registry.load_sites(path)


def test_sites_json_keeps_the_api_sites_shape(enterprise_file):
    assert plant_registry.sites_json(enterprise_file)["wtp"] == {
        "name": "Waterworks",
        "region": "Metro Region",
        "topology_file": "topology.yaml",
        "chat_ui_url": "http://localhost:8080",
        "aggregator_url": None,
    }


# ── diagnose_plant_mcp: formatting the plant's verdict (gh-25) ────────────
#
# The plant's chat-ui parses its SUMMARY/FINDINGS block once (chat-ui/
# verdict.py) and sends it as a "verdict" event; diagnose_plant formats that
# event with fieldworks.agents.format_plant_summary instead of re-matching
# the text.


def _verdict(**fields):
    return {
        "type": "verdict",
        "kind": "summary",
        "confidence": None,
        "overview": None,
        "points": [],
        **fields,
    }


def _plant_stream(events):
    import json

    import httpx

    body = "".join(f"data: {json.dumps(e)}\n\n" for e in events)

    def handler(request):
        return httpx.Response(
            200, text=body, headers={"content-type": "text/event-stream"}
        )

    real = httpx.AsyncClient
    return lambda **kw: real(transport=httpx.MockTransport(handler), **kw)


def test_diagnose_plant_uses_the_plants_verdict_event(enterprise_file, monkeypatch):
    """Bolded labels used to defeat this module's regex while PlantPanel's
    tolerated them; now the plant's parse is the only one."""
    monkeypatch.setenv("ENTERPRISE_FILE", str(enterprise_file))
    text = "SUMMARY:\n**Status:** Anomaly Detected\n**Overview:** Low flow.\n\nDetail"
    monkeypatch.setattr(
        diagnose_server.httpx,
        "AsyncClient",
        _plant_stream(
            [
                {"type": "text", "text": text},
                _verdict(status="Anomaly Detected", overview="Low flow."),
                {"type": "done"},
            ]
        ),
    )
    result = asyncio.run(diagnose_server.diagnose_plant("wtp", "status?"))
    assert result == "[wtp] Status: Anomaly Detected\nOverview: Low flow."


def test_diagnose_plant_without_verdict_returns_the_text(enterprise_file, monkeypatch):
    monkeypatch.setenv("ENTERPRISE_FILE", str(enterprise_file))
    monkeypatch.setattr(
        diagnose_server.httpx,
        "AsyncClient",
        _plant_stream([{"type": "text", "text": "All fine."}, {"type": "done"}]),
    )
    result = asyncio.run(diagnose_server.diagnose_plant("wtp", "hi"))
    assert result == "[wtp] All fine."


# ── diagnose_plant: unknown site_id fast path (no network needed) ──────────


def test_diagnose_plant_unknown_site_id_returns_clean_error(
    enterprise_file, monkeypatch
):
    monkeypatch.setenv("ENTERPRISE_FILE", str(enterprise_file))
    result = asyncio.run(diagnose_server.diagnose_plant("bogus", "any question"))
    assert "unknown site_id" in result.lower()
    assert "bogus" in result


def test_diagnose_plant_unreachable_reads_as_unknown(enterprise_file, monkeypatch):
    import httpx

    monkeypatch.setenv("ENTERPRISE_FILE", str(enterprise_file))

    def handler(request):
        raise httpx.ConnectError("refused")

    real = httpx.AsyncClient
    monkeypatch.setattr(
        diagnose_server.httpx,
        "AsyncClient",
        lambda **kw: real(transport=httpx.MockTransport(handler), **kw),
    )
    result = asyncio.run(diagnose_server.diagnose_plant("wtp", "status?"))
    assert result.startswith("[wtp] Status unknown — could not reach")
    assert "not confirmed normal" in result


def test_tools_carry_the_framework_descriptions_and_are_read_only():
    tools = {t.name: t for t in asyncio.run(diagnose_server.mcp.list_tools())}
    assert set(tools) == {"diagnose_plant", "get_plant_status"}
    for name, tool in tools.items():
        assert tool.description == diagnose_server._DESCRIPTIONS[name]
        assert tool.annotations.read_only_hint is True
