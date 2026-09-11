"""Waterworks-AI chat UI — Starlette backend."""

import asyncio
import json
import logging
import os
import sqlite3
import sys
import uuid
from datetime import datetime, timezone
from logging.handlers import RotatingFileHandler
from urllib.parse import urlparse

_log_dir = os.path.join(os.path.dirname(__file__), "logs")
os.makedirs(_log_dir, exist_ok=True)

_fmt = logging.Formatter(
    "%(asctime)s %(levelname)s %(name)s: %(message)s", datefmt="%Y-%m-%d %H:%M:%S"
)
_file_handler = RotatingFileHandler(
    os.path.join(_log_dir, "chat_ui.log"),
    maxBytes=5 * 1024 * 1024,  # 5 MB
    backupCount=3,
)
_file_handler.setFormatter(_fmt)

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s %(levelname)s %(message)s",
    datefmt="%Y-%m-%d %H:%M:%S",
    handlers=[logging.StreamHandler(sys.stdout), _file_handler],
)
logger = logging.getLogger(__name__)

sys.path.insert(0, os.path.dirname(__file__))

import uvicorn
from dotenv import load_dotenv

load_dotenv()

from contextlib import asynccontextmanager

from sse_starlette.sse import EventSourceResponse
from starlette.applications import Starlette
from starlette.requests import Request
from starlette.responses import FileResponse, HTMLResponse, JSONResponse
from starlette.routing import Mount, Route
from starlette.staticfiles import StaticFiles

import audit
import auth
import claude_loop
import control
import metrics
import mcp_client
import monitor as _monitor_mod
import multi_agent_loop
import openai_loop
import reactive_loop as _reactive_loop
import session_store
import status_heartbeat
import topology as _topo_loader

ANTHROPIC_API_KEY = os.environ.get("ANTHROPIC_API_KEY", "")
MCP_AGGREGATOR_URL = os.environ.get("MCP_AGGREGATOR_URL", "http://localhost:8100/sse")
SIMULATOR_CONTROL = os.environ.get("SIMULATOR_CONTROL_URL", "http://localhost:8090")
STATIC_DIR = os.path.join(os.path.dirname(__file__), "static")
_METRICS_DB = os.environ.get(
    "METRICS_DB_PATH", os.path.join(os.path.dirname(__file__), "metrics.db")
)

# M10 Phase 4: this plant's own identity + where to find the enterprise
# directory. SITE_NAME/REGION_NAME match enterprise.yaml's `name` fields for
# this site_id by convention (same pattern as SITE_ID matching
# facility.site_id — see session_store.py) — not parsed out of enterprise.yaml,
# since that file only lives in one plant's checkout (see enterprise.yaml's
# own header comment) and every other plant needs these too.
SITE_ID = os.environ.get("SITE_ID", "wtp")
SITE_NAME = os.environ.get("SITE_NAME", "Waterworks")
REGION_NAME = os.environ.get("REGION_NAME", "Metro Region")
GRAFANA_PORT = int(os.environ.get("GRAFANA_PORT", "3000"))
ENTERPRISE_ORCHESTRATOR_URL = os.environ.get(
    "ENTERPRISE_ORCHESTRATOR_URL", "http://localhost:8020"
)

_topology = _topo_loader.load()
_topology_extensions = _topo_loader.load_extensions()


def _specialist_for_node(node_id: str) -> str | None:
    """Return the process-area name (== specialist name) for a given equipment id."""
    for area in _topology.process_areas:
        instances = _topology.instances_in_area(area.id)
        if any(i.name == node_id for i in instances):
            return area.name
    return None


# ── Reactive alert pub-sub ─────────────────────────────────────────────────────

_alert_subs: list[asyncio.Queue] = []


def broadcast_alert(event: dict) -> int:
    """Returns the number of subscribers the event was delivered to, so
    callers (see reactive_loop.py's _collect_text) can detect and log the
    "reactive mode with no subscriber" case instead of assuming delivery
    just because nothing raised."""
    for q in _alert_subs:
        q.put_nowait(event)
    return len(_alert_subs)


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
    with open(os.path.join(STATIC_DIR, "index.html"), encoding="utf-8") as f:
        html = f.read()
    # Embed the token so the SPA's own fetch calls can present it. While
    # exposed (BIND_HOST off loopback), only echo back a token the request
    # already proved it holds — otherwise loading the bare homepage would
    # hand the secret to anyone who can reach the server.
    if auth.EXPOSED:
        given = auth.presented(request)
        embed_token = given if auth.check(request) else ""
    else:
        embed_token = auth.token()
    html = html.replace(
        "</head>", f'<meta name="api-token" content="{embed_token}">\n</head>'
    )
    return HTMLResponse(html)


async def models_endpoint(request: Request):
    import httpx

    local: list[str] = []
    for p in PROVIDERS:
        if p.get("loop") == "openai":
            try:
                async with httpx.AsyncClient() as http:
                    resp = await http.get(f"{p['base_url']}/api/tags", timeout=3.0)
                    local = [m["name"] for m in resp.json().get("models", [])]
            except Exception:
                pass

    cloud = claude_loop.CLAUDE_MODELS if ANTHROPIC_API_KEY else []
    return JSONResponse({"cloud": cloud, "local": local})


def _port_from_url(url: str, default: int) -> int:
    try:
        return urlparse(url).port or default
    except Exception:
        return default


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

    # Ports read from the same env vars each service actually binds to (see
    # M10 Phase 0) — previously hardcoded to wtp1's defaults, which silently
    # reported wtp1's port status under wtp2's own /api/health.
    results = await asyncio.gather(
        tcp_ok("localhost", _port_from_url(MCP_AGGREGATOR_URL, 8100)),
        tcp_ok("localhost", int(os.environ.get("INFLUXDB_HOST_PORT", 8086))),
        tcp_ok("localhost", int(os.environ.get("MQTT_BROKER_PORT", 1883))),
        tcp_ok("localhost", _port_from_url(SIMULATOR_CONTROL, 8090)),
        tcp_ok("localhost", int(os.environ.get("AUDIT_MCP_PORT", 8004))),
        tcp_ok("localhost", int(os.environ.get("CONTROL_MCP_PORT", 8005))),
        tcp_ok("localhost", int(os.environ.get("MEMORY_MCP_PORT", 8006))),
    )
    keys = (
        "aggregator",
        "influxdb",
        "mqtt",
        "simulator",
        "audit_mcp",
        "control_mcp",
        "memory_mcp",
    )
    health = {k: "ok" if v else "error" for k, v in zip(keys, results)}
    # Distinct from "mqtt" above (a raw TCP port check against mosquitto
    # itself) — this reflects whether the mqtt-mcp *adapter's* explicit
    # connect() call is currently believed to be live, per
    # _connect_mqtt_adapter / _mqtt_health_check_loop.
    health["mqtt_adapter"] = "ok" if _mqtt_adapter_connected else "error"
    return JSONResponse(health)


