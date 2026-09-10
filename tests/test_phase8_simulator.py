"""Phase 8 simulator tests — topology.yaml drives instances and fault modes.

All tests are import-level only: no MQTT, no OPC-UA, no network.

Topology-loader tests rewritten for the fieldworks-core port (M8):
topology.py now delegates to fieldworks.topology.load(), returning a
validated TopologyConfig object (raises ValueError with Pydantic's message
on schema violations) instead of a raw dict validated by hand-rolled
assertions.
"""

import pytest

# ── topology loader ────────────────────────────────────────────────────────────


def test_topology_loads():
    from topology import load

    data = load()
    assert data.facility.name
    assert len(data.equipment_types) > 0
    assert len(data.process_areas) > 0
    assert len(data.equipment_instances) > 0


def test_topology_validation_missing_facility(tmp_path):
    from topology import load

    bad = tmp_path / "bad.yaml"
    bad.write_text(
        "process_areas: []\nequipment_types: []\nequipment_instances: []\n"
        "historian: {default_lookback_hours: 24, max_lookback_days: 90}\n"
    )
    with pytest.raises(ValueError, match="facility"):
        load(bad)


def test_topology_validation_missing_equipment_types(tmp_path):
    from topology import load

    bad = tmp_path / "bad.yaml"
    bad.write_text(
        "facility: {name: Test, site_id: t, timezone: UTC}\n"
        "process_areas: []\nequipment_instances: []\n"
        "historian: {default_lookback_hours: 24, max_lookback_days: 90}\n"
    )
    with pytest.raises(ValueError, match="equipment_types"):
        load(bad)


def test_topology_validation_missing_historian(tmp_path):
    from topology import load

    bad = tmp_path / "bad.yaml"
    bad.write_text(
        "facility: {name: Test, site_id: t, timezone: UTC}\n"
        "process_areas: []\nequipment_types: []\nequipment_instances: []\n"
    )
    with pytest.raises(ValueError, match="historian"):
        load(bad)


def test_topology_file_env_override(monkeypatch, tmp_path):
    from topology import load

    alt = tmp_path / "alt.yaml"
    alt.write_text("""
facility: {name: Test Plant, site_id: test, timezone: UTC}
process_areas:
  - id: area_a
    name: Area A
    description: Test area
equipment_types:
  - id: pump
    name: Pump
    description: A pump
    attributes:
      - id: flow
        name: Flow
        units: L/min
        normal_range: {min: 0, max: 10}
    fault_modes: []
equipment_instances:
  - id: test_pump_01
    name: TestPump_01
    type_id: pump
    process_area_id: area_a
    tag_bindings:
      flow: Test/TestPump_01/Flow
historian: {default_lookback_hours: 24, max_lookback_days: 90}
""")
    monkeypatch.setenv("TOPOLOGY_FILE", str(alt))
    data = load()
    assert data.equipment_instances[0].name == "TestPump_01"


# ── instances ──────────────────────────────────────────────────────────────────


def test_instances_total_count():
    from instances import INSTANCES

    assert len(INSTANCES) == 10


def test_instances_equipment_types_present():
    from instances import INSTANCES

    types = {eq_type for eq_type, _, _ in INSTANCES}
    assert types == {"Pump", "Clarifier", "StorageTank", "Dosing", "UV"}


def test_instances_no_legacy_tank_type():
    from instances import INSTANCES

    types = {eq_type for eq_type, _, _ in INSTANCES}
    assert "Tank" not in types


def test_instance_ids():
    from instances import INSTANCES

    ids = {inst_id for _, inst_id, _ in INSTANCES}
    assert ids == {
        "RawWater_01",
        "RawWater_02",
        "HighService_01",
        "HighService_02",
        "Clarifier_01",
        "FinishedWater_01",
        "Chlorine_01",
        "Fluoride_01",
        "UV_01",
        "UV_02",
    }


def test_clarifier_has_no_ph():
    from instances import INSTANCES

    _, _, attrs = next(x for x in INSTANCES if x[1] == "Clarifier_01")
    assert set(attrs.keys()) == {"Level", "Turbidity"}
    assert "pH" not in attrs


