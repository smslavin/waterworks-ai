"""Tests for the control-action approval gate (chat-ui/control.py).

Covers the fix for the approval gate being advisory-only: set_setpoint/
clear_fault must be refused unless a grant was stamped by an approved
propose_action with matching session/tool/args.
"""

import sys
from pathlib import Path

import pytest

root = Path(__file__).parent.parent
sys.path.insert(0, str(root / "chat-ui"))

import control  # noqa: E402


@pytest.fixture(autouse=True)
def _clean_control_state():
    control._pending.clear()
    control._proposals.clear()
    control._grants.clear()
    yield
    control._pending.clear()
    control._proposals.clear()
    control._grants.clear()


def _propose(
    session_id="s1",
    action_type="setpoint_adjustment",
    target="Chlorine_01",
    attribute="FlowRate",
    value="2.8",
):
    action_id = "a1"
    control.register(
        action_id,
        {
            "session_id": session_id,
            "action_type": action_type,
            "target": target,
            "attribute": attribute,
            "value": value,
        },
    )
    return action_id


def test_execution_refused_without_any_proposal():
    assert (
        control.consume_grant(
            "s1",
            "control__set_setpoint",
            {"target": "Chlorine_01", "attribute": "FlowRate", "value": 2.8},
        )
        is False
    )


def test_approval_grants_matching_execution_call():
    action_id = _propose()
    assert control.resolve(action_id, "approved") is True

    granted = control.consume_grant(
        "s1",
        "control__set_setpoint",
        {"target": "Chlorine_01", "attribute": "FlowRate", "value": 2.8},
    )
    assert granted is True


def test_grant_is_single_use():
    action_id = _propose()
    control.resolve(action_id, "approved")
    args = {"target": "Chlorine_01", "attribute": "FlowRate", "value": 2.8}

    assert control.consume_grant("s1", "control__set_setpoint", args) is True
    assert control.consume_grant("s1", "control__set_setpoint", args) is False


def test_denial_grants_nothing():
    action_id = _propose()
    control.resolve(action_id, "denied")

    assert (
        control.consume_grant(
            "s1",
            "control__set_setpoint",
            {"target": "Chlorine_01", "attribute": "FlowRate", "value": 2.8},
        )
        is False
    )


def test_mismatched_target_is_refused():
    action_id = _propose(target="Chlorine_01")
    control.resolve(action_id, "approved")

    assert (
        control.consume_grant(
            "s1",
            "control__set_setpoint",
            {"target": "RawWater_01", "attribute": "FlowRate", "value": 2.8},
        )
        is False
    )


def test_mismatched_value_is_refused():
    action_id = _propose(value="2.8")
    control.resolve(action_id, "approved")

    assert (
        control.consume_grant(
            "s1",
            "control__set_setpoint",
            {"target": "Chlorine_01", "attribute": "FlowRate", "value": 9.9},
        )
        is False
    )


def test_grant_scoped_to_session():
    action_id = _propose(session_id="s1")
    control.resolve(action_id, "approved")

    args = {"target": "Chlorine_01", "attribute": "FlowRate", "value": 2.8}
    assert control.consume_grant("s2", "control__set_setpoint", args) is False
    assert control.consume_grant("s1", "control__set_setpoint", args) is True


def test_int_and_float_value_are_equivalent():
    action_id = _propose(value="3")
    control.resolve(action_id, "approved")

    granted = control.consume_grant(
        "s1",
        "control__set_setpoint",
        {"target": "Chlorine_01", "attribute": "FlowRate", "value": 3},
    )
    assert granted is True


def test_fault_clear_payload_has_no_attribute_or_value():
    action_id = _propose(
        action_type="fault_clear", target="RawWater_01", attribute="", value=""
    )
    control.resolve(action_id, "approved")

    assert (
        control.consume_grant("s1", "control__clear_fault", {"target": "RawWater_01"})
        is True
    )


def test_unparseable_setpoint_value_grants_nothing():
    action_id = _propose(action_type="setpoint_adjustment", value="not-a-number")
    control.resolve(action_id, "approved")

    assert (
        control.consume_grant(
            "s1",
            "control__set_setpoint",
            {"target": "Chlorine_01", "attribute": "FlowRate", "value": "not-a-number"},
        )
        is False
    )