async def site_endpoint(request: Request):
    """This plant's own identity, for the frontend to seed activeSite/
    activeRegion instead of SiteNav.vue's old hardcoded 'Waterworks' default.
    grafana_port travels the same way — GRAFANA_PORT varies per plant
    (docker-compose host port), and the frontend only knows how the browser
    actually reached this page (window.location.hostname), not this
    process's own env, so the port has to come from here."""
    return JSONResponse(
        {
            "site_id": SITE_ID,
            "site_name": SITE_NAME,
            "region_name": REGION_NAME,
            "grafana_port": GRAFANA_PORT,
        }
    )


async def topology_endpoint(request: Request):
    """This plant's own equipment graph, for stores/topology.ts's
    loadTopology() to fetch instead of hardcoding a copy of topology.yaml's
    shape (INITIAL_NODES/AREA_ORDER) — the actual bug this route exists to
    fix: with a single shared Vite build (chat-ui/static/) serving every
    plant checkout, a genuinely different second plant's browser previously
    rendered whatever plant's equipment/areas happened to be baked into that
    static bundle, silently wrong for anything but the demo's wtp2 fixture
    (which happens to share instance/area names with wtp1). Derived from the
    same `_topology` object as every other route here (see
    `_specialist_for_node`, which this reuses) — nodes are grouped by
    process area (matching `instances_in_area`'s own per-area order) so the
    array arrives pre-sorted the way the frontend's `nodesByArea` grouping
    expects.

    `specialist` is always equal to `area` today (this app's specialists are
    1:1 with process areas — see CLAUDE.md's "Multi-agent architecture"
    table; `historian` is the one specialist with no area/node of its own
    and is correctly absent here) — kept as a separate field rather than
    collapsed into `area` because `_specialist_for_node` and the frontend's
    `TopologyNode.specialist` both already model them as distinct concepts,
    and a framework fork with non-1:1 specialist/area mapping would need
    this to stay a real field, not a derived one.

    Deliberately does NOT include flow-diagram edges: topology.yaml's schema
    (fieldworks.topology.EquipmentInstance / ProcessArea) carries no
    upstream/downstream or connectivity field at all, so there is nothing
    authoritative here to derive them from. See stores/topology.ts's
    INITIAL_EDGES comment for why edges are left as a frontend-only,
    non-authoritative display layout rather than a fabricated heuristic
    (e.g. chaining equipment_instances' declaration order) that could draw
    plausible-looking but wrong connections for a genuinely different plant."""
    areas = [area.name for area in _topology.process_areas]
    nodes = [
        {
            "id": inst.name,
            "area": area.name,
            "specialist": area.name,
            "equipmentType": inst.type_id,
        }
        for area in _topology.process_areas
        for inst in _topology.instances_in_area(area.id)
    ]
    return JSONResponse({"areas": areas, "nodes": nodes})


async def plant_status_endpoint(request: Request):
    """status_heartbeat.py's persisted rollup — a plain DB read, no LLM call,
    for enterprise-level overview questions. See diagnose_plant_mcp's
    get_plant_status tool, which proxies this per plant. Empty object (not
    an error status) if the heartbeat hasn't produced a first reading yet
    (e.g. right after startup, before its first tick) — callers should
    treat that the same as "unknown", not "down"."""
    status = session_store.get_plant_status()
    return JSONResponse(status or {})


async def sites_endpoint(request: Request):
    """Proxy to the enterprise orchestrator's /api/sites (itself a thin read
    of enterprise.yaml — see enterprise/orchestrator/backend.py). Proxied
    rather than fetched directly by the browser so the orchestrator's URL
    stays server-side config, not a second CORS surface. Empty dict (not an
    error status) when the enterprise layer isn't running — SiteNav.vue falls
    back to showing just this plant."""
    import httpx

    try:
        async with httpx.AsyncClient() as http:
            resp = await http.get(
                f"{ENTERPRISE_ORCHESTRATOR_URL}/api/sites", timeout=3.0
            )
            resp.raise_for_status()
            return JSONResponse(resp.json())
    except Exception:
        return JSONResponse({})


async def chat_endpoint(request: Request):
    body = await request.json()
    messages = body.get("messages", [])
    model = body.get("model", claude_loop.CLAUDE_MODELS[0])
    thinking_enabled = bool(body.get("thinking", False))
    mode = body.get("mode", "single")

    if mode == "multi":
        api_key = os.environ.get("ANTHROPIC_API_KEY") or ANTHROPIC_API_KEY
        scope = body.get("scope")  # optional node id — scopes to one specialist

        async def generate_multi():
            try:
                async for chunk in multi_agent_loop.run_multi_agent(
                    messages,
                    model,
                    api_key=api_key,
                    scope_instance_id=scope,
                    include_orchestrator=(scope is None),
                ):
                    yield {"data": chunk}
            except Exception as exc:
                logger.exception("Multi-agent stream error")
                yield {"data": json.dumps({"type": "error", "error": str(exc)})}

        return EventSourceResponse(generate_multi())

    if mode == "enterprise":
        # Cross-plant question (Region/Enterprise breadcrumb level) — proxy to
        # the enterprise orchestrator's own /api/chat rather than answering
        # locally, same rationale as sites_endpoint's proxy: the orchestrator's
        # URL stays server-side config, not a second CORS surface for the
        # browser. See enterprise/orchestrator/enterprise_loop.py for the
        # diagnose_plant fan-out this triggers.
        import httpx

        async def generate_enterprise():
            try:
                async with httpx.AsyncClient(
                    timeout=httpx.Timeout(120.0, connect=5.0)
                ) as http:
                    async with http.stream(
                        "POST",
                        f"{ENTERPRISE_ORCHESTRATOR_URL}/api/chat",
                        json={"messages": messages},
                    ) as resp:
                        async for line in resp.aiter_lines():
                            if line.startswith("data:"):
                                yield {"data": line[len("data:") :].strip()}
            except Exception as exc:
                logger.exception("Enterprise chat proxy error")
                yield {"data": json.dumps({"type": "error", "error": str(exc)})}

        return EventSourceResponse(generate_enterprise())

    provider = _resolve_provider(model)
    run_fn = _LOOP_MODULES[provider["loop"]].run_chat
    api_key = (
        os.environ.get(provider["api_key_env"]) if provider.get("api_key_env") else None
    )

    extra = {}
    if provider["loop"] == "claude" and thinking_enabled:
        extra["thinking_enabled"] = True

    async def generate():
        try:
            async for chunk in run_fn(
                messages,
                model,
                base_url=provider["base_url"],
                api_key=api_key,
                **extra,
            ):
                yield {"data": chunk}
        except Exception as exc:
            logger.exception("Stream error")
            yield {"data": json.dumps({"type": "error", "error": str(exc)})}

    return EventSourceResponse(generate())


