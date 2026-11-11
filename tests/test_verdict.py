"""chat-ui/verdict.py: the one parser for FINDINGS/SUMMARY blocks (gh-25).

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


def test_summary_block():
    v = verdict.parse(SUMMARY)
    assert v["kind"] == "summary"
    assert v["status"] == "Fault Detected"
    assert v["overview"] == "RawWater_01 shows suction starvation."
    assert v["points"] == ["Flow near zero", "Pressure dropping"]
    assert v["confidence"] is None
    assert v["block"] == SUMMARY.split("\n\n")[0]


def test_findings_block():
    v = verdict.parse(FINDINGS)
    assert (v["kind"], v["status"], v["confidence"]) == (
        "findings",
        "Anomaly Detected",
        0.72,
    )
    assert v["points"] == ["Vibration elevated", "Flow steady"]
    assert v["block"] == FINDINGS[FINDINGS.index("FINDINGS:") :]


@pytest.mark.parametrize(
    "text",
    [
        # gh-25: bold labels and a blank line before the list
        "SUMMARY:\n**Status:** Fault Detected\n**Overview:** Starving.\n\n"
        "**Key points:**\n- Flow near zero\n\nMore",
        "SUMMARY:\n**Status: Fault Detected**\n**Overview: Starving.**\n"
        "Key points:\n- Flow near zero\n",
        "**SUMMARY:**\nstatus: fault detected.\noverview: Starving.\n"
        "key points:\n* Flow near zero\n",
        "SUMMARY:\r\nStatus: Fault Detected\r\nOverview: Starving.\r\n"
        "Key points:\r\n- Flow near zero\r\n",
    ],
    ids=["bold-labels-blank-line", "bold-lines", "lowercase-star-bullets", "crlf"],
)
def test_formatting_variants_parse_the_same(text):
    v = verdict.parse(text)
    assert (v["status"], v["overview"], v["points"]) == (
        "Fault Detected",
        "Starving.",
        ["Flow near zero"],
    )


def test_summary_without_points():
    v = verdict.parse("SUMMARY:\nStatus: Normal\nOverview: Quiet.\n\nRest of answer.")
    assert v["points"] == [] and v["overview"] == "Quiet."


def test_unknown_status_is_kept_verbatim():
    v = verdict.parse("SUMMARY:\nStatus: Degraded\nOverview: Hmm.\n")
    assert v["status"] == "Degraded"


@pytest.mark.parametrize(
    "text",
    [
        "Just chatting, nothing to report.",
        "SUMMARY:\nOverview: no status line\n",
        "FINDINGS:\nStatus: Normal\nKey observations:\n- missing confidence\n",
        "SUMMARY:\nStatus: Normal\n",  # no overview
    ],
)
def test_incomplete_or_absent_blocks(text):
    assert verdict.parse(text) is None


def test_last_block_wins():
    first = "FINDINGS:\nStatus: Normal\nConfidence: 0.5\nKey observations:\n- a\n\n"
    v = verdict.parse(first + FINDINGS)
    assert v["status"] == "Anomaly Detected"


def test_streaming_waits_for_the_block_to_close():
    open_list = "SUMMARY:\nStatus: Normal\nOverview: Ok.\nKey points:\n- partial"
    assert verdict.parse(open_list, final=False) is None
    assert verdict.parse(open_list, final=True)["points"] == ["partial"]
    assert verdict.parse(open_list + "\n\nMore", final=False)["points"] == ["partial"]


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
