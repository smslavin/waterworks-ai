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
    assert sites["wtp"]["region"] == "Metro Region"
    assert sites["wtp"]["chat_ui_url"] == "http://localhost:8080"


def test_load_sites_skips_empty_region(enterprise_file):
    sites = plant_registry.load_sites(enterprise_file)
    assert "valley" not in sites


def test_get_site_returns_none_for_unknown_site(enterprise_file):
    assert plant_registry.get_site("nonexistent", enterprise_file) is None


def test_get_site_returns_metadata_for_known_site(enterprise_file):
    site = plant_registry.get_site("wtp2", enterprise_file)
    assert site is not None
    assert site["name"] == "Eastside"
    assert site["topology_file"] == "topology-wtp2.yaml"


# ── diagnose_plant_mcp: SUMMARY extraction ──────────────────────────────────


def test_extract_summary_parses_full_block():
    text = (
        "Here is my analysis.\n\n"
        "SUMMARY:\n"
        "Status: Fault Detected\n"
        "Overview: RawWater_01 shows suction starvation.\n"
        "Key points:\n"
        "- Flow near zero\n"
        "- Pressure dropping\n\n"
        "Detailed reasoning follows..."
    )
    result = diagnose_server._extract_summary(text)
    assert "Status: Fault Detected" in result
    assert "Overview: RawWater_01 shows suction starvation." in result
    assert "- Flow near zero" in result
    assert "- Pressure dropping" in result


def test_extract_summary_handles_no_key_points():
    text = "SUMMARY:\nStatus: Normal\nOverview: All units nominal.\n\nNothing else to report."
    result = diagnose_server._extract_summary(text)
    assert "Status: Normal" in result
    assert "Overview: All units nominal." in result
    assert "Key points:" not in result


def test_extract_summary_falls_back_to_raw_text_when_absent():
    text = "Sure — RawWater_01 is running fine right now."
    result = diagnose_server._extract_summary(text)
    assert result == text


def test_extract_summary_truncates_long_fallback_text():
    text = "x" * 5000
    result = diagnose_server._extract_summary(text)
    assert len(result) <= 2000


# ── diagnose_plant: unknown site_id fast path (no network needed) ──────────


def test_diagnose_plant_unknown_site_id_returns_clean_error(
    enterprise_file, monkeypatch
):
    monkeypatch.setenv("ENTERPRISE_FILE", str(enterprise_file))
    result = asyncio.run(diagnose_server.diagnose_plant("bogus", "any question"))
    assert "unknown site_id" in result.lower()
    assert "bogus" in result