@auth.require
async def fault_endpoint(request: Request):
    """Proxy fault injection requests to the simulator control plane."""
    import httpx

    body = await request.json()
    target = body.get("target", "")
    mode = body.get("mode", "normal")
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


async def fault_modes_endpoint(request: Request):
    import httpx

    try:
        async with httpx.AsyncClient() as http:
            resp = await http.get(f"{SIMULATOR_CONTROL}/fault-modes", timeout=5.0)
            return JSONResponse(resp.json())
    except Exception as exc:
        return JSONResponse({"error": str(exc)}, status_code=503)


@auth.require
async def action_respond_endpoint(request: Request):
    """Operator approval/denial for a pending AI-proposed action."""
    body = await request.json()
    action_id = body.get("action_id", "")
    decision = body.get("decision", "")
    if not action_id or decision not in ("approved", "denied"):
        return JSONResponse(
            {"error": "Requires action_id and decision (approved|denied)"},
            status_code=400,
        )
    ok = control.resolve(action_id, decision)
    if not ok:
        return JSONResponse(
            {"error": "Unknown or already-resolved action_id"}, status_code=404
        )
    return JSONResponse({"ok": True, "action_id": action_id, "decision": decision})


@auth.require
async def audit_endpoint(request: Request):
    return JSONResponse(audit.read_log())


@auth.require
async def audit_clear_endpoint(request: Request):
    archive = audit.rotate_log()
    return JSONResponse({"ok": True, "archived": archive})


@auth.require
async def audit_download_endpoint(request: Request):
    from starlette.responses import FileResponse, Response

    if not audit.LOG_PATH.exists():
        return Response(
            content="",
            media_type="application/octet-stream",
            headers={"Content-Disposition": "attachment; filename=audit.jsonl"},
        )
    return FileResponse(
        audit.LOG_PATH,
        media_type="application/octet-stream",
        filename="audit.jsonl",
    )


