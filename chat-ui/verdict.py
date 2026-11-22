"""The FINDINGS and SUMMARY blocks: annotate() wraps a chat stream with them.

The templates and the one parser are fieldworks-core's
(`fieldworks.agents.verdict`, spec Part III "Verdict Blocks"); core's
specialist and orchestrator prompts already embed them. What stays here is
host behavior: annotate() wraps a chat event stream and emits
{"type": "verdict", ...} as soon as a block is complete. The panels,
session_store and diagnose_plant_mcp read that event instead of the text
(gh-25: five hand-written parsers had drifted apart).
"""

from __future__ import annotations

import json
from collections.abc import AsyncIterator

from fieldworks.agents.verdict import (  # noqa: F401 — re-exported
    FINDINGS_BLOCK,
    FINDINGS_INSTRUCTION,
    STATUSES,
    SUMMARY_BLOCK,
    parse,
)


def _event(verdict: dict) -> str:
    return json.dumps({"type": "verdict", **verdict})


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
                yield _event(verdict)
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
                    yield _event(verdict)
