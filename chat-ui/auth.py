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

What's gated: every route that changes state (chat, actions, faults,
reactive toggle, insights, topology commit, audit rotation) and every route
that reads operator content or control actions (audit, metrics with its
user_message column, the reactive event stream, recent alerts, reviews).
What stays open, deliberately: the SPA shell and the read-only plant
description it boots from (/api/site, /api/topology, /api/sites,
/api/plant-status, /api/models, /api/health, /api/insight/categories,
/api/reactive) and the simulator's fault status (/api/fault/status,
/api/fault/modes). None of those carries operator input or proposed
actions, and the page needs them before it can attach a token.
"""

import functools
import logging
import os
import re
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


# Who approved an action, as far as this deployment can tell (spec Part I,
# Operator identity; gh-82). Neither case authenticates a person, so
# neither names one: exposed, an approval proves someone held the shared
# token; on loopback, which checks no token, it proves someone could reach
# the host. Recorded with every operator decision and granted execution.
EXPOSED_OPERATOR_ID = "shared-token"
LOOPBACK_OPERATOR_ID = "local-console"


def approver() -> dict[str, str]:
    """operator_id and auth_method for an operator decision made now."""
    return {
        "operator_id": EXPOSED_OPERATOR_ID if EXPOSED else LOOPBACK_OPERATOR_ID,
        "auth_method": "shared_credential",
    }


# ── Keep the token out of the access log ─────────────────────────────────────
#
# Plain navigations and the mobile page's EventSource can only send the
# token as ?token=, and uvicorn's access log prints every request path, so
# the token landed in logs/chat-ui.log in plain text.

_TOKEN_IN_QUERY = re.compile(r"([?&]token=)[^&#\s]*")


def redact(path: str) -> str:
    return _TOKEN_IN_QUERY.sub(r"\1[redacted]", path)


class RedactTokenFilter(logging.Filter):
    """Rewrites the request path in uvicorn.access records. uvicorn passes
    (client_addr, method, full_path, http_version, status_code) as args."""

    def filter(self, record: logging.LogRecord) -> bool:
        args = record.args
        if isinstance(args, tuple) and len(args) >= 3 and isinstance(args[2], str):
            record.args = (*args[:2], redact(args[2]), *args[3:])
        return True


def redact_access_log() -> None:
    """Attach the filter once. Call after uvicorn configures logging (the
    app's lifespan): its dictConfig runs at server start."""
    access = logging.getLogger("uvicorn.access")
    if not any(isinstance(f, RedactTokenFilter) for f in access.filters):
        access.addFilter(RedactTokenFilter())