@auth.require
async def audit_page_endpoint(request: Request):
    # Propagate the token that got us past @auth.require into this page's own
    # links, so "JSON" / "Download JSONL" keep working when EXPOSED.
    token_qs = f"?token={auth.presented(request)}" if auth.EXPOSED else ""

    entries = audit.read_log()

    sessions = []
    current = None
    for e in entries:
        if e.get("event") == "session_start":
            current = {"header": e, "entries": []}
            sessions.append(current)
        elif current is not None:
            current["entries"].append(e)
        else:
            sessions.append({"header": None, "entries": [e]})

    def render_entry(e):
        ts = e.get("ts", "")[:19].replace("T", " ")
        event = e.get("event", "")
        if event == "tool_call":
            args = json.dumps(e.get("args", {}), indent=2)
            return f"""<div class="entry tool-call">
              <span class="ts">{ts}</span>
              <span class="badge tool-badge">tool</span>
              <span class="tool-name">{e.get('tool','')}</span>
              <pre class="args">{args}</pre>
            </div>"""
        elif event == "tool_result":
            result = e.get("result", "")
            err = isinstance(result, str) and result.startswith("Error")
            cls = "error-badge" if err else "result-badge"
            label = "error" if err else "result"
            return f"""<div class="entry tool-result {'err' if err else ''}">
              <span class="ts">{ts}</span>
              <span class="badge {cls}">{label}</span>
              <span class="tool-name">{e.get('tool','')}</span>
              <div class="text">{result}</div>
            </div>"""
        elif event == "response":
            return f"""<div class="entry response">
              <span class="ts">{ts}</span>
              <span class="badge response-badge">response</span>
              <div class="text">{e.get('text','')}</div>
            </div>"""
        elif event == "action_decision":
            decision = e.get("decision", "")
            dcls = (
                "approve-badge"
                if decision == "approved"
                else "deny-badge" if decision == "denied" else "warn-badge"
            )
            return f"""<div class="entry action-event">
              <span class="ts">{ts}</span>
              <span class="badge {dcls}">action {decision}</span>
              <span class="tool-name">{e.get('action_id','')}</span>
            </div>"""
        elif event.startswith("reactive_"):
            parts = []
            if e.get("instance_id"):
                parts.append(f"<strong>{e['instance_id']}</strong>")
            if e.get("attribute"):
                parts.append(e["attribute"])
            if e.get("escalate") is not None:
                parts.append("↑ escalate" if e["escalate"] else "↓ suppress")
            if e.get("severity"):
                parts.append(e["severity"])
            if e.get("reason"):
                parts.append(f"<em>{e['reason'][:80]}</em>")
            detail = " · ".join(parts)
            label = event.replace("reactive_", "").replace("_", " ")
            return f"""<div class="entry reactive-event">
              <span class="ts">{ts}</span>
              <span class="badge reactive-badge">reactive {label}</span>
              {'<span class="tool-name">' + detail + '</span>' if detail else ''}
            </div>"""
        elif event == "error":
            return f"""<div class="entry tool-result err">
              <span class="ts">{ts}</span>
              <span class="badge error-badge">error</span>
              <div class="text">{e.get('error','')}</div>
            </div>"""
        return ""

    def render_session(s, idx):
        h = s["header"]
        inner = "\n".join(render_entry(e) for e in s["entries"])
        tc = sum(1 for e in s["entries"] if e.get("event") == "tool_call")
        rc = sum(1 for e in s["entries"] if e.get("event", "").startswith("reactive_"))
        ac = sum(1 for e in s["entries"] if e.get("event") == "action_decision")
        has_err = any(
            e.get("event") == "error"
            or (
                e.get("event") == "tool_result"
                and isinstance(e.get("result", ""), str)
                and e.get("result", "").startswith("Error")
            )
            for e in s["entries"]
        )
        err_cls = " has-error" if has_err else ""
        if h:
            ts = h.get("ts", "")[:19].replace("T", " ")
            model = h.get("model", "")
            msg = h.get("user_message", "")
            parts = [f"{tc} tool call{'s' if tc != 1 else ''}"]
            if rc:
                parts.append(f"{rc} reactive")
            if ac:
                parts.append(f"{ac} action{'s' if ac != 1 else ''}")
            summary = " · ".join(parts)
            return f"""<div class="session-block{err_cls}">
              <div class="session-header" onclick="toggle({idx})">
                <span class="chevron" id="chev-{idx}">▶</span>
                <span class="ts">{ts}</span>
                <span class="badge session-badge">session</span>
                <span class="model-tag">{model}</span>
                <span class="msg-preview">{msg[:80]}{'…' if len(msg)>80 else ''}</span>
                <span class="tool-count">{summary}</span>
                {'<span class="err-flag">⚠ error</span>' if has_err else ''}
              </div>
              <div class="session-body" id="body-{idx}" style="display:none">
                {inner if inner.strip() else '<p class="no-entries">No subsequent entries.</p>'}
              </div>
            </div>"""
        return f'<div class="session-body">{inner}</div>'

    blocks = "\n".join(render_session(s, i) for i, s in enumerate(sessions))
    body = blocks if sessions else "<p class='empty'>No audit entries yet.</p>"

    html = f"""<!DOCTYPE html>
<html lang="en">
<head>
<meta charset="UTF-8">
<title>Waterworks AI — Audit Log</title>
<style>
  :root {{
    --bg:#f5f5f5;--text:#1a1a1a;--block-bg:#fff;--border:#e0e0e0;
    --hdr-hover:#f9f9f9;--body-border:#f0f0f0;--entry-bg:#fafafa;--entry-border:#ececec;
    --meta:#888;--btn-bg:#fff;--btn-border:#d0d0d0;--btn-color:#555;--btn-hover:#f0f0f0;
    --ts:#aaa;--preview:#333;--count:#999;--text-color:#444;--pre-bg:#f4f4f4;--pre-border:#e8e8e8;
    --session-badge-bg:#e3f2fd;--tool-badge-bg:#fff8e1;--result-badge-bg:#e8f5e9;--response-badge-bg:#f3e5f5;
  }}
  [data-theme="dark"] {{
    --bg:#1a1a1a;--text:#e0e0e0;--block-bg:#242424;--border:#333;
    --hdr-hover:#2a2a2a;--body-border:#2e2e2e;--entry-bg:#1e1e1e;--entry-border:#333;
    --meta:#666;--btn-bg:#2a2a2a;--btn-border:#444;--btn-color:#aaa;--btn-hover:#333;
    --ts:#666;--preview:#ccc;--count:#666;--text-color:#bbb;--pre-bg:#1a1a1a;--pre-border:#333;
    --session-badge-bg:#1e2e42;--tool-badge-bg:#2a2000;--result-badge-bg:#1a2e1a;--response-badge-bg:#2a1a35;
  }}
  body{{font-family:-apple-system,BlinkMacSystemFont,"Segoe UI",sans-serif;font-size:13px;
        background:var(--bg);color:var(--text);margin:0;padding:24px}}
  h1{{font-size:18px;font-weight:600;margin-bottom:6px}}
  .meta{{font-size:12px;color:var(--meta);margin-bottom:20px}}
  .meta a{{color:#2563eb;text-decoration:none}}
  .controls{{margin-bottom:16px;display:flex;gap:10px;align-items:center}}
  .btn{{font-size:12px;padding:5px 12px;border:1px solid var(--btn-border);
        border-radius:6px;background:var(--btn-bg);cursor:pointer;color:var(--btn-color)}}
  .btn:hover{{background:var(--btn-hover)}}
  .session-block{{background:var(--block-bg);border:1px solid var(--border);
                  border-radius:10px;margin-bottom:10px;overflow:hidden}}
  .session-block.has-error{{border-color:#f5c6cb}}
  [data-theme="dark"] .session-block.has-error{{border-color:#5a2020}}
  .session-header{{display:flex;align-items:center;gap:8px;flex-wrap:wrap;
                   padding:10px 14px;cursor:pointer;border-left:4px solid #2563eb;user-select:none}}
  .session-header:hover{{background:var(--hdr-hover)}}
  .session-block.has-error .session-header{{border-left-color:#c62828}}
  .chevron{{font-size:10px;color:var(--ts);transition:transform 0.15s;flex-shrink:0}}
  .chevron.open{{transform:rotate(90deg)}}
  .session-body{{padding:10px 14px 14px;border-top:1px solid var(--body-border)}}
  .entry{{background:var(--entry-bg);border:1px solid var(--entry-border);border-radius:7px;
          padding:8px 12px;margin-bottom:7px;display:flex;flex-wrap:wrap;align-items:flex-start;gap:8px}}
  .entry:last-child{{margin-bottom:0}}
  .entry.tool-call{{border-left:3px solid #f9a825}}
  .entry.tool-result{{border-left:3px solid #2e7d32}}
  .entry.tool-result.err{{border-left-color:#c62828}}
  .entry.response{{border-left:3px solid #6a1b9a}}
  .ts{{font-size:11px;color:var(--ts);white-space:nowrap;padding-top:2px}}
  .badge{{font-size:10px;font-weight:700;text-transform:uppercase;letter-spacing:0.5px;
          padding:2px 7px;border-radius:10px;white-space:nowrap}}
  .session-badge{{background:var(--session-badge-bg);color:#2563eb}}
  .tool-badge{{background:var(--tool-badge-bg);color:#f57f17}}
  .result-badge{{background:var(--result-badge-bg);color:#2e7d32}}
  .error-badge{{background:#ffebee;color:#c62828}}
  .response-badge{{background:var(--response-badge-bg);color:#9c4dcc}}
  .tool-name{{font-weight:600}}
  .model-tag{{font-size:11px;color:var(--ts);font-style:italic}}
  .msg-preview{{flex:1;color:var(--preview);min-width:0;overflow:hidden;text-overflow:ellipsis;white-space:nowrap}}
  .tool-count{{font-size:11px;color:var(--count);white-space:nowrap}}
  .err-flag{{font-size:11px;color:#c62828;font-weight:600}}
  .text{{width:100%;color:var(--text-color);line-height:1.5;margin-top:2px;word-break:break-word;white-space:pre-wrap}}
  pre.args{{width:100%;background:var(--pre-bg);border:1px solid var(--pre-border);
            border-radius:5px;padding:7px 10px;font-size:11.5px;color:var(--text-color);
            margin:4px 0 0;overflow-x:auto;white-space:pre-wrap}}
  .no-entries{{color:var(--ts);font-style:italic;margin:0}}
  .empty{{color:var(--ts);text-align:center;padding:40px}}
  .entry.reactive-event{{border-left:3px solid #0288d1}}
  .entry.action-event{{border-left:3px solid #f57c00}}
  .reactive-badge{{background:#e1f5fe;color:#0277bd}}
  .approve-badge{{background:#e8f5e9;color:#2e7d32}}
  .deny-badge{{background:#ffebee;color:#c62828}}
  .warn-badge{{background:#fff3e0;color:#e65100}}
  [data-theme="dark"] .reactive-badge{{background:#0a2a40;color:#4fc3f7}}
  [data-theme="dark"] .approve-badge{{background:#1a2e1a;color:#66bb6a}}
  [data-theme="dark"] .deny-badge{{background:#2e1a1a;color:#ef5350}}
  body.hide-tools .entry.tool-call,
  body.hide-tools .entry.tool-result{{display:none}}
  body.reactive-only .entry:not(.reactive-event):not(.action-event):not(.response){{display:none}}
  .filter-btn.active{{background:#2563eb!important;color:#fff!important;border-color:#2563eb!important}}
</style>
</head>
<body>
<h1>Waterworks AI — Audit Log</h1>
<div class="meta">{len(entries)} entries &nbsp;&middot;&nbsp; {len(sessions)} sessions &nbsp;|&nbsp;
  <a href="/api/audit{token_qs}">JSON</a> &nbsp;|&nbsp;
  <a href="/api/audit/download{token_qs}">Download JSONL</a>
</div>
<div class="controls">
  <button class="btn" onclick="expandAll()">Expand all</button>
  <button class="btn" onclick="collapseAll()">Collapse all</button>
  <span style="width:1px;background:var(--border);height:20px;display:inline-block;margin:0 4px"></span>
  <button class="btn filter-btn" id="filter-all"      onclick="setFilter('')">All events</button>
  <button class="btn filter-btn" id="filter-hide-tools" onclick="setFilter('hide-tools')">Hide tools</button>
  <button class="btn filter-btn" id="filter-reactive-only" onclick="setFilter('reactive-only')">Reactive only</button>
  <span style="width:1px;background:var(--border);height:20px;display:inline-block;margin:0 4px"></span>
  <button class="btn" id="theme-toggle" onclick="toggleTheme()">🌙 Dark mode</button>
</div>
{body}
<script>
  function toggle(idx) {{
    const body = document.getElementById('body-' + idx);
    const chev = document.getElementById('chev-' + idx);
    const open = body.style.display !== 'none';
    body.style.display = open ? 'none' : 'block';
    chev.classList.toggle('open', !open);
  }}
  function expandAll() {{
    document.querySelectorAll('.session-body').forEach(b => b.style.display = 'block');
    document.querySelectorAll('.chevron').forEach(c => c.classList.add('open'));
  }}
  function collapseAll() {{
    document.querySelectorAll('.session-body').forEach(b => b.style.display = 'none');
    document.querySelectorAll('.chevron').forEach(c => c.classList.remove('open'));
  }}
  function applyTheme(dark) {{
    document.documentElement.setAttribute('data-theme', dark ? 'dark' : 'light');
    document.getElementById('theme-toggle').textContent = dark ? '☀ Light mode' : '🌙 Dark mode';
  }}
  function toggleTheme() {{
    const dark = document.documentElement.getAttribute('data-theme') !== 'dark';
    localStorage.setItem('theme', dark ? 'dark' : 'light');
    applyTheme(dark);
  }}
  applyTheme(localStorage.getItem('theme') === 'dark');
  const _FILTERS = ['hide-tools', 'reactive-only'];
  function setFilter(mode) {{
    _FILTERS.forEach(f => document.body.classList.remove(f));
    if (mode) document.body.classList.add(mode);
    document.querySelectorAll('.filter-btn').forEach(b => b.classList.remove('active'));
    const activeId = mode ? 'filter-' + mode : 'filter-all';
    document.getElementById(activeId)?.classList.add('active');
    localStorage.setItem('audit-filter', mode);
  }}
  setFilter(localStorage.getItem('audit-filter') || '');
</script>
</body>
</html>"""
    return HTMLResponse(html)


