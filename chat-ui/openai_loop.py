"""OpenAI-compatible chat loop for Ollama. Yields SSE-ready JSON strings."""

import json
import time
import uuid
from typing import AsyncIterator

from openai import AsyncOpenAI

import audit
import metrics
from mcp_client import call_mcp_tool, list_mcp_tools


async def run_chat(
    messages: list[dict],
    model: str,
    *,
    base_url: str,
    api_key: str | None = None,
    **kwargs,
) -> AsyncIterator[str]:
    session_id = str(uuid.uuid4())
    start_ts = time.monotonic()
    input_tokens = output_tokens = 0
    tool_call_count = error_count = 0
    user_message = next(
        (m["content"] for m in reversed(messages) if m["role"] == "user"), ""
    )

    audit.log(
        "session_start", session_id=session_id, model=model, user_message=user_message
    )

    client = AsyncOpenAI(
        base_url=f"{base_url.rstrip('/')}/v1",
        api_key=api_key or "ollama",
    )

    mcp_tools = await list_mcp_tools()
    tools_oai = [
        {
            "type": "function",
            "function": {
                "name": t["name"],
                "description": t["description"],
                "parameters": t.get(
                    "inputSchema", {"type": "object", "properties": {}}
                ),
            },
        }
        for t in mcp_tools
    ]

    conv_messages = list(messages)

    try:
        while True:
            stream_kwargs: dict = dict(model=model, messages=conv_messages, stream=True)
            if tools_oai:
                stream_kwargs["tools"] = tools_oai

            stream = await client.chat.completions.create(**stream_kwargs)

            full_text = ""
            # tool_calls_acc: index → {id, name, arguments_str}
            tool_calls_acc: dict[int, dict] = {}

            async for chunk in stream:
                choice = chunk.choices[0] if chunk.choices else None
                if choice is None:
                    continue
                delta = choice.delta

                if delta.content:
                    full_text += delta.content
                    yield json.dumps({"type": "text", "text": delta.content})

                if delta.tool_calls:
                    for tc in delta.tool_calls:
                        idx = tc.index
                        if idx not in tool_calls_acc:
                            tool_calls_acc[idx] = {
                                "id": "",
                                "name": "",
                                "arguments_str": "",
                            }
                        if tc.id:
                            tool_calls_acc[idx]["id"] = tc.id
                        if tc.function:
                            if tc.function.name:
                                tool_calls_acc[idx]["name"] += tc.function.name
                            if tc.function.arguments:
                                tool_calls_acc[idx][
                                    "arguments_str"
                                ] += tc.function.arguments

                if getattr(chunk, "usage", None):
                    input_tokens += chunk.usage.prompt_tokens or 0
                    output_tokens += chunk.usage.completion_tokens or 0

            if full_text:
                audit.log("response", session_id=session_id, text=full_text)

            if not tool_calls_acc:
                break

            # Execute tool calls
            assistant_tool_calls = []
            tool_result_messages = []

            for idx in sorted(tool_calls_acc):
                tc = tool_calls_acc[idx]
                try:
                    args = (
                        json.loads(tc["arguments_str"]) if tc["arguments_str"] else {}
                    )
                except json.JSONDecodeError:
                    args = {}

                tool_call_count += 1
                audit.log(
                    "tool_call", session_id=session_id, tool=tc["name"], args=args
                )
                yield json.dumps(
                    {"type": "tool_call", "tool": tc["name"], "args": args}
                )

                result = await call_mcp_tool(tc["name"], args)
                if result.startswith("Error"):
                    error_count += 1

                audit.log(
                    "tool_result", session_id=session_id, tool=tc["name"], result=result
                )
                yield json.dumps(
                    {"type": "tool_result", "tool": tc["name"], "result": result}
                )

                assistant_tool_calls.append(
                    {
                        "id": tc["id"],
                        "type": "function",
                        "function": {
                            "name": tc["name"],
                            "arguments": tc["arguments_str"],
                        },
                    }
                )
                tool_result_messages.append(
                    {
                        "role": "tool",
                        "tool_call_id": tc["id"],
                        "content": result,
                    }
                )

            conv_messages = conv_messages + [
                {
                    "role": "assistant",
                    "content": full_text or None,
                    "tool_calls": assistant_tool_calls,
                },
                *tool_result_messages,
            ]

    except Exception as exc:
        error_count += 1
        audit.log("error", session_id=session_id, error=str(exc))
        yield json.dumps({"type": "error", "error": str(exc)})

    finally:
        latency_ms = int((time.monotonic() - start_ts) * 1000)
        metrics.log_turn(
            session_id=session_id,
            model=model,
            input_tokens=input_tokens or None,
            output_tokens=output_tokens or None,
            tool_call_count=tool_call_count,
            error_count=error_count,
            latency_ms=latency_ms,
            user_message=user_message,
        )
        yield json.dumps({"type": "done"})
