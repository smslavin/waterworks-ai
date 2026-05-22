"""Waterworks-AI chat UI — Starlette backend."""

import asyncio
import json
import logging
import os
import sys

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s %(levelname)s %(message)s",
    datefmt="%Y-%m-%d %H:%M:%S",
)
logger = logging.getLogger(__name__)

sys.path.insert(0, os.path.dirname(__file__))

import uvicorn
from dotenv import load_dotenv
from sse_starlette.sse import EventSourceResponse
from starlette.applications import Starlette
from starlette.requests import Request
from starlette.responses import FileResponse, JSONResponse
from starlette.routing import Mount, Route
from starlette.staticfiles import StaticFiles

import audit
import claude_loop
import openai_loop

load_dotenv()

ANTHROPIC_API_KEY    = os.environ.get("ANTHROPIC_API_KEY", "")
MCP_AGGREGATOR_URL   = os.environ.get("MCP_AGGREGATOR_URL", "http://localhost:8100/sse")
SIMULATOR_CONTROL    = os.environ.get("SIMULATOR_CONTROL_URL", "http://localhost:8090")
STATIC_DIR           = os.path.join(os.path.dirname(__file__), "static")

_LOOP_MODULES = {"claude": claude_loop, "openai": openai_loop}


def _load_providers() -> list[dict]:
    path = os.path.join(os.path.dirname(__file__), "providers.json")
    with open(path) as f:
        providers = json.load(f)["providers"]
    for p in providers:
        if p.get("base_url_env"):
            p["base_url"] = os.environ.get(p["base_url_env"], p["base_url"])
    return providers


PROVIDERS = _load_providers()


def _resolve_provider(model: str) -> dict:
    default = None
    for p in PROVIDERS:
        if any(model.startswith(pat) for pat in p["model_patterns"]):
            return p
        if p.get("default"):
            default = p
    return default or PROVIDERS[0]


# ── Routes ────────────────────────────────────────────────────────────────────

async def index(request: Request):
    return FileResponse(os.path.join(STATIC_DIR, "index.html"))


async def models_endpoint(request: Request):
    import httpx
    local: list[str] = []
    for p in PROVIDERS:
        if p.get("loop") == "openai":
            try:
                async with httpx.AsyncClient() as http:
                    resp = await http.get(
                        f"{p['base_url']}/api/tags", timeout=3.0
                    )
                    local = [m["name"] for m in resp.json().get("models", [])]
            except Exception:
                pass

    cloud = claude_loop.CLAUDE_MODELS if ANTHROPIC_API_KEY else []
    return JSONResponse({"cloud": cloud, "local": local})


async def health_endpoint(request: Request):
    async def tcp_ok(host: str, port: int) -> bool:
        try:
            _, writer = await asyncio.wait_for(
                asyncio.open_connection(host, port), timeout=2.0
            )
            writer.close()
            await writer.wait_closed()
            return True
        except Exception:
            return False

    results = await asyncio.gather(
        tcp_ok("localhost", 8100),  # aggregator
        tcp_ok("localhost", 8086),  # influxdb
        tcp_ok("localhost", 1883),  # mqtt
        tcp_ok("localhost", 8090),  # simulator control
    )
    keys = ("aggregator", "influxdb", "mqtt", "simulator")
    return JSONResponse({k: "ok" if v else "error" for k, v in zip(keys, results)})


async def chat_endpoint(request: Request):
    body     = await request.json()
    messages = body.get("messages", [])
    model    = body.get("model", claude_loop.CLAUDE_MODELS[0])

    provider = _resolve_provider(model)
    run_fn   = _LOOP_MODULES[provider["loop"]].run_chat
    api_key  = os.environ.get(provider["api_key_env"]) if provider.get("api_key_env") else None

    async def generate():
        async for chunk in run_fn(
            messages, model,
            base_url=provider["base_url"],
            api_key=api_key,
        ):
            yield {"data": chunk}

    return EventSourceResponse(generate())


async def fault_endpoint(request: Request):
    """Proxy fault injection requests to the simulator control plane."""
    import httpx
    body   = await request.json()
    target = body.get("target", "")
    mode   = body.get("mode", "normal")
    try:
        async with httpx.AsyncClient() as http:
            resp = await http.post(
                f"{SIMULATOR_CONTROL}/fault",
                params={"target": target, "mode": mode},
                timeout=5.0,
            )
            return JSONResponse(resp.json(), status_code=resp.status_code)
    except Exception as exc:
        return JSONResponse({"error": str(exc)}, status_code=503)


async def fault_status_endpoint(request: Request):
    import httpx
    try:
        async with httpx.AsyncClient() as http:
            resp = await http.get(f"{SIMULATOR_CONTROL}/status", timeout=5.0)
            return JSONResponse(resp.json())
    except Exception as exc:
        return JSONResponse({"error": str(exc)}, status_code=503)


async def audit_endpoint(request: Request):
    return JSONResponse(audit.read_log())


async def audit_clear_endpoint(request: Request):
    audit.clear_log()
    return JSONResponse({"ok": True})


routes = [
    Route("/",                   index),
    Route("/api/models",         models_endpoint),
    Route("/api/health",         health_endpoint),
    Route("/api/chat",           chat_endpoint,        methods=["POST"]),
    Route("/api/fault",          fault_endpoint,       methods=["POST"]),
    Route("/api/fault/status",   fault_status_endpoint),
    Route("/api/audit",          audit_endpoint),
    Route("/api/audit/clear",    audit_clear_endpoint, methods=["POST"]),
    Mount("/static", StaticFiles(directory=STATIC_DIR), name="static"),
]

app = Starlette(routes=routes)

if __name__ == "__main__":
    uvicorn.run(app, host="0.0.0.0", port=8080, log_level="info")
