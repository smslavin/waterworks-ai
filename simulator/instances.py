"""WTP instance registry — loaded from topology.yaml.

Each entry: (ObjectType, InstanceID, {attribute: generator})

Topic structure:    Plant/WTP/<ObjectType>/<InstanceID>/<Attribute>
OPC-UA path:        Objects/Plant/WTP/<ObjectType>/<InstanceID>/<Attribute>
"""

from topology import load
from generators import ob, rw


def _build_instances(data: dict) -> list[tuple[str, str, dict]]:
    instances = []
    for eq_type, inst_list in data["instances"].items():
        type_attrs = data["equipment_types"][eq_type]["attributes"]
        for inst in inst_list:
            inst_id = inst["id"]
            overrides = inst.get("overrides", {})
            attr_gens = {}
            for attr_name, attr_cfg in type_attrs.items():
                cfg = {**attr_cfg, **overrides.get(attr_name, {})}
                if cfg.get("type") == "bool":
                    attr_gens[attr_name] = ob(
                        cfg.get("initial", True), cfg.get("flip", 0.01)
                    )
                else:
                    attr_gens[attr_name] = rw(cfg["lo"], cfg["hi"], cfg.get("step"))
            instances.append((eq_type, inst_id, attr_gens))
    return instances


INSTANCES = _build_instances(load())
