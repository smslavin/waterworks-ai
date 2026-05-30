"""Shared state for the operator action-approval flow.

The claude_loop generator registers a Future when it intercepts propose_action,
then awaits it. The backend's /api/action/respond endpoint resolves the Future
with the operator's decision, unblocking the generator.
"""

import asyncio

_pending: dict[str, "asyncio.Future[str]"] = {}


def register(action_id: str) -> "asyncio.Future[str]":
    """Create and store a Future for the given action_id. Returns the Future."""
    loop = asyncio.get_event_loop()
    fut: asyncio.Future[str] = loop.create_future()
    _pending[action_id] = fut
    return fut


def resolve(action_id: str, decision: str) -> bool:
    """Resolve a pending action Future with 'approved' or 'denied'.

    Returns True if the action was found and resolved, False otherwise.
    """
    fut = _pending.pop(action_id, None)
    if not fut or fut.done():
        return False
    fut.set_result(decision)
    return True


def pending_ids() -> list[str]:
    return list(_pending.keys())
