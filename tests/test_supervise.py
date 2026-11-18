"""scripts/lib/supervise.sh: settings lookup, backends rendering, and the
startup checks start.sh/restart.sh run (gh-69, gh-70).

Each test sources the library into a fresh bash in a scratch directory, the
way the scripts do, and checks what it prints.
"""

import os
import socket
import subprocess
from pathlib import Path

import pytest

ROOT = Path(__file__).parent.parent
LIB = ROOT / "scripts" / "lib" / "supervise.sh"


def _bash(script, cwd, env=None):
    return subprocess.run(
        ["bash", "-c", f"set -m; source '{LIB}'; {script}"],
        cwd=cwd,
        env={**os.environ, **(env or {})},
        capture_output=True,
        text=True,
        timeout=30,
    )


def _free_port():
    with socket.socket() as s:
        s.bind(("127.0.0.1", 0))
        return s.getsockname()[1]


@pytest.fixture()
def listener():
    s = socket.socket()
    s.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
    s.bind(("127.0.0.1", 0))
    s.listen()
    yield s.getsockname()[1]
    s.close()


def test_env_value_prefers_shell_then_last_env_line_then_default(tmp_path):
    (tmp_path / ".env").write_text(
        'CHAT_UI_PORT=8010\n# CHAT_UI_PORT=9999\nCHAT_UI_PORT="8011"  # last wins\n'
    )
    out = _bash(
        "env_value CHAT_UI_PORT 8080; env_value MISSING 42; env_value SHELL_SET 1",
        tmp_path,
        {"SHELL_SET": "from-shell"},
    )
    assert out.stdout.split() == ["8011", "42", "from-shell"]


def test_env_value_reads_env_file_override(tmp_path):
    (tmp_path / "root.env").write_text("ENTERPRISE_PORT=8021\n")
    out = _bash("ENV_FILE=root.env env_value ENTERPRISE_PORT 8020", tmp_path)
    assert out.stdout.strip() == "8021"


def test_render_substitutes_ports_from_env_with_defaults(tmp_path):
    (tmp_path / ".env").write_text("INFLUXDB_MCP_PORT=8013\n")
    template = ROOT / "mcp-aggregator" / "backends.json"
    out = _bash(f"supervise_render '{template}' rendered.json", tmp_path)
    assert out.returncode == 0, out.stderr
    rendered = (tmp_path / "rendered.json").read_text()
    assert "localhost:8013/sse" in rendered  # from .env
    assert "localhost:8004/sse" in rendered  # default
    assert "${" not in rendered


def test_preflight_names_the_process_holding_a_port(tmp_path, listener):
    out = _bash(
        f"supervise_expect chat-ui {listener}; supervise_expect bridge; supervise_preflight",
        tmp_path,
    )
    assert out.returncode == 1
    assert f"[chat-ui] port {listener} is already in use by" in out.stdout


def test_preflight_passes_when_ports_are_free(tmp_path):
    out = _bash(
        f"supervise_expect chat-ui {_free_port()}; supervise_preflight", tmp_path
    )
    assert out.returncode == 0, out.stdout


def test_verify_reports_ok_and_failed_with_log_tail(tmp_path, listener):
    (tmp_path / "dies.sh").write_text("echo boom: address in use\nexit 1\n")
    script = f"""
    mkdir -p logs .pids
    supervise_start up . "sleep 30" .pids/up.pid >/dev/null
    supervise_start dies . "sh dies.sh" .pids/dies.pid >/dev/null
    supervise_expect up {listener}
    supervise_expect dies {_free_port()}
    supervise_verify 5
    status=$?
    kill -- -$(sed -n 1p .pids/up.pid) 2>/dev/null
    exit $status
    """
    out = _bash(script, tmp_path)
    assert out.returncode == 1
    assert f"[up] OK (port {listener})" in out.stdout
    assert "[dies] FAILED: exited during startup" in out.stdout
    assert "boom: address in use" in out.stdout


def test_verify_times_out_a_service_that_never_listens(tmp_path):
    port = _free_port()
    script = f"""
    mkdir -p logs .pids
    supervise_start slow . "sleep 30" .pids/slow.pid >/dev/null
    supervise_expect slow {port}
    supervise_verify 2
    status=$?
    kill -- -$(sed -n 1p .pids/slow.pid) 2>/dev/null
    exit $status
    """
    out = _bash(script, tmp_path)
    assert out.returncode == 1
    assert f"[slow] FAILED: not listening on port {port} after 2s" in out.stdout
