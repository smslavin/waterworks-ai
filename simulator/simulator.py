"""Waterworks-AI WTP simulator.

Publishes synthetic water treatment plant process values simultaneously to:
  - Mosquitto MQTT broker  (paho, loop_start background thread)
  - asyncua OPC-UA server  (asyncio, same event loop)

Also exposes an HTTP control plane for runtime fault injection:
  POST /fault?target=<instance_id>&mode=<fault_mode>
  GET  /status   → JSON of every instance and its current fault mode

Environment variables
---------------------
MQTT_BROKER_URL     Broker hostname          (default: localhost)
MQTT_BROKER_PORT    Broker port              (default: 1883)
PLANT_TOPIC_ROOT    MQTT topic root prefix   (default: Plant/WTP)
OPCUA_PORT          OPC-UA server port       (default: 4840)
CONTROL_PORT        HTTP control plane port  (default: 8090)
PUBLISH_INTERVAL    Seconds between ticks    (default: 2.0)
"""

import asyncio
import json
import logging
import logging.handlers
import math
import os

import paho.mqtt.client as mqtt
from aiohttp import web
from asyncua import Server, ua
from dotenv import load_dotenv

from faults import FaultMode, FaultState, TYPE_FAULT_MODES
from generators import OscillatingBool
from instances import INSTANCES
from topology import load as _load_topology

load_dotenv()

MQTT_BROKER = os.environ.get("MQTT_BROKER_URL", "localhost")
MQTT_PORT = int(os.environ.get("MQTT_BROKER_PORT", 1883))
OPCUA_PORT = int(os.environ.get("OPCUA_PORT", 4840))
CONTROL_PORT = int(os.environ.get("CONTROL_PORT", 8090))
INTERVAL = float(os.environ.get("PUBLISH_INTERVAL", 2.0))

MQTT_ROOT = os.environ.get("PLANT_TOPIC_ROOT", "Plant/WTP")
OPCUA_NS_URI = "urn:waterworks-ai:simulator"

_log_dir = os.path.join(os.path.dirname(__file__), "logs")
os.makedirs(_log_dir, exist_ok=True)
_fh = logging.handlers.RotatingFileHandler(
    os.path.join(_log_dir, "simulator.log"), maxBytes=5 * 1024 * 1024, backupCount=3
)
_fh.setFormatter(
    logging.Formatter(
        "%(asctime)s %(levelname)s %(name)s: %(message)s", datefmt="%Y-%m-%d %H:%M:%S"
    )
)
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s %(levelname)s %(name)s: %(message)s",
    datefmt="%Y-%m-%d %H:%M:%S",
    handlers=[logging.StreamHandler(), _fh],
)
logger = logging.getLogger("waterworks-simulator")


# ── Fault registry ────────────────────────────────────────────────────────────

fault_registry: dict[str, FaultState] = {
    instance_id: FaultState() for _, instance_id, _ in INSTANCES
}

instance_types: dict[str, str] = {
    instance_id: obj_type for obj_type, instance_id, _ in INSTANCES
}

# ── Setpoint overrides ────────────────────────────────────────────────────────
# Written by /setpoint endpoint; applied in the main publish loop.
# {instance_id: {attribute: target_value}}
setpoint_overrides: dict[str, dict[str, float]] = {}

# First-order ramp state: current ramped value per (instance_id, attribute).
# Initialized from the live value when a setpoint is first set.
# {instance_id: {attribute: current_ramped_value}}
_setpoint_ramp: dict[str, dict[str, float]] = {}
_RAMP_FRACTION = 0.10  # move 10 % of remaining gap each tick → exponential approach


