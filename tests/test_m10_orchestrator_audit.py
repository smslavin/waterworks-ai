"""The enterprise orchestrator's sessions fall under the Part III audit
contract (spec Part V, gh-83): session_start, a tool_call/tool_result pair
per plant asked carrying its site_id, and the response. The model client
and the diagnose_plant MCP server are faked — no network, no API key."""

import asyncio
import json
import sys
from pathlib import Path
from types import SimpleNamespace

root = Path(__file__).parent.parent
sys.path.insert(0, str(root / "enterprise"))
sys.path.insert(0, str(root / "enterprise" / "orchestrator"))

import enterprise_loop  # noqa: E402


class _FakeStream:
    def __init__(self, final, texts):
        self._final, self._texts = final, texts

    async def __aenter__(self):
        return self

    async def __aexit__(self, *exc):
        return False

    async def get_final_message(self):
        return self._final


def _tool_use(site_id):
    return SimpleNamespace(
        type="tool_use",
        id=f"tu-{site_id}",
        name="diagnose_plant",
        input={"site_id": site_id, "query": "status?"},
    )


def _client_factory(turns):
    """Each stream() call plays the next (stop_reason, content, texts) turn."""
    turns = iter(turns)

    def stream(**kwargs):
        stop_reason, content, texts = next(turns)
        final = SimpleNamespace(stop_reason=stop_reason, content=content)
        return _FakeStream(final, texts)

    client = SimpleNamespace(
        beta=SimpleNamespace(messages=SimpleNamespace(stream=stream))
    )
    return lambda api_key=None: client


def _fake_model_params():
    async def visible_text(stream):
        for t in stream._texts:
            yield t

    return SimpleNamespace(
        request_params=lambda model, effort: {},
        visible_text=visible_text,
        refusal_message=lambda final: None,
        assistant_turn=lambda content: [],
        error_text=str,
    )


def test_orchestrator_session_is_audited_with_site_ids(monkeypatch, tmp_path):
    events = []
    monkeypatch.setattr(
        enterprise_loop.audit, "log", lambda event, **f: events.append((event, f))
    )
    monkeypatch.setattr(enterprise_loop, "_build_system_prompt", lambda: "system")
    monkeypatch.setattr(enterprise_loop, "model_params", _fake_model_params())

    async def list_tools(url):
        return []

    async def call_tool(name, args, url):
        return f"[{args['site_id']}] Status: Normal"

    monkeypatch.setattr(enterprise_loop, "list_mcp_tools", list_tools)
    monkeypatch.setattr(enterprise_loop, "call_mcp_tool", call_tool)
    monkeypatch.setattr(
        enterprise_loop.anthropic,
        "AsyncAnthropic",
        _client_factory(
            [
                ("tool_use", [_tool_use("wtp"), _tool_use("wtp2")], []),
                ("end_turn", [], ["SUMMARY:\n", "Status: Normal"]),
            ]
        ),
    )

    async def collect():
        return [
            json.loads(c)
            async for c in enterprise_loop.run_chat(
                [{"role": "user", "content": "all plants ok?"}]
            )
        ]

    chunks = asyncio.run(collect())
    assert chunks[-1]["type"] == "done"

    kinds = [e for e, _ in events]
    assert kinds == [
        "session_start",
        "tool_call",
        "tool_call",
        "tool_result",
        "tool_result",
        "response",
    ]
    session_ids = {f["session_id"] for _, f in events}
    assert session_ids == {chunks[-1]["session_id"]}

    start = events[0][1]
    assert start["user_message"] == "all plants ok?"
    assert start["model"].startswith("enterprise/")

    assert [f["site_id"] for e, f in events if e == "tool_call"] == ["wtp", "wtp2"]
    results = [f for e, f in events if e == "tool_result"]
    assert [r["site_id"] for r in results] == ["wtp", "wtp2"]
    assert results[0]["result"] == "[wtp] Status: Normal"
    assert events[-1][1]["text"] == "SUMMARY:\nStatus: Normal"


def test_orchestrator_never_writes_to_a_plants_audit_log(tmp_path):
    """The shared root .env may point AUDIT_LOG_PATH at a plant's log; the
    orchestrator must override it before audit reads it at import. Run in a
    fresh interpreter: this test process has already imported audit."""
    import os
    import subprocess

    env = {k: v for k, v in os.environ.items() if k != "ENTERPRISE_AUDIT_LOG_PATH"}
    env["AUDIT_LOG_PATH"] = str(tmp_path / "plant-audit.jsonl")
    code = (
        "import sys; sys.path[:0] = [{e!r}, {o!r}]\n"
        "import enterprise_loop, audit; print(audit.LOG_PATH)"
    ).format(e=str(root / "enterprise"), o=str(root / "enterprise" / "orchestrator"))
    out = subprocess.run(
        [sys.executable, "-c", code],
        env=env,
        capture_output=True,
        text=True,
        check=True,
    ).stdout.strip()
    assert out == str(root / "enterprise" / "orchestrator" / "audit.jsonl")
