"""Regression tests for monitor.py's _populate_severities dedup fix.

Severity is keyed by (type_id, attr_id) in LadybugDB, but _NORMAL_MAP is
indexed per equipment *instance* (that's the key _on_message needs for its
MQTT-topic lookup). The original _populate_severities looped over every
_NORMAL_MAP entry directly, asking the same (type_id, attr_id, condition)
question once per instance instead of once per distinct equipment type —
on the current topology, ~50 sequential calls for only ~24 distinct answers.
These tests assert the actual call count against a mock, not just eyeball
the dedup logic.
"""

import asyncio
import json

import monitor


def test_populate_severities_dedupes_calls_to_distinct_type_attr_pairs(
    monkeypatch,
):
    calls = []

    async def fake_call_mcp_tool(name, args, url):
        calls.append((args["type_id"], args["attr_id"], args["condition"]))
        return json.dumps("warning")

    monkeypatch.setattr(monitor, "call_mcp_tool", fake_call_mcp_tool)

    asyncio.run(monitor._populate_severities("http://localhost:8100/sse"))

    unique_pairs = {
        (meta["type_id"], meta["attr_id"]) for meta in monitor._NORMAL_MAP.values()
    }
    expected_call_count = len(unique_pairs) * 2  # below_min + above_max

    assert len(calls) == expected_call_count
    # No duplicate (type_id, attr_id, condition) lookups.
    assert len(set(calls)) == len(calls)

    # The whole point: far fewer calls than one-per-instance would make.
    instance_count = len(monitor._NORMAL_MAP)
    assert expected_call_count < instance_count * 2
    # Sanity: this topology actually has instances sharing a type (otherwise
    # the dedup wouldn't be exercised at all).
    assert len(unique_pairs) < instance_count


def test_populate_severities_applies_fetched_value_to_every_sharing_instance(
    monkeypatch,
):
    """A severity fetched once for a (type_id, attr_id) pair must be applied
    to *every* _NORMAL_MAP instance that shares that pair, not just the
    first one encountered."""
    # Reset to defaults so this test doesn't depend on ordering vs. the
    # other test in this module mutating shared module-level state.
    for meta in monitor._NORMAL_MAP.values():
        meta["severity_below"] = monitor._DEFAULT_SEVERITY
        meta["severity_above"] = monitor._DEFAULT_SEVERITY

    async def fake_call_mcp_tool(name, args, url):
        if args["condition"] == "below_min":
            return json.dumps("critical")
        return json.dumps("warning")

    monkeypatch.setattr(monitor, "call_mcp_tool", fake_call_mcp_tool)

    # Find a (type_id, attr_id) pair with more than one instance sharing it.
    from collections import defaultdict

    by_pair = defaultdict(list)
    for key, meta in monitor._NORMAL_MAP.items():
        by_pair[(meta["type_id"], meta["attr_id"])].append(key)
    shared_pair, shared_keys = max(by_pair.items(), key=lambda kv: len(kv[1]))
    assert len(shared_keys) > 1, "expected at least one shared (type_id, attr_id) pair"

    asyncio.run(monitor._populate_severities("http://localhost:8100/sse"))

    for key in shared_keys:
        meta = monitor._NORMAL_MAP[key]
        assert meta["severity_below"] == "critical"
        assert meta["severity_above"] == "warning"


def test_populate_severities_keeps_default_on_lookup_failure(monkeypatch):
    for meta in monitor._NORMAL_MAP.values():
        meta["severity_below"] = monitor._DEFAULT_SEVERITY
        meta["severity_above"] = monitor._DEFAULT_SEVERITY

    async def failing_call_mcp_tool(name, args, url):
        raise ConnectionError("memory-mcp unreachable")

    monkeypatch.setattr(monitor, "call_mcp_tool", failing_call_mcp_tool)

    asyncio.run(monitor._populate_severities("http://localhost:8100/sse"))

    assert all(
        meta["severity_below"] == monitor._DEFAULT_SEVERITY
        and meta["severity_above"] == monitor._DEFAULT_SEVERITY
        for meta in monitor._NORMAL_MAP.values()
    )
