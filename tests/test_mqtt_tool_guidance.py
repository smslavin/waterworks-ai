"""Regression tests for fieldworks-core#33: the M8 Rust-adapter migration
(2026-07-19) renamed/removed several mqtt-mcp tools, but claude_loop.py and
multi_agent_loop.py's prompts/code still referenced the old names
(get_full_topic_tree, read_topic_value, connect_server) for weeks afterward.
That silently broke claude_loop._fetch_process_state() (always errored,
falling back to "MQTT not reachable" even when it wasn't) and misdirected
specialists toward guessed tag_ids that timed out — a plausible contributor
to a specialist fabricating a live MQTT reading during an active fault."""

import asyncio
import json

import claude_loop
import multi_agent_loop

# ── guidance text no longer references tools that don't exist ─────────────────


def test_specialist_tool_guidance_has_no_stale_tool_names():
    stale = ("get_full_topic_tree", "read_topic_value", "connect_server")
    for name in stale:
        assert name not in multi_agent_loop._SPECIALIST_TOOL_GUIDANCE


def test_specialist_tool_guidance_references_real_tools():
    for name in ("mqtt__scan", "mqtt__read_tag"):
        assert name in multi_agent_loop._SPECIALIST_TOOL_GUIDANCE


def test_single_agent_system_prompt_has_no_stale_tool_names():
    stale = ("get_full_topic_tree", "read_topic_value", "connect_server")
    for name in stale:
        assert name not in claude_loop._SYSTEM_PROMPT_BASE


def test_single_agent_system_prompt_references_real_tools():
    for name in ("scan()", "read_tag(", "connect first"):
        assert name in claude_loop._SYSTEM_PROMPT_BASE


# ── _fetch_process_state calls the real tool ───────────────────────────────────


def test_fetch_process_state_calls_mqtt_scan(monkeypatch):
    calls = []

    async def fake_call_mcp_tool(tool, args):
        calls.append((tool, args))
        return json.dumps({"entries": []})

    monkeypatch.setattr(claude_loop, "call_mcp_tool", fake_call_mcp_tool)
    monkeypatch.setattr(claude_loop, "_process_state_cache", None)
    asyncio.run(claude_loop._fetch_process_state())
    assert calls == [("mqtt__scan", {})]


# ── _parse_scan_entries: mqtt__scan's real JSON shape, not the old text tree ──


def _entry(topic, value):
    return {"topic": topic, "last_value": value, "quality": "good", "retain": False}


def test_parse_scan_entries_buckets_running_and_stopped_by_type():
    raw = json.dumps(
        {
            "entries": [
                _entry("Plant/WTP/Pump/RawWater_01/Running", 1.0),
                _entry("Plant/WTP/Pump/RawWater_02/Running", 0.0),
                _entry("Plant/WTP/UV/UV_01/Running", 1.0),
            ]
        }
    )
    units = claude_loop._parse_scan_entries(raw)
    assert units["Pump"]["running"] == ["RawWater_01"]
    assert units["Pump"]["stopped"] == ["RawWater_02"]
    assert units["UV"]["running"] == ["UV_01"]


def test_parse_scan_entries_handles_multi_segment_topic_root():
    # PLANT_TOPIC_ROOT can itself contain "/" (e.g. "Plant/WTP2") — parsing
    # must pull the last 3 segments, not assume a fixed prefix depth.
    raw = json.dumps({"entries": [_entry("Plant/WTP2/UV/UV_01/Running", 1.0)]})
    units = claude_loop._parse_scan_entries(raw)
    assert units["UV"]["running"] == ["UV_01"]


def test_parse_scan_entries_ignores_non_running_attributes():
    raw = json.dumps({"entries": [_entry("Plant/WTP/UV/UV_01/Intensity", 18.9)]})
    units = claude_loop._parse_scan_entries(raw)
    assert units == {}


def test_parse_scan_entries_survives_malformed_json():
    assert claude_loop._parse_scan_entries("not json") == {}
