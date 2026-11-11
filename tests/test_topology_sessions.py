"""topology-builder discovery sessions are bounded (gh-22).

Each session holds a full discovered instance list, and the module-level
_sessions dict was never evicted. Now: a finished session is dropped
TOPOLOGY_SESSION_TTL seconds after it was last used, the total is capped at
TOPOLOGY_MAX_SESSIONS (least recently used finished session first), and a
running discovery is never evicted; when every slot is running, a new
discovery is refused rather than spawning another adapter process.
"""

import asyncio
import importlib.util
import sys
from pathlib import Path

import pytest

_TB_DIR = Path(__file__).parent.parent / "topology-builder"
if str(_TB_DIR) not in sys.path:
    sys.path.insert(0, str(_TB_DIR))
pytest.importorskip("discovery", reason="topology-builder deps not installed")

_spec = importlib.util.spec_from_file_location(
    "_topology_builder_server_sessions", _TB_DIR / "server.py"
)
server = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(server)


class _Clock:
    def __init__(self):
        self.now = 1000.0

    def __call__(self):
        return self.now


@pytest.fixture()
def tb(monkeypatch):
    clock = _Clock()
    monkeypatch.setattr(server.time, "monotonic", clock)
    monkeypatch.setattr(server, "_SESSION_TTL_S", 60)
    monkeypatch.setattr(server, "_MAX_SESSIONS", 3)
    finish = {"status": "complete"}

    async def fake_discovery(discovery_id, broker_url, opcua_url, template):
        if finish["status"] is not None:
            server._sessions[discovery_id]["status"] = finish["status"]

    monkeypatch.setattr(server, "_run_discovery", fake_discovery)
    server._sessions.clear()
    yield clock, finish
    server._sessions.clear()


def _start():
    async def go():
        result = await server.start_discovery("localhost:1883")
        await asyncio.sleep(0)  # let the discovery task run
        return result

    return asyncio.run(go())


def _progress(discovery_id):
    return asyncio.run(server.get_discovery_progress(discovery_id))


def test_finished_session_expires_after_ttl(tb):
    clock, _ = tb
    sid = _start()["discovery_id"]
    clock.now += 61
    _start()  # eviction runs when a new discovery starts
    assert sid not in server._sessions
    assert "expired" in _progress(sid)["error"]


def test_using_a_session_keeps_it_alive(tb):
    clock, _ = tb
    sid = _start()["discovery_id"]
    clock.now += 50
    assert _progress(sid)["status"] == "complete"
    clock.now += 50  # 100s since start, 50s since last use
    _start()
    assert sid in server._sessions


def test_cap_evicts_least_recently_used_finished_session(tb):
    clock, _ = tb
    ids = []
    for _ in range(3):
        ids.append(_start()["discovery_id"])
        clock.now += 1  # distinct last-used times; ties would be arbitrary
    first, second, third = ids
    _progress(first)  # first is now the most recently used
    fourth = _start()["discovery_id"]
    assert set(server._sessions) == {first, third, fourth}
    assert second not in server._sessions


def test_running_sessions_are_never_evicted_and_cap_new_ones(tb):
    clock, finish = tb
    finish["status"] = None  # discoveries stay "running"
    running = [_start()["discovery_id"] for _ in range(3)]
    clock.now += 10_000
    refused = _start()
    assert "already running" in refused["error"]
    assert set(server._sessions) == set(running)


def test_discovery_task_is_referenced_until_done(tb):
    async def go():
        await server.start_discovery("localhost:1883")
        held = len(server._tasks)
        await asyncio.gather(*server._tasks)
        await asyncio.sleep(0)  # done-callbacks run on the next loop turn
        return held, len(server._tasks)

    held, after = asyncio.run(go())
    assert held == 1 and after == 0