def test_storage_tank_has_ph():
    from instances import INSTANCES

    _, _, attrs = next(x for x in INSTANCES if x[1] == "FinishedWater_01")
    assert set(attrs.keys()) == {"Level", "Turbidity", "pH"}


def test_finished_water_turbidity_override():
    from instances import INSTANCES
    from generators import RandomWalk

    _, _, attrs = next(x for x in INSTANCES if x[1] == "FinishedWater_01")
    gen = attrs["Turbidity"]
    assert isinstance(gen, RandomWalk)
    assert gen.hi == 1.0  # override: lo: 0, hi: 1


def test_high_service_pressure_override():
    from instances import INSTANCES
    from generators import RandomWalk

    _, _, attrs = next(x for x in INSTANCES if x[1] == "HighService_01")
    gen = attrs["Pressure"]
    assert isinstance(gen, RandomWalk)
    assert gen.lo == 2.0  # override: lo: 2


def test_high_service_02_starts_stopped():
    from instances import INSTANCES
    from generators import OscillatingBool

    _, _, attrs = next(x for x in INSTANCES if x[1] == "HighService_02")
    gen = attrs["Running"]
    assert isinstance(gen, OscillatingBool)
    assert gen.value is False  # override: initial: false


def test_uv_02_starts_stopped():
    from instances import INSTANCES
    from generators import OscillatingBool

    _, _, attrs = next(x for x in INSTANCES if x[1] == "UV_02")
    gen = attrs["Running"]
    assert isinstance(gen, OscillatingBool)
    assert gen.value is False


def test_instances_interface_is_list_of_tuples():
    from instances import INSTANCES

    for item in INSTANCES:
        eq_type, inst_id, attrs = item
        assert isinstance(eq_type, str)
        assert isinstance(inst_id, str)
        assert isinstance(attrs, dict)
        assert len(attrs) > 0


# ── fault modes ────────────────────────────────────────────────────────────────


def test_fault_modes_all_types_present():
    from faults import TYPE_FAULT_MODES

    assert set(TYPE_FAULT_MODES.keys()) == {
        "Pump",
        "Clarifier",
        "StorageTank",
        "Dosing",
        "UV",
    }


def test_fault_modes_no_legacy_tank():
    from faults import TYPE_FAULT_MODES

    assert "Tank" not in TYPE_FAULT_MODES


def test_fault_modes_normal_always_first():
    from faults import TYPE_FAULT_MODES, FaultMode

    for eq_type, modes in TYPE_FAULT_MODES.items():
        assert modes[0] == FaultMode.NORMAL, f"{eq_type}: NORMAL must be first"


def test_pump_fault_modes():
    from faults import TYPE_FAULT_MODES, FaultMode

    modes = TYPE_FAULT_MODES["Pump"]
    assert FaultMode.SUCTION_STARVATION in modes
    assert FaultMode.RUN_STATUS_FAULT in modes
    assert FaultMode.PRESSURE_DRIFT in modes
    assert FaultMode.CAVITATION in modes


def test_clarifier_fault_modes():
    from faults import TYPE_FAULT_MODES, FaultMode

    modes = TYPE_FAULT_MODES["Clarifier"]
    assert FaultMode.LEVEL_SENSOR_FAULT in modes
    assert FaultMode.TURBIDITY_SPIKE in modes


def test_storage_tank_fault_modes():
    from faults import TYPE_FAULT_MODES, FaultMode

    modes = TYPE_FAULT_MODES["StorageTank"]
    assert FaultMode.LEVEL_SENSOR_FAULT in modes
    assert FaultMode.TURBIDITY_SPIKE in modes


def test_dosing_fault_modes():
    from faults import TYPE_FAULT_MODES, FaultMode

    modes = TYPE_FAULT_MODES["Dosing"]
    assert FaultMode.DOSING_BLOCKAGE in modes
    assert FaultMode.TANK_EMPTY in modes
    assert FaultMode.RUN_STATUS_FAULT in modes