# ── Setpoint validation ──────────────────────────────────────────────────────
# Attribute identity and engineering (alarm) limits for /setpoint validation,
# built once from topology.yaml — the source of truth for what attributes an
# instance actually has and what range is safe to write into it. Keyed by the
# same instance/attribute *names* used on the wire (matches INSTANCES/
# fault_registry), not topology.yaml's internal ids.
# {instance_name: {attribute_name: AttributeDef}}
_ATTRIBUTE_INDEX: dict[str, dict[str, object]] = {}
_topology = _load_topology()
for _inst in _topology.equipment_instances:
    _eq_type = _topology.get_equipment_type(_inst.type_id)
    _ATTRIBUTE_INDEX[_inst.name] = {attr.name: attr for attr in _eq_type.attributes}
del _topology, _inst, _eq_type


def instance_attributes(target: str) -> dict[str, object]:
    """Known attribute-name → AttributeDef for a given instance name."""
    return _ATTRIBUTE_INDEX.get(target, {})


def engineering_limits(target: str, attribute: str) -> tuple[float, float] | None:
    """(lo, hi) engineering/alarm limits for a numeric attribute, from
    topology.yaml's normal_range. Returns None for non-numeric attributes
    (e.g. boolean Running) or unknown target/attribute — callers should have
    already validated the attribute is known before calling this."""
    attr_def = instance_attributes(target).get(attribute)
    if attr_def is None or getattr(attr_def, "normal_range", None) is None:
        return None
    return attr_def.normal_range.min, attr_def.normal_range.max


# ── MQTT ──────────────────────────────────────────────────────────────────────


def _start_mqtt() -> mqtt.Client:
    client = mqtt.Client(mqtt.CallbackAPIVersion.VERSION2)

    def on_connect(c, userdata, flags, rc, properties=None):
        if rc == 0:
            logger.info("MQTT connected  %s:%d", MQTT_BROKER, MQTT_PORT)
        else:
            logger.error("MQTT connect failed  rc=%d", rc)

    client.on_connect = on_connect
    try:
        client.connect(MQTT_BROKER, MQTT_PORT)
    except OSError as exc:
        logger.error(
            "Cannot reach MQTT broker at %s:%d — %s", MQTT_BROKER, MQTT_PORT, exc
        )
        raise
    client.loop_start()
    return client


# ── OPC-UA ────────────────────────────────────────────────────────────────────


async def _build_opcua_server() -> tuple[Server, dict[str, dict[str, any]]]:
    """Initialise the OPC-UA server and build the node tree.

    Returns (server, node_map) where node_map is:
        {instance_id: {attr_name: asyncua_variable_node}}
    """
    server = Server()
    await server.init()
    server.set_endpoint(f"opc.tcp://0.0.0.0:{OPCUA_PORT}/waterworks")
    server.set_server_name("Waterworks-AI WTP Simulator")

    idx = await server.register_namespace(OPCUA_NS_URI)

    plant_folder = await server.nodes.objects.add_folder(
        ua.NodeId("Plant", idx), "Plant"
    )
    wtp_folder = await plant_folder.add_folder(ua.NodeId("Plant.WTP", idx), "WTP")

    node_map: dict[str, dict[str, any]] = {}
    type_folders: dict[str, any] = {}

    for obj_type, instance_id, attrs in INSTANCES:
        if obj_type not in type_folders:
            type_folders[obj_type] = await wtp_folder.add_folder(
                ua.NodeId(f"Plant.WTP.{obj_type}", idx), obj_type
            )
        inst_folder = await type_folders[obj_type].add_folder(
            ua.NodeId(f"Plant.WTP.{obj_type}.{instance_id}", idx), instance_id
        )
        node_map[instance_id] = {}
        for attr_name, gen in attrs.items():
            node_id = ua.NodeId(f"Plant.WTP.{obj_type}.{instance_id}.{attr_name}", idx)
            if isinstance(gen, OscillatingBool):
                var = await inst_folder.add_variable(
                    node_id, attr_name, bool(gen.value)
                )
            else:
                var = await inst_folder.add_variable(
                    node_id,
                    attr_name,
                    ua.Variant(float(gen.value), ua.VariantType.Float),
                )
            node_map[instance_id][attr_name] = var

    return server, node_map