async def metrics_page_endpoint(request: Request):
    from starlette.responses import HTMLResponse

    summary = metrics.get_summary()
    turns = metrics.get_recent_turns(100)

    def fmt_tokens(n):
        return "—" if n is None else f"{int(n):,}"

    def fmt_ms(n):
        return "—" if n is None else f"{int(n):,} ms"

    rows_html = ""
    for t in turns:
        ts = (t.get("ts") or "")[:19].replace("T", " ")
        err_cls = " class='row-err'" if t.get("error_count", 0) else ""
        rows_html += f"""<tr{err_cls}>
          <td>{ts}</td>
          <td>{t.get('model','')}</td>
          <td>{fmt_tokens(t.get('input_tokens'))}</td>
          <td>{fmt_tokens(t.get('output_tokens'))}</td>
          <td>{t.get('tool_call_count', 0)}</td>
          <td>{t.get('error_count', 0)}</td>
          <td>{fmt_ms(t.get('latency_ms'))}</td>
          <td style="max-width:300px;overflow:hidden;text-overflow:ellipsis;white-space:nowrap">{(t.get('user_message') or '')[:80]}</td>
        </tr>"""

    s = summary
    html = f"""<!DOCTYPE html>
<html lang="en">
<head>
<meta charset="UTF-8">
<title>Waterworks AI — Metrics</title>
<style>
  :root {{
    --bg:#f5f5f5;--text:#1a1a1a;--meta:#999;--border:#e0e0e0;
    --th-bg:#f9f9f9;--th-color:#666;--row-odd:#ffffff;--row-even:#eef2f5;
    --row-hover:#e0eaf5;--btn-bg:#fff;--btn-border:#d0d0d0;--btn-color:#555;--btn-hover:#f0f0f0;
  }}
  [data-theme="dark"] {{
    --bg:#1a1a1a;--text:#e0e0e0;--meta:#666;--border:#333;
    --th-bg:#242424;--th-color:#888;--row-odd:#1e1e1e;--row-even:#252f38;
    --row-hover:#2a3a45;--btn-bg:#2a2a2a;--btn-border:#444;--btn-color:#aaa;--btn-hover:#333;
  }}
  body{{font-family:-apple-system,BlinkMacSystemFont,"Segoe UI",sans-serif;font-size:13px;
        background:var(--bg);color:var(--text);margin:0;padding:24px}}
  h1{{font-size:18px;font-weight:600;margin-bottom:4px}}
  .meta{{font-size:12px;color:var(--meta);margin-bottom:16px}}
  .meta a{{color:#2563eb;text-decoration:none}}
  .controls{{margin-bottom:20px}}
  .btn{{font-size:12px;padding:5px 12px;border:1px solid var(--btn-border);
        border-radius:6px;background:var(--btn-bg);cursor:pointer;color:var(--btn-color)}}
  .btn:hover{{background:var(--btn-hover)}}
  .cards{{display:flex;gap:12px;flex-wrap:wrap;margin-bottom:24px}}
  .card{{background:#2563eb;border-radius:10px;padding:14px 20px;min-width:120px}}
  .card-label{{font-size:11px;color:rgba(255,255,255,0.75);text-transform:uppercase;letter-spacing:0.5px}}
  .card-value{{font-size:22px;font-weight:700;color:#fff;margin-top:4px}}
  table{{width:100%;border-collapse:collapse;border:1px solid var(--border);border-radius:10px;overflow:hidden}}
  th{{background:var(--th-bg);text-align:left;padding:8px 12px;font-size:11px;color:var(--th-color);
      text-transform:uppercase;letter-spacing:0.4px;border-bottom:1px solid var(--border)}}
  tbody tr:nth-child(odd)  td{{background:var(--row-odd)}}
  tbody tr:nth-child(even) td{{background:var(--row-even)}}
  tbody tr:hover td{{background:var(--row-hover)!important}}
  td{{padding:7px 12px;border-bottom:1px solid var(--border);vertical-align:top}}
  tr:last-child td{{border-bottom:none}}
  tr.row-err td{{color:#c62828}}
  [data-theme="dark"] tr.row-err td{{color:#ef9a9a}}
</style>
</head>
<body>
<h1>Waterworks AI — Metrics</h1>
<div class="meta">Last 100 turns &nbsp;·&nbsp; <a href="/api/metrics">JSON</a> &nbsp;·&nbsp; <a href="/audit">Audit log</a></div>
<div class="controls">
  <button class="btn" id="theme-toggle" onclick="toggleTheme()">🌙 Dark mode</button>
</div>
<div class="cards">
  <div class="card"><div class="card-label">Sessions</div><div class="card-value">{s.get('total_sessions') or 0}</div></div>
  <div class="card"><div class="card-label">Turns</div><div class="card-value">{s.get('total_turns') or 0}</div></div>
  <div class="card"><div class="card-label">Input tokens</div><div class="card-value">{fmt_tokens(s.get('total_input_tokens'))}</div></div>
  <div class="card"><div class="card-label">Output tokens</div><div class="card-value">{fmt_tokens(s.get('total_output_tokens'))}</div></div>
  <div class="card"><div class="card-label">Tool calls</div><div class="card-value">{s.get('total_tool_calls') or 0}</div></div>
  <div class="card"><div class="card-label">Errors</div><div class="card-value">{s.get('total_errors') or 0}</div></div>
  <div class="card"><div class="card-label">Avg latency</div><div class="card-value">{fmt_ms(s.get('avg_latency_ms'))}</div></div>
</div>
<table>
  <thead><tr>
    <th>Time</th><th>Model</th><th>In tokens</th><th>Out tokens</th>
    <th>Tools</th><th>Errors</th><th>Latency</th><th>Message</th>
  </tr></thead>
  <tbody>{rows_html}</tbody>
</table>
<script>
  function applyTheme(dark) {{
    document.documentElement.setAttribute('data-theme', dark ? 'dark' : 'light');
    document.getElementById('theme-toggle').textContent = dark ? '☀ Light mode' : '🌙 Dark mode';
  }}
  function toggleTheme() {{
    const dark = document.documentElement.getAttribute('data-theme') !== 'dark';
    localStorage.setItem('theme', dark ? 'dark' : 'light');
    applyTheme(dark);
  }}
  applyTheme(localStorage.getItem('theme') === 'dark');
</script>
</body>
</html>"""
    return HTMLResponse(html)


