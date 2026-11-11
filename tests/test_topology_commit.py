"""POST /api/topology/commit (gh-22): validate instances before seeding, and
don't report a count that isn't known.

Before: instances went straight to memory__seed_discovered_topology, so a
malformed instance list was half-seeded; and an unreadable seed result was
reported as {"committed_count": 0, "errors": 1}, claiming nothing had been
written when the seed may have written some instances first.
"""

import asyncio
import json

import pytest

import backend

GOOD = {
    "instance_id": "RawWater_01",
    "ladybug_type_id": "centrifugal_pump",
    "area_id": "intake",
    "confidence_level": "verified",
    "attributes": {"FlowRate": {"tag": "wtp/RawWater_01/FlowRate"}},
}


class _Request:
    def __init__(self, body=None, raw=None):
        self._body, self._raw = body, raw

    async def json(self):
        if self._raw is not None:
            return json.loads(self._raw)
        return self._body


@pytest.fixture()
def seed(monkeypatch):
    calls = []
    reply = {"text": json.dumps({"seeded_count": 1, "errors": 0})}

    async def call(name, args, aggregator_url=None):
        calls.append((name, args))
        return reply["text"]

    monkeypatch.setattr(backend.mcp_client, "call_mcp_tool", call)
    return calls, reply


def _post(body=None, raw=None):
    resp = asyncio.run(backend.topology_commit_endpoint(_Request(body, raw)))
    return resp.status_code, json.loads(resp.body)


def test_valid_commit_reports_the_seed_counts(seed):
    calls, _ = seed
    status, body = _post({"instances": [GOOD]})
    assert status == 200
    assert body == {"status": "ok", "committed_count": 1, "errors": 0}
    assert calls[0][0] == "memory__seed_discovered_topology"
    assert calls[0][1]["instances"] == [GOOD]


def test_partial_seed_is_reported_as_partial(seed):
    _, reply = seed
    reply["text"] = json.dumps({"seeded_count": 3, "errors": 2})
    status, body = _post({"instances": [GOOD]})
    assert status == 200
    assert body == {"status": "partial", "committed_count": 3, "errors": 2}


@pytest.mark.parametrize(
    "instances,problem",
    [
        (None, "instances must be a non-empty list"),
        ([], "instances must be a non-empty list"),
        ("RawWater_01", "instances must be a non-empty list"),
        (["RawWater_01"], "instances[0] must be an object"),
        (
            [{"area_id": "intake"}],
            "instances[0].instance_id must be a non-empty string",
        ),
        ([{**GOOD, "area_id": 7}], "instances[0].area_id must be a string"),
        (
            [{**GOOD, "attributes": ["FlowRate"]}],
            "instances[0].attributes must be an object",
        ),
        (
            [GOOD, {**GOOD, "attributes": {"FlowRate": {"unit": "L/s"}}}],
            "instances[1].attributes.FlowRate.tag must be a string",
        ),
    ],
)
def test_malformed_instances_are_refused_before_seeding(seed, instances, problem):
    calls, _ = seed
    status, body = _post({"instances": instances})
    assert status == 400
    assert problem in body["problems"]
    assert calls == []  # nothing half-seeded


def test_every_problem_is_listed(seed):
    status, body = _post({"instances": [{"area_id": 1}, "x"]})
    assert status == 400
    assert len(body["problems"]) == 3


def test_non_json_body_is_refused(seed):
    calls, _ = seed
    status, body = _post(raw="{not json")
    assert status == 400 and calls == []


@pytest.mark.parametrize(
    "reply",
    [
        "Error calling memory__seed_discovered_topology: connection refused",
        "Error executing tool seed_discovered_topology: database locked",
        "not json at all",
        json.dumps({"unexpected": True}),
    ],
)
def test_unreadable_seed_result_is_unknown_not_zero(seed, reply):
    _, r = seed
    r["text"] = reply
    status, body = _post({"instances": [GOOD]})
    assert status == 502
    assert body["status"] == "unknown"
    assert body["committed_count"] is None
    assert body["detail"] == reply
