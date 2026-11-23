"""Honest operator identity and the startup trust-mode record (gh-82).

Spec Part I: operator_id names what the deployment authenticated, never a
placeholder person. Part III: auth_method says how, and every trust mode
configuration is logged on startup.
"""

import pytest

import auth
import backend
import pages.audit
from fieldworks.trust import check_approver


@pytest.mark.parametrize(
    "exposed,operator_id",
    [(True, "shared-token"), (False, "local-console")],
)
def test_approver_names_the_credential_not_a_person(monkeypatch, exposed, operator_id):
    monkeypatch.setattr(auth, "EXPOSED", exposed)
    who = auth.approver()
    assert who == {"operator_id": operator_id, "auth_method": "shared_credential"}
    # Both values pass fieldworks-core's rules for an operator's decision.
    check_approver(decision="approved", **who)


def _startup_records(monkeypatch, **facility):
    records = []
    monkeypatch.setattr(
        backend.audit, "log", lambda event, **f: records.append((event, f))
    )
    monkeypatch.setattr(
        backend,
        "_topology",
        backend._topology.model_copy(
            update={"facility": backend._topology.facility.model_copy(update=facility)}
        ),
    )
    backend._log_trust_mode()
    return records


def test_startup_records_supervised(monkeypatch):
    ((event, fields),) = _startup_records(monkeypatch)
    assert event == "trust_mode_configured"
    assert fields["trust_mode"] == "SUPERVISED"
    assert fields["configured_trust_mode"] == "SUPERVISED"
    assert fields["site_id"] == backend.SITE_ID


def test_startup_names_a_mode_it_cannot_honor(monkeypatch, caplog):
    ((_, fields),) = _startup_records(
        monkeypatch,
        trust_mode="autonomous",
        autonomous_notify_channel="mailto:ops@example.com",
        trust_mode_notes="Elevated after review.",
    )
    # The approval flow always intercepts, so the record says SUPERVISED and
    # keeps what the topology asked for beside it.
    assert fields["trust_mode"] == "SUPERVISED"
    assert fields["configured_trust_mode"] == "AUTONOMOUS"
    assert fields["trust_mode_notes"] == "Elevated after review."
    assert "implements only supervised" in caplog.text


def test_audit_page_shows_who_decided():
    entry = {
        "event": "action_decision",
        "ts": "2026-11-23T10:00:00",
        "action_id": "a1",
        "decision": "approved",
        "operator_id": "shared-token",
        "auth_method": "shared_credential",
    }
    assert "by shared-token (shared_credential)" in pages.audit._entry(entry)
    timed_out = {**entry, "decision": "timed_out"}
    del timed_out["operator_id"], timed_out["auth_method"]
    assert "by " not in pages.audit._entry(timed_out)
