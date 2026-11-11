"""session_store reads equipment names and fault words from topology (gh-29).

Both used to be this plant's literals: a second plant with different
equipment (M10) got `equipment: ""` on every session summary, and a fault
mode added to topology.yaml was invisible to the status heuristic.
"""

from types import SimpleNamespace

import session_store


def _topology(instances, faults):
    return SimpleNamespace(
        equipment_instances=[SimpleNamespace(name=n) for n in instances],
        equipment_types=[
            SimpleNamespace(fault_modes=[SimpleNamespace(name=f) for f in faults])
        ],
    )


EASTSIDE = _topology(["Intake_A", "Intake_AB", "Ozone_1"], ["Ozone Generator Trip"])


def test_equipment_comes_from_the_plants_own_instances():
    pattern = session_store._equipment_re(EASTSIDE)
    found = pattern.findall("checked Intake_AB, Ozone_1 and RawWater_01")
    assert found == ["Intake_AB", "Ozone_1"]  # longest name wins; not this plant's


def test_extract_equipment_uses_this_plants_topology():
    calls = [
        ("mqtt__read_tag", {"tag_id": "Plant/WTP/RawWater_01/Flow"}),
        ("influxdb__query", {"flux_query": 'r.instance == "UV_02"'}),
        ("mqtt__read_tag", {"tag_id": "RawWater_99"}),
    ]
    assert session_store.extract_equipment(calls) == ["RawWater_01", "UV_02"]


def test_fault_words_come_from_declared_fault_modes():
    pattern = session_store._fault_mode_re(EASTSIDE)
    for text in (
        "ozone generator trip",
        "ozone-generator-trip",
        "ozone_generator_trip",
    ):
        assert pattern.search(text), text
    assert not pattern.search("generator tripped the breaker")


def test_heuristic_status_uses_this_plants_fault_modes():
    # "Dosing Blockage" is declared in topology.yaml; it wasn't in the old list.
    assert session_store.extract_status_single("Looks like a dosing blockage.") == (
        "Fault Detected",
        0.7,
    )
    assert session_store.extract_status_single("All nominal.") == ("Normal", 0.8)
