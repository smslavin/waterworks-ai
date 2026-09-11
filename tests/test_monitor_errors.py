"""Regression tests for gh-19: monitor.py's _window dict was mutated from
paho's network thread and iterated from the event loop with no lock (can
raise RuntimeError: dictionary changed size during iteration on the
/api/plant-status heartbeat path), _on_message's parse failures were logged
at DEBUG (invisible at the default INFO level) and unbounded, and
_on_connect ignored the MQTT connect return code.
"""

import logging
import threading
import time

import monitor


class _FakeMsg:
    def __init__(self, topic: str, payload: bytes):
        self.topic = topic
        self.payload = payload


class _FakeClient:
    def __init__(self):
        self.subscribed_to = None

    def subscribe(self, topic):
        self.subscribed_to = topic


def _pick_key():
    """Grab a real (instance, attribute) pair from _NORMAL_MAP so tests
    exercise the actual topology-derived thresholds rather than fabricated
    ones."""
    key = next(iter(monitor._NORMAL_MAP))
    meta = monitor._NORMAL_MAP[key]
    instance_id, attribute = key
    topic = f"Plant/WTP/{meta['eq_type']}/{instance_id}/{attribute}"
    return key, meta, topic


def _new_monitor(min_duration: float = 0.0) -> monitor.AnomalyMonitor:
    m = monitor.AnomalyMonitor.__new__(monitor.AnomalyMonitor)
    m._min_duration = min_duration
    m._loop = None  # _on_message guards `if anomaly is not None and self._loop`
    return m


# ── _on_connect: must check rc, not log "connected" unconditionally ────────


def test_on_connect_subscribes_and_logs_info_on_success(caplog):
    m = _new_monitor()
    client = _FakeClient()
    with caplog.at_level(logging.INFO, logger="monitor"):
        m._on_connect(client, None, None, 0)
    assert client.subscribed_to == f"{monitor.PLANT_TOPIC_ROOT}/#"
    assert any("connected" in r.message.lower() for r in caplog.records)


def test_on_connect_does_not_subscribe_and_logs_error_on_failure(caplog):
    m = _new_monitor()
    client = _FakeClient()
    with caplog.at_level(logging.ERROR, logger="monitor"):
        m._on_connect(client, None, None, 5)  # rc=5: not authorized
    assert client.subscribed_to is None
    assert any(
        "connect failed" in r.message and r.levelno == logging.ERROR
        for r in caplog.records
    )


# ── _on_message: parse failures must warn (not debug) and be bounded ───────


def test_on_message_warns_on_unparseable_payload(caplog):
    _, _, topic = _pick_key()
    monitor._warned_topics.discard(topic)
    m = _new_monitor(min_duration=30.0)
    with caplog.at_level(logging.WARNING, logger="monitor"):
        m._on_message(None, None, _FakeMsg(topic, b"12.5 psi"))
    assert topic in monitor._warned_topics
    records = [r for r in caplog.records if r.levelno == logging.WARNING]
    assert any("failed to parse/process message" in r.message for r in records)
    assert any(topic in r.message for r in records)


def test_on_message_bounds_repeated_warnings_for_same_topic(caplog):
    _, _, topic = _pick_key()
    monitor._warned_topics.discard(topic)
    m = _new_monitor(min_duration=30.0)
    with caplog.at_level(logging.WARNING, logger="monitor"):
        m._on_message(None, None, _FakeMsg(topic, b"not-a-number"))
        m._on_message(None, None, _FakeMsg(topic, b"still-not-a-number"))
        m._on_message(None, None, _FakeMsg(topic, b"nope"))
    warnings = [
        r
        for r in caplog.records
        if r.levelno == logging.WARNING and "failed to parse" in r.message
    ]
    assert len(warnings) == 1  # a device stuck sending garbage warns once, not 3x


def test_on_message_warns_again_after_recovery(caplog):
    key, meta, topic = _pick_key()
    monitor._warned_topics.discard(topic)
    with monitor._window_lock:
        monitor._window.pop(key, None)
    m = _new_monitor(min_duration=30.0)
    lo, hi = meta["normal"]
    good_value = (lo + hi) / 2.0

    with caplog.at_level(logging.WARNING, logger="monitor"):
        m._on_message(None, None, _FakeMsg(topic, b"garbage-1"))
        assert topic in monitor._warned_topics
        m._on_message(None, None, _FakeMsg(topic, str(good_value).encode()))
        assert topic not in monitor._warned_topics  # recovered — flag cleared
        m._on_message(None, None, _FakeMsg(topic, b"garbage-2"))

    warnings = [
        r
        for r in caplog.records
        if r.levelno == logging.WARNING and "failed to parse" in r.message
    ]
    assert len(warnings) == 2  # warned once, recovered, warned again


# ── _window race: lock must survive concurrent read (current_status_level)
#    and write (_on_message) from separate threads without raising ─────────


def test_window_lock_survives_concurrent_readers_and_writers():
    keys = list(monitor._NORMAL_MAP.items())[:3]
    assert keys, "topology must expose at least one numeric attribute to test"

    with monitor._window_lock:
        for key, _ in keys:
            monitor._window.pop(key, None)

    m = _new_monitor(min_duration=0.0)  # fire on every call, maximize churn
    errors: list[Exception] = []
    stop = threading.Event()

    def writer(key, meta):
        instance_id, attribute = key
        topic = f"Plant/WTP/{meta['eq_type']}/{instance_id}/{attribute}"
        lo, hi = meta["normal"]
        out_of_range = hi + max(1.0, (hi - lo))
        in_range = (lo + hi) / 2.0
        toggle = False
        try:
            while not stop.is_set():
                val = out_of_range if toggle else in_range
                toggle = not toggle
                m._on_message(None, None, _FakeMsg(topic, str(val).encode()))
        except Exception as exc:  # pragma: no cover - only on real bug
            errors.append(exc)

    def reader():
        try:
            while not stop.is_set():
                monitor.current_status_level()
        except Exception as exc:  # pragma: no cover - only on real bug
            errors.append(exc)

    threads = [threading.Thread(target=writer, args=(k, meta)) for k, meta in keys]
    threads += [threading.Thread(target=reader) for _ in range(4)]

    for t in threads:
        t.start()
    time.sleep(0.5)
    stop.set()
    for t in threads:
        t.join(timeout=5)

    with monitor._window_lock:
        for key, _ in keys:
            monitor._window.pop(key, None)

    assert errors == [], f"lock did not prevent races: {errors!r}"


def test_current_status_level_reflects_window_contents():
    with monitor._window_lock:
        monitor._window.clear()
    assert monitor.current_status_level() == "Normal"

    key, meta, _ = _pick_key()
    with monitor._window_lock:
        monitor._window[key] = {
            "violation_start": time.time(),
            "condition": "above_max",
            "severity": "warning",
            "value": meta["normal"][1] + 1,
        }
    assert monitor.current_status_level() == "Anomaly Detected"

    with monitor._window_lock:
        monitor._window[key]["severity"] = "critical"
    assert monitor.current_status_level() == "Fault Detected"

    with monitor._window_lock:
        monitor._window.clear()
