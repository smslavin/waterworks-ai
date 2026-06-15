import pytest
from inference import load_template, infer_topology
from tests.fixtures.legacy_wtp_topics import LEGACY_TOPICS, LEGACY_OPCUA_NODES

CLEAN_TOPICS = {
    "Plant/WTP/Pump/RawWater_01/Flow": "312.0",
    "Plant/WTP/Pump/RawWater_01/Pressure": "4.2",
    "Plant/WTP/Pump/RawWater_01/Power": "42.0",
    "Plant/WTP/Pump/RawWater_01/Running": "true",
    "Plant/WTP/Pump/RawWater_02/Flow": "290.0",
    "Plant/WTP/Pump/RawWater_02/Pressure": "4.0",
    "Plant/WTP/Pump/RawWater_02/Power": "38.0",
    "Plant/WTP/Pump/RawWater_02/Running": "true",
    "Plant/WTP/Clarifier/Clarifier_01/Level": "62.0",
    "Plant/WTP/Clarifier/Clarifier_01/Turbidity": "2.1",
    "Plant/WTP/UV/UV_01/Intensity": "92.0",
    "Plant/WTP/UV/UV_01/Running": "true",
}

CLEAN_OPCUA = [
    "Objects/Plant/WTP/Pump/RawWater_01/Flow",
    "Objects/Plant/WTP/Pump/RawWater_01/Pressure",
    "Objects/Plant/WTP/Pump/RawWater_01/Running",
]


@pytest.fixture
def template():
    return load_template("water-treatment-municipal")


def _get(results, instance_id):
    return next((r for r in results if r["instance_id"] == instance_id), None)


# ── Clean WTP — MQTT only ────────────────────────────────────────────────────


def test_clean_wtp_pumps_inferred_without_opcua(template):
    results = infer_topology(CLEAN_TOPICS, [], template)
    pumps = [r for r in results if r["equipment_type"] == "Pump"]
    assert len(pumps) == 2
    for p in pumps:
        assert p["confidence_level"] == "inferred"
        assert p["missing_required"] == []


def test_clean_wtp_pump_verified_with_opcua(template):
    results = infer_topology(CLEAN_TOPICS, CLEAN_OPCUA, template)
    rw01 = _get(results, "RawWater_01")
    assert rw01["confidence_level"] == "verified"
    assert rw01["confidence_score"] >= 0.90
    assert "opcua" in rw01["sources"]
    # RawWater_02 has no OPC-UA nodes — stays inferred
    rw02 = _get(results, "RawWater_02")
    assert rw02["confidence_level"] == "inferred"


def test_clean_wtp_process_areas(template):
    results = infer_topology(CLEAN_TOPICS, [], template)
    by_id = {r["instance_id"]: r for r in results}
    assert by_id["RawWater_01"]["process_area"] == "Intake"
    assert by_id["RawWater_02"]["process_area"] == "Intake"
    assert by_id["Clarifier_01"]["process_area"] == "Treatment"
    assert by_id["UV_01"]["process_area"] == "Treatment"


# ── Legacy WTP — MQTT only ───────────────────────────────────────────────────


def test_legacy_standard_pump_inferred_without_opcua(template):
    results = infer_topology(LEGACY_TOPICS, [], template)
    rw01 = _get(results, "RawWater_01")
    assert rw01 is not None
    assert rw01["confidence_level"] == "inferred"
    assert rw01["missing_required"] == []


def test_legacy_abbreviated_attrs_not_verified(template):
    # RawWater_02 publishes FLW/PRS/PWR/RUN — abbreviated attrs don't satisfy
    # required attribute names, so the instance is found but incomplete.
    results = infer_topology(LEGACY_TOPICS, [], template)
    rw02 = _get(results, "RawWater_02")
    assert rw02 is not None
    assert rw02["confidence_level"] in ("inferred", "suspect")
    assert rw02["confidence_level"] != "verified"
    assert len(rw02["missing_required"]) > 0


def test_legacy_ghost_tag_not_verified(template):
    # OldPump_03 is a decommissioned pump: standard topic path, constant-zero values,
    # missing Running attr. Inference can't detect the zero-value signal, but the
    # missing required attr prevents it from reaching verified.
    results = infer_topology(LEGACY_TOPICS, [], template)
    old = _get(results, "OldPump_03")
    if old:
        assert old["confidence_level"] != "verified"
        assert "Running" in old["missing_required"]


