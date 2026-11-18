""".env and API-key diagnostics (gh-66, gh-67).

On the demo VM a duplicate ANTHROPIC_API_KEY line in one plant's .env
produced bare 401s while an identical-looking file worked elsewhere. Every
service now runs fieldworks.service_env.check_env_file before load_dotenv,
and a rejected key says which key and where it was set.
"""

import ast
import asyncio
import json
import logging
from pathlib import Path

import anthropic
import httpx
import pytest

import model_params
import status_heartbeat

ROOT = Path(__file__).parent.parent
SERVICES = [
    "audit-mcp/server.py",
    "chat-ui/backend.py",
    "control-mcp/server.py",
    "enterprise/diagnose_plant_mcp/server.py",
    "enterprise/orchestrator/backend.py",
    "enterprise/query_history_mcp/server.py",
    "influxdb-mcp/server.py",
    "memory-mcp/server.py",
    "mqtt-influx-bridge/bridge.py",
    "simulator/simulator.py",
    "topology-builder/server.py",
]


def _first_call_line(tree, name):
    lines = [
        node.lineno
        for node in ast.walk(tree)
        if isinstance(node, ast.Call) and getattr(node.func, "id", None) == name
    ]
    return min(lines) if lines else None


@pytest.mark.parametrize("path", SERVICES)
def test_every_service_checks_env_before_loading_it(path):
    # After load_dotenv the environment can't tell shell values from .env
    # values, so the check is only meaningful before it.
    tree = ast.parse((ROOT / path).read_text())
    check, load = _first_call_line(tree, "check_env_file"), _first_call_line(
        tree, "load_dotenv"
    )
    assert check is not None, f"{path} never calls check_env_file"
    assert load is not None and check < load, f"{path}: check after load_dotenv"


def _auth_error(key):
    request = httpx.Request(
        "POST", "https://api.anthropic.com/v1/messages", headers={"x-api-key": key}
    )
    return anthropic.AuthenticationError(
        "invalid x-api-key",
        response=httpx.Response(401, request=request),
        body=None,
    )


@pytest.fixture(autouse=True)
def _fresh_reports(monkeypatch):
    monkeypatch.setattr(model_params, "_reported_keys", set())


def test_rejected_key_names_its_ending_not_the_key(caplog):
    text = model_params.error_text(_auth_error("sk-ant-api03-secretpart-wxyz"))
    assert "ending ...wxyz" in text
    assert "secretpart" not in text
    assert "/" not in text  # no file paths in what the UI shows


def test_rejected_key_logs_where_it_was_set_once(caplog, monkeypatch):
    monkeypatch.setattr(model_params, "env_source", lambda name: "/p/.env line 12")
    caplog.set_level(logging.ERROR, logger=model_params.logger.name)
    for _ in range(3):
        model_params.error_text(_auth_error("sk-ant-api03-secretpart-wxyz"))
    errors = [r.getMessage() for r in caplog.records]
    assert len(errors) == 1
    assert "/p/.env line 12" in errors[0]
    assert "secretpart" not in errors[0]


def test_other_errors_pass_through_unchanged():
    assert model_params.error_text(RuntimeError("boom")) == "boom"


def test_heartbeat_does_not_cache_a_narrative_from_a_failed_run(monkeypatch):
    async def failing_run(messages, model, api_key=None):
        yield json.dumps({"type": "text", "text": "Partial status"})
        yield json.dumps({"type": "error", "error": "Anthropic rejected ..."})

    monkeypatch.setattr(status_heartbeat, "run_multi_agent", failing_run)
    with pytest.raises(RuntimeError, match="Anthropic rejected"):
        asyncio.run(status_heartbeat._generate_narrative())