# ── HTTP control plane ────────────────────────────────────────────────────────


def _build_control_app(mqtt_client: mqtt.Client) -> web.Application:
    """Build the aiohttp Application for the HTTP control plane.

    Split out from _start_control_plane so tests can exercise the handlers
    with aiohttp's TestClient/TestServer without binding a real TCP port.
    """

    async def handle_fault(request: web.Request) -> web.Response:
        target = request.query.get("target", "").strip()
        mode_str = request.query.get("mode", "normal").strip().lower()

        if not target:
            return web.Response(
                status=400,
                text=json.dumps({"error": "Missing ?target=<instance_id>"}),
                content_type="application/json",
            )
        if target not in fault_registry:
            known = list(fault_registry)
            return web.Response(
                status=404,
                text=json.dumps(
                    {"error": f"Unknown instance '{target}'", "known": known}
                ),
                content_type="application/json",
            )
        try:
            mode = FaultMode(mode_str)
        except ValueError:
            valid = [m.value for m in FaultMode]
            return web.Response(
                status=400,
                text=json.dumps(
                    {"error": f"Unknown mode '{mode_str}'", "valid": valid}
                ),
                content_type="application/json",
            )

        eq_type = instance_types.get(target, "")
        valid_for_type = TYPE_FAULT_MODES.get(eq_type, [FaultMode.NORMAL])
        if mode != FaultMode.NORMAL and mode not in valid_for_type:
            return web.Response(
                status=400,
                text=json.dumps(
                    {
                        "error": f"Fault mode '{mode_str}' is not valid for {eq_type} '{target}'",
                        "valid": [m.value for m in valid_for_type],
                    }
                ),
                content_type="application/json",
            )

        fault_registry[target].set_mode(mode)
        mqtt_client.publish(
            f"{MQTT_ROOT}/Events/FaultInjected",
            json.dumps({"target": target, "mode": mode.value}),
        )
        logger.info("Fault: %s → %s", target, mode.value)
        return web.Response(
            text=json.dumps({"target": target, "mode": mode.value}),
            content_type="application/json",
        )

    async def handle_status(request: web.Request) -> web.Response:
        payload = {iid: fs.mode.value for iid, fs in fault_registry.items()}
        return web.Response(
            text=json.dumps(payload, indent=2),
            content_type="application/json",
        )

    async def handle_fault_modes(request: web.Request) -> web.Response:
        payload = {
            instance_id: [
                m.value for m in TYPE_FAULT_MODES.get(itype, [FaultMode.NORMAL])
            ]
            for instance_id, itype in instance_types.items()
        }
        return web.Response(
            text=json.dumps(payload),
            content_type="application/json",
        )

    async def handle_setpoint(request: web.Request) -> web.Response:
        target = request.query.get("target", "").strip()
        attribute = request.query.get("attribute", "").strip()
        value_str = request.query.get("value", "").strip()

        if not target or not attribute or not value_str:
            return web.Response(
                status=400,
                text=json.dumps({"error": "Required params: target, attribute, value"}),
                content_type="application/json",
            )
        if target not in fault_registry:
            return web.Response(
                status=404,
                text=json.dumps(
                    {
                        "error": f"Unknown instance '{target}'",
                        "known": list(fault_registry),
                    }
                ),
                content_type="application/json",
            )
        try:
            value = float(value_str)
        except ValueError:
            return web.Response(
                status=400,
                text=json.dumps({"error": f"value must be numeric, got '{value_str}'"}),
                content_type="application/json",
            )
        if not math.isfinite(value):
            return web.Response(
                status=400,
                text=json.dumps({"error": f"value must be finite, got '{value_str}'"}),
                content_type="application/json",
            )

        known_attrs = instance_attributes(target)
        if attribute not in known_attrs:
            return web.Response(
                status=400,
                text=json.dumps(
                    {
                        "error": f"Unknown attribute '{attribute}' for '{target}'",
                        "known": sorted(known_attrs),
                    }
                ),
                content_type="application/json",
            )

        limits = engineering_limits(target, attribute)
        if limits is not None:
            lo, hi = limits
            if not lo <= value <= hi:
                return web.Response(
                    status=400,
                    text=json.dumps(
                        {
                            "error": (
                                f"{value} outside engineering limits "
                                f"[{lo}, {hi}] for {target}.{attribute}"
                            )
                        }
                    ),
                    content_type="application/json",
                )

        setpoint_overrides.setdefault(target, {})[attribute] = value
        logger.info("Setpoint: %s.%s → %s", target, attribute, value)
        return web.Response(
            text=json.dumps({"target": target, "attribute": attribute, "value": value}),
            content_type="application/json",
        )

    app = web.Application()
    app.router.add_post("/fault", handle_fault)
    app.router.add_post("/setpoint", handle_setpoint)
    app.router.add_get("/status", handle_status)
    app.router.add_get("/fault-modes", handle_fault_modes)
    return app


