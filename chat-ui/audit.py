"""Per-turn audit log — encrypted, hash-chained, append-only.

Chain integrity: each line's `prev` is an HMAC-SHA256 of the previous line
under AUDIT_KEY (not a plain hash — a plain hash lets anyone who can write
the file recompute the chain after editing it; the HMAC requires the key).
`seq` must increase by exactly 1 record to record; audit_verify.py checks
both. rotate_log() seeds the new file's first record with the archive's
final hash, so the chain spans the rotation instead of restarting blind.

AUDIT_KEY: unset is allowed (plaintext, dev mode) and logs a WARNING. Set
but invalid (bad base64, wrong decoded length, or the `cryptography`
package missing) raises at import — a misconfigured key must never
silently downgrade to plaintext. Set AUDIT_REQUIRE_ENCRYPTION=1 to refuse
to start at all without a valid key.
"""

import base64
import hashlib
import hmac
import json
import os
import threading
import warnings
from datetime import datetime, timezone
from pathlib import Path

try:
    from cryptography.hazmat.primitives.ciphers.aead import AESGCM

    _CRYPTO_AVAILABLE = True
except ImportError:
    _CRYPTO_AVAILABLE = False

LOG_PATH = Path(os.environ.get("AUDIT_LOG_PATH", Path(__file__).parent / "audit.jsonl"))
_REQUIRE_ENCRYPTION = os.environ.get("AUDIT_REQUIRE_ENCRYPTION", "0") == "1"
_lock = threading.Lock()
_seq = 0
_prev_hash = ""  # HMAC-SHA256 hex (keyed) or SHA-256 hex (unkeyed) of last written line


def _load_key() -> bytes | None:
    raw = os.environ.get("AUDIT_KEY", "")
    if not raw:
        if _REQUIRE_ENCRYPTION:
            raise RuntimeError(
                "AUDIT_REQUIRE_ENCRYPTION=1 but AUDIT_KEY is unset. Set a valid "
                "base64-encoded 32-byte AUDIT_KEY or unset AUDIT_REQUIRE_ENCRYPTION."
            )
        warnings.warn(
            "AUDIT_KEY unset — audit log will be written in plaintext "
            "(dev mode only; set AUDIT_KEY in production).",
            stacklevel=1,
        )
        return None
    if not _CRYPTO_AVAILABLE:
        raise RuntimeError(
            "AUDIT_KEY is set but the 'cryptography' package is not installed — "
            "refusing to silently fall back to plaintext. Install cryptography "
            "or unset AUDIT_KEY."
        )
    try:
        key = base64.b64decode(raw, validate=True)
    except Exception as exc:
        raise RuntimeError(f"AUDIT_KEY is not valid base64: {exc}") from exc
    if len(key) != 32:
        raise RuntimeError(
            f"AUDIT_KEY must decode to exactly 32 bytes, got {len(key)}."
        )
    return key


_KEY = _load_key()
MODE = "encrypted" if _KEY else "plaintext"


def _get_key() -> bytes | None:
    return _KEY


def _hash_line(line: str) -> str:
    """Chain link for `line`: HMAC-SHA256 under AUDIT_KEY if set, else a plain
    SHA-256 (unkeyed — plaintext mode has no secret to key it with, so the
    chain there only catches accidental corruption, not deliberate tampering;
    that's what plaintext mode already gives up)."""
    if _KEY:
        return hmac.new(_KEY, line.encode(), hashlib.sha256).hexdigest()
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
    Archive the current log and start a new one. The chain spans the
    rotation: the new log's first record carries the archive's final line
    hash as its `prev`, rather than resetting to "" — an empty `prev` on a
    non-first file would otherwise look identical to (and be indistinguishable
    from) a legitimately fresh log, letting a rotation quietly sever history
    without verify() ever flagging it.
    Returns the archive path. Replaces clear_log().
    """
    global _seq, _prev_hash
    with _lock:
        archive_path = ""
        chain_from = _prev_hash
        if LOG_PATH.exists() and LOG_PATH.stat().st_size > 0:
            ts = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
            archive = LOG_PATH.with_name(f"audit.{ts}.jsonl")
            LOG_PATH.rename(archive)
            archive_path = str(archive)
        else:
            chain_from = ""
        _seq = 0
        _prev_hash = chain_from
    log("log_rotated", archived=archive_path)
    return archive_path


# Recover continuity on import, then record the active mode as the first
# thing anyone reading this process's slice of the log will see.
_load_state()
log("audit_log_opened", mode=MODE)
