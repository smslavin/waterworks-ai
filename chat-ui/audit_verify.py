#!/usr/bin/env python3
"""Verify chain integrity of an encrypted audit log, or decrypt for export.

The hash chain and seq check catch a record edited or removed anywhere
before the last surviving line — the chain breaks, or (for a tamperer who
edits content but doesn't renumber seq) seq skips. Neither catches records
deleted off the *end* of the file with nothing rewritten after them: there's
nothing left in the file to reference what's missing. Detecting that needs
an external anchor (a periodic backup, an external append-only witness) —
out of scope here.
"""

import argparse
import base64
import hashlib
import hmac
import json
import os
import sys

try:
    from cryptography.hazmat.primitives.ciphers.aead import AESGCM
except ImportError:
    print("ERROR: pip install cryptography", file=sys.stderr)
    sys.exit(2)


def _decode(line: str, key: bytes | None) -> str:
    if key:
        padded = line + "=" * (-len(line) % 4)
        raw = base64.urlsafe_b64decode(padded)
        return AESGCM(key).decrypt(raw[:12], raw[12:], None).decode()
    return line


def _hash_line(line: str, key: bytes | None) -> str:
    """Must match audit.py's _hash_line exactly: HMAC-SHA256 under the key
    when one is configured, else a plain (unkeyed) SHA-256."""
    if key:
        return hmac.new(key, line.encode(), hashlib.sha256).hexdigest()
    return hashlib.sha256(line.encode()).hexdigest()


def _last_line_hash(log_path: str, key: bytes | None) -> str:
    with open(log_path, encoding="utf-8") as f:
        lines = [l.strip() for l in f if l.strip()]
    if not lines:
        return ""
    return _hash_line(lines[-1], key)


def verify(
    log_path: str,
    key: bytes | None,
    verbose: bool = False,
    prev_file: str | None = None,
) -> bool:
    with open(log_path, encoding="utf-8") as f:
        lines = [l.strip() for l in f if l.strip()]
    if not lines:
        print("Log is empty.")
        return True

    ok = True
    prev_hash = _last_line_hash(prev_file, key) if prev_file else ""
    expected_seq: int | None = None

    for i, line in enumerate(lines, 1):
        try:
            payload = json.loads(_decode(line, key))
        except Exception as e:
            print(f"  Record {i}: DECRYPT/PARSE ERROR — {e}")
            ok = False
            prev_hash = _hash_line(line, key)
            expected_seq = None
            continue

        expected = payload.get("prev", "")
        seq = payload.get("seq")

        if i == 1 and not prev_file and expected:
            # Nothing in this file can verify record 1's claimed prev without
            # the archive it rotated from — accept it as given rather than
            # comparing against "", and chain forward from there. Its mere
            # presence is itself the signal worth surfacing: a legitimate
            # from-scratch log has an empty prev on record 1, so a non-empty
            # one here means this is a continuation, not the complete history.
            print(
                f"  Record 1: this log continues from a prior file "
                f"(prev={expected[:16]}…) rather than starting fresh — pass "
                f"--prev-file to verify continuity across the rotation, or "
                f"treat a non-empty prev here as itself suspicious if this "
                f"is supposed to be the complete history."
            )
            prev_hash = expected

        if expected != prev_hash:
            print(
                f"  Record {i} seq={seq}: CHAIN BROKEN "
                f"(expected {prev_hash[:16]}… got {expected[:16]}…)"
            )
            ok = False
        elif expected_seq is not None and seq != expected_seq:
            print(
                f"  Record {i}: SEQUENCE GAP (expected seq={expected_seq}, got {seq}) "
                f"— records may have been deleted without breaking the hash chain"
            )
            ok = False
        elif verbose:
            print(f"  {i:>5} seq={seq} {payload.get('ts')} {payload.get('event')} ✓")

        prev_hash = _hash_line(line, key)
        expected_seq = (seq if isinstance(seq, int) else 0) + 1

    status = "✓ chain intact" if ok else "✗ CHAIN BROKEN — possible tampering"
    print(f"{len(lines)} records — {status}")
    return ok


def decrypt_all(log_path: str, key: bytes) -> None:
    with open(log_path, encoding="utf-8") as f:
        for line in f:
            line = line.strip()
            if not line:
                continue
            try:
                print(json.dumps(json.loads(_decode(line, key))))
            except Exception as e:
                print(f"# error: {e} — line: {line[:40]}…")


def main():
    ap = argparse.ArgumentParser(description="Audit log integrity verifier")
    ap.add_argument("log", help="Path to audit.jsonl")
    ap.add_argument(
        "--key", help="Base64-encoded 32-byte AES key (or set AUDIT_KEY env var)"
    )
    ap.add_argument("--verbose", "-v", action="store_true")
    ap.add_argument(
        "--prev-file",
        help="Archive this log was rotated from (audit.<timestamp>.jsonl) — "
        "verifies the chain spans the rotation instead of treating record 1's "
        "prev as unverifiable",
    )
    ap.add_argument(
        "--decrypt",
        "-d",
        action="store_true",
        help="Print all records as plaintext JSONL (requires --key)",
    )
    args = ap.parse_args()

    raw = args.key or os.environ.get("AUDIT_KEY", "")
    key = None
    if raw:
        key = base64.b64decode(raw)
        if len(key) != 32:
            print("ERROR: key must decode to exactly 32 bytes", file=sys.stderr)
            sys.exit(2)

    if args.decrypt:
        if not key:
            print("ERROR: --decrypt requires a key", file=sys.stderr)
            sys.exit(2)
        decrypt_all(args.log, key)
        return

    sys.exit(0 if verify(args.log, key, args.verbose, args.prev_file) else 1)


if __name__ == "__main__":
    main()
