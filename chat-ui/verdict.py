"""The FINDINGS and SUMMARY blocks: their format, and the one parser for them.

Models end an equipment diagnosis with a FINDINGS block and lead an area or
plant overview with a SUMMARY block. That block drives node colour, the
panels' verdict cards, session_summaries.status and the enterprise summary.
It used to be parsed by five hand-written regexes (backend, three Vue
panels, diagnose_plant_mcp) that had drifted apart (gh-25): the same model
output rendered as a card in one panel and raw text in another.

Now the backend parses it once. annotate() wraps a chat event stream and
emits {"type": "verdict", ...} as soon as a block is complete; the panels
and diagnose_plant_mcp read that event instead of the text.
"""

from __future__ import annotations

import json
import re
from collections.abc import AsyncIterator

STATUSES = ("Normal", "Anomaly Detected", "Fault Detected")

# The block templates prompts embed. The enterprise orchestrator
# (enterprise/orchestrator/enterprise_loop.py) runs in its own process and
# carries its own copy of the SUMMARY template; keep the labels in step.
FINDINGS_BLOCK = """FINDINGS:
Status: Normal | Anomaly Detected | Fault Detected
Confidence: 0.0–1.0
Key observations:
- [bullet points]"""

SUMMARY_BLOCK = """SUMMARY:
Status: Normal | Anomaly Detected | Fault Detected
Overview: [one or two plain-language sentences]
Key points:
- [bullet points — omit the list entirely if there is nothing notable]"""

# Labels as models actually write them: optionally bolded ("**Status:**"),
# any case, with a stray blank line before the bullet list.
_B = r"\**"  # optional markdown bold around a label


def _label(name: str) -> str:
    return rf"^[ \t]*{_B}{name}{_B}:{_B}[ \t]*"


_HEADER = re.compile(rf"^[ \t]*{_B}(FINDINGS|SUMMARY){_B}:{_B}[ \t]*$", re.I | re.M)
_STATUS = re.compile(_label("Status") + r"(.+)$", re.I | re.M)
_CONFIDENCE = re.compile(_label("Confidence") + r"([0-9]*\.?[0-9]+)", re.I | re.M)
_OVERVIEW = re.compile(_label("Overview") + r"(.+)$", re.I | re.M)
_POINTS = re.compile(_label(r"Key (?:points|observations)") + r"$", re.I | re.M)
_BULLET = re.compile(r"^[ \t]*[-*•][ \t]+(.+)$")


def _status(raw: str) -> str:
    cleaned = raw.strip().strip("*").strip().rstrip(".").strip()
    for status in STATUSES:
        if cleaned.lower() == status.lower():
            return status
    return cleaned


def parse(text: str, final: bool = True) -> dict | None:
    """The last complete FINDINGS or SUMMARY block in `text`, or None.

    While a response is still streaming (final=False) a block only counts
    once a blank line follows it, so a half-written bullet list isn't
    reported; at the end of the response (final=True) the end of the text
    closes it too. The returned "block" is the exact substring parsed, so a
    reader holding the same text can show the rest without it.
    """
    text = text.replace("\r\n", "\n")
    for header in reversed(list(_HEADER.finditer(text))):
        verdict = _parse_block(text, header, final)
        if verdict is not None:
            return verdict
    return None


def _parse_block(text: str, header: re.Match, final: bool) -> dict | None:
    kind = header.group(1).lower()
    lines = text[header.end() :].split("\n")[1:]
    fields: dict[str, str] = {}
    points: list[str] = []
    in_points = False
    consumed = 0  # lines belonging to the block
    closed = False
    for i, line in enumerate(lines):
        if not line.strip():
            # One blank line may sit between the fields and the bullet list.
            nxt = lines[i + 1] if i + 1 < len(lines) else ""
            if not points and not in_points and _POINTS.match(nxt):
                consumed = i + 1
                continue
            closed = True
            break
        if in_points:
            bullet = _BULLET.match(line)
            if not bullet:
                closed = True
                break
            points.append(bullet.group(1).strip())
        elif m := _STATUS.match(line):
            fields["status"] = m.group(1)
        elif m := _CONFIDENCE.match(line):
            fields["confidence"] = m.group(1)
        elif m := _OVERVIEW.match(line):
            fields["overview"] = m.group(1).strip().strip("*").strip()
        elif _POINTS.match(line):
            in_points = True
        else:
            closed = True
            break
        consumed = i + 1

    if "status" not in fields or not (closed or final):
        return None
    if kind == "findings" and "confidence" not in fields:
        return None
    if kind == "summary" and "overview" not in fields:
        return None

    start = header.start()
    end = header.end() + sum(len(line) + 1 for line in lines[:consumed])
    end = min(end, len(text))
    return {
        "type": "verdict",
        "kind": kind,
        "status": _status(fields["status"]),
        "confidence": float(fields["confidence"]) if "confidence" in fields else None,
        "overview": fields.get("overview"),
        "points": points,
        "block": text[start:end].rstrip("\n"),
    }


async def annotate(chunks: AsyncIterator[str]) -> AsyncIterator[str]:
    """Pass a chat event stream through, adding one verdict event.

    Text is joined the way the frontend joins it (useSSE.ts: a blank line
    after a tool call), so the verdict's "block" is a substring of what the
    panel holds. The verdict goes out as soon as a block is complete, which
    lets a leading SUMMARY show while the detailed breakdown still streams,
    and at the latest just before "done".
    """
    text = ""
    after_tool_call = False
    sent = False
    async for chunk in chunks:
        try:
            event = json.loads(chunk)
        except (TypeError, ValueError):
            yield chunk
            continue
        kind = event.get("type") if isinstance(event, dict) else None
        if kind == "done" and not sent:
            verdict = parse(text, final=True)
            if verdict is not None:
                sent = True
                yield json.dumps(verdict)
        yield chunk
        if kind == "tool_call":
            after_tool_call = True
        elif kind == "text":
            text += ("\n\n" if after_tool_call else "") + event.get("text", "")
            after_tool_call = False
            if not sent:
                verdict = parse(text, final=False)
                if verdict is not None:
                    sent = True
                    yield json.dumps(verdict)
