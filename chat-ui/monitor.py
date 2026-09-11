"""MQTT anomaly monitor. Watches PLANT_TOPIC_ROOT/# (default Plant/WTP/#) against
topology normal ranges.

Severity comes from LadybugDB via memory-mcp's get_severity_for_attribute
tool (fieldworks-core#6/#7) rather than static topology.yaml alarm_lo/
alarm_hi config — fetched once at startup (see _populate_severities), not
per-message, so the synchronous _on_message callback never needs to await.
"""

import asyncio
import json
import logging
import os
import threading
import time

import paho.mqtt.client as mqtt

from mcp_client import call_mcp_tool
from topology import load as _load_topology

logger = logging.getLogger(__name__)

PLANT_TOPIC_ROOT = os.environ.get("PLANT_TOPIC_ROOT", "Plant/WTP")

_topology = _load_topology()
_window: dict[tuple, dict] = {}
# _window is written from paho's loop_start() network thread (_on_message)
# and read from the asyncio event-loop thread (current_status_level(), on
# the /api/plant-status heartbeat path). Both sides must hold this lock —
# a snapshot copy on the read side alone wouldn't fix the torn read/write
# on a nested dict value (e.g. _window[key]["value"] = value racing a
# concurrent v.get("severity") read), only serializing both sides does.
_window_lock = threading.Lock()

# Per-topic "already warned" set for _on_message's parse-failure logging —
# bounds a stuck/garbage-publishing device to one warning until it recovers,
# instead of unbounded spam. Only ever touched from the paho network thread
# (_on_message runs exclusively there), so it needs no lock of its own.
_warned_topics: set[str] = set()

_DEFAULT_SEVERITY = "warning"  # used until _populate_severities() completes


def _build_normal_map() -> dict[tuple, dict]:
    """Return {(instance_name, attribute_name): {normal, eq_type, type_id,
    attr_id, severity_below, severity_above}} for all numeric attributes.
    Boolean/discrete attributes (e.g. Running) aren't watched for threshold
    excursions, matching the original topology.yaml-based behavior.
    """
    result = {}
    for eq_type in _topology.equipment_types:
        instances = [
            i for i in _topology.equipment_instances if i.type_id == eq_type.id
        ]
        for attr in eq_type.attributes:
            if attr.data_type != "numeric":
                continue
            for inst in instances:
                result[(inst.name, attr.name)] = {
                    "normal": (attr.normal_range.min, attr.normal_range.max),
                    "eq_type": eq_type.name,
                    "type_id": eq_type.id,
                    "attr_id": attr.id,
                    "severity_below": _DEFAULT_SEVERITY,
                    "severity_above": _DEFAULT_SEVERITY,
                }
    return result


_NORMAL_MAP = _build_normal_map()


async def _populate_severities(aggregator_url: str) -> None:
    """Fetch real severities from LadybugDB via memory-mcp. Call once at
    monitor startup, before the MQTT client connects, so no message can
    arrive before _NORMAL_MAP has real severities.
    """
    for key, meta in _NORMAL_MAP.items():
        for condition, field in (
            ("below_min", "severity_below"),
            ("above_max", "severity_above"),
        ):
            try:
                raw = await call_mcp_tool(
                    "memory__get_severity_for_attribute",
                    {
                        "type_id": meta["type_id"],
                        "attr_id": meta["attr_id"],
                        "condition": condition,
                    },
                    aggregator_url,
                )
                severity = json.loads(raw)
                if severity:
                    meta[field] = severity
            except Exception as e:
                logger.warning(
                    "severity fetch failed for %s (%s): %s — using default %r",
                    key,
                    condition,
                    e,
                    _DEFAULT_SEVERITY,
                )


def current_status_level() -> str:
    """Worst-of severity across everything currently in _window (out of
    range), in the Normal/Anomaly Detected/Fault Detected vocabulary used
    everywhere else (session_summaries.status, specialist FINDINGS) rather
    than monitor's own raw warning/critical labels — so status_heartbeat.py
    can compare this directly against a specialist-generated status without
    a separate mapping step. This is the raw threshold read, not Deadband's
    verified verdict (see reactive_loop.py) — cheap and always-on by design,
    so it can be more sensitive to noise than an escalation trigger would
    be; the narrative half of the heartbeat still goes through a real
    diagnosis, which accounts for that.
    """
    with _window_lock:
        if not _window:
            return "Normal"
        if any(v.get("severity") == "critical" for v in _window.values()):
            return "Fault Detected"
        return "Anomaly Detected"


