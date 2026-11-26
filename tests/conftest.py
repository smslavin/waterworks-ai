import asyncio
import sys
from pathlib import Path

import pytest

root = Path(__file__).parent.parent
sys.path.insert(0, str(root / "chat-ui"))
# Both directories have a topology.py; they are identical shims over the
# root loader (tests/test_topology_shims.py), so which one wins is moot.
sys.path.insert(0, str(root / "simulator"))


@pytest.fixture(autouse=True)
def _reset_event_loop_policy():
    """chat-ui/control.py calls the deprecated bare asyncio.get_event_loop()
    outside a running loop, relying on it to auto-create one. asyncio.run()
    (used throughout this suite) leaves the event loop policy in a state
    (loop=None, _set_called=True) where a later bare get_event_loop() call
    raises RuntimeError instead of creating a new one — order-dependent
    breakage in test_control_gate.py unrelated to whatever it's actually
    testing, depending on which other tests using asyncio.run() happened to
    run first. Set a fresh loop after every test so that pattern keeps
    working regardless of collection order."""
    yield
    try:
        asyncio.set_event_loop(asyncio.new_event_loop())
    except Exception:
        pass


@pytest.fixture(autouse=True)
def _loopback_auth_by_default(monkeypatch):
    """chat-ui loads the developer's .env at import, so a local
    WATERWORKS_REQUIRE_TOKEN=1 or BIND_HOST (set for Tailscale Serve, gh-80)
    would switch the token gate on for every test that expects the loopback
    default. Start each test there; tests that want the gate set it."""
    try:
        import auth
    except ImportError:
        return
    monkeypatch.setattr(auth, "EXPOSED", False)
    monkeypatch.setattr(auth, "REQUIRE_TOKEN", False)
