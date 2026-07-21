"""WTP instance registry — loaded from topology.yaml (identity) + simulator.yaml
(generation mechanics: lo/hi/step/type/initial/flip, per-instance overrides).

Each entry: (ObjectType, InstanceID, {attribute: generator})

Topic structure:    Plant/WTP/<ObjectType>/<InstanceID>/<Attribute>
OPC-UA path:        Objects/Plant/WTP/<ObjectType>/<InstanceID>/<Attribute>
"""

import os
from pathlib import Path

import yaml
from topology import load as _load_topology

from generators import ob, rw

_SIMULATOR_CONFIG_PATH = Path(__file__).parent.parent / "simulator.yaml"


def _load_simulator_config() -> dict:
    path = Path(os.environ.get("SIMULATOR_CONFIG_FILE", _SIMULATOR_CONFIG_PATH))
    with open(path) as f:
        return yaml.safe_load(f)


def _build_instances() -> list[tuple[str, str, dict]]:
    topology = _load_topology()
    sim_cfg = _load_simulator_config()
    sim_types = sim_cfg.get("equipment_types", {})
    sim_instances = sim_cfg.get("equipment_instances", {})

    instances = []
    for eq_type in topology.equipment_types:
        type_attrs = sim_types.get(eq_type.id, {}).get("attributes", {})
        insts = [i for i in topology.equipment_instances if i.type_id == eq_type.id]
        for inst in insts:
            overrides = sim_instances.get(inst.id, {}).get("overrides", {})
            attr_gens = {}
            for attr in eq_type.attributes:
                cfg = {**type_attrs.get(attr.id, {}), **overrides.get(attr.id, {})}
                if cfg.get("type") == "bool":
                    attr_gens[attr.name] = ob(
                        cfg.get("initial", True), cfg.get("flip", 0.01)
                    )
                else:
                    attr_gens[attr.name] = rw(cfg["lo"], cfg["hi"], cfg.get("step"))
            instances.append((eq_type.name, inst.name, attr_gens))
    return instances


INSTANCES = _build_instances()
