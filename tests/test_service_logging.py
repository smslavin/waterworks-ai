"""service_logging.setup_logging, and every service using it (gh-29).

Eight services carried their own copy of the logging setup; memory-mcp
printed instead, and topology-builder and the enterprise orchestrator had no
log file. The helper is a stopgap until fieldworks-core ships one
(fieldworks-build/fieldworks-core#40).
"""

import ast
import io
import logging
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).parent.parent
sys.path.append(str(ROOT))
import service_logging  # noqa: E402

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


def test_logs_to_file_next_to_the_service_and_to_the_console(tmp_path):
    service = tmp_path / "some-mcp" / "server.py"
    service.parent.mkdir()
    console = io.StringIO()
    # basicConfig only configures a root logger with no handlers, and pytest's
    # logging plugin adds its own at the start of the test body, so clear
    # them here rather than in a fixture.
    root = logging.getLogger()
    saved, level = root.handlers[:], root.level
    root.handlers = []
    try:
        path = service_logging.setup_logging(service, "some_mcp", console=console)
        logging.getLogger("some.module").info("hello")
        handler = next(h for h in root.handlers if hasattr(h, "maxBytes"))
        rotation = (handler.maxBytes, handler.backupCount)
    finally:
        for h in root.handlers:
            h.close()
        root.handlers, root.level = saved, level

    assert path == tmp_path / "some-mcp" / "logs" / "some_mcp.log"
    line = path.read_text().strip()
    assert line.endswith("INFO some.module: hello")
    assert console.getvalue().strip() == line
    assert rotation == (5 * 1024 * 1024, 3)


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
    assert _setup_call(path) == log_name
    assert "RotatingFileHandler" not in source
    assert "logging.basicConfig" not in source
