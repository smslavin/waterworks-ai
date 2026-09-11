"""Tests for GET /api/topology (chat-ui/backend.py's topology_endpoint) —
added alongside the frontend fix that makes stores/topology.ts fetch this
plant's real equipment/area data instead of hardcoding a copy of
topology.yaml's shape. See CLAUDE.md's "topology.yaml is the source of
truth" note and the M10 multi-plant section: a genuinely different second
plant (its own topology.yaml via enterprise.yaml's topology_file) needs its
own equipment/areas/specialists here, not whatever plant's data happened to
be baked into the shared chat-ui/static/ Vite build.
"""

import asyncio
import json

import backend


def test_topology_endpoint_returns_areas_in_process_area_order():
    resp = asyncio.run(backend.topology_endpoint(None))
    body = json.loads(resp.body)
    assert body["areas"] == ["Intake", "Treatment", "Distribution"]


def test_topology_endpoint_returns_all_ten_instances():
    resp = asyncio.run(backend.topology_endpoint(None))
    body = json.loads(resp.body)
    assert len(body["nodes"]) == 10


def test_topology_endpoint_node_shape_matches_frontend_expectations():
    """Shape must match stores/topology.ts's TopologyApiNode exactly —
    id/area/specialist/equipmentType, camelCase equipmentType key included,
    since that's what loadTopology() destructures directly."""
    resp = asyncio.run(backend.topology_endpoint(None))
    body = json.loads(resp.body)
    raw_water_01 = next(n for n in body["nodes"] if n["id"] == "RawWater_01")
    assert raw_water_01 == {
        "id": "RawWater_01",
        "area": "Intake",
        "specialist": "Intake",
        "equipmentType": "pump",
    }


def test_topology_endpoint_specialist_equals_area_for_every_node():
    """This app's specialists are 1:1 with process areas (see CLAUDE.md's
    Multi-agent architecture table) — historian is the one exception and
    owns no equipment instances, so it never appears here at all."""
    resp = asyncio.run(backend.topology_endpoint(None))
    body = json.loads(resp.body)
    assert body["nodes"]  # sanity: not accidentally empty
    for node in body["nodes"]:
        assert node["specialist"] == node["area"]


def test_topology_endpoint_groups_nodes_by_area():
    """Nodes are grouped by process area (matching instances_in_area's own
    per-area order) rather than topology.yaml's raw equipment_instances
    declaration order (which interleaves areas) — this is what the
    frontend's nodesByArea grouping expects to reproduce the pre-fix
    hardcoded ordering closely."""
    resp = asyncio.run(backend.topology_endpoint(None))
    body = json.loads(resp.body)
    intake_ids = [n["id"] for n in body["nodes"] if n["area"] == "Intake"]
    assert intake_ids == ["RawWater_01", "RawWater_02"]
    distribution_ids = [n["id"] for n in body["nodes"] if n["area"] == "Distribution"]
    assert distribution_ids == [
        "HighService_01",
        "HighService_02",
        "FinishedWater_01",
    ]


def test_topology_endpoint_omits_edges():
    """Deliberate, not an oversight: topology.yaml's schema (fieldworks.
    topology.EquipmentInstance/ProcessArea) has no upstream/downstream or
    connectivity field at all, so there is nothing authoritative to derive
    flow-diagram edges from. See stores/topology.ts's INITIAL_EDGES comment
    — edges stay a frontend-only, non-authoritative display layout."""
    resp = asyncio.run(backend.topology_endpoint(None))
    body = json.loads(resp.body)
    assert "edges" not in body
