"""chat-ui/verdict.py: annotate() and the session status built on the framework parser (gh-25).

Five parsers used to disagree. The reproducible case from gh-25: a model
that bolds its labels and leaves a blank line before "Key points:" rendered
as a verdict card in PlantPanel and as raw text in AreaPanel and
diagnose_plant. Those inputs are in the cases below.
"""

import asyncio
import json

import pytest

import session_store
import verdict

SUMMARY = (
    "SUMMARY:\n"
    "Status: Fault Detected\n"
    "Overview: RawWater_01 shows suction starvation.\n"
    "Key points:\n"
    "- Flow near zero\n"
    "- Pressure dropping\n"
    "\n"
    "Detailed reasoning follows..."
)
FINDINGS = (
    "Checked the pump.\n\n"
    "FINDINGS:\n"
    "Status: Anomaly Detected\n"
    "Confidence: 0.72\n"
    "Key observations:\n"
    "- Vibration elevated\n"
    "- Flow steady"
)


def test_parse_is_the_frameworks():
    """Templates and parser are fieldworks.agents.verdict's (spec Part III);
    their cases, including the gh-25 inputs, are tested in fieldworks-core."""
    from fieldworks.agents import verdict as fw

    assert verdict.parse is fw.parse
    assert verdict.SUMMARY_BLOCK is fw.SUMMARY_BLOCK


# ── annotate(): one verdict event on the stream ────────────────────────────


def _events(*events):
    async def gen():
        for e in events:
            yield json.dumps(e)

    async def collect():
        return [json.loads(c) async for c in verdict.annotate(gen())]

    return asyncio.run(collect())


def test_leading_summary_is_sent_while_text_still_streams():
    out = _events(
        {"type": "text", "text": SUMMARY.split("Detailed")[0]},
        {"type": "text", "text": "Detailed reasoning..."},
        {"type": "done"},
    )
    kinds = [e["type"] for e in out]
    assert kinds == ["text", "verdict", "text", "done"]


def test_trailing_findings_is_sent_before_done():
    out = _events(
        {"type": "text", "text": "Checked."},
        {"type": "tool_call", "tool": "mqtt__scan", "args": {}},
        {"type": "text", "text": FINDINGS[FINDINGS.index("FINDINGS:") :]},
        {"type": "done", "input_tokens": 5},
    )
    assert [e["type"] for e in out] == ["text", "tool_call", "text", "verdict", "done"]
    v = out[3]
    assert v["status"] == "Anomaly Detected"
    # Joined as the frontend joins it: a blank line after the tool call.
    assert (
        "Checked.\n\n" + v["block"]
        == "Checked.\n\n" + FINDINGS[FINDINGS.index("FINDINGS:") :]
    )


def test_only_one_verdict_and_every_event_passes_through():
    events = [
        {"type": "text", "text": SUMMARY},
        {"type": "specialist_done", "specialist": "intake", "status": "Normal"},
        {"type": "text", "text": "\n\n" + SUMMARY},
        {"type": "done"},
    ]
    out = _events(*events)
    assert [e for e in out if e["type"] != "verdict"] == events
    assert sum(e["type"] == "verdict" for e in out) == 1


def test_no_block_no_verdict():
    out = _events({"type": "text", "text": "Hello!"}, {"type": "done"})
    assert [e["type"] for e in out] == ["text", "done"]


# ── session summaries follow the block when there is one ───────────────────


def test_session_status_comes_from_the_block():
    # The keyword heuristic would call this a fault ("cavitation").
    text = "No cavitation seen.\n\n" + FINDINGS[FINDINGS.index("FINDINGS:") :]
    assert session_store.extract_status_single(text) == ("Anomaly Detected", 0.72)


def test_session_status_falls_back_to_heuristic_without_a_block():
    status, _ = session_store.extract_status_single("Pump shows cavitation.")
    assert status == "Fault Detected"
