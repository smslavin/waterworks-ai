"""Shim — delegates to shared loader at repo root."""
import importlib.util
from pathlib import Path

_spec = importlib.util.spec_from_file_location("_topology_shared", Path(__file__).parent.parent / "topology.py")
_mod  = importlib.util.module_from_spec(_spec); _spec.loader.exec_module(_mod)
load  = _mod.load
