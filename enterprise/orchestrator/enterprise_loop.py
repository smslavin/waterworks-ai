"""Enterprise orchestrator — Cascade-shaped, single tool (diagnose_plant).

Coordinates cross-plant diagnostic questions by calling diagnose_plant(site_id,
query) against each relevant plant's own chat-ui (via diagnose_plant_mcp), then
synthesizes a single cross-plant answer. This loop never touches a plant's
aggregator, MQTT, or InfluxDB directly — diagnose_plant is the only tool it
has access to, structurally, not just by prompt instruction.
"""

import json
import logging
import os
import sys
import uuid
from pathlib import Path
from typing import AsyncIterator

import anthropic

sys.path.insert(0, str(Path(__file__).parent.parent))
sys.path.insert(0, str(Path(__file__).parent.parent.parent / "chat-ui"))
from mcp_client import call_mcp_tool, list_mcp_tools
from plant_registry import load_sites

logger = logging.getLogger(__name__)

MODEL = os.environ.get("ENTERPRISE_MODEL", "claude-sonnet-4-6")
DIAGNOSE_PLANT_MCP_URL = os.environ.get(
    "DIAGNOSE_PLANT_MCP_URL", "http://localhost:8200/sse"
)

TOOL_RESULT_MAX_CHARS = 4_000
MAX_HISTORY_MESSAGES = 20


def _build_system_prompt() -> str:
    sites = load_sites()
    if sites:
        site_lines = "\n".join(
            f"  - {site_id}: {info['name']} ({info['region']})"
            for site_id, info in sorted(sites.items())
        )
    else:
        site_lines = "  (no sites registered in enterprise.yaml)"
    return f"""You are the enterprise-level diagnostics coordinator for a multi-plant
water utility. You have no direct access to sensor data, MQTT, InfluxDB, or
any single plant's tools — the only thing you can do is ask a plant's own
diagnostic system a question via diagnose_plant(site_id, query) and read its
answer, exactly the way a human operator would call each plant's control
room.

Registered plants:
{site_lines}

For a question about one specific plant, call diagnose_plant once for that
plant. For a cross-plant or "all plants" question, call diagnose_plant once
per relevant plant and synthesize a single answer that clearly attributes
each finding to the correct site_id. Do not guess at another plant's status
without calling diagnose_plant for it — you have no other source of truth.

── Diagnostic output format ───────────────────────────────────────────────────
Start every status-overview response with this block, before any detailed
per-plant breakdown — you already have everything you called diagnose_plant
for this turn, so lead with the conclusion rather than building up to it:
SUMMARY:
Status: Normal | Anomaly Detected | Fault Detected
Overview: [one or two plain-language sentences covering every plant you checked]
Key points:
- [one bullet per plant with anything notable — omit the list entirely if there is nothing notable]

Status must reflect the single most severe status among every plant
checked (one plant "Fault Detected" makes the overall Status "Fault
Detected" even if every other plant is Normal). Detailed per-plant
reasoning belongs after this block, not before it — the block must never
be pushed to the end where it risks being cut off by the response length
limit.

Omit the block entirely for follow-up conversational replies that are not
a fresh status overview."""


async def run_chat(
    messages: list[dict], *, api_key: str | None = None
) -> AsyncIterator[str]:
    session_id = str(uuid.uuid4())
    client = anthropic.AsyncAnthropic(api_key=api_key)

    mcp_tools = await list_mcp_tools(DIAGNOSE_PLANT_MCP_URL)
    tools = [
        {
            "name": t["name"],
            "description": t["description"],
            "input_schema": t["inputSchema"],
        }
        for t in mcp_tools
    ]

    conv_messages = list(messages)
    if len(conv_messages) > MAX_HISTORY_MESSAGES:
        conv_messages = conv_messages[-MAX_HISTORY_MESSAGES:]
        while conv_messages and conv_messages[0]["role"] != "user":
            conv_messages = conv_messages[1:]

    system = _build_system_prompt()

    try:
        while True:
            stream_kwargs: dict = dict(
                model=MODEL,
                max_tokens=4096,
                system=system,
                messages=conv_messages,
            )
            if tools:
                stream_kwargs["tools"] = tools

            async with client.messages.stream(**stream_kwargs) as stream:
                async for text in stream.text_stream:
                    yield json.dumps({"type": "text", "text": text})
                final = await stream.get_final_message()

            if final.stop_reason == "tool_use":
                assistant_content = []
                for block in final.content:
                    if block.type == "text":
                        assistant_content.append({"type": "text", "text": block.text})
                    elif block.type == "tool_use":
                        assistant_content.append(
                            {
                                "type": "tool_use",
                                "id": block.id,
                                "name": block.name,
                                "input": dict(block.input),
                            }
                        )

                tool_results = []
                for block in final.content:
                    if block.type != "tool_use":
                        continue
                    args = dict(block.input)
                    yield json.dumps(
                        {"type": "tool_call", "tool": block.name, "args": args}
                    )

                    result = await call_mcp_tool(
                        block.name, args, DIAGNOSE_PLANT_MCP_URL
                    )
                    if len(result) > TOOL_RESULT_MAX_CHARS:
                        result = result[:TOOL_RESULT_MAX_CHARS] + "... [truncated]"

                    yield json.dumps(
                        {"type": "tool_result", "tool": block.name, "result": result}
                    )
                    tool_results.append(
                        {
                            "type": "tool_result",
                            "tool_use_id": block.id,
                            "content": result,
                        }
                    )

                conv_messages.append(
                    {"role": "assistant", "content": assistant_content}
                )
                conv_messages.append({"role": "user", "content": tool_results})
                continue

            # end_turn or any other stop_reason (max_tokens, etc.) — done.
            yield json.dumps({"type": "done", "session_id": session_id})
            return
    except Exception as exc:
        logger.exception("Enterprise orchestrator stream error")
        yield json.dumps({"type": "error", "error": str(exc)})
