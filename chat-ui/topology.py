"""Load topology.yaml for the chat-ui layer."""

import os
from pathlib import Path

import yaml

_DEFAULT_PATH = Path(__file__).parent.parent / "topology.yaml"


def load(path: str | Path | None = None) -> dict:
    p = Path(path) if path else Path(os.environ.get("TOPOLOGY_FILE", _DEFAULT_PATH))
    with open(p) as f:
        return yaml.safe_load(f)
