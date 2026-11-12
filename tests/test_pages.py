"""The /audit and /metrics pages (gh-29): moved out of backend.py, and every
interpolated value escaped.

The old pages put tool results (MQTT and InfluxDB data among them), model
responses and user messages into the HTML raw, so markup in any of them ran
in the operator's browser on /audit.
"""

import pages.audit
import pages.metrics

XSS = '<img src=x onerror="alert(1)">'
ESCAPED = "&lt;img src=x onerror=&quot;alert(1)&quot;&gt;"


def _entries(value):
    return [
        {
            "event": "session_start",
            "ts": "2026-11-11T10:00:00",
            "model": value,
            "user_message": value,
        },
        {
            "event": "tool_call",
            "ts": "2026-11-11T10:00:01",
            "tool": value,
            "args": {"q": value},
        },
        {
            "event": "tool_result",
            "ts": "2026-11-11T10:00:02",
            "tool": "mqtt__scan",
            "result": value,
        },
        {"event": "response", "ts": "2026-11-11T10:00:03", "text": value},
        {
            "event": "action_decision",
            "ts": "2026-11-11T10:00:04",
            "action_id": value,
            "decision": value,
        },
        {
            "event": "reactive_escalation",
            "ts": "2026-11-11T10:00:05",
            "instance_id": value,
            "attribute": value,
            "severity": value,
            "reason": value,
        },
        {"event": "error", "ts": "2026-11-11T10:00:06", "error": value},
    ]


def test_audit_page_escapes_every_logged_value():
    page = pages.audit.render(_entries(XSS))
    assert XSS not in page
    assert page.count(ESCAPED) >= 10


def test_audit_page_escapes_the_token_in_its_links():
    page = pages.audit.render([], token='abc"><script>x</script>')
    assert "<script>x</script>" not in page
    assert 'href="/api/audit?token=abc%22%3E%3Cscript%3Ex%3C%2Fscript%3E"' in page


def test_audit_page_without_token_has_plain_links():
    page = pages.audit.render([])
    assert 'href="/api/audit"' in page and "No audit entries yet." in page


def test_audit_page_groups_sessions_and_flags_errors():
    entries = [
        {
            "event": "session_start",
            "ts": "2026-11-11T10:00:00",
            "model": "m",
            "user_message": "hi",
        },
        {"event": "tool_call", "ts": "2026-11-11T10:00:01", "tool": "t", "args": {}},
        {
            "event": "tool_result",
            "ts": "2026-11-11T10:00:02",
            "tool": "t",
            "result": "Error: x",
        },
    ]
    page = pages.audit.render(entries)
    assert "3 entries" in page and "1 sessions" in page
    assert "1 tool call<" in page
    assert "session-block has-error" in page and "⚠ error" in page


def test_metrics_page_escapes_turn_values():
    turns = [
        {
            "ts": "2026-11-11T10:00:00",
            "model": XSS,
            "user_message": XSS,
            "input_tokens": 1,
            "output_tokens": 1,
            "tool_call_count": 0,
            "error_count": 0,
            "latency_ms": 5,
        }
    ]
    page = pages.metrics.render({"total_turns": 1}, turns)
    assert XSS not in page
    assert page.count(ESCAPED) == 2


def test_metrics_page_formats_totals():
    page = pages.metrics.render(
        {"total_input_tokens": 12345, "avg_latency_ms": 2345.6, "total_errors": None},
        [],
    )
    assert ">12,345<" in page and ">2,345 ms<" in page and ">0<" in page
