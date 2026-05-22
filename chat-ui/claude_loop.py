"""Claude API chat loop with MCP tool calling. Yields SSE-ready JSON strings."""

import json
import time
import uuid
from typing import AsyncIterator

import anthropic

import audit
import metrics
from mcp_client import call_mcp_tool, list_mcp_tools

CLAUDE_MODELS = [
    "claude-sonnet-4-6",
    "claude-opus-4-7",
    "claude-haiku-4-5-20251001",
]

SYSTEM_PROMPT = """You are a process diagnostics assistant for a water treatment plant (WTP).

You have access to tools that read live sensor data via MQTT and OPC-UA, and query
historical trends from InfluxDB. Use them together to give accurate, grounded answers.

── Process units ──────────────────────────────────────────────────────────────
Pumps
  RawWater_01, RawWater_02       raw water intake (suction → clarifier)
  HighService_01, HighService_02 treated water distribution to mains
  Attributes: Flow (L/min), Pressure (bar), Power (kW), Running (bool)

Tanks
  Clarifier_01      Level (%), Turbidity (NTU)
  FinishedWater_01  Level (%), pH, Turbidity (NTU)

Chemical dosing
  Chlorine_01, Fluoride_01  FlowRate (L/h), Running (bool), TankLevel (%)

UV disinfection
  UV_01, UV_02  Intensity (%), Running (bool), LampHours

── Data access ────────────────────────────────────────────────────────────────
MQTT topic root : Plant/WTP/<Type>/<Instance>/<Attribute>
OPC-UA endpoint : opc.tcp://localhost:4840/waterworks  (call connect_server first)
InfluxDB        : call list_measurements to discover available data

── Diagnostic approach ────────────────────────────────────────────────────────
1. Read current values via MQTT or OPC-UA to establish present state
2. Compare against expected ranges for the unit type
3. Look for correlated anomalies (e.g. Flow≈0 + Power≈0 + Running=True → run-status fault)
4. Query InfluxDB for historical context when current readings alone are ambiguous

Always cite specific values and timestamps (e.g. "Flow is 12.4 L/min at 14:32:05").
Do not assert a value without first reading it from a tool."""


async def run_chat(
    messages: list[dict],
    model: str,
    *,
    base_url: str,
    api_key: str | None = None,
    thinking_enabled: bool = False,
    **kwargs,
) -> AsyncIterator[str]:
    session_id = str(uuid.uuid4())
    start_ts = time.monotonic()
    input_tokens = output_tokens = 0
    tool_call_count = error_count = 0
    user_message = next(
        (m["content"] for m in reversed(messages) if m["role"] == "user"), ""
    )

    audit.log("session_start", session_id=session_id, model=model, user_message=user_message)

    effective_model = "claude-opus-4-7" if thinking_enabled else model
    client = anthropic.AsyncAnthropic(api_key=api_key, base_url=base_url)

    mcp_tools = await list_mcp_tools()
    tools = [
        {
            "name": t["name"],
            "description": t["description"],
            "input_schema": t["inputSchema"],
        }
        for t in mcp_tools
    ]

    conv_messages = list(messages)

    try:
        while True:
            stream_kwargs: dict = dict(
                model=effective_model,
                max_tokens=8192,
                system=SYSTEM_PROMPT,
                messages=conv_messages,
            )
            if tools:
                stream_kwargs["tools"] = tools
            if thinking_enabled:
                stream_kwargs["thinking"]      = {"type": "adaptive"}
                stream_kwargs["output_config"] = {"effort": "high"}

            async with client.messages.stream(**stream_kwargs) as stream:
                if thinking_enabled:
                    _in_thinking = False
                    _thinking_streamed = False
                    async for event in stream:
                        if event.type == "content_block_start":
                            cb = getattr(event, "content_block", None)
                            if cb and getattr(cb, "type", None) == "thinking":
                                _in_thinking = True
                        elif event.type == "content_block_stop":
                            if _in_thinking:
                                _in_thinking = False
                                _thinking_streamed = True
                                yield json.dumps({"type": "thinking_stop"})
                        elif event.type == "content_block_delta":
                            delta = event.delta
                            if _in_thinking and hasattr(delta, "thinking"):
                                yield json.dumps({"type": "thinking_delta", "text": delta.thinking})
                            elif not _in_thinking and hasattr(delta, "text"):
                                yield json.dumps({"type": "text", "text": delta.text})
                else:
                    async for text in stream.text_stream:
                        yield json.dumps({"type": "text", "text": text})

                final = await stream.get_final_message()

                if thinking_enabled and not _thinking_streamed:
                    for block in final.content:
                        if hasattr(block, "thinking") and block.thinking:
                            yield json.dumps({"type": "thinking_delta", "text": block.thinking})
                            yield json.dumps({"type": "thinking_stop"})
                            break

            input_tokens  += final.usage.input_tokens
            output_tokens += final.usage.output_tokens

            if final.stop_reason == "end_turn":
                text_content = " ".join(
                    b.text for b in final.content if hasattr(b, "text")
                )
                audit.log("response", session_id=session_id, text=text_content)
                break

            if final.stop_reason == "tool_use":
                # Build assistant message for history
                assistant_content = []
                for block in final.content:
                    if block.type == "text":
                        assistant_content.append({"type": "text", "text": block.text})
                    elif block.type == "tool_use":
                        assistant_content.append({
                            "type": "tool_use",
                            "id": block.id,
                            "name": block.name,
                            "input": dict(block.input),
                        })

                tool_results = []
                for block in final.content:
                    if block.type != "tool_use":
                        continue
                    tool_call_count += 1
                    args = dict(block.input)
                    audit.log("tool_call", session_id=session_id, tool=block.name, args=args)
                    yield json.dumps({"type": "tool_call", "tool": block.name, "args": args})

                    result = await call_mcp_tool(block.name, args)
                    if result.startswith("Error"):
                        error_count += 1

                    audit.log("tool_result", session_id=session_id, tool=block.name, result=result)
                    yield json.dumps({"type": "tool_result", "tool": block.name, "result": result})

                    tool_results.append({
                        "type": "tool_result",
                        "tool_use_id": block.id,
                        "content": result,
                    })

                conv_messages = conv_messages + [
                    {"role": "assistant", "content": assistant_content},
                    {"role": "user",      "content": tool_results},
                ]
                continue

            # Unexpected stop reason — exit cleanly
            break

    except Exception as exc:
        error_count += 1
        audit.log("error", session_id=session_id, error=str(exc))
        yield json.dumps({"type": "error", "error": str(exc)})

    finally:
        latency_ms = int((time.monotonic() - start_ts) * 1000)
        metrics.log_turn(
            session_id=session_id,
            model=model,
            input_tokens=input_tokens,
            output_tokens=output_tokens,
            tool_call_count=tool_call_count,
            error_count=error_count,
            latency_ms=latency_ms,
            user_message=user_message,
        )
        yield json.dumps({"type": "done"})
