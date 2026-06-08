#!/usr/bin/env python3
"""Verify chain integrity of an encrypted audit log, or decrypt for export."""

import argparse
import base64
import hashlib
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


def verify(log_path: str, key: bytes | None, verbose: bool = False) -> bool:
    with open(log_path, encoding="utf-8") as f:
        lines = [l.strip() for l in f if l.strip()]
    if not lines:
        print("Log is empty.")
        return True

    ok = True
    prev_hash = ""
    for i, line in enumerate(lines, 1):
        try:
            payload = json.loads(_decode(line, key))
        except Exception as e:
            print(f"  Record {i}: DECRYPT/PARSE ERROR — {e}")
            ok = False
            prev_hash = hashlib.sha256(line.encode()).hexdigest()
            continue

        expected = payload.get("prev", "")
        if expected != prev_hash:
            print(
                f"  Record {i} seq={payload.get('seq')}: CHAIN BROKEN "
                f"(expected {prev_hash[:16]}… got {expected[:16]}…)"
            )
            ok = False
        elif verbose:
            print(f"  {i:>5} seq={payload.get('seq')} {payload.get('ts')} {payload.get('event')} ✓")

        prev_hash = hashlib.sha256(line.encode()).hexdigest()

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
    ap.add_argument("--key", help="Base64-encoded 32-byte AES key (or set AUDIT_KEY env var)")
    ap.add_argument("--verbose", "-v", action="store_true")
    ap.add_argument("--decrypt", "-d", action="store_true",
                    help="Print all records as plaintext JSONL (requires --key)")
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

    sys.exit(0 if verify(args.log, key, args.verbose) else 1)


if __name__ == "__main__":
    main()