async def metrics_api_endpoint(request: Request):
    return JSONResponse(
        {
            "summary": metrics.get_summary(),
            "turns": metrics.get_recent_turns(100),
        }
    )


async def reactive_status_endpoint(request: Request):
    return JSONResponse({"enabled": _reactive_loop.is_running()})


async def reactive_toggle_endpoint(request: Request):
    body = await request.json()
    enable = bool(body.get("enable", False))
    if enable:
        if _reactive_loop.is_running():
            return JSONResponse({"enabled": True, "changed": False})
        monitor = await _ensure_monitor_started()
        _, aggregator_url, model = _reactive_params()
        _reactive_loop.start(monitor, aggregator_url, model, broadcast_alert)
        logger.info("Reactive mode enabled via UI")
        return JSONResponse({"enabled": True, "changed": True})
    else:
        if not _reactive_loop.is_running():
            return JSONResponse({"enabled": False, "changed": False})
        _reactive_loop.stop()
        logger.info("Reactive mode disabled via UI")
        return JSONResponse({"enabled": False, "changed": True})


async def events_endpoint(request: Request):
    """SSE stream for reactive alerts — all three severity tiers."""
    q: asyncio.Queue = asyncio.Queue()
    _alert_subs.append(q)

    async def _gen():
        try:
            while True:
                try:
                    event = await asyncio.wait_for(q.get(), timeout=25.0)
                    yield {"data": json.dumps(event)}
                except asyncio.TimeoutError:
                    yield {"data": json.dumps({"type": "ping"})}
        finally:
            if q in _alert_subs:
                _alert_subs.remove(q)

    return EventSourceResponse(_gen())


