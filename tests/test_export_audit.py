"""
The audit-log reader (/export/audit + gateway.read_external_audit) — the
read-only, after-the-fact half of the charter's transparency rule. Everything
here runs against the per-test isolated audit log (conftest's autouse
_isolate_audit_log), never the real gateway_audit.log.
"""

from __future__ import annotations

import json

import gateway


def _write_lines(lines: list[str]) -> None:
    with open(gateway._AUDIT_LOG, "w", encoding="utf-8") as fh:
        fh.write("\n".join(lines) + "\n")


def _external_line(ts: str, task: str = "explain_metric", **extra) -> str:
    entry = {"ts": ts, "task": task, "engine": "hosted", "provider": "anthropic",
             "destination": "external", "payload": [{"metric": "X", "value": 1}],
             "provider_settings": {"tier": "api"}, "redactions": [], **extra}
    return json.dumps(entry)


def _local_line(ts: str) -> str:
    return json.dumps({"ts": ts, "task": "summarize_labs", "engine": "in_program",
                       "destination": "local", "model": None})


# ------------------------------------------------------------ gateway reader

def test_missing_log_is_empty_list():
    # The isolated log file doesn't exist until something writes it.
    assert gateway.read_external_audit() == []


def test_filters_to_external_and_newest_first():
    _write_lines([
        _local_line("2026-01-01T00:00:00+00:00"),
        _external_line("2026-01-02T00:00:00+00:00", model="claude-sonnet-5"),
        _local_line("2026-01-03T00:00:00+00:00"),
        _external_line("2026-01-04T00:00:00+00:00", error="boom"),
    ])
    entries = gateway.read_external_audit()
    assert [e["ts"] for e in entries] == [
        "2026-01-04T00:00:00+00:00", "2026-01-02T00:00:00+00:00"]
    # A failed ATTEMPT is part of the honest record, marked by its error key.
    assert entries[0]["error"] == "boom"
    assert "error" not in entries[1]


def test_malformed_and_blank_lines_never_hide_the_rest():
    _write_lines([
        "not json at all {{{",
        "",
        json.dumps(["a", "list", "not", "a", "dict"]),
        _external_line("2026-01-01T00:00:00+00:00"),
    ])
    entries = gateway.read_external_audit()
    assert len(entries) == 1
    assert entries[0]["ts"] == "2026-01-01T00:00:00+00:00"


def test_limit_keeps_the_newest():
    _write_lines([_external_line(f"2026-01-0{i}T00:00:00+00:00") for i in range(1, 6)])
    entries = gateway.read_external_audit(limit=2)
    assert [e["ts"] for e in entries] == [
        "2026-01-05T00:00:00+00:00", "2026-01-04T00:00:00+00:00"]


def test_real_attempt_writes_what_the_reader_returns():
    """End-to-end through the REAL gateway machinery with zero egress: with no
    provider named, the confirmed send fails honestly (provider_error — the
    unwired-provider path raises before any socket opens), and the gateway
    audits the ATTEMPT with the payload verbatim. The reader must return
    exactly that record."""
    labs = [{"metric": "Ferritin", "value": 30, "unit": "ng/mL",
             "ref_low": 20, "ref_high": 200, "mrn": "secret-id"}]
    req = gateway.LLMRequest(task="summarize_labs", engine="hosted", fields=labs)
    preview = gateway.complete(req).preview
    result = gateway.complete(req, confirmation=preview.confirmation_token)
    assert result.status == "provider_error"
    entries = gateway.read_external_audit()
    assert len(entries) == 1
    assert entries[0]["error"]
    # Verbatim record of what would have been sent: the allowlisted payload,
    # with the non-allowlisted key (mrn) absent by construction.
    assert entries[0]["payload"] == preview.payload
    assert "mrn" not in entries[0]["payload"][0]


# -------------------------------------------------------------------- route

def test_route_empty_log(client):
    r = client.get("/export/audit")
    assert r.status_code == 200
    assert r.json() == {"entries": []}


def test_route_not_gated_by_export_enabled(client):
    """The record of what already left must stay reviewable with the
    capability OFF (revocability doesn't erase history) — no 403 here."""
    _write_lines([_external_line("2026-01-01T00:00:00+00:00", model="claude-sonnet-5")])
    # export_hosted_enabled was never turned on in this client fixture.
    r = client.get("/export/audit")
    assert r.status_code == 200
    entries = r.json()["entries"]
    assert len(entries) == 1
    e = entries[0]
    assert e["ts"] == "2026-01-01T00:00:00+00:00"
    assert e["provider"] == "anthropic"
    assert e["model"] == "claude-sonnet-5"
    assert e["payload"] == [{"metric": "X", "value": 1}]
    assert e["error"] is None


def test_route_serializes_failed_attempts(client):
    _write_lines([_external_line("2026-01-01T00:00:00+00:00", error="401 from provider")])
    e = client.get("/export/audit").json()["entries"][0]
    assert e["error"] == "401 from provider"
    assert e["model"] is None


# ------------------------------------------------------------ log isolation

def test_audit_log_is_isolated_from_the_repo(tmp_path):
    """The autouse fixture must point the audit log INTO the test's temp dir —
    this is what stops every pytest run appending fake external sends to the
    user's real transparency record (the pollution the reader surfaced)."""
    assert gateway._AUDIT_LOG.startswith(str(tmp_path))
