"""Enterprise orchestrator — Cascade-shaped, single tool (diagnose_plant).

Coordinates cross-plant diagnostic questions by calling diagnose_plant(site_id,
query) against each relevant plant's own chat-ui (via diagnose_plant_mcp), then
synthesizes a single cross-plant answer. This loop never touches a plant's
aggregator, MQTT, or InfluxDB directly — diagnose_plant is the only tool it
has access to, structurally, not just by prompt instruction.
"""

import asyncio
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
# The orchestrator keeps its own audit log (spec Part V: its sessions fall
# under the Part III audit contract). Forced, not defaulted: the checkout's
# root .env may set AUDIT_LOG_PATH for a plant's chat-ui, and an enterprise
# session must never land in a plant's log. Set before importing audit,
# which reads it at import time.
os.environ["AUDIT_LOG_PATH"] = os.environ.get(
    "ENTERPRISE_AUDIT_LOG_PATH", str(Path(__file__).parent / "audit.jsonl")
)

import audit  # noqa: E402
import model_params  # noqa: E402
from fieldworks.agents import build_enterprise_system  # noqa: E402
from mcp_client import call_mcp_tool, list_mcp_tools  # noqa: E402
from plant_registry import load_enterprise  # noqa: E402

logger = logging.getLogger(__name__)

MODEL = os.environ.get("ENTERPRISE_MODEL", "claude-sonnet-5-5")
DIAGNOSE_PLANT_MCP_URL = os.environ.get(
    "DIAGNOSE_PLANT_MCP_URL", "http://localhost:8200/sse"
)

# Same cap as the plant loops (chat-ui/tool_dispatch.py); this process can't
# import chat-ui, so keep the two in step by hand.
TOOL_RESULT_MAX_CHARS = 8_000
MAX_HISTORY_MESSAGES = 20


def _build_system_prompt() -> str:
    """fieldworks-core owns the orchestrator's contract (prompt, tool
    schemas, SUMMARY block); this deployment only says what kind of
    enterprise it is."""
    return build_enterprise_system(load_enterprise(), kind="water utility")


async def run_chat(
    messages: list[dict], *, api_key: str | None = None
) -> AsyncIterator[str]:
    session_id = str(uuid.uuid4())
    user_message = next(
        (m["content"] for m in reversed(messages) if m["role"] == "user"), ""
    )
    audit.log(
        "session_start",
        session_id=session_id,
        model=f"enterprise/{MODEL}",
        user_message=user_message,
    )
    response_text: list[str] = []
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
            stream_kwargs.update(model_params.request_params(MODEL, effort="medium"))

            async with client.beta.messages.stream(**stream_kwargs) as stream:
                async for text in model_params.visible_text(stream):
                    response_text.append(text)
                    yield json.dumps({"type": "text", "text": text})
                final = await stream.get_final_message()

            if refusal := model_params.refusal_message(final):
                audit.log("error", session_id=session_id, error=refusal)
                yield json.dumps({"type": "error", "error": refusal})
                return

            if final.stop_reason == "tool_use":
                assistant_content = model_params.assistant_turn(final.content)

                tool_use_blocks = [b for b in final.content if b.type == "tool_use"]
                for block in tool_use_blocks:
                    audit.log(
                        "tool_call",
                        session_id=session_id,
                        tool=block.name,
                        args=dict(block.input),
                        site_id=block.input.get("site_id"),
                    )
                    yield json.dumps(
                        {
                            "type": "tool_call",
                            "tool": block.name,
                            "args": dict(block.input),
                        }
                    )

                # Each diagnose_plant call is its own full agentic round-trip to a
                # plant's own diagnostic loop — the slow part. When the model asks
                # about multiple plants in one turn, run them concurrently instead
                # of one at a time (same pattern multi_agent_loop.py already uses
                # for its own specialist fan-out) — total wait becomes the slowest
                # plant checked, not the sum of every plant checked.
                results = await asyncio.gather(
                    *(
                        call_mcp_tool(
                            block.name, dict(block.input), DIAGNOSE_PLANT_MCP_URL
                        )
                        for block in tool_use_blocks
                    )
                )

                tool_results = []
                for block, result in zip(tool_use_blocks, results):
                    if len(result) > TOOL_RESULT_MAX_CHARS:
                        result = result[:TOOL_RESULT_MAX_CHARS] + "... [truncated]"
                    audit.log(
                        "tool_result",
                        session_id=session_id,
                        tool=block.name,
                        result=result,
                        site_id=block.input.get("site_id"),
                    )

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
            audit.log("response", session_id=session_id, text="".join(response_text))
            yield json.dumps({"type": "done", "session_id": session_id})
            return
    except Exception as exc:
        logger.exception("Enterprise orchestrator stream error")
        audit.log("error", session_id=session_id, error=str(exc))
        yield json.dumps({"type": "error", "error": model_params.error_text(exc)})
