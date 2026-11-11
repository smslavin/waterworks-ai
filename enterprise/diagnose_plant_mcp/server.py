"""diagnose_plant MCP server — thin HTTP client of each plant's own chat-ui.

Tools
-----
diagnose_plant   Ask one plant's multi-agent diagnostic system a question,
                 return its synthesized status summary.

This process never holds aggregator URLs or MCP credentials for any plant —
only each plant's chat-ui base URL, from enterprise.yaml via plant_registry.
That's a structural guarantee against raw cross-plant sensor access (the
enterprise orchestrator can only ask a plant a question and read its
synthesized answer, the same way an operator would), not just a convention.
It also means specialist fan-out/synthesis logic lives in exactly one place
(each plant's own multi_agent_loop.py) rather than being reimplemented here.

Environment variables
---------------------
ENTERPRISE_FILE  Path to enterprise.yaml (default: ../enterprise.yaml)
FASTMCP_PORT     Port to bind             (default: 8200)
"""

import asyncio
import json
import logging
import logging.handlers
import os
import sys
from pathlib import Path

import httpx
from dotenv import load_dotenv
from mcp.server import MCPServer

sys.path.insert(0, str(Path(__file__).parent.parent))
from plant_registry import get_site, load_sites

load_dotenv()

_log_dir = os.path.join(os.path.dirname(__file__), "logs")
os.makedirs(_log_dir, exist_ok=True)
_fh = logging.handlers.RotatingFileHandler(
    os.path.join(_log_dir, "diagnose_plant_mcp.log"),
    maxBytes=5 * 1024 * 1024,
    backupCount=3,
)
_fh.setFormatter(
    logging.Formatter(
        "%(asctime)s %(levelname)s %(name)s: %(message)s", datefmt="%Y-%m-%d %H:%M:%S"
    )
)
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s %(levelname)s %(name)s: %(message)s",
    datefmt="%Y-%m-%d %H:%M:%S",
    handlers=[logging.StreamHandler(), _fh],
)
logger = logging.getLogger(__name__)

mcp = MCPServer("diagnose-plant-mcp")

# A plant's own multi-agent diagnostic loop can legitimately take a couple
# minutes (several sequential specialist/tool-calling turns) — generous, but
# still a hard ceiling. This guards against more than slowness: chat-ui's SSE
# responses send periodic keep-alive pings (sse_starlette), which keep bytes
# flowing — and therefore keep httpx's own *read* timeout from ever firing —
# even if the plant's own loop has actually stalled with no real progress.
# Only a wall-clock deadline around the whole request catches that case.
PLANT_TIMEOUT_SECONDS = 240


class _PlantSideError(Exception):
    """A plant's own /api/chat reported an error event on its SSE stream —
    distinct from httpx.HTTPError (transport-level) or asyncio.TimeoutError
    (this call's own deadline), so each gets its own message to the caller."""


def _format_summary(verdict: dict | None, full_text: str) -> str:
    """A plant's answer for the enterprise orchestrator: its verdict block
    when it sent one, else the raw (truncated) text for conversational
    replies that don't warrant a SUMMARY block.

    The plant's chat-ui parses the block itself (chat-ui/verdict.py) and
    sends it as a "verdict" event; matching the text again here was one of
    five parsers that had drifted apart (gh-25).
    """
    if verdict is None:
        return full_text.strip()[:2000] or "(empty response)"
    lines = [f"Status: {verdict['status']}"]
    if verdict.get("overview"):
        lines.append(f"Overview: {verdict['overview']}")
    if verdict.get("confidence") is not None:
        lines.append(f"Confidence: {verdict['confidence']}")
    if verdict.get("points"):
        lines.append("Key points:")
        lines.extend(f"- {p}" for p in verdict["points"])
    return "\n".join(lines)


