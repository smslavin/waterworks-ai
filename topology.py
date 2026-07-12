"""Shared topology.yaml loader for the waterworks-ai stack.

simulator/topology.py and chat-ui/topology.py are thin shims that re-export
this module. Edit here; both layers pick it up automatically.

Thin wrapper around fieldworks.topology.load() — env-var/default path
resolution is waterworks-ai's own concern, not the framework's.
"""

import os
from pathlib import Path

import yaml
from fieldworks.topology import TopologyConfig
from fieldworks.topology import load as _fw_load

_DEFAULT_PATH = Path(__file__).parent / "topology.yaml"


def _resolve_path(path: str | Path | None) -> Path:
    return Path(path) if path else Path(os.environ.get("TOPOLOGY_FILE", _DEFAULT_PATH))


def load(path: str | Path | None = None) -> TopologyConfig:
    return _fw_load(_resolve_path(path))


def load_extensions(path: str | Path | None = None) -> dict:
    """Raw top-level keys fieldworks.topology.load() doesn't know about
    (insight_categories, specialists) — waterworks-ai's own config sections,
    ignored (not rejected) by the fieldworks-core schema.
    """
    with open(_resolve_path(path)) as f:
        return yaml.safe_load(f)