def test_uv_fault_modes():
    from faults import TYPE_FAULT_MODES, FaultMode

    modes = TYPE_FAULT_MODES["UV"]
    assert FaultMode.LAMP_DEGRADATION in modes
    assert FaultMode.LAMP_FAILURE in modes


# ── /setpoint HTTP endpoint ─────────────────────────────────────────────────
#
# Regression coverage for a production-safety bug: handle_setpoint accepted
# any float() for `value` (including nan/inf) and any string for `attribute`
# without checking it belongs to the target instance, storing bad data via
# setpoint_overrides. NaN/inf poisons the first-order ramp permanently once
# it lands in _setpoint_ramp (gap = new - nan is still nan), and an unknown
# attribute silently no-ops while returning 200. See simulator.py's
# handle_setpoint, instance_attributes(), and engineering_limits().


def _setpoint_request(params: dict) -> tuple[int, dict]:
    """POST /setpoint against a freshly-built control-plane app (no real TCP
    bind, no real MQTT client) and return (status, json_body)."""
    import asyncio
    import json as json_module
    from unittest.mock import MagicMock

    from aiohttp.test_utils import TestClient, TestServer

    import simulator

    async def run():
        app = simulator._build_control_app(MagicMock())
        server = TestServer(app)
        client = TestClient(server)
        await client.start_server()
        try:
            resp = await client.post("/setpoint", params=params)
            body = json_module.loads(await resp.text())
            return resp.status, body
        finally:
            await client.close()

    return asyncio.run(run())


def test_setpoint_rejects_nan():
    status, body = _setpoint_request(
        {"target": "Chlorine_01", "attribute": "FlowRate", "value": "nan"}
    )
    assert status == 400
    assert "finite" in body["error"]

    import simulator

    assert "FlowRate" not in simulator.setpoint_overrides.get("Chlorine_01", {})


def test_setpoint_rejects_inf():
    for value_str in ("inf", "-inf", "Infinity"):
        status, body = _setpoint_request(
            {"target": "Chlorine_01", "attribute": "FlowRate", "value": value_str}
        )
        assert status == 400, value_str
        assert "finite" in body["error"]


def test_setpoint_rejects_unknown_attribute():
    status, body = _setpoint_request(
        {"target": "Chlorine_01", "attribute": "Bogus", "value": "5.0"}
    )
    assert status == 400
    assert "Unknown attribute" in body["error"]
    assert "FlowRate" in body["known"]

    import simulator

    assert "Chlorine_01" not in simulator.setpoint_overrides or "Bogus" not in (
        simulator.setpoint_overrides.get("Chlorine_01", {})
    )


def test_setpoint_rejects_out_of_range_value():
    # Chlorine_01.FlowRate normal_range in topology.yaml is [4.5, 5.5] L/h.
    status, body = _setpoint_request(
        {"target": "Chlorine_01", "attribute": "FlowRate", "value": "100"}
    )
    assert status == 400
    assert "engineering limits" in body["error"]


def test_setpoint_valid_value_succeeds_and_is_stored():
    status, body = _setpoint_request(
        {"target": "Chlorine_01", "attribute": "FlowRate", "value": "5.0"}
    )
    assert status == 200
    assert body == {"target": "Chlorine_01", "attribute": "FlowRate", "value": 5.0}

    import simulator

    assert simulator.setpoint_overrides["Chlorine_01"]["FlowRate"] == 5.0


def test_setpoint_valid_value_advances_simulated_value():
    """A valid setpoint actually changes the ramped value applied in the main
    publish loop, not just the stored override."""
    import simulator

    simulator.setpoint_overrides.clear()
    simulator._setpoint_ramp.clear()

    status, _ = _setpoint_request(
        {"target": "Chlorine_01", "attribute": "FlowRate", "value": "5.5"}
    )
    assert status == 200

    # Simulate one tick of the ramp logic from simulator.py's main loop.
    sp_target = simulator.setpoint_overrides["Chlorine_01"]["FlowRate"]
    inst_ramp = simulator._setpoint_ramp.setdefault("Chlorine_01", {})
    live_value = 4.5  # stand-in for the generator's current raw value
    inst_ramp.setdefault("FlowRate", live_value)
    current = inst_ramp["FlowRate"]
    gap = sp_target - current
    assert gap == gap  # not NaN
    current = (
        sp_target
        if abs(gap) < 0.01
        else round(current + gap * simulator._RAMP_FRACTION, 2)
    )
    inst_ramp["FlowRate"] = current

    assert current != live_value
    assert current == round(4.5 + (5.5 - 4.5) * simulator._RAMP_FRACTION, 2)


