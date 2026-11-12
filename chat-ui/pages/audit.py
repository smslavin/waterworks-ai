"""The audit log page (/audit): sessions with their tool calls, results,
responses, operator decisions and reactive events, newest log entries last."""

from __future__ import annotations

import json
from urllib.parse import quote

from pages import asset, esc


def _group_sessions(entries: list[dict]) -> list[dict]:
    sessions: list[dict] = []
    current = None
    for e in entries:
        if e.get("event") == "session_start":
            current = {"header": e, "entries": []}
            sessions.append(current)
        elif current is not None:
            current["entries"].append(e)
        else:
            sessions.append({"header": None, "entries": [e]})
    return sessions


def _ts(e: dict) -> str:
    return esc(e.get("ts", "")[:19].replace("T", " "))


def _is_error_result(e: dict) -> bool:
    result = e.get("result", "")
    return isinstance(result, str) and result.startswith("Error")


def _entry(e: dict) -> str:
    ts, event = _ts(e), e.get("event", "")
    if event == "tool_call":
        args = esc(json.dumps(e.get("args", {}), indent=2))
        return f"""<div class="entry tool-call">
  <span class="ts">{ts}</span>
  <span class="badge tool-badge">tool</span>
  <span class="tool-name">{esc(e.get('tool'))}</span>
  <pre class="args">{args}</pre>
</div>"""
    if event == "tool_result":
        err = _is_error_result(e)
        badge, label = ("error-badge", "error") if err else ("result-badge", "result")
        return f"""<div class="entry tool-result {'err' if err else ''}">
  <span class="ts">{ts}</span>
  <span class="badge {badge}">{label}</span>
  <span class="tool-name">{esc(e.get('tool'))}</span>
  <div class="text">{esc(e.get('result'))}</div>
</div>"""
    if event == "response":
        return f"""<div class="entry response">
  <span class="ts">{ts}</span>
  <span class="badge response-badge">response</span>
  <div class="text">{esc(e.get('text'))}</div>
</div>"""
    if event == "action_decision":
        decision = e.get("decision", "")
        badge = {"approved": "approve-badge", "denied": "deny-badge"}.get(
            decision, "warn-badge"
        )
        return f"""<div class="entry action-event">
  <span class="ts">{ts}</span>
  <span class="badge {badge}">action {esc(decision)}</span>
  <span class="tool-name">{esc(e.get('action_id'))}</span>
</div>"""
    if event.startswith("reactive_"):
        parts = []
        if e.get("instance_id"):
            parts.append(f"<strong>{esc(e['instance_id'])}</strong>")
        if e.get("attribute"):
            parts.append(esc(e["attribute"]))
        if e.get("escalate") is not None:
            parts.append("↑ escalate" if e["escalate"] else "↓ suppress")
        if e.get("severity"):
            parts.append(esc(e["severity"]))
        if e.get("reason"):
            parts.append(f"<em>{esc(e['reason'][:80])}</em>")
        detail = " · ".join(parts)
        label = esc(event.replace("reactive_", "").replace("_", " "))
        detail_html = f'<span class="tool-name">{detail}</span>' if detail else ""
        return f"""<div class="entry reactive-event">
  <span class="ts">{ts}</span>
  <span class="badge reactive-badge">reactive {label}</span>
  {detail_html}
</div>"""
    if event == "error":
        return f"""<div class="entry tool-result err">
  <span class="ts">{ts}</span>
  <span class="badge error-badge">error</span>
  <div class="text">{esc(e.get('error'))}</div>
</div>"""
    return ""


def _session(s: dict, idx: int) -> str:
    entries = s["entries"]
    inner = "\n".join(_entry(e) for e in entries)
    header = s["header"]
    if not header:
        return f'<div class="session-body">{inner}</div>'

    tools = sum(1 for e in entries if e.get("event") == "tool_call")
    reactive = sum(1 for e in entries if e.get("event", "").startswith("reactive_"))
    actions = sum(1 for e in entries if e.get("event") == "action_decision")
    has_err = any(
        e.get("event") == "error"
        or (e.get("event") == "tool_result" and _is_error_result(e))
        for e in entries
    )
    parts = [f"{tools} tool call{'s' if tools != 1 else ''}"]
    if reactive:
        parts.append(f"{reactive} reactive")
    if actions:
        parts.append(f"{actions} action{'s' if actions != 1 else ''}")
    msg = header.get("user_message", "") or ""
    preview = esc(msg[:80]) + ("…" if len(msg) > 80 else "")
    body = (
        inner if inner.strip() else '<p class="no-entries">No subsequent entries.</p>'
    )
    return f"""<div class="session-block{' has-error' if has_err else ''}">
  <div class="session-header" onclick="toggle({idx})">
    <span class="chevron" id="chev-{idx}">▶</span>
    <span class="ts">{_ts(header)}</span>
    <span class="badge session-badge">session</span>
    <span class="model-tag">{esc(header.get('model'))}</span>
    <span class="msg-preview">{preview}</span>
    <span class="tool-count">{' · '.join(parts)}</span>
    {'<span class="err-flag">⚠ error</span>' if has_err else ''}
  </div>
  <div class="session-body" id="body-{idx}" style="display:none">
    {body}
  </div>
</div>"""


def render(entries: list[dict], token: str | None = None) -> str:
    """The page for these audit entries. `token`, when the app is exposed,
    is carried into the page's own JSON/JSONL links."""
    sessions = _group_sessions(entries)
    blocks = "\n".join(_session(s, i) for i, s in enumerate(sessions))
    body = blocks if sessions else "<p class='empty'>No audit entries yet.</p>"
    token_qs = esc(f"?token={quote(token, safe='')}") if token else ""
    return f"""<!DOCTYPE html>
<html lang="en">
<head>
<meta charset="UTF-8">
<title>Waterworks AI — Audit Log</title>
<style>
{asset('audit.css')}</style>
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
  <button class="btn filter-btn" id="filter-all" onclick="setFilter('')">All events</button>
  <button class="btn filter-btn" id="filter-hide-tools" onclick="setFilter('hide-tools')">Hide tools</button>
  <button class="btn filter-btn" id="filter-reactive-only" onclick="setFilter('reactive-only')">Reactive only</button>
  <span style="width:1px;background:var(--border);height:20px;display:inline-block;margin:0 4px"></span>
  <button class="btn" id="theme-toggle" onclick="toggleTheme()">🌙 Dark mode</button>
</div>
{body}
<script>
{asset('audit.js')}{asset('theme.js')}</script>
</body>
</html>"""
