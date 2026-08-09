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

import json
import logging
import logging.handlers
import os
import re
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

# Matches chat-ui/frontend/src/components/panels/PlantPanel.vue's SUMMARY_RE —
# same convention, same source text (the plant's own orchestrator synthesis),
# kept in sync deliberately rather than importing across the JS/Python boundary.
_SUMMARY_RE = re.compile(
    r"SUMMARY:\s*\nStatus:\s*([^\n]+)\nOverview:\s*([^\n]+)\n"
    r"(?:Key points:\n([\s\S]+?))?(?:\n\n|$)",
    re.IGNORECASE,
)


def _extract_summary(full_text: str) -> str:
    """Pull the SUMMARY block out of a plant's full synthesis text. Falls back
    to the raw (truncated) text for simple conversational replies that don't
    warrant a SUMMARY block per the plant's own system prompt."""
    m = _SUMMARY_RE.search(full_text)
    if not m:
        return full_text.strip()[:2000] or "(empty response)"
    status, overview, points_block = m.group(1), m.group(2), m.group(3)
    points = [
        line.strip().lstrip("-").strip()
        for line in (points_block or "").splitlines()
        if line.strip().startswith("-")
    ]
    lines = [f"Status: {status.strip()}", f"Overview: {overview.strip()}"]
    if points:
        lines.append("Key points:")
        lines.extend(f"- {p}" for p in points)
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
    full_text: list[str] = []
    try:
        async with httpx.AsyncClient(timeout=120.0) as client:
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
                    elif event_type == "error":
                        logger.warning(
                            "diagnose_plant(%s) plant-side error: %s",
                            site_id,
                            event.get("error"),
                        )
                        return f"Error from plant '{site_id}': {event.get('error')}"
                    elif event_type == "done":
                        # The plant's chat-ui may keep the SSE connection open
                        # after this (EventSourceResponse's own keep-alive
                        # pings), so this loop must stop itself here rather
                        # than waiting for the stream to close on its own.
                        break
    except httpx.HTTPError as exc:
        logger.warning(
            "diagnose_plant(%s) request to %s failed: %s", site_id, chat_ui_url, exc
        )
        return f"Error reaching plant '{site_id}' at {chat_ui_url}: {exc}"

    response_text = "".join(full_text)
    if not response_text:
        return f"Plant '{site_id}' returned no response."
    return f"[{site_id}] " + _extract_summary(response_text)


if __name__ == "__main__":
    mcp.run(transport="sse", port=int(os.environ.get("FASTMCP_PORT", 8200)))