class AnomalyMonitor:
    def __init__(
        self, broker_url: str, aggregator_url: str, min_duration: float = 30.0
    ):
        host, port = (
            broker_url.split(":") if ":" in broker_url else (broker_url, "1883")
        )
        self._host = host
        self._port = int(port)
        self._aggregator_url = aggregator_url
        self._min_duration = min_duration
        # Bounded: this monitor now runs unconditionally (see backend.py's
        # lifespan), independent of whether anything is consuming .events()
        # (only the reactive escalation task does, gated behind
        # REACTIVE_ENABLED). current_status_level() reads _window directly,
        # not this queue, so dropping on overflow when there's no active
        # consumer is safe — it only means a stale escalation-worthy anomaly
        # from before reactive was turned on doesn't get replayed, which is
        # the desired behavior anyway.
        self._queue: asyncio.Queue = asyncio.Queue(maxsize=200)
        self._loop = None
        # paho 2.x requires CallbackAPIVersion
        self._client = mqtt.Client(mqtt.CallbackAPIVersion.VERSION1)
        self._client.reconnect_delay_set(min_delay=1, max_delay=60)
        self._client.on_connect = self._on_connect
        self._client.on_message = self._on_message

    def _on_connect(self, client, userdata, flags, rc):
        if rc == 0:
            client.subscribe(f"{PLANT_TOPIC_ROOT}/#")
            logger.info("Anomaly monitor connected to MQTT broker")
        else:
            logger.error("Anomaly monitor MQTT connect failed  rc=%d", rc)

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
            # Parseable again — clear any standing "already warned" state for
            # this topic so a future parse failure warns again (see except
            # block below).
            _warned_topics.discard(msg.topic)
            lo, hi = meta["normal"]
            now = time.time()

            span = hi - lo
            in_normal = lo <= value <= hi
            minor_excursion = (value < lo and (lo - value) < 0.02 * span) or (
                value > hi and (value - hi) < 0.02 * span
            )

            anomaly = None
            with _window_lock:
                if in_normal or minor_excursion:
                    if key in _window:
                        # Value returned toward normal — start a grace period rather than
                        # immediately resetting. Oscillating faults (level_sensor_fault)
                        # briefly cross back into range; only truly clear after 10s sustained.
                        ws = _window[key].setdefault("recovery_start", now)
                        if now - ws >= 10.0:
                            _window.pop(key, None)
                else:
                    condition = "below_min" if value < lo else "above_max"
                    severity = (
                        meta["severity_below"]
                        if condition == "below_min"
                        else meta["severity_above"]
                    )

                    if key not in _window:
                        _window[key] = {
                            "violation_start": now,
                            "condition": condition,
                            "severity": severity,
                            "value": value,
                        }
                    else:
                        # Back in significant violation — cancel any pending recovery
                        _window[key].pop("recovery_start", None)
                        _window[key]["value"] = value
                        elapsed = now - _window[key]["violation_start"]
                        # Re-queue every min_duration seconds while the fault persists.
                        # The reactive loop's _can_trigger (cooldown + _active) handles
                        # deduplication. A permanent fired=True flag caused silently
                        # dropped faults when _MAX_CONCURRENT was full — those instances
                        # would never re-trigger after being blocked.
                        last_fire = _window[key].get("last_fire", 0)
                        if (
                            elapsed >= self._min_duration
                            and now - last_fire >= self._min_duration
                        ):
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

            if anomaly is not None and self._loop:
                self._loop.call_soon_threadsafe(self._enqueue, anomaly)
        except Exception as e:
            # Default log level is INFO — logger.debug here would make a
            # device stuck sending garbage (a unit string, JSON, a bad
            # payload) silently and permanently stop being monitored, with
            # no visible sign of it. Bounded to one warning per topic until
            # it recovers (see the _warned_topics.discard above) so a device
            # wedged in a parse-failure loop doesn't spam the log forever.
            if msg.topic not in _warned_topics:
                logger.warning(
                    "monitor: failed to parse/process message on topic %s "
                    "(payload=%r): %s",
                    msg.topic,
                    msg.payload,
                    e,
                )
                _warned_topics.add(msg.topic)

    def _enqueue(self, anomaly: dict) -> None:
        try:
            self._queue.put_nowait(anomaly)
        except asyncio.QueueFull:
            pass  # no active consumer draining .events() right now — see __init__

    async def start(self):
        self._loop = asyncio.get_event_loop()
        await _populate_severities(self._aggregator_url)
        self._client.connect_async(self._host, self._port)
        self._client.loop_start()
        logger.info("Anomaly monitor started (min_duration=%.0fs)", self._min_duration)

    async def events(self):
        while True:
            yield await self._queue.get()