def test_setpoint_nan_does_not_poison_ramp_state():
    """Directly demonstrates the bug this fix closes: previously, once a nan
    value reached _setpoint_ramp, gap = new_value - nan stayed nan forever,
    even for a subsequent valid corrective setpoint. With validation in
    place, nan is rejected before it ever reaches setpoint_overrides or
    _setpoint_ramp, so the ramp state is never poisoned."""
    import math

    import simulator

    simulator.setpoint_overrides.clear()
    simulator._setpoint_ramp.clear()

    status, _ = _setpoint_request(
        {"target": "Chlorine_01", "attribute": "FlowRate", "value": "nan"}
    )
    assert status == 400
    assert "FlowRate" not in simulator.setpoint_overrides.get("Chlorine_01", {})

    # A follow-up valid setpoint must still work normally.
    status, body = _setpoint_request(
        {"target": "Chlorine_01", "attribute": "FlowRate", "value": "5.0"}
    )
    assert status == 200
    assert not math.isnan(simulator.setpoint_overrides["Chlorine_01"]["FlowRate"])


def test_setpoint_boolean_attribute_has_no_range_check():
    """Running is data_type=boolean (no normal_range) — a finite value should
    be accepted without an engineering-limits check."""
    status, body = _setpoint_request(
        {"target": "Chlorine_01", "attribute": "Running", "value": "1"}
    )
    assert status == 200
    assert body["value"] == 1.0


def test_instance_attributes_and_engineering_limits_helpers():
    import simulator

    attrs = simulator.instance_attributes("Chlorine_01")
    assert set(attrs) == {"FlowRate", "TankLevel", "Running"}

    assert simulator.engineering_limits("Chlorine_01", "FlowRate") == (4.5, 5.5)
    assert simulator.engineering_limits("Chlorine_01", "Running") is None
    assert simulator.engineering_limits("Chlorine_01", "NoSuchAttr") is None
    assert simulator.instance_attributes("NoSuchInstance") == {}


def test_unknown_fault_in_topology_skipped(tmp_path, monkeypatch):
    """A fault id in topology with no FaultMode enum entry is silently skipped."""
    import yaml
    import faults as faults_module

    alt = tmp_path / "alt.yaml"
    alt.write_text(
        yaml.dump(
            {
                "facility": {"name": "Test", "site_id": "t", "timezone": "UTC"},
                "process_areas": [
                    {"id": "area_a", "name": "Area A", "description": "Test"}
                ],
                "equipment_types": [
                    {
                        "id": "pump",
                        "name": "Pump",
                        "description": "A pump",
                        "attributes": [
                            {
                                "id": "flow",
                                "name": "Flow",
                                "units": "L/min",
                                "normal_range": {"min": 0, "max": 10},
                            }
                        ],
                        "fault_modes": [
                            {
                                "id": "nonexistent_fault",
                                "name": "Nonexistent",
                                "description": "test",
                                "severity": "warning",
                                "affected_attributes": ["flow"],
                            }
                        ],
                    }
                ],
                "equipment_instances": [
                    {
                        "id": "p1",
                        "name": "P1",
                        "type_id": "pump",
                        "process_area_id": "area_a",
                        "tag_bindings": {"flow": "Test/P1/Flow"},
                    }
                ],
                "historian": {"default_lookback_hours": 24, "max_lookback_days": 90},
            }
        )
    )
    monkeypatch.setenv("TOPOLOGY_FILE", str(alt))

    from topology import load as _load

    data = _load()
    result = faults_module._build_type_fault_modes(data)
    from faults import FaultMode

    assert result["Pump"] == [FaultMode.NORMAL]  # unknown fault skipped, NORMAL remains