_monitor: "_monitor_mod.AnomalyMonitor | None" = None


async def _ensure_monitor_started() -> "_monitor_mod.AnomalyMonitor":
    """The AnomalyMonitor (MQTT threshold tracking, no LLM) runs
    unconditionally from chat-ui boot — independent of REACTIVE_ENABLED,
    which now only gates the escalation consumer (Deadband + Cascade) built
    on top of it. status_heartbeat.py reads its _window directly for a
    free, always-fresh status level; reactive_loop attaches to its
    .events() stream only when toggled on. Idempotent — safe to call from
    both lifespan and the reactive toggle endpoint."""
    global _monitor
    if _monitor is not None:
        return _monitor
    broker_url, aggregator_url, _ = _reactive_params()
    _monitor = _monitor_mod.AnomalyMonitor(
        broker_url=broker_url,
        aggregator_url=aggregator_url,
        min_duration=_reactive_loop.MIN_DURATION,
    )
    await _monitor.start()
    logger.info("Anomaly monitor started (broker=%s)", broker_url)
    return _monitor


def _reactive_params() -> tuple[str, str, str]:
    # MQTT_BROKER_URL is host-only everywhere else in this codebase (simulator.py,
    # bridge.py, monitor.py), paired with a separate MQTT_BROKER_PORT — build the
    # combined "host:port" string AnomalyMonitor expects from those two, rather than
    # relying on a port encoded into MQTT_BROKER_URL itself (nothing else sets it
    # that way, so it silently fell back to the hardcoded 1883 default).
    host = os.environ.get("MQTT_BROKER_URL", "localhost")
    port = os.environ.get("MQTT_BROKER_PORT", "1883")
    broker_url = f"{host}:{port}"
    aggregator_url = os.environ.get("MCP_AGGREGATOR_URL", "http://localhost:8100/sse")
    model = os.environ.get("REACTIVE_MODEL", "claude-haiku-4-5-20251001")
    return broker_url, aggregator_url, model


# Strong references for fire-and-forget background tasks created in this
# module (mirrors reactive_loop.py's _bg_tasks). Without this, asyncio's
# weak reference to a task with nothing else holding it can let CPython's
# GC drop the task mid-execution — here that means the startup mqtt__connect
# (or a later health-check reconnect) can silently stop partway through with
# no error anywhere.
_bg_tasks: set[asyncio.Task] = set()


def _spawn_tracked(coro, *, task_name: str) -> asyncio.Task:
    task = asyncio.create_task(coro, name=task_name)
    _bg_tasks.add(task)

    def _done(t: asyncio.Task) -> None:
        _bg_tasks.discard(t)
        if t.cancelled():
            return
        exc = t.exception()
        if exc is not None:
            logger.error("Background task %s crashed", t.get_name(), exc_info=exc)

    task.add_done_callback(_done)
    return task


# Adapter connection health, surfaced on /api/health as "mqtt_adapter" and
# used to decide when the periodic health-check loop should retry connect.
_mqtt_adapter_connected = False

_MQTT_HEALTH_CHECK_INTERVAL = int(os.environ.get("MQTT_HEALTH_CHECK_INTERVAL", "60"))


async def _connect_mqtt_adapter() -> None:
    """The fieldworks-adapters mqtt-mcp binary (unlike the old Python one) doesn't
    auto-connect at startup — connect is an explicit MCP tool call. Specialists
    call mqtt__* tools assuming a live connection, so establish one here, once,
    before serving any requests. Bounded retry absorbs the aggregator/mosquitto
    startup-ordering race in start.sh (no health-check gating between services).

    Also called from _mqtt_health_check_loop to re-establish the connection
    if it's later found unhealthy (e.g. mosquitto restarted — docker-compose
    restarts it on failure — after this ran once at boot)."""
    global _mqtt_adapter_connected
    host = os.environ.get("MQTT_BROKER_URL", "localhost")
    port = int(os.environ.get("MQTT_BROKER_PORT", "1883"))
    for attempt in range(1, 6):
        result = await mcp_client.call_mcp_tool(
            "mqtt__connect",
            {"host": host, "port": port},
            MCP_AGGREGATOR_URL,
        )
        # mcp_client.call_mcp_tool normalizes both a client-side exception and
        # a tool-level isError result to a string starting with "Error" — a
        # narrower "Error calling" check here previously missed a tool-level
        # failure from the Rust adapter (e.g. "Error: connection refused"),
        # which doesn't share that exact literal prefix, and logged it as a
        # startup success.
        if not result.startswith("Error"):
            logger.info("mqtt__connect succeeded (attempt %d): %s", attempt, result)
            _mqtt_adapter_connected = True
            return
        logger.warning("mqtt__connect attempt %d/5 failed: %s", attempt, result)
        await asyncio.sleep(2)
    _mqtt_adapter_connected = False
    logger.error(
        "mqtt__connect failed after 5 attempts — mqtt__* tools will error until reconnected"
    )


async def _mqtt_health_check_loop() -> None:
    """Periodic liveness check for the mqtt-mcp adapter connection.
    _connect_mqtt_adapter above only runs once at boot; if mosquitto (or the
    aggregator) restarts later, mqtt__* tools stay broken silently until this
    loop notices via a lightweight mqtt__scan call and retries connect —
    previously the only fix was manually restarting chat-ui itself, with the
    original startup log still claiming success."""
    global _mqtt_adapter_connected
    while True:
        await asyncio.sleep(_MQTT_HEALTH_CHECK_INTERVAL)
        try:
            result = await mcp_client.call_mcp_tool(
                "mqtt__scan", {}, MCP_AGGREGATOR_URL
            )
            if result.startswith("Error"):
                logger.warning(
                    "mqtt health check: mqtt__scan failed (%s) — reconnecting", result
                )
                _mqtt_adapter_connected = False
                await _connect_mqtt_adapter()
            else:
                _mqtt_adapter_connected = True
        except Exception:
            logger.exception("mqtt health check loop iteration failed")


