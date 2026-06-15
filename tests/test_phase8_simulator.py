"""Phase 8 simulator tests — topology.yaml drives instances and fault modes.

All tests are import-level only: no MQTT, no OPC-UA, no network.
"""

import os
import pytest
from pathlib import Path

TOPOLOGY_PATH = Path(__file__).parent.parent.parent / "topology.yaml"


# ── topology loader ────────────────────────────────────────────────────────────


def test_topology_loads():
    from topology import load

    data = load()
    assert "equipment_types" in data
    assert "instances" in data
    assert "process_areas" in data


def test_topology_validation_missing_equipment_types(tmp_path):
    from topology import load

    bad = tmp_path / "bad.yaml"
    bad.write_text("instances:\n  Pump: []\n")
    with pytest.raises(AssertionError, match="equipment_types"):
        load(bad)


def test_topology_validation_missing_instances(tmp_path):
    from topology import load

    bad = tmp_path / "bad.yaml"
    bad.write_text("equipment_types:\n  Pump:\n    attributes: {}\n    faults: []\n")
    with pytest.raises(AssertionError, match="instances"):
        load(bad)


def test_topology_validation_missing_attributes(tmp_path):
    from topology import load

    bad = tmp_path / "bad.yaml"
    bad.write_text(
        "equipment_types:\n  Pump:\n    faults: []\ninstances:\n  Pump: []\n"
    )
    with pytest.raises(AssertionError, match="attributes"):
        load(bad)


def test_topology_file_env_override(monkeypatch, tmp_path):
    from topology import load

    alt = tmp_path / "alt.yaml"
    alt.write_text(
        "equipment_types:\n  Pump:\n    attributes: {Flow: {lo: 0, hi: 10, step: 1}}\n    faults: []\n"
        "instances:\n  Pump:\n    - id: TestPump_01\n"
    )
    monkeypatch.setenv("TOPOLOGY_FILE", str(alt))
    data = load()
    assert list(data["instances"]["Pump"][0]["id"]) == list("TestPump_01")


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


def test_unknown_fault_in_topology_skipped(tmp_path, monkeypatch):
    """A fault name in topology with no FaultMode enum entry is silently skipped."""
    import yaml
    import importlib
    import faults as faults_module

    alt = tmp_path / "alt.yaml"
    alt.write_text(
        yaml.dump(
            {
                "equipment_types": {
                    "Pump": {
                        "attributes": {"Flow": {"lo": 0, "hi": 10, "step": 1}},
                        "faults": {"nonexistent_fault": {"heuristic": "test"}},
                    }
                },
                "instances": {"Pump": [{"id": "P1"}]},
            }
        )
    )
    monkeypatch.setenv("TOPOLOGY_FILE", str(alt))

    from topology import load as _load

    data = _load()
    result = faults_module._build_type_fault_modes(data)
    from faults import FaultMode

    assert result["Pump"] == [FaultMode.NORMAL]  # unknown fault skipped, NORMAL remains
