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
OPCUA_PORT          OPC-UA server port       (default: 4840)
CONTROL_PORT        HTTP control plane port  (default: 8090)
PUBLISH_INTERVAL    Seconds between ticks    (default: 2.0)
"""

import asyncio
import json
import logging
import os

import paho.mqtt.client as mqtt
from aiohttp import web
from asyncua import Server, ua
from dotenv import load_dotenv

from faults import FaultMode, FaultState, TYPE_FAULT_MODES
from generators import OscillatingBool
from instances import INSTANCES

load_dotenv()

MQTT_BROKER  = os.environ.get("MQTT_BROKER_URL", "localhost")
MQTT_PORT    = int(os.environ.get("MQTT_BROKER_PORT", 1883))
OPCUA_PORT   = int(os.environ.get("OPCUA_PORT", 4840))
CONTROL_PORT = int(os.environ.get("CONTROL_PORT", 8090))
INTERVAL     = float(os.environ.get("PUBLISH_INTERVAL", 2.0))

MQTT_ROOT    = "Plant/WTP"
OPCUA_NS_URI = "urn:waterworks-ai:simulator"

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s %(levelname)s %(name)s: %(message)s",
)
logger = logging.getLogger("waterworks-simulator")


# ── Fault registry ────────────────────────────────────────────────────────────

fault_registry: dict[str, FaultState] = {
    instance_id: FaultState()
    for _, instance_id, _ in INSTANCES
}

instance_types: dict[str, str] = {
    instance_id: obj_type
    for obj_type, instance_id, _ in INSTANCES
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
        logger.error("Cannot reach MQTT broker at %s:%d — %s", MQTT_BROKER, MQTT_PORT, exc)
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
    wtp_folder = await plant_folder.add_folder(
        ua.NodeId("Plant.WTP", idx), "WTP"
    )

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
                var = await inst_folder.add_variable(node_id, attr_name, bool(gen.value))
            else:
                var = await inst_folder.add_variable(
                    node_id, attr_name,
                    ua.Variant(float(gen.value), ua.VariantType.Float),
                )
            node_map[instance_id][attr_name] = var

    return server, node_map


# ── HTTP control plane ────────────────────────────────────────────────────────

async def _start_control_plane(mqtt_client: mqtt.Client) -> None:
    """Start aiohttp server for fault injection. Returns immediately after bind."""

    async def handle_fault(request: web.Request) -> web.Response:
        target   = request.query.get("target", "").strip()
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
                text=json.dumps({"error": f"Unknown instance '{target}'", "known": known}),
                content_type="application/json",
            )
        try:
            mode = FaultMode(mode_str)
        except ValueError:
            valid = [m.value for m in FaultMode]
            return web.Response(
                status=400,
                text=json.dumps({"error": f"Unknown mode '{mode_str}'", "valid": valid}),
                content_type="application/json",
            )

        eq_type = instance_types.get(target, "")
        valid_for_type = TYPE_FAULT_MODES.get(eq_type, [FaultMode.NORMAL])
        if mode != FaultMode.NORMAL and mode not in valid_for_type:
            return web.Response(
                status=400,
                text=json.dumps({
                    "error": f"Fault mode '{mode_str}' is not valid for {eq_type} '{target}'",
                    "valid": [m.value for m in valid_for_type],
                }),
                content_type="application/json",
            )

        fault_registry[target].set_mode(mode)
        mqtt_client.publish(
            "Plant/WTP/Events/FaultInjected",
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
            instance_id: [m.value for m in TYPE_FAULT_MODES.get(itype, [FaultMode.NORMAL])]
            for instance_id, itype in instance_types.items()
        }
        return web.Response(
            text=json.dumps(payload),
            content_type="application/json",
        )

    async def handle_setpoint(request: web.Request) -> web.Response:
        target    = request.query.get("target", "").strip()
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
                text=json.dumps({"error": f"Unknown instance '{target}'",
                                 "known": list(fault_registry)}),
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

        setpoint_overrides.setdefault(target, {})[attribute] = value
        logger.info("Setpoint: %s.%s → %s", target, attribute, value)
        return web.Response(
            text=json.dumps({"target": target, "attribute": attribute, "value": value}),
            content_type="application/json",
        )

    app = web.Application()
    app.router.add_post("/fault",       handle_fault)
    app.router.add_post("/setpoint",    handle_setpoint)
    app.router.add_get("/status",       handle_status)
    app.router.add_get("/fault-modes",  handle_fault_modes)

    runner = web.AppRunner(app)
    await runner.setup()
    await web.TCPSite(runner, "0.0.0.0", CONTROL_PORT).start()
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
    logger.info("  OPC-UA  opc.tcp://0.0.0.0:%d/waterworks  ns=%s", OPCUA_PORT, OPCUA_NS_URI)
    logger.info("  Units   %d instances  %d attributes  %.1fs interval",
                len(INSTANCES), attr_count, INTERVAL)

    await _start_control_plane(mqtt_client)

    async with opcua_server:
        while True:
            for obj_type, instance_id, attrs in INSTANCES:
                fault = fault_registry[instance_id]
                fault.tick()
                for attr_name, gen in attrs.items():
                    raw   = gen.next()
                    value = fault.apply(attr_name, raw)
                    sp_target = setpoint_overrides.get(instance_id, {}).get(attr_name)
                    if sp_target is not None:
                        inst_ramp = _setpoint_ramp.setdefault(instance_id, {})
                        if attr_name not in inst_ramp:
                            inst_ramp[attr_name] = value  # seed from live value
                        current = inst_ramp[attr_name]
                        gap = sp_target - current
                        current = sp_target if abs(gap) < 0.01 else round(current + gap * _RAMP_FRACTION, 2)
                        inst_ramp[attr_name] = current
                        value = current

                    topic   = f"{MQTT_ROOT}/{obj_type}/{instance_id}/{attr_name}"
                    payload = str(int(value) if isinstance(value, bool) else value)
                    mqtt_client.publish(topic, payload, retain=True)

                    var = node_map[instance_id][attr_name]
                    if isinstance(value, bool):
                        await var.write_value(bool(value))
                    else:
                        await var.write_value(ua.Variant(float(value), ua.VariantType.Float))

            await asyncio.sleep(INTERVAL)


if __name__ == "__main__":
    try:
        asyncio.run(main())
    except KeyboardInterrupt:
        logger.info("Stopped.")
