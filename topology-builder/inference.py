"""Pattern matching and confidence scoring for discovered topology."""

import re
from pathlib import Path

import yaml


def load_template(name: str) -> dict:
    p = Path(__file__).parent / "templates" / f"{name}.yaml"
    return yaml.safe_load(p.read_text())


def infer_topology(
    mqtt_topics: dict[str, str],
    opcua_nodes: list[str],
    template: dict,
) -> list[dict]:
    """
    Returns list of discovered instances:
    {
        "instance_id": "RawWater_01",
        "equipment_type": "Pump",
        "ladybug_type_id": "centrifugal_pump",
        "process_area": "Intake",
        "area_id": "intake",
        "confidence_score": 0.92,
        "confidence_level": "verified",
        "attributes": {"Flow": {"tag": "Plant/WTP/Pump/RawWater_01/Flow", "source": "mqtt"}},
        "missing_required": [],
        "sources": ["mqtt"],
    }
    """
    opcua_set = set(opcua_nodes)
    instances: dict[str, dict] = {}

    for topic in mqtt_topics:
        for eq_type, spec in template["equipment_types"].items():
            match = _match_equipment(topic, spec)
            if not match:
                continue
            instance_id, attr_name, via_legacy = match
            if instance_id not in instances:
                instances[instance_id] = _new_instance(instance_id, eq_type, spec, via_legacy)
            instances[instance_id]["attributes"][attr_name] = {
                "tag": topic,
                "source": "mqtt",
            }
            if _has_opcua_match(topic, opcua_set):
                instances[instance_id]["sources"].add("opcua")
            break

    results = []
    for inst in instances.values():
        inst["sources"] = list(inst["sources"])
        _assign_process_area(inst, template)
        _score_confidence(inst, template)
        results.append(inst)

    area_order = {a["name"]: i for i, a in enumerate(template["process_areas"])}
    results.sort(key=lambda x: (area_order.get(x["process_area"], 99), x["instance_id"]))
    return results


def _new_instance(instance_id: str, eq_type: str, spec: dict, via_legacy: bool = False) -> dict:
    return {
        "instance_id": instance_id,
        "equipment_type": eq_type,
        "ladybug_type_id": spec.get("ladybug_type_id", ""),
        "process_area": "Unknown",
        "area_id": "unknown",
        "confidence_score": 0.0,
        "confidence_level": "suspect",
        "attributes": {},
        "missing_required": [],
        "sources": {"mqtt"},
        "via_legacy_pattern": via_legacy,
    }


def _match_equipment(topic: str, spec: dict) -> tuple[str, str, bool] | None:
    for pattern in spec["topic_patterns"]:
        result = _apply_pattern(topic, pattern)
        if result:
            return result[0], result[1], False
    for pattern in spec.get("legacy_patterns", []):
        result = _apply_pattern(topic, pattern)
        if result:
            return result[0], result[1], True
    return None


def _apply_pattern(topic: str, pattern: str) -> tuple[str, str] | None:
    """
    Convert pattern to regex. ** matches any path segments, * matches one segment.
    The instance_id is the second-to-last path segment; {attr} is the last.
    """
    regex = (
        pattern
        .replace(".", r"\.")
        .replace("{attr}", r"(?P<attr>[^/]+)")
        .replace("**", r"(?:.+)")
        .replace("*", r"([^/]+)")
    )
    m = re.fullmatch(regex, topic)
    if not m:
        return None
    attr = m.group("attr")
    parts = topic.split("/")
    if len(parts) < 2:
        return None
    instance_id = parts[-2]
    return instance_id, attr


def _has_opcua_match(topic: str, opcua_set: set[str]) -> bool:
    parts = topic.split("/")
    if len(parts) < 2:
        return False
    suffix = "/".join(parts[-2:])  # "InstanceId/AttrName" — avoids false positives on shared attr names
    return any(suffix in node for node in opcua_set)


def _assign_process_area(inst: dict, template: dict) -> None:
    for area in template["process_areas"]:
        for pattern in area["patterns"]:
            regex = pattern.replace("*", ".*")
            if re.search(regex, inst["instance_id"], re.IGNORECASE):
                inst["process_area"] = area["name"]
                inst["area_id"] = area.get("area_id", area["name"].lower())
                return
    inst["process_area"] = "Unknown"
    inst["area_id"] = "unknown"


def _score_confidence(inst: dict, template: dict) -> None:
    spec = template["equipment_types"][inst["equipment_type"]]
    required = set(spec.get("required_attributes", []))
    found = set(inst["attributes"].keys())
    missing = required - found
    inst["missing_required"] = list(missing)

    has_opcua = "opcua" in inst["sources"]
    all_required = len(missing) == 0

    if all_required and has_opcua:
        inst["confidence_score"] = 0.95
        inst["confidence_level"] = "verified"
    elif all_required:
        inst["confidence_score"] = 0.75
        inst["confidence_level"] = "inferred"
    elif found:
        inst["confidence_score"] = 0.70
        inst["confidence_level"] = "inferred"
    else:
        inst["confidence_score"] = 0.40
        inst["confidence_level"] = "suspect"

    # Legacy pattern matches are capped at inferred regardless of OPC-UA coverage.
    # A match via abbreviated or non-standard topic structure can't be trusted as verified.
    if inst.get("via_legacy_pattern") and inst["confidence_level"] == "verified":
        inst["confidence_score"] = 0.75
        inst["confidence_level"] = "inferred"
