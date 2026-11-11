"""Fault modes: topology.yaml, FaultMode and the handlers agree (gh-29).

A fault mode declared in topology.yaml without simulation code used to be
skipped silently: it never appeared in /fault-modes and nothing said why.
Now it is logged, and this test fails on one in the repo's topology.
"""

import logging
from types import SimpleNamespace

import faults
from faults import FaultMode, FaultState
from topology import load as load_topology


def test_every_mode_has_a_handler_method():
    modes = set(FaultMode) - {FaultMode.NORMAL}
    assert set(faults._HANDLERS) == modes
    for mode, method in faults._HANDLERS.items():
        assert callable(getattr(FaultState, method, None)), (mode, method)


def test_topology_declares_no_unimplemented_fault_modes():
    assert faults.unimplemented_fault_modes(load_topology()) == []


def test_unimplemented_mode_is_logged_and_left_out(caplog):
    topology = SimpleNamespace(
        equipment_types=[
            SimpleNamespace(
                name="Pump",
                fault_modes=[
                    SimpleNamespace(id="cavitation"),
                    SimpleNamespace(id="impeller_wear"),
                ],
            )
        ]
    )
    with caplog.at_level(logging.WARNING, logger="faults"):
        modes = faults._build_type_fault_modes(topology)
    assert modes == {"Pump": [FaultMode.NORMAL, FaultMode.CAVITATION]}
    assert any("impeller_wear" in r.getMessage() for r in caplog.records)


def test_apply_dispatches_through_the_registry():
    state = FaultState()
    assert state.apply("Intensity", 80.0) == 80.0  # normal passes through
    state.set_mode(FaultMode.LAMP_FAILURE)
    assert state.apply("Intensity", 80.0) < 10.0
    state.set_mode(FaultMode.RUN_STATUS_FAULT)
    assert state.apply("Running", False) is True
