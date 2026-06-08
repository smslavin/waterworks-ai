"""
Legacy WTP MQTT publisher — interactive demo for topology builder.

Usage:
    python topology-builder/legacy_sim/publisher.py
    python topology-builder/legacy_sim/publisher.py --broker localhost:1883 --interval 2.0

Publishes the same messy topic set as the static test fixture, with live
random-walk values. Ghost tags (decommissioned equipment) publish once on
startup then go silent — mirroring real plants where MQTT bridges aren't
cleaned up when equipment is removed.

Run this instead of (or alongside) the main WTP simulator to demo topology
builder inference against a realistic legacy installation.
"""

import argparse
import asyncio
import random

import paho.mqtt.client as mqtt


# Topics published continuously. Tuple = (center, step) for random walk.
# None = boolean, published as "true" or hardcoded "false" for retired equipment.
LIVE_TOPICS: dict[str, tuple[float, float] | None] = {
    # Clean pump — standard path, all required attrs + duplicate flow sensors
    "Plant/WTP/Pump/RawWater_01/Flow":          (250.0, 5.0),
    "Plant/WTP/Pump/RawWater_01/Pressure":      (4.2,  0.1),
    "Plant/WTP/Pump/RawWater_01/Power":         (42.0, 1.0),
    "Plant/WTP/Pump/RawWater_01/Running":       None,
    "Plant/WTP/Pump/RawWater_01/FlowPrimary":   (252.0, 5.0),
    "Plant/WTP/Pump/RawWater_01/FlowBackup":    (248.0, 5.0),

    # Abbreviated attrs — operator has to tell inference what FLW/PRS/PWR/RUN mean
    "Plant/WTP/Pump/RawWater_02/FLW":           (290.0, 4.0),
    "Plant/WTP/Pump/RawWater_02/PRS":           (4.0,  0.1),
    "Plant/WTP/Pump/RawWater_02/PWR":           (38.0, 1.0),
    "Plant/WTP/Pump/RawWater_02/RUN":           None,

    # Non-standard depth — 3 levels instead of 5; matches only via legacy_patterns
    "WTP/HS_Pump_1/Flow":                       (220.0, 3.0),
    "WTP/HS_Pump_1/Pressure":                   (6.8,  0.2),
    "WTP/HS_Pump_1/Running":                    None,

    # Ambiguous equipment — no type match in template; Cascade will ask the operator
    "Plant/WTP/Drive/ABB_Drive_01/ActualSpeed": (1450.0, 20.0),
    "Plant/WTP/Drive/ABB_Drive_01/Torque":      (85.0, 5.0),
    "Plant/WTP/Drive/ABB_Drive_01/Running":     None,

    # Clarifier — clean + deprecated alias still publishing
    "Plant/WTP/Clarifier/Clarifier_01/Level":     (62.0, 0.5),
    "Plant/WTP/Clarifier/Clarifier_01/Turbidity": (2.1,  0.1),
    "Plant/WTP/Clarifier/Clarifier_01/TRBD":      (2.0,  0.1),

    # Storage tank — pH sensor offline, non-standard attrs publishing instead
    "Plant/WTP/StorageTank/FinishedWater_01/Level":     (78.0, 0.4),
    "Plant/WTP/StorageTank/FinishedWater_01/Turbidity": (0.4,  0.02),
    "Plant/WTP/StorageTank/FinishedWater_01/pH_raw":    (7.1,  0.05),
    "Plant/WTP/StorageTank/FinishedWater_01/pH_units":  None,  # publishes "pH" string

    # Dosing — clean
    "Plant/WTP/Dosing/Chlorine_01/FlowRate":    (3.2,  0.1),
    "Plant/WTP/Dosing/Chlorine_01/TankLevel":   (68.0, 0.2),
    "Plant/WTP/Dosing/Chlorine_01/Running":     None,

    # UV — active bank (clean)
    "Plant/WTP/UV/UV_01/Intensity":             (92.0, 0.3),
    "Plant/WTP/UV/UV_01/LampHours":             (4312.0, 0.01),
    "Plant/WTP/UV/UV_01/Running":               None,

    # UV — retired bank; constant zero, always "false", no OPC-UA
    "Plant/WTP/UV/UV_03/Intensity":             (0.0, 0.0),
    "Plant/WTP/UV/UV_03/LampHours":             (9999.0, 0.0),
    "Plant/WTP/UV/UV_03/Running":               None,

    # Vendor-prefixed namespace — Siemens S7 OPC-UA bridge with wrong root
    "Siemens/S7/Pump/HS_Pump_2/Speed_rpm":     (2900.0, 30.0),
    "Siemens/S7/Pump/HS_Pump_2/Current_mA":    (14.2, 0.3),
}

# These publish once on startup then go silent. Mirrors decommissioned equipment
# where the MQTT bridge was never cleaned up after removal.
GHOST_TOPICS: dict[str, str] = {
    "Plant/WTP/Pump/OldPump_03/Flow":           "0.0",
    "Plant/WTP/Pump/OldPump_03/Pressure":       "0.0",
}

_BOOLEAN_OVERRIDES: dict[str, str] = {
    "Plant/WTP/UV/UV_03/Running":               "false",
    "Plant/WTP/StorageTank/FinishedWater_01/pH_units": "pH",
    "Plant/WTP/Pump/RawWater_02/RUN":           "1",
}

_state: dict[str, float] = {
    t: v[0] for t, v in LIVE_TOPICS.items() if v is not None
}


def _next_value(topic: str, center: float, step: float) -> float:
    current = _state.get(topic, center)
    new_val = max(0.0, current + random.uniform(-step, step))
    _state[topic] = new_val
    return new_val


async def _publish_loop(client: mqtt.Client, interval: float) -> None:
    while True:
        for topic, spec in LIVE_TOPICS.items():
            if topic in _BOOLEAN_OVERRIDES:
                val = _BOOLEAN_OVERRIDES[topic]
            elif spec is None:
                val = "true"
            else:
                val = str(round(_next_value(topic, *spec), 2))
            client.publish(topic, val, qos=0)
        await asyncio.sleep(interval)


def main() -> None:
    parser = argparse.ArgumentParser(description="Legacy WTP MQTT publisher")
    parser.add_argument("--broker",   default="localhost:1883",
                        help="MQTT broker host:port (default: localhost:1883)")
    parser.add_argument("--interval", type=float, default=2.0,
                        help="Publish interval in seconds (default: 2.0)")
    args = parser.parse_args()

    parts = args.broker.rsplit(":", 1)
    host = parts[0]
    port = int(parts[1]) if len(parts) == 2 else 1883

    client = mqtt.Client(mqtt.CallbackAPIVersion.VERSION2)
    client.connect(host, port, keepalive=60)
    client.loop_start()

    for topic, val in GHOST_TOPICS.items():
        client.publish(topic, val, qos=1, retain=True)
    print(f"[legacy_sim] Ghost tags published ({len(GHOST_TOPICS)} topics, retained).")
    print(f"[legacy_sim] Live loop starting — {len(LIVE_TOPICS)} topics @ {args.broker} "
          f"every {args.interval}s. Ctrl+C to stop.")

    try:
        asyncio.run(_publish_loop(client, args.interval))
    except KeyboardInterrupt:
        print("\n[legacy_sim] Stopped.")
    finally:
        client.loop_stop()
        client.disconnect()


if __name__ == "__main__":
    main()
