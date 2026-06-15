"""Shared topology.yaml loader for the waterworks-ai stack.

simulator/topology.py and chat-ui/topology.py are thin shims that re-export
this module. Edit here; both layers pick it up automatically.
"""

import os
from pathlib import Path

import yaml

_DEFAULT_PATH = Path(__file__).parent / "topology.yaml"


def load(path: str | Path | None = None) -> dict:
    p = Path(path) if path else Path(os.environ.get("TOPOLOGY_FILE", _DEFAULT_PATH))
    with open(p) as f:
        data = yaml.safe_load(f)
    _validate(data)
    return data


def _validate(data: dict) -> None:
    assert "equipment_types" in data, "topology.yaml missing 'equipment_types'"
    assert "instances" in data, "topology.yaml missing 'instances'"
    for eq_type, spec in data["equipment_types"].items():
        assert "attributes" in spec, f"{eq_type}: missing 'attributes'"
        assert "faults" in spec, f"{eq_type}: missing 'faults'"
