"""Tests for chat-ui/audit.py + audit_verify.py — hash-chain integrity and
AUDIT_KEY validation, fixing the gaps from the production-safety review:
plain (unkeyed) hashes, no seq check, rotation severing the chain, and
AUDIT_KEY misconfiguration silently downgrading to plaintext.

audit.py computes _KEY/MODE once at import and recovers _seq/_prev_hash from
LOG_PATH at import too, so every test reloads the module after pointing
AUDIT_LOG_PATH/AUDIT_KEY at a fresh scratch file — matching how a real
process only ever sees one configuration for its whole lifetime.
"""

import base64
import importlib
import os
import sys
from pathlib import Path

import pytest

root = Path(__file__).parent.parent
sys.path.insert(0, str(root / "chat-ui"))

import audit  # noqa: E402
import audit_verify  # noqa: E402

VALID_KEY = base64.b64encode(os.urandom(32)).decode()


def _reload_audit(monkeypatch, log_path, key=None, require_encryption=False):
    monkeypatch.setenv("AUDIT_LOG_PATH", str(log_path))
    if key is None:
        monkeypatch.delenv("AUDIT_KEY", raising=False)
    else:
        monkeypatch.setenv("AUDIT_KEY", key)
    monkeypatch.setenv("AUDIT_REQUIRE_ENCRYPTION", "1" if require_encryption else "0")
    return importlib.reload(audit)


@pytest.fixture()
def log_path(tmp_path):
    return tmp_path / "audit.jsonl"


def test_unset_key_is_plaintext_mode_with_a_warning(monkeypatch, log_path):
    with pytest.warns(UserWarning, match="plaintext"):
        mod = _reload_audit(monkeypatch, log_path)
    assert mod.MODE == "plaintext"
    assert mod._get_key() is None


def test_require_encryption_without_a_key_raises(monkeypatch, log_path):
    with pytest.raises(RuntimeError, match="AUDIT_REQUIRE_ENCRYPTION"):
        _reload_audit(monkeypatch, log_path, require_encryption=True)


def test_invalid_base64_key_raises(monkeypatch, log_path):
    with pytest.raises(RuntimeError, match="base64"):
        _reload_audit(monkeypatch, log_path, key="not-valid-base64!!!")


def test_wrong_length_key_raises(monkeypatch, log_path):
    short_key = base64.b64encode(os.urandom(16)).decode()
    with pytest.raises(RuntimeError, match="32 bytes"):
        _reload_audit(monkeypatch, log_path, key=short_key)


def test_valid_key_is_encrypted_mode(monkeypatch, log_path):
    mod = _reload_audit(monkeypatch, log_path, key=VALID_KEY)
    assert mod.MODE == "encrypted"


def test_log_and_read_round_trip_encrypted(monkeypatch, log_path):
    mod = _reload_audit(monkeypatch, log_path, key=VALID_KEY)
    mod.log("tool_call", tool="mqtt__read_tag", args={"topic": "x"})
    entries = mod.read_log()
    # First entry is audit.py's own "audit_log_opened" record from import.
    assert entries[-1]["event"] == "tool_call"
    assert entries[-1]["tool"] == "mqtt__read_tag"


def test_first_record_is_audit_log_opened_with_the_active_mode(monkeypatch, log_path):
    mod = _reload_audit(monkeypatch, log_path, key=VALID_KEY)
    entries = mod.read_log()
    assert entries[0]["event"] == "audit_log_opened"
    assert entries[0]["mode"] == "encrypted"


def test_verify_passes_on_an_untampered_log(monkeypatch, log_path):
    mod = _reload_audit(monkeypatch, log_path, key=VALID_KEY)
    for i in range(5):
        mod.log("tool_call", tool=f"tool_{i}")
    assert audit_verify.verify(str(log_path), base64.b64decode(VALID_KEY)) is True


def test_verify_fails_on_plaintext_default_sha256_mismatch_when_tampered(
    monkeypatch, log_path
):
    mod = _reload_audit(monkeypatch, log_path)  # plaintext mode
    for i in range(5):
        mod.log("tool_call", tool=f"tool_{i}")

    lines = log_path.read_text().splitlines()
    target = next(i for i, line in enumerate(lines) if '"tool_2"' in line)
    lines[target] = lines[target].replace('"tool_2"', '"tampered"')
    log_path.write_text("\n".join(lines) + "\n")

    assert audit_verify.verify(str(log_path), None) is False


def test_verify_fails_on_a_middle_record_deleted_even_with_seq_preserved(
    monkeypatch, log_path
):
    """Simulates the 'lazy tamperer' who filters out an unwanted line without
    re-chaining or renumbering seq afterward — seq gap catches it even where
    a naive editor might otherwise think just removing the line is enough."""
    mod = _reload_audit(monkeypatch, log_path, key=VALID_KEY)
    for i in range(5):
        mod.log("tool_call", tool=f"tool_{i}")

    lines = log_path.read_text().splitlines()
    del lines[2]  # drop one record from the middle, chain now also breaks
    log_path.write_text("\n".join(lines) + "\n")

    assert audit_verify.verify(str(log_path), base64.b64decode(VALID_KEY)) is False


def test_rotation_seeds_new_log_with_archives_final_hash(monkeypatch, log_path):
    mod = _reload_audit(monkeypatch, log_path, key=VALID_KEY)
    mod.log("tool_call", tool="before_rotation")
    archive_path = mod.rotate_log()

    mod.log("tool_call", tool="after_rotation")

    key = base64.b64decode(VALID_KEY)
    # The new log alone: record 1 (log_rotated) has a non-empty prev even
    # though nothing in this file can verify it — that's the point, it's
    # detectably a continuation, not indistinguishable from a fresh log.
    entries = mod.read_log()
    assert entries[0]["event"] == "log_rotated"
    assert entries[0]["prev"] != ""

    # Verified against its archive, the chain is intact end to end.
    assert audit_verify.verify(str(log_path), key, prev_file=archive_path) is True
    # Verified without the archive, still internally consistent — no false
    # CHAIN BROKEN — verify() only notes record 1 continues from elsewhere.
    assert audit_verify.verify(str(log_path), key) is True


def test_rotation_does_not_let_new_log_pass_as_a_fresh_complete_history(
    monkeypatch, log_path
):
    """A rotated log's record 1 always carries a non-empty prev — the
    original bug this replaces let POST /api/audit/clear produce a new log
    indistinguishable from a legitimate from-scratch log."""
    mod = _reload_audit(monkeypatch, log_path, key=VALID_KEY)
    mod.log("tool_call", tool="before_rotation")
    mod.rotate_log()
    mod.log("tool_call", tool="after_rotation")

    entries = mod.read_log()
    assert entries[0]["prev"] != ""
