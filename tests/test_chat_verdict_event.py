"""POST /api/chat emits one "verdict" event per response (gh-25).

Every chat mode is wrapped in verdict.annotate(), so the panels and
diagnose_plant_mcp get the parsed FINDINGS/SUMMARY block as data. The loops
are faked; the Starlette route, SSE encoding and annotate() are real.
"""

import json

import pytest
from starlette.testclient import TestClient

import backend
import claude_loop
import multi_agent_loop

SUMMARY = "SUMMARY:\nStatus: Normal\nOverview: All units nominal.\n\nDetails follow."


async def _fake_loop(*args, **kwargs):
    yield json.dumps({"type": "text", "text": SUMMARY})
    yield json.dumps({"type": "done", "input_tokens": 1})


def _events(body):
    client = TestClient(backend.app)
    resp = client.post("/api/chat", json=body)
    return [
        json.loads(line[len("data: ") :])
        for line in resp.text.splitlines()
        if line.startswith("data: ")
    ]


@pytest.fixture()
def fake_loops(monkeypatch):
    monkeypatch.setattr(claude_loop, "run_chat", _fake_loop)
    monkeypatch.setattr(multi_agent_loop, "run_multi_agent", _fake_loop)


@pytest.mark.parametrize("mode", ["single", "multi"])
def test_chat_stream_carries_a_verdict_event(fake_loops, mode):
    events = _events(
        {
            "messages": [{"role": "user", "content": "status?"}],
            "mode": mode,
            "model": claude_loop.CLAUDE_MODELS[0],
        }
    )
    kinds = [e["type"] for e in events]
    assert kinds == ["text", "verdict", "done"]
    verdict = events[1]
    assert (verdict["kind"], verdict["status"], verdict["overview"]) == (
        "summary",
        "Normal",
        "All units nominal.",
    )
