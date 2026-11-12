"""Every service logs through fieldworks.service_logging.setup_logging.

Eight services carried their own copy of the logging setup; memory-mcp
printed instead, and topology-builder and the enterprise orchestrator had no
log file (gh-29). A root-level stopgap module served until fieldworks-core
1.2.0 shipped the helper (fieldworks-build/fieldworks-core#40); its behavior
is tested there.
"""

import ast
from pathlib import Path

import pytest

ROOT = Path(__file__).parent.parent

SERVICES = {
    "audit-mcp/server.py": "audit_mcp",
    "chat-ui/backend.py": "chat_ui",
    "control-mcp/server.py": "control_mcp",
    "influxdb-mcp/server.py": "influxdb_mcp",
    "memory-mcp/server.py": "memory_mcp",
    "mqtt-influx-bridge/bridge.py": "bridge",
    "simulator/simulator.py": "simulator",
    "topology-builder/server.py": "topology_builder",
    "enterprise/diagnose_plant_mcp/server.py": "diagnose_plant_mcp",
    "enterprise/query_history_mcp/server.py": "query_history_mcp",
    "enterprise/orchestrator/backend.py": "orchestrator",
}


def _setup_call(path):
    """The log name a module passes to setup_logging, or None."""
    tree = ast.parse((ROOT / path).read_text())
    for node in ast.walk(tree):
        if (
            isinstance(node, ast.Call)
            and getattr(node.func, "id", None) == "setup_logging"
            and len(node.args) == 2
        ):
            return node.args[1].value
    return None


@pytest.mark.parametrize("path,log_name", SERVICES.items())
def test_every_service_uses_the_shared_setup(path, log_name):
    source = (ROOT / path).read_text()
    assert "from fieldworks.service_logging import setup_logging" in source
    assert _setup_call(path) == log_name
    assert "RotatingFileHandler" not in source
    assert "logging.basicConfig" not in source
