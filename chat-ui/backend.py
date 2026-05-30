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
import control
import metrics
import multi_agent_loop
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
        tcp_ok("localhost", 8004),  # audit-mcp
        tcp_ok("localhost", 8005),  # control-mcp
    )
    keys = ("aggregator", "influxdb", "mqtt", "simulator", "audit_mcp", "control_mcp")
    return JSONResponse({k: "ok" if v else "error" for k, v in zip(keys, results)})


async def chat_endpoint(request: Request):
    body             = await request.json()
    messages         = body.get("messages", [])
    model            = body.get("model", claude_loop.CLAUDE_MODELS[0])
    thinking_enabled = bool(body.get("thinking", False))
    mode             = body.get("mode", "single")

    if mode == "multi":
        api_key = os.environ.get("ANTHROPIC_API_KEY") or ANTHROPIC_API_KEY

        async def generate_multi():
            try:
                async for chunk in multi_agent_loop.run_multi_agent(
                    messages, model, api_key=api_key
                ):
                    yield {"data": chunk}
            except Exception as exc:
                logger.exception("Multi-agent stream error")
                yield {"data": json.dumps({"type": "error", "error": str(exc)})}

        return EventSourceResponse(generate_multi())

    provider = _resolve_provider(model)
    run_fn   = _LOOP_MODULES[provider["loop"]].run_chat
    api_key  = os.environ.get(provider["api_key_env"]) if provider.get("api_key_env") else None

    extra = {}
    if provider["loop"] == "claude" and thinking_enabled:
        extra["thinking_enabled"] = True

    async def generate():
        try:
            async for chunk in run_fn(
                messages, model,
                base_url=provider["base_url"],
                api_key=api_key,
                **extra,
            ):
                yield {"data": chunk}
        except Exception as exc:
            logger.exception("Stream error")
            yield {"data": json.dumps({"type": "error", "error": str(exc)})}

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


async def fault_modes_endpoint(request: Request):
    import httpx
    try:
        async with httpx.AsyncClient() as http:
            resp = await http.get(f"{SIMULATOR_CONTROL}/fault-modes", timeout=5.0)
            return JSONResponse(resp.json())
    except Exception as exc:
        return JSONResponse({"error": str(exc)}, status_code=503)


async def action_respond_endpoint(request: Request):
    """Operator approval/denial for a pending AI-proposed action."""
    body      = await request.json()
    action_id = body.get("action_id", "")
    decision  = body.get("decision", "")
    if not action_id or decision not in ("approved", "denied"):
        return JSONResponse({"error": "Requires action_id and decision (approved|denied)"}, status_code=400)
    ok = control.resolve(action_id, decision)
    if not ok:
        return JSONResponse({"error": "Unknown or already-resolved action_id"}, status_code=404)
    return JSONResponse({"ok": True, "action_id": action_id, "decision": decision})


async def audit_endpoint(request: Request):
    return JSONResponse(audit.read_log())


async def audit_clear_endpoint(request: Request):
    audit.clear_log()
    return JSONResponse({"ok": True})


async def audit_download_endpoint(request: Request):
    from starlette.responses import Response
    entries = audit.read_log()
    lines   = "\n".join(json.dumps(e) for e in entries)
    return Response(
        content=lines,
        media_type="application/jsonl",
        headers={"Content-Disposition": "attachment; filename=audit.jsonl"},
    )


async def audit_page_endpoint(request: Request):
    from starlette.responses import HTMLResponse
    entries = audit.read_log()

    sessions = []
    current  = None
    for e in entries:
        if e.get("event") == "session_start":
            current = {"header": e, "entries": []}
            sessions.append(current)
        elif current is not None:
            current["entries"].append(e)
        else:
            sessions.append({"header": None, "entries": [e]})

    def render_entry(e):
        ts    = e.get("ts", "")[:19].replace("T", " ")
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
            err    = isinstance(result, str) and result.startswith("Error")
            cls    = "error-badge" if err else "result-badge"
            label  = "error" if err else "result"
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
        elif event == "error":
            return f"""<div class="entry tool-result err">
              <span class="ts">{ts}</span>
              <span class="badge error-badge">error</span>
              <div class="text">{e.get('error','')}</div>
            </div>"""
        return ""

    def render_session(s, idx):
        h      = s["header"]
        inner  = "\n".join(render_entry(e) for e in s["entries"])
        tc     = sum(1 for e in s["entries"] if e.get("event") == "tool_call")
        has_err = any(e.get("event") == "error" or
                      (e.get("event") == "tool_result" and
                       isinstance(e.get("result",""), str) and
                       e.get("result","").startswith("Error"))
                      for e in s["entries"])
        err_cls = " has-error" if has_err else ""
        if h:
            ts      = h.get("ts", "")[:19].replace("T", " ")
            model   = h.get("model", "")
            msg     = h.get("user_message", "")
            summary = f"{tc} tool call{'s' if tc != 1 else ''}"
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
    body   = blocks if sessions else "<p class='empty'>No audit entries yet.</p>"

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
</style>
</head>
<body>
<h1>Waterworks AI — Audit Log</h1>
<div class="meta">{len(entries)} entries &nbsp;&middot;&nbsp; {len(sessions)} sessions &nbsp;|&nbsp;
  <a href="/api/audit">JSON</a> &nbsp;|&nbsp;
  <a href="/api/audit/download">Download JSONL</a>
</div>
<div class="controls">
  <button class="btn" onclick="expandAll()">Expand all</button>
  <button class="btn" onclick="collapseAll()">Collapse all</button>
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
</script>
</body>
</html>"""
    return HTMLResponse(html)


async def metrics_page_endpoint(request: Request):
    from starlette.responses import HTMLResponse
    summary = metrics.get_summary()
    turns   = metrics.get_recent_turns(100)

    def fmt_tokens(n):
        return "—" if n is None else f"{int(n):,}"

    def fmt_ms(n):
        return "—" if n is None else f"{int(n):,} ms"

    rows_html = ""
    for t in turns:
        ts      = (t.get("ts") or "")[:19].replace("T", " ")
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

    s   = summary
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
    return JSONResponse({
        "summary": metrics.get_summary(),
        "turns":   metrics.get_recent_turns(100),
    })


routes = [
    Route("/",                    index),
    Route("/api/models",          models_endpoint),
    Route("/api/health",          health_endpoint),
    Route("/api/chat",            chat_endpoint,         methods=["POST"]),
    Route("/api/action/respond",   action_respond_endpoint, methods=["POST"]),
    Route("/api/fault",           fault_endpoint,        methods=["POST"]),
    Route("/api/fault/status",    fault_status_endpoint),
    Route("/api/fault/modes",     fault_modes_endpoint),
    Route("/api/audit",           audit_endpoint),
    Route("/api/audit/clear",     audit_clear_endpoint,  methods=["POST"]),
    Route("/api/audit/download",  audit_download_endpoint),
    Route("/api/metrics",         metrics_api_endpoint),
    Route("/audit",               audit_page_endpoint),
    Route("/metrics",             metrics_page_endpoint),
    Mount("/static", StaticFiles(directory=STATIC_DIR), name="static"),
]

app = Starlette(routes=routes)

if __name__ == "__main__":
    uvicorn.run(app, host="0.0.0.0", port=8080, log_level="info")