@mcp.tool()
async def diagnose_plant(site_id: str, query: str) -> str:
    """Ask one plant's own multi-agent diagnostic system a question and return
    its synthesized status summary.

    Args:
        site_id: Plant identifier from enterprise.yaml, e.g. "wtp" or "wtp2".
        query:   Natural-language diagnostic question for that plant.
    """
    site = get_site(site_id)
    if site is None:
        known = ", ".join(sorted(load_sites().keys())) or "(none registered)"
        return f"Error: unknown site_id '{site_id}'. Known sites: {known}."

    chat_ui_url = site["chat_ui_url"]

    verdict: dict | None = None

    async def _ask() -> list[str]:
        nonlocal verdict
        full_text: list[str] = []
        # timeout here is per-read (resets on every chunk, including the
        # plant's own SSE keep-alive pings) — real deadline enforcement is
        # the asyncio.wait_for around this whole call, below.
        async with httpx.AsyncClient(timeout=30.0) as client:
            async with client.stream(
                "POST",
                f"{chat_ui_url}/api/chat",
                json={
                    "messages": [{"role": "user", "content": query}],
                    "mode": "multi",
                },
            ) as resp:
                resp.raise_for_status()
                async for line in resp.aiter_lines():
                    if not line.startswith("data: "):
                        continue
                    try:
                        event = json.loads(line[len("data: ") :])
                    except json.JSONDecodeError:
                        continue
                    event_type = event.get("type")
                    if event_type == "text":
                        full_text.append(event.get("text", ""))
                    elif event_type == "verdict":
                        verdict = event
                    elif event_type == "error":
                        logger.warning(
                            "diagnose_plant(%s) plant-side error: %s",
                            site_id,
                            event.get("error"),
                        )
                        raise _PlantSideError(event.get("error"))
                    elif event_type == "done":
                        # The plant's chat-ui may keep the SSE connection open
                        # after this (EventSourceResponse's own keep-alive
                        # pings), so this loop must stop itself here rather
                        # than waiting for the stream to close on its own.
                        break
        return full_text

    try:
        full_text = await asyncio.wait_for(_ask(), timeout=PLANT_TIMEOUT_SECONDS)
    except asyncio.TimeoutError:
        logger.warning(
            "diagnose_plant(%s) timed out after %ss (%s)",
            site_id,
            PLANT_TIMEOUT_SECONDS,
            chat_ui_url,
        )
        return (
            f"Plant '{site_id}' did not respond within {PLANT_TIMEOUT_SECONDS}s — "
            "treat its status as unknown, not confirmed normal."
        )
    except _PlantSideError as exc:
        return f"Error from plant '{site_id}': {exc}"
    except httpx.HTTPError as exc:
        logger.warning(
            "diagnose_plant(%s) request to %s failed: %s", site_id, chat_ui_url, exc
        )
        return f"Error reaching plant '{site_id}' at {chat_ui_url}: {exc}"

    response_text = "".join(full_text)
    if not response_text:
        return f"Plant '{site_id}' returned no response."
    return f"[{site_id}] " + _format_summary(verdict, response_text)


@mcp.tool()
async def get_plant_status(site_id: str) -> str:
    """Get one plant's last-known status — a pre-computed rollup refreshed
    periodically in the background (see status_heartbeat.py on each
    plant's own chat-ui), not a live diagnosis. Near-instant: this is a
    plain database read on the plant's side, not a fresh multi-agent
    run. Use this for overview/status questions ("what's the status of
    X", "is everything okay across the enterprise"). Use diagnose_plant
    instead when the question calls for genuine drill-down into a
    specific issue, since that runs a fresh live diagnosis — this can be
    up to roughly an hour stale (bounded by STATUS_HEARTBEAT_MAX_STALE_TICKS
    on that plant), whereas diagnose_plant is always current but slow.

    Args:
        site_id: Plant identifier from enterprise.yaml, e.g. "wtp" or "wtp2".
    """
    site = get_site(site_id)
    if site is None:
        known = ", ".join(sorted(load_sites().keys())) or "(none registered)"
        return f"Error: unknown site_id '{site_id}'. Known sites: {known}."

    chat_ui_url = site["chat_ui_url"]
    try:
        async with httpx.AsyncClient(timeout=10.0) as client:
            resp = await client.get(f"{chat_ui_url}/api/plant-status")
            resp.raise_for_status()
            data = resp.json()
    except httpx.HTTPError as exc:
        logger.warning(
            "get_plant_status(%s) request to %s failed: %s", site_id, chat_ui_url, exc
        )
        return f"Error reaching plant '{site_id}' at {chat_ui_url}: {exc}"

    if not data or not data.get("narrative"):
        return (
            f"Plant '{site_id}' has no status check recorded yet — its "
            "status heartbeat may not have completed a first check, or is "
            "disabled for this plant. Try diagnose_plant for a live answer."
        )

    return (
        f"[{site_id}] Status: {data['status_level']} "
        f"(as of {data['narrative_updated_at']})\n{data['narrative']}"
    )


if __name__ == "__main__":
    mcp.run(transport="sse", port=int(os.environ.get("FASTMCP_PORT", 8200)))
