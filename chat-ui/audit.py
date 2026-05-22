"""Per-turn audit log — appends JSONL entries to audit.jsonl."""

import json
import os
import threading
from datetime import datetime, timezone

_LOG_PATH = os.path.join(os.path.dirname(__file__), "audit.jsonl")
_lock = threading.Lock()


def _entry(event: str, **kwargs) -> dict:
    return {"ts": datetime.now(timezone.utc).isoformat(), "event": event, **kwargs}


def log(event: str, **kwargs) -> None:
    record = _entry(event, **kwargs)
    with _lock:
        with open(_LOG_PATH, "a", encoding="utf-8") as f:
            f.write(json.dumps(record) + "\n")


def read_log(limit: int = 500) -> list[dict]:
    if not os.path.exists(_LOG_PATH):
        return []
    with _lock:
        with open(_LOG_PATH, encoding="utf-8") as f:
            lines = f.readlines()
    entries = []
    for line in lines[-limit:]:
        try:
            entries.append(json.loads(line))
        except json.JSONDecodeError:
            pass
    return entries


def clear_log() -> None:
    with _lock:
        open(_LOG_PATH, "w").close()
