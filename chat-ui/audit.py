"""Per-turn audit log — encrypted, hash-chained, append-only."""

import base64
import hashlib
import json
import os
import threading
from datetime import datetime, timezone
from pathlib import Path

try:
    from cryptography.hazmat.primitives.ciphers.aead import AESGCM

    _CRYPTO_AVAILABLE = True
except ImportError:
    _CRYPTO_AVAILABLE = False
    import warnings

    warnings.warn(
        "cryptography package not installed — audit log will be unencrypted",
        stacklevel=1,
    )

LOG_PATH = Path(os.environ.get("AUDIT_LOG_PATH", Path(__file__).parent / "audit.jsonl"))
_KEY_B64 = os.environ.get("AUDIT_KEY", "")
_lock = threading.Lock()
_seq = 0
_prev_hash = ""  # SHA-256 hex of last written encoded line


def _get_key() -> bytes | None:
    if not _KEY_B64 or not _CRYPTO_AVAILABLE:
        return None
    try:
        key = base64.b64decode(_KEY_B64)
        return key if len(key) == 32 else None
    except Exception:
        return None


def _hash_line(line: str) -> str:
    return hashlib.sha256(line.encode()).hexdigest()


def _encode(payload: str, key: bytes | None) -> str:
    if key:
        nonce = os.urandom(12)
        ct = AESGCM(key).encrypt(nonce, payload.encode(), None)
        return base64.urlsafe_b64encode(nonce + ct).decode().rstrip("=")
    return payload


def _decode(line: str, key: bytes | None) -> str:
    if key:
        padded = line + "=" * (-len(line) % 4)
        raw = base64.urlsafe_b64decode(padded)
        nonce, ct = raw[:12], raw[12:]
        return AESGCM(key).decrypt(nonce, ct, None).decode()
    return line


def _load_state() -> None:
    """Recover _seq and _prev_hash from the last line of an existing log."""
    global _seq, _prev_hash
    if not LOG_PATH.exists():
        return
    key = _get_key()
    with open(LOG_PATH, encoding="utf-8") as f:
        lines = [l.strip() for l in f if l.strip()]
    if not lines:
        return
    last_line = lines[-1]
    _prev_hash = _hash_line(last_line)
    try:
        payload = json.loads(_decode(last_line, key))
        _seq = payload.get("seq", 0)
    except Exception:
        pass  # corrupted last line — seq stays at 0, chain breaks on next write


def log(event: str, **kwargs) -> None:
    global _seq, _prev_hash
    key = _get_key()
    with _lock:
        _seq += 1
        record = {
            "seq": _seq,
            "prev": _prev_hash,
            "ts": datetime.now(timezone.utc).isoformat(),
            "event": event,
            **kwargs,
        }
        payload = json.dumps(record, separators=(",", ":"))
        line = _encode(payload, key)
        _prev_hash = _hash_line(line)
        with open(LOG_PATH, "a", encoding="utf-8") as f:
            f.write(line + "\n")


def read_log(limit: int = 500) -> list[dict]:
    """Decrypt and return the last `limit` records for UI display."""
    if not LOG_PATH.exists():
        return []
    key = _get_key()
    with _lock:
        with open(LOG_PATH, encoding="utf-8") as f:
            lines = [l.strip() for l in f if l.strip()]
    entries = []
    for line in lines[-limit:]:
        try:
            entries.append(json.loads(_decode(line, key)))
        except Exception:
            entries.append({"error": "decryption_failed", "preview": line[:40]})
    return entries


def rotate_log() -> str:
    """
    Archive the current log and start a new one.
    Returns the archive path. Replaces clear_log().
    """
    global _seq, _prev_hash
    with _lock:
        archive_path = ""
        if LOG_PATH.exists() and LOG_PATH.stat().st_size > 0:
            ts = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
            archive = LOG_PATH.with_name(f"audit.{ts}.jsonl")
            LOG_PATH.rename(archive)
            archive_path = str(archive)
        _seq = 0
        _prev_hash = ""
    log("log_rotated", archived=archive_path)
    return archive_path


# Recover continuity on import
_load_state()
