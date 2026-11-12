"""Waterworks-AI chat UI — Starlette backend."""

import asyncio
import json
import logging
import os
import sys
from pathlib import Path
from urllib.parse import urlparse

sys.path.append(str(Path(__file__).resolve().parents[1]))  # repo root
from service_logging import setup_logging  # noqa: E402

# stdout, not stderr: the Windows service wrapper captures them separately.
setup_logging(__file__, "chat_ui", console=sys.stdout)
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
import insights
import multi_agent_loop
import pages.audit
import pages.metrics
import openai_loop
import reactive_loop as _reactive_loop
import session_store
import verdict
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
                async for chunk in verdict.annotate(
                    multi_agent_loop.run_multi_agent(
                        messages,
                        model,
                        api_key=api_key,
                        scope_instance_id=scope,
                        include_orchestrator=(scope is None),
                    )
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

        async def enterprise_events():
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
                            yield line[len("data:") :].strip()

        async def generate_enterprise():
            try:
                async for chunk in verdict.annotate(enterprise_events()):
                    yield {"data": chunk}
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
            async for chunk in verdict.annotate(
                run_fn(
                    messages,
                    model,
                    base_url=provider["base_url"],
                    api_key=api_key,
                    **extra,
                )
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
    # Carry the token that got us past @auth.require into the page's own
    # links, so "JSON" / "Download JSONL" keep working when EXPOSED.
    token = auth.presented(request) if auth.EXPOSED else None
    return HTMLResponse(pages.audit.render(audit.read_log(), token))


async def metrics_page_endpoint(request: Request):
    return HTMLResponse(
        pages.metrics.render(metrics.get_summary(), metrics.get_recent_turns(100))
    )


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
    both lifespan and the reactive toggle endpoint.

    monitor.start() no longer awaits _populate_severities itself (its ~24
    distinct LadybugDB lookups after dedup) — that's spawned here as a
    tracked background task instead, via the same _spawn_tracked/_bg_tasks
    pattern used for _connect_mqtt_adapter below, so a slow or unreachable
    memory-mcp can no longer stall chat-ui's own startup (lifespan used to
    await this directly, ahead of the MQTT connect). Every attribute uses
    _DEFAULT_SEVERITY until the background fetch completes — the same
    fallback already used per-lookup on failure."""
    global _monitor
    if _monitor is not None:
        return _monitor
    broker_url, aggregator_url, _ = _reactive_params()
    _monitor = _monitor_mod.AnomalyMonitor(
        broker_url=broker_url,
        aggregator_url=aggregator_url,
        min_duration=_reactive_loop.MIN_DURATION,
    )
    _spawn_tracked(
        _monitor_mod._populate_severities(aggregator_url),
        task_name="populate_severities",
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
        # a tool-level is_error result to a string starting with "Error" — a
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

    try:
        result = await insights.save(
            node_id=node_id,
            category=cat,
            note=note,
            specialist=_specialist_for_node(node_id),
            call_tool=mcp_client.call_mcp_tool,
            db_path=_METRICS_DB,
        )
    except insights.SaveFailed as exc:
        logger.error("insight for %s not saved: %s", node_id, exc)
        return JSONResponse(
            {"error": "insight not saved", "detail": str(exc)[:500]}, status_code=502
        )
    return JSONResponse(result)


_INSTANCE_STR_FIELDS = ("ladybug_type_id", "area_id", "confidence_level")


def _instance_problems(instances) -> list[str]:
    """What's wrong with a topology commit's instances, or [] if nothing.

    Mirrors what fieldworks' GraphClient.seed_discovered_topology reads:
    a required instance_id, three optional strings, and attributes as
    {name: {"tag": str, ...}}. Checked before dispatch so a malformed
    request is refused whole instead of half-seeding the graph.
    """
    if not isinstance(instances, list) or not instances:
        return ["instances must be a non-empty list"]
    problems = []
    for i, inst in enumerate(instances):
        where = f"instances[{i}]"
        if not isinstance(inst, dict):
            problems.append(f"{where} must be an object")
            continue
        if not isinstance(inst.get("instance_id"), str) or not inst["instance_id"]:
            problems.append(f"{where}.instance_id must be a non-empty string")
        for key in _INSTANCE_STR_FIELDS:
            if key in inst and not isinstance(inst[key], str):
                problems.append(f"{where}.{key} must be a string")
        attributes = inst.get("attributes", {})
        if not isinstance(attributes, dict):
            problems.append(f"{where}.attributes must be an object")
            continue
        for name, info in attributes.items():
            if not isinstance(info, dict) or not isinstance(info.get("tag"), str):
                problems.append(f"{where}.attributes.{name}.tag must be a string")
    return problems


@auth.require
async def topology_commit_endpoint(request: Request):
    try:
        body = await request.json()
    except ValueError:
        return JSONResponse({"error": "body must be JSON"}, status_code=400)
    if not isinstance(body, dict):
        return JSONResponse({"error": "body must be a JSON object"}, status_code=400)
    instances = body.get("instances")
    problems = _instance_problems(instances)
    if problems:
        return JSONResponse(
            {"error": "invalid instances", "problems": problems}, status_code=400
        )
    result_str = await mcp_client.call_mcp_tool(
        "memory__seed_discovered_topology",
        {
            "facility_id": body.get("facility_id", "WTP_001"),
            "facility_name": body.get("facility_name", "Water Treatment Plant"),
            "instances": instances,
        },
    )
    try:
        result = json.loads(result_str)
        committed, errors = int(result["seeded_count"]), int(result["errors"])
    except (ValueError, TypeError, KeyError):
        # The seed may have written some instances before failing, or the
        # call may never have reached memory-mcp; either way the count is
        # unknown, and reporting 0 would claim nothing was written.
        logger.error("topology commit: unreadable seed result: %s", result_str[:500])
        return JSONResponse(
            {
                "status": "unknown",
                "committed_count": None,
                "errors": None,
                "detail": result_str[:500],
            },
            status_code=502,
        )
    return JSONResponse(
        {
            "status": "ok" if errors == 0 else "partial",
            "committed_count": committed,
            "errors": errors,
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
