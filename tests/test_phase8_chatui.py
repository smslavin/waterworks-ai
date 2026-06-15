"""Phase 8 chat-ui tests — topology.yaml drives specialist and orchestrator prompts.

All tests are import-level only: no API calls, no MCP servers, no network.
"""

import pytest
from topology import load
from topology_prompts import build_specialists, build_orchestrator_system


# Shared fixture: load topology and build specialists once per session
@pytest.fixture(scope="session")
def topology():
    return load()


@pytest.fixture(scope="session")
def specialists(topology):
    return build_specialists(topology)


@pytest.fixture(scope="session")
def orchestrator_system(specialists):
    return build_orchestrator_system(specialists)


# ── specialist list structure ──────────────────────────────────────────────────


def test_specialist_count(specialists):
    assert len(specialists) == 4  # Intake, Treatment, Distribution, Historian


def test_specialist_names(specialists):
    names = [s["name"] for s in specialists]
    assert names == ["intake", "treatment", "distribution", "historian"]


def test_specialist_labels(specialists):
    labels = [s["label"] for s in specialists]
    assert labels == ["Intake", "Treatment", "Distribution", "Historian"]


def test_historian_is_last(specialists):
    assert specialists[-1]["name"] == "historian"


def test_each_specialist_has_required_keys(specialists):
    required = {"name", "label", "unit_names", "tool_prefixes", "system"}
    for s in specialists:
        assert required.issubset(s.keys()), f"{s['name']} missing keys"


# ── tool prefixes ──────────────────────────────────────────────────────────────


def test_area_specialists_have_mqtt_prefix(specialists):
    for s in specialists:
        if s["name"] != "historian":
            assert "mqtt__" in s["tool_prefixes"], f"{s['name']} missing mqtt__ prefix"


def test_historian_influxdb_only(specialists):
    hist = next(s for s in specialists if s["name"] == "historian")
    assert hist["tool_prefixes"] == ("influxdb__",)
    assert "mqtt__" not in hist["tool_prefixes"]


# ── unit names ─────────────────────────────────────────────────────────────────


def test_intake_unit_names(specialists):
    intake = next(s for s in specialists if s["name"] == "intake")
    assert set(intake["unit_names"]) == {"RawWater_01", "RawWater_02"}


def test_treatment_unit_names(specialists):
    treatment = next(s for s in specialists if s["name"] == "treatment")
    assert set(treatment["unit_names"]) == {
        "Clarifier_01",
        "Chlorine_01",
        "Fluoride_01",
        "UV_01",
        "UV_02",
    }


def test_distribution_unit_names(specialists):
    dist = next(s for s in specialists if s["name"] == "distribution")
    assert set(dist["unit_names"]) == {
        "HighService_01",
        "HighService_02",
        "FinishedWater_01",
    }


def test_historian_has_no_unit_names(specialists):
    hist = next(s for s in specialists if s["name"] == "historian")
    assert hist["unit_names"] == []


# ── system prompt content ──────────────────────────────────────────────────────


def test_system_prompts_do_not_contain_findings_block(specialists):
    """_FINDINGS_FORMAT must not be pre-embedded — _run_specialist() appends it."""
    for s in specialists:
        assert (
            "FINDINGS:\nStatus:" not in s["system"]
        ), f"{s['name']} system prompt contains FINDINGS block — will be doubled by _run_specialist()"


def test_system_prompts_do_not_contain_tool_guidance(specialists):
    """_SPECIALIST_TOOL_GUIDANCE must not be pre-embedded — _run_specialist() appends it."""
    for s in specialists:
        assert (
            "── Tool selection" not in s["system"]
        ), f"{s['name']} system prompt contains tool guidance — will be doubled by _run_specialist()"


def test_distribution_uses_correct_storage_tank_path(specialists):
    dist = next(s for s in specialists if s["name"] == "distribution")
    assert "StorageTank" in dist["system"]
    assert "Tank/FinishedWater" not in dist["system"]  # stale Phase 7 path


def test_treatment_uses_correct_clarifier_path(specialists):
    treat = next(s for s in specialists if s["name"] == "treatment")
    assert "Clarifier" in treat["system"]
    assert "Tank/Clarifier" not in treat["system"]  # stale Phase 7 path


def test_intake_system_contains_pump_heuristics(specialists):
    intake = next(s for s in specialists if s["name"] == "intake")
    assert "suction starvation" in intake["system"].lower()
    assert "run-status fault" in intake["system"].lower()


def test_system_prompts_contain_area_description(specialists):
    for s in specialists:
        if s["name"] != "historian":
            assert (
                "Area context:" in s["system"]
            ), f"{s['name']} missing area description"


def test_system_prompts_contain_mqtt_topic_root(specialists):
    for s in specialists:
        if s["name"] != "historian":
            assert "Plant/WTP/" in s["system"], f"{s['name']} missing MQTT topic root"


def test_historian_system_contains_flux_rules(specialists):
    hist = next(s for s in specialists if s["name"] == "historian")
    assert "columns:" in hist["system"]  # Flux group() syntax rule


def test_historian_system_contains_updated_types(specialists):
    hist = next(s for s in specialists if s["name"] == "historian")
    assert "Clarifier" in hist["system"]
    assert "StorageTank" in hist["system"]


# ── orchestrator ───────────────────────────────────────────────────────────────


def test_orchestrator_lists_all_specialist_labels(orchestrator_system, specialists):
    for s in specialists:
        assert s["label"] in orchestrator_system


def test_orchestrator_contains_control_guidance(orchestrator_system):
    assert "control__propose_action" in orchestrator_system


def test_orchestrator_no_hardcoded_four(orchestrator_system):
    """Orchestrator should not hardcode 'four specialist agents'."""
    assert "four\nspecialist" not in orchestrator_system.lower().replace("\n", " ")
    assert "four specialist agents: Intake" not in orchestrator_system


# ── claude_loop type labels (tested via topology, not claude_loop import) ──────
# claude_loop imports anthropic at module level so it can't be imported without
# the full dependency stack. We verify the derived TYPE_ORDER/TYPE_LABELS logic
# directly from topology — same computation, no heavy deps required.


def test_type_order_matches_topology_keys(topology):
    eq_type_keys = list(topology["equipment_types"].keys())
    assert "Clarifier" in eq_type_keys
    assert "StorageTank" in eq_type_keys
    assert "Tank" not in eq_type_keys


def test_type_labels_derived_correctly(topology):
    _LABEL_OVERRIDES = {"UV": "UV", "Dosing": "Dosing", "StorageTank": "Storage Tanks"}
    keys = list(topology["equipment_types"].keys())
    labels = {k: _LABEL_OVERRIDES.get(k, k + "s") for k in keys}
    assert labels["Pump"] == "Pumps"
    assert labels["Clarifier"] == "Clarifiers"
    assert labels["StorageTank"] == "Storage Tanks"
    assert labels["UV"] == "UV"
    assert labels["Dosing"] == "Dosing"
    assert "Tank" not in labels


# ── idempotency ────────────────────────────────────────────────────────────────


def test_build_specialists_idempotent(topology):
    s1 = build_specialists(topology)
    s2 = build_specialists(topology)
    for a, b in zip(s1, s2):
        assert a["name"] == b["name"]
        assert a["system"] == b["system"]
        assert a["tool_prefixes"] == b["tool_prefixes"]