def test_legacy_hs_pump_found_via_legacy_pattern(template):
    # HS_Pump_1 is published at 3-level depth (WTP/HS_Pump_1/attr).
    # Standard patterns require 4+ levels; this only matches via legacy_patterns.
    results = infer_topology(LEGACY_TOPICS, [], template)
    hs = _get(results, "HS_Pump_1")
    assert hs is not None
    assert hs["equipment_type"] == "Pump"
    assert hs["confidence_level"] == "inferred"
    assert hs["via_legacy_pattern"] is True
    assert hs["missing_required"] == []


def test_legacy_ambiguous_equipment_not_typed(template):
    # ABB_Drive_01 is under Plant/WTP/Drive/ — no "Drive" type in the template.
    # It should not appear in results, or if somehow matched, never as verified.
    results = infer_topology(LEGACY_TOPICS, [], template)
    abb = _get(results, "ABB_Drive_01")
    if abb:
        assert abb["confidence_level"] == "suspect"
        assert abb["equipment_type"] != "Pump"


def test_legacy_retired_uv_not_verified(template):
    # UV_03 publishes constant 0.0/false — structurally valid but dead signal.
    # With the scoring fix (MQTT-only → inferred), it cannot reach verified.
    results = infer_topology(LEGACY_TOPICS, [], template)
    uv3 = _get(results, "UV_03")
    assert uv3 is not None
    assert uv3["confidence_level"] == "inferred"
    assert uv3["confidence_level"] != "verified"


def test_legacy_no_flat_tags_produce_instances(template):
    # Flat tags like "wtp_rawpump_flow" have no path structure and match no pattern.
    results = infer_topology(LEGACY_TOPICS, [], template)
    instance_ids = {r["instance_id"] for r in results}
    assert "wtp_rawpump_flow" not in instance_ids
    assert "wtp_rawpump_pressure" not in instance_ids


def test_legacy_instance_count_reasonable(template):
    results = infer_topology(LEGACY_TOPICS, [], template)
    # Expect: RawWater_01, RawWater_02, OldPump_03, HS_Pump_1, Clarifier_01,
    #         FinishedWater_01, Chlorine_01, UV_01, UV_03, HS_Pump_2 = ~10
    assert 6 <= len(results) <= 14


# ── Legacy WTP — with OPC-UA ─────────────────────────────────────────────────


def test_legacy_opcua_elevates_active_equipment(template):
    # With LEGACY_OPCUA_NODES, active equipment with full OPC-UA coverage → verified.
    results = infer_topology(LEGACY_TOPICS, LEGACY_OPCUA_NODES, template)
    rw01 = _get(results, "RawWater_01")
    assert rw01["confidence_level"] == "verified"
    assert "opcua" in rw01["sources"]

    clarifier = _get(results, "Clarifier_01")
    assert clarifier["confidence_level"] == "verified"
    assert "opcua" in clarifier["sources"]


def test_legacy_opcua_absent_keeps_ghost_tag_unverified(template):
    # OldPump_03 and UV_03 are MQTT-only — absent from LEGACY_OPCUA_NODES.
    # Even with OPC-UA active for other instances, these stay unverified.
    results = infer_topology(LEGACY_TOPICS, LEGACY_OPCUA_NODES, template)

    old = _get(results, "OldPump_03")
    if old:
        assert old["confidence_level"] != "verified"
        assert "opcua" not in old["sources"]

    uv3 = _get(results, "UV_03")
    if uv3:
        assert uv3["confidence_level"] != "verified"
        assert "opcua" not in uv3["sources"]


def test_legacy_pattern_cap_prevents_verified(template):
    # HS_Pump_1 matches via legacy_patterns. Even with OPC-UA coverage (hypothetical),
    # a legacy-pattern match is capped at inferred — the topic structure itself is suspect.
    # Here we fabricate an OPC-UA node list that includes HS_Pump_1.
    fake_opcua = LEGACY_OPCUA_NODES + [
        "Objects/WTP/HS_Pump_1/Flow",
        "Objects/WTP/HS_Pump_1/Pressure",
        "Objects/WTP/HS_Pump_1/Running",
    ]
    results = infer_topology(LEGACY_TOPICS, fake_opcua, template)
    hs = _get(results, "HS_Pump_1")
    assert hs is not None
    assert hs["confidence_level"] == "inferred"
    assert hs["confidence_level"] != "verified"


# ── Confidence score ordering contract ──────────────────────────────────────


def test_confidence_score_ordering(template):
    results = infer_topology(LEGACY_TOPICS, LEGACY_OPCUA_NODES, template)
    for r in results:
        if r["confidence_level"] == "verified":
            assert r["confidence_score"] >= 0.85
        elif r["confidence_level"] == "inferred":
            assert 0.5 <= r["confidence_score"] < 0.85
        elif r["confidence_level"] == "suspect":
            assert r["confidence_score"] < 0.5
