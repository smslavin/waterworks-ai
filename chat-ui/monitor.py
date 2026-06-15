"""MQTT anomaly monitor. Watches Plant/WTP/# against topology.yaml normal ranges and alarm severities."""

import asyncio
import logging
import time

import paho.mqtt.client as mqtt

from topology import load as _load_topology

logger = logging.getLogger(__name__)

_topology = _load_topology()
_window: dict[tuple, dict] = {}


def _build_normal_map() -> dict[tuple, dict]:
    """Return {(instance_id, attribute): {normal, alarm_lo, alarm_hi, eq_type}} for all numeric attributes."""
    result = {}
    types = _topology.get("equipment_types", {})
    for eq_type, type_def in types.items():
        for attr, attr_def in type_def.get("attributes", {}).items():
            if "normal" not in attr_def:
                continue
            for inst in _topology.get("instances", {}).get(eq_type, []):
                result[(inst["id"], attr)] = {
                    "normal": attr_def["normal"],
                    "alarm_lo": attr_def.get("alarm_lo", "warning"),
                    "alarm_hi": attr_def.get("alarm_hi", "warning"),
                    "eq_type": eq_type,
                }
    return result


_NORMAL_MAP = _build_normal_map()


class AnomalyMonitor:
    def __init__(self, broker_url: str, min_duration: float = 30.0):
        host, port = (
            broker_url.split(":") if ":" in broker_url else (broker_url, "1883")
        )
        self._host = host
        self._port = int(port)
        self._min_duration = min_duration
        self._queue: asyncio.Queue = asyncio.Queue()
        self._loop = None
        # paho 2.x requires CallbackAPIVersion
        self._client = mqtt.Client(mqtt.CallbackAPIVersion.VERSION1)
        self._client.reconnect_delay_set(min_delay=1, max_delay=60)
        self._client.on_connect = self._on_connect
        self._client.on_message = self._on_message

    def _on_connect(self, client, userdata, flags, rc):
        client.subscribe("Plant/WTP/#")
        logger.info("Anomaly monitor connected to MQTT broker")

    def _on_message(self, client, userdata, msg):
        try:
            parts = msg.topic.split("/")
            if len(parts) != 5:
                return
            _, _, eq_type, instance_id, attribute = parts
            key = (instance_id, attribute)
            if key not in _NORMAL_MAP:
                return
            meta = _NORMAL_MAP[key]
            value = float(msg.payload.decode())
            lo, hi = meta["normal"]
            now = time.time()

            span = hi - lo
            in_normal = lo <= value <= hi
            minor_excursion = (value < lo and (lo - value) < 0.02 * span) or (
                value > hi and (value - hi) < 0.02 * span
            )

            if in_normal or minor_excursion:
                if key in _window:
                    # Value returned toward normal — start a grace period rather than
                    # immediately resetting. Oscillating faults (level_sensor_fault)
                    # briefly cross back into range; only truly clear after 10s sustained.
                    ws = _window[key].setdefault("recovery_start", now)
                    if now - ws >= 10.0:
                        _window.pop(key, None)
                return

            condition = "below_min" if value < lo else "above_max"
            severity = (
                meta["alarm_lo"] if condition == "below_min" else meta["alarm_hi"]
            )

            if key not in _window:
                _window[key] = {
                    "violation_start": now,
                    "condition": condition,
                    "severity": severity,
                    "value": value,
                }
                return

            # Back in significant violation — cancel any pending recovery
            _window[key].pop("recovery_start", None)
            _window[key]["value"] = value
            elapsed = now - _window[key]["violation_start"]
            # Re-queue every min_duration seconds while the fault persists.
            # The reactive loop's _can_trigger (cooldown + _active) handles deduplication.
            # A permanent fired=True flag caused silently dropped faults when _MAX_CONCURRENT
            # was full — those instances would never re-trigger after being blocked.
            last_fire = _window[key].get("last_fire", 0)
            if elapsed >= self._min_duration and now - last_fire >= self._min_duration:
                _window[key]["last_fire"] = now
                anomaly = {
                    "instance_id": instance_id,
                    "equipment_type": eq_type,
                    "attribute": attribute,
                    "current_value": value,
                    "normal_range": [lo, hi],
                    "condition": condition,
                    "severity": severity,
                    "duration_seconds": elapsed,
                }
                if self._loop:
                    self._loop.call_soon_threadsafe(self._queue.put_nowait, anomaly)
        except Exception as e:
            logger.debug("monitor parse error: %s", e)

    async def start(self):
        self._loop = asyncio.get_event_loop()
        self._client.connect_async(self._host, self._port)
        self._client.loop_start()
        logger.info("Anomaly monitor started (min_duration=%.0fs)", self._min_duration)

    async def events(self):
        while True:
            yield await self._queue.get()