@asynccontextmanager
async def lifespan(app):
    if auth.EXPOSED:
        logger.warning(
            "BIND_HOST=%s — bound off loopback. The approval endpoint, audit "
            "log, and topology-commit endpoint now require the "
            "WATERWORKS_API_TOKEN token (header 'Authorization: Bearer "
            "<token>' or '?token=' query param). Token%s: %s",
            auth.BIND_HOST,
            (
                " (generated — set WATERWORKS_API_TOKEN to pin it)"
                if auth.GENERATED
                else ""
            ),
            auth.token(),
        )
    else:
        logger.info(
            "Bound to loopback (%s) — mutating/audit routes are not "
            "token-gated. Set BIND_HOST to reach this from another device.",
            auth.BIND_HOST,
        )

    recovered = session_store.recover_abandoned_actions()
    if recovered:
        logger.warning(
            "Recovered %d action_events row(s) left pending by a previous "
            "process — marked abandoned_restart (the operator answer they "
            "were awaiting can no longer arrive).",
            recovered,
        )

    _spawn_tracked(_connect_mqtt_adapter(), task_name="connect_mqtt_adapter")
    _spawn_tracked(_mqtt_health_check_loop(), task_name="mqtt_health_check_loop")

    monitor = await _ensure_monitor_started()

    if os.environ.get("REACTIVE_ENABLED", "0") == "1":
        _, aggregator_url, model = _reactive_params()
        _reactive_loop.start(monitor, aggregator_url, model, broadcast_alert)
        logger.info("Reactive mode auto-started")

    if os.environ.get("STATUS_HEARTBEAT_ENABLED", "1") == "1":
        status_heartbeat.start(monitor)

    yield


async def insight_categories_endpoint(request: Request):
    categories = _topology_extensions.get("insight_categories", [])
    result = [
        {
            "id": c["id"],
            "label": c["label"],
            "target": c["target"],
            "requires_review": c.get("requires_review", False),
            "correlates_to": c.get("correlates_to", []),
        }
        for c in categories
    ]
    return JSONResponse(result)


async def insight_save_endpoint(request: Request):
    body = await request.json()
    node_id = body.get("nodeId", "")
    category_id = body.get("categoryId", "")
    note = body.get("note", "")

    if not node_id or not category_id:
        return JSONResponse(
            {"error": "nodeId and categoryId required"}, status_code=400
        )

    categories = {
        c["id"]: c for c in _topology_extensions.get("insight_categories", [])
    }
    cat = categories.get(category_id)
    if not cat:
        return JSONResponse(
            {"error": f"Unknown category '{category_id}'"}, status_code=400
        )

    target = cat["target"]
    requires_review = cat.get("requires_review", False)

    if target in ("graph_observation", "specialist_memory"):
        specialist = _specialist_for_node(node_id)
        session_id = str(uuid.uuid4())

    if requires_review:
        now = datetime.now(timezone.utc).isoformat()
        review_id = str(uuid.uuid4())
        conn = sqlite3.connect(_METRICS_DB)
        conn.execute(
            """INSERT INTO insight_reviews
               (id, node_id, category_id, category_label, target, note, created_at)
               VALUES (?, ?, ?, ?, ?, ?, ?)""",
            (review_id, node_id, category_id, cat["label"], target, note or None, now),
        )
        conn.commit()
        conn.close()
        return JSONResponse({"status": "queued", "review_id": review_id})

    if target == "graph_observation":
        await mcp_client.call_mcp_tool(
            "memory__record_observation",
            {
                "session_id": session_id,
                "equipment_id": node_id,
                "text": note or f"Operator insight: {cat['label']}",
                "confidence": 1.0,
                "specialist": specialist or "operator",
            },
        )
    elif target == "specialist_memory":
        await mcp_client.call_mcp_tool(
            "memory__append_specialist_memory",
            {
                "specialist": specialist or node_id,
                "content": note or f"Operator insight ({cat['label']}) on {node_id}",
            },
        )
    else:
        audit.log(
            "insight_saved",
            node_id=node_id,
            category_id=category_id,
            category_label=cat["label"],
            target=target,
            note=note or None,
        )

    return JSONResponse({"status": "ok"})


@auth.require
async def topology_commit_endpoint(request: Request):
    body = await request.json()
    facility_id = body.get("facility_id", "WTP_001")
    facility_name = body.get("facility_name", "Water Treatment Plant")
    instances = body.get("instances", [])
    if not instances:
        return JSONResponse({"error": "no instances provided"}, status_code=400)
    result_str = await mcp_client.call_mcp_tool(
        "memory__seed_discovered_topology",
        {
            "facility_id": facility_id,
            "facility_name": facility_name,
            "instances": instances,
        },
    )
    try:
        result = json.loads(result_str)
    except Exception:
        result = {"seeded_count": 0, "errors": 1}
    return JSONResponse(
        {
            "committed_count": result.get("seeded_count", 0),
            "errors": result.get("errors", 0),
        }
    )


routes = [
    Route("/", index),
    Route("/api/models", models_endpoint),
    Route("/api/health", health_endpoint),
    Route("/api/site", site_endpoint),
    Route("/api/topology", topology_endpoint),
    Route("/api/plant-status", plant_status_endpoint),
    Route("/api/sites", sites_endpoint),
    Route("/api/chat", chat_endpoint, methods=["POST"]),
    Route("/api/action/respond", action_respond_endpoint, methods=["POST"]),
    Route("/api/fault", fault_endpoint, methods=["POST"]),
    Route("/api/fault/status", fault_status_endpoint),
    Route("/api/fault/modes", fault_modes_endpoint),
    Route("/api/audit", audit_endpoint),
    Route("/api/audit/clear", audit_clear_endpoint, methods=["POST"]),
    Route("/api/audit/download", audit_download_endpoint),
    Route("/api/metrics", metrics_api_endpoint),
    Route("/api/topology/commit", topology_commit_endpoint, methods=["POST"]),
    Route("/api/insight/categories", insight_categories_endpoint),
    Route("/api/insight", insight_save_endpoint, methods=["POST"]),
    Route("/api/reactive", reactive_status_endpoint),
    Route("/api/reactive/toggle", reactive_toggle_endpoint, methods=["POST"]),
    Route("/api/events", events_endpoint),
    Route("/audit", audit_page_endpoint),
    Route("/metrics", metrics_page_endpoint),
    Mount("/static", StaticFiles(directory=STATIC_DIR), name="static"),
]

app = Starlette(routes=routes, lifespan=lifespan)

if __name__ == "__main__":
    uvicorn.run(
        app,
        host=auth.BIND_HOST,
        port=int(os.environ.get("CHAT_UI_PORT", 8080)),
        log_level="info",
    )
