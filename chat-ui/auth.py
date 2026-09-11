"""Shared-secret gate for chat-ui's mutating and audit-read HTTP routes.

This is defense-in-depth, not a login system. The primary protection is
backend.py binding to loopback by default (see BIND_HOST in backend.py) —
nothing on the network can reach these routes at all unless an operator
deliberately opts into BIND_HOST=0.0.0.0 or similar to reach the app from
a second device. This token exists for that opted-in case.

The token is accepted via an `Authorization: Bearer <token>` header (used
by the SPA's own fetch calls) or a `?token=` query param (used by plain
page navigations and links, e.g. /audit and /api/audit/download, which
can't set custom headers). Gated server-rendered pages must propagate the
presented token into any links/hrefs they emit so navigation keeps working.
"""

import functools
import os
import secrets

import starlette.responses

_ENV_VAR = "WATERWORKS_API_TOKEN"
_TOKEN = os.environ.get(_ENV_VAR) or secrets.token_urlsafe(32)
GENERATED = _ENV_VAR not in os.environ

_LOOPBACK_HOSTS = {"127.0.0.1", "localhost", "::1"}
BIND_HOST = os.environ.get("BIND_HOST", "127.0.0.1")
EXPOSED = BIND_HOST not in _LOOPBACK_HOSTS


def token() -> str:
    return _TOKEN


def presented(request) -> str:
    """The token the request is carrying, from header or query param, if any."""
    header = request.headers.get("authorization", "")
    if header.lower().startswith("bearer "):
        return header[7:]
    return request.query_params.get("token", "")


def check(request) -> bool:
    """True if the request may proceed.

    A no-op while bound to loopback: nothing off-host can reach these
    routes regardless, and requiring a token for the default single-operator
    case would be friction with no security benefit. Real enforcement only
    kicks in once BIND_HOST opts into exposing the app beyond loopback.
    """
    if not EXPOSED:
        return True
    given = presented(request)
    return bool(given) and secrets.compare_digest(given, _TOKEN)


def require(handler):
    """Route decorator: 401s unless the request presents the matching token."""

    @functools.wraps(handler)
    async def wrapped(request, *args, **kwargs):
        if not check(request):
            return starlette.responses.JSONResponse(
                {"error": "Missing or invalid API token"}, status_code=401
            )
        return await handler(request, *args, **kwargs)

    return wrapped
