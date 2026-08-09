"""Enterprise orchestrator — Starlette app, cross-plant diagnostic chat endpoint.

Talks to exactly one MCP server (diagnose_plant_mcp) and nothing else — no
aggregator, no direct plant tool access. See enterprise_loop.py for the
orchestration logic itself.
"""

import json
import logging
import os
import sys
from pathlib import Path

sys.path.insert(0, os.path.dirname(__file__))
sys.path.insert(0, str(Path(__file__).parent.parent))

import uvicorn
from dotenv import load_dotenv

load_dotenv()

from sse_starlette.sse import EventSourceResponse
from starlette.applications import Starlette
from starlette.requests import Request
from starlette.responses import JSONResponse
from starlette.routing import Route

import enterprise_loop
from plant_registry import load_sites

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
logger = logging.getLogger(__name__)

ANTHROPIC_API_KEY = os.environ.get("ANTHROPIC_API_KEY", "")


async def chat_endpoint(request: Request):
    body = await request.json()
    messages = body.get("messages", [])

    async def generate():
        try:
            async for chunk in enterprise_loop.run_chat(
                messages, api_key=ANTHROPIC_API_KEY
            ):
                yield {"data": chunk}
        except Exception as exc:
            logger.exception("Enterprise chat stream error")
            yield {"data": json.dumps({"type": "error", "error": str(exc)})}

    return EventSourceResponse(generate())


async def sites_endpoint(request: Request):
    return JSONResponse(load_sites())


routes = [
    Route("/api/chat", chat_endpoint, methods=["POST"]),
    Route("/api/sites", sites_endpoint),
]

app = Starlette(routes=routes)

if __name__ == "__main__":
    uvicorn.run(
        app,
        host="0.0.0.0",  # nosec B104
        port=int(os.environ.get("ENTERPRISE_PORT", 8020)),
        log_level="info",
    )
