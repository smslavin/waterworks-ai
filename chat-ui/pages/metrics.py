"""The metrics page (/metrics): totals and the last 100 turns."""

from __future__ import annotations

from pages import asset, esc


def _tokens(n) -> str:
    return "—" if n is None else f"{int(n):,}"


def _ms(n) -> str:
    return "—" if n is None else f"{int(n):,} ms"


def _row(t: dict) -> str:
    ts = esc((t.get("ts") or "")[:19].replace("T", " "))
    err = " class='row-err'" if t.get("error_count", 0) else ""
    return f"""<tr{err}>
  <td>{ts}</td>
  <td>{esc(t.get('model'))}</td>
  <td>{_tokens(t.get('input_tokens'))}</td>
  <td>{_tokens(t.get('output_tokens'))}</td>
  <td>{esc(t.get('tool_call_count', 0))}</td>
  <td>{esc(t.get('error_count', 0))}</td>
  <td>{_ms(t.get('latency_ms'))}</td>
  <td style="max-width:300px;overflow:hidden;text-overflow:ellipsis;white-space:nowrap">{esc((t.get('user_message') or '')[:80])}</td>
</tr>"""


def _card(label: str, value) -> str:
    return (
        f'<div class="card"><div class="card-label">{label}</div>'
        f'<div class="card-value">{esc(value)}</div></div>'
    )


def render(summary: dict, turns: list[dict]) -> str:
    s = summary
    cards = "\n".join(
        [
            _card("Sessions", s.get("total_sessions") or 0),
            _card("Turns", s.get("total_turns") or 0),
            _card("Input tokens", _tokens(s.get("total_input_tokens"))),
            _card("Output tokens", _tokens(s.get("total_output_tokens"))),
            _card("Tool calls", s.get("total_tool_calls") or 0),
            _card("Errors", s.get("total_errors") or 0),
            _card("Avg latency", _ms(s.get("avg_latency_ms"))),
        ]
    )
    rows = "".join(_row(t) for t in turns)
    return f"""<!DOCTYPE html>
<html lang="en">
<head>
<meta charset="UTF-8">
<title>Waterworks AI — Metrics</title>
<style>
{asset('metrics.css')}</style>
</head>
<body>
<h1>Waterworks AI — Metrics</h1>
<div class="meta">Last 100 turns &nbsp;·&nbsp; <a href="/api/metrics">JSON</a> &nbsp;·&nbsp; <a href="/audit">Audit log</a></div>
<div class="controls">
  <button class="btn" id="theme-toggle" onclick="toggleTheme()">🌙 Dark mode</button>
</div>
<div class="cards">
{cards}
</div>
<table>
  <thead><tr>
    <th>Time</th><th>Model</th><th>In tokens</th><th>Out tokens</th>
    <th>Tools</th><th>Errors</th><th>Latency</th><th>Message</th>
  </tr></thead>
  <tbody>{rows}</tbody>
</table>
<script>
{asset('theme.js')}</script>
</body>
</html>"""