async def _start_control_plane(mqtt_client: mqtt.Client) -> None:
    """Start aiohttp server for fault injection. Returns immediately after bind."""
    app = _build_control_app(mqtt_client)

    runner = web.AppRunner(app)
    await runner.setup()
    await web.TCPSite(runner, "0.0.0.0", CONTROL_PORT).start()  # nosec B104
    logger.info(
        "Control plane    http://0.0.0.0:%d  POST /fault  POST /setpoint  GET /status",
        CONTROL_PORT,
    )


# ── Main ──────────────────────────────────────────────────────────────────────


async def main() -> None:
    mqtt_client = _start_mqtt()
    opcua_server, node_map = await _build_opcua_server()

    attr_count = sum(len(a) for _, _, a in INSTANCES)
    logger.info("WTP Simulator ready")
    logger.info("  MQTT    %s:%d  root=%s", MQTT_BROKER, MQTT_PORT, MQTT_ROOT)
    logger.info(
        "  OPC-UA  opc.tcp://0.0.0.0:%d/waterworks  ns=%s", OPCUA_PORT, OPCUA_NS_URI
    )
    logger.info(
        "  Units   %d instances  %d attributes  %.1fs interval",
        len(INSTANCES),
        attr_count,
        INTERVAL,
    )

    await _start_control_plane(mqtt_client)

    async with opcua_server:
        while True:
            for obj_type, instance_id, attrs in INSTANCES:
                fault = fault_registry[instance_id]
                fault.tick()
                for attr_name, gen in attrs.items():
                    raw = gen.next()
                    value = fault.apply(attr_name, raw)
                    sp_target = setpoint_overrides.get(instance_id, {}).get(attr_name)
                    if sp_target is not None:
                        if isinstance(value, bool):
                            # Boolean attributes (Running): apply directly, no ramping
                            value = bool(sp_target)
                        else:
                            inst_ramp = _setpoint_ramp.setdefault(instance_id, {})
                            if attr_name not in inst_ramp:
                                inst_ramp[attr_name] = value  # seed from live value
                            current = inst_ramp[attr_name]
                            gap = sp_target - current
                            current = (
                                sp_target
                                if abs(gap) < 0.01
                                else round(current + gap * _RAMP_FRACTION, 2)
                            )
                            inst_ramp[attr_name] = current
                            value = current

                    topic = f"{MQTT_ROOT}/{obj_type}/{instance_id}/{attr_name}"
                    payload = str(int(value) if isinstance(value, bool) else value)
                    mqtt_client.publish(topic, payload, retain=True)

                    var = node_map[instance_id][attr_name]
                    if isinstance(value, bool):
                        await var.write_value(bool(value))
                    else:
                        await var.write_value(
                            ua.Variant(float(value), ua.VariantType.Float)
                        )

            await asyncio.sleep(INTERVAL)


if __name__ == "__main__":
    try:
        asyncio.run(main())
    except KeyboardInterrupt:
        logger.info("Stopped.")
