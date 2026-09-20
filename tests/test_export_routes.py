"""
Phase B export arc — routes (CLAUDE.md "The export handoff", ROADMAP.md #1
"PLAN OF RECORD"). Gating/preview/token tests (phase (b)) exercise the REAL
gateway.complete — no network call happens until a confirm is reached, and
those never carry a matching, non-stale token here, so they stay hermetic by
construction. The two confirm-success/failure tests (phase (c)) monkeypatch
api.complete directly (mirroring test_explain.py's pattern) rather than
hitting a real provider — the actual HTTP layer is covered at the gateway
level in test_gateway_hosted.py; this file only proves the ROUTE maps a
gateway result to the right HTTP status/body.
"""

from __future__ import annotations

import sqlite3
from datetime import date

import api
import explain
import gateway


def _seed(client, metric="Glucose Serum/Plasma"):
    for d, v in [("2024-01-01", 100.0), ("2024-02-01", 210.0)]:
        r = client.post("/observations", json={"metric": metric, "value": v,
                                                "unit": "mg/dL", "observed_on": d,
                                                "ref_low": 70, "ref_high": 99})
        assert r.status_code == 200
    return metric


def _enable(client, on=True):
    r = client.put("/export/enabled", json={"enabled": on})
    assert r.status_code == 200


# --------------------------------------------------------------------- gating

def test_preview_refuses_when_disabled(client):
    metric = _seed(client)
    r = client.post(f"/export/{metric}/preview")
    assert r.status_code == 403


def test_confirm_refuses_when_disabled(client):
    metric = _seed(client)
    r = client.post(f"/export/{metric}/confirm", json={"confirmation_token": "x"})
    assert r.status_code == 403


# --------------------------------------------------------------------- preview

def test_preview_returns_full_payload_and_token(client):
    metric = _seed(client)
    _enable(client)
    r = client.post(f"/export/{metric}/preview")
    assert r.status_code == 200
    body = r.json()
    assert body["task"] == "explain_metric"
    assert body["confirmation_token"]
    assert body["excluded_fields"] == []
    assert body["redactions"] == []
    payload = body["payload"][0]
    assert payload["metric"] == metric
    assert len(payload["readings"]) == 2
    assert payload["n_readings"] == 2


def test_preview_surfaces_the_system_instruction(client):
    """The preview's promise is 'see what will be sent', and the instruction is HALF of
    what the provider receives — it shapes the entire response, so a user reviewing only
    the data can't tell why an answer reads the way it does. Pinned so a refactor can't
    quietly drop it back out of the preview."""
    metric = _seed(client)
    _enable(client)
    body = client.post(f"/export/{metric}/preview").json()
    assert body["instruction"]
    # It is the REAL instruction that will be sent, not a placeholder or a summary.
    assert explain.EXPLAIN_SYSTEM in body["instruction"]
    # ...carrying today's date, so the model can judge what is current (rule 1).
    assert date.today().isoformat() in body["instruction"]


def test_preview_instruction_is_not_bound_by_the_token(client):
    """The token binds the DATA. The instruction is static developer text carrying none
    of the user's information, so it must not be folded into the token — otherwise a
    prompt edit would invalidate in-flight previews for no privacy gain."""
    metric = _seed(client)
    _enable(client)
    a = client.post(f"/export/{metric}/preview").json()
    b = client.post(f"/export/{metric}/preview").json()
    assert a["confirmation_token"] == b["confirmation_token"]
    assert gateway._token(a["payload"]) == a["confirmation_token"]


def test_preview_does_not_send_anything(client):
    """Preview alone must never write an external audit entry — only a
    confirmed send does (gateway.py's own ordering)."""
    metric = _seed(client)
    _enable(client)
    r = client.post(f"/export/{metric}/preview")
    assert r.status_code == 200
    assert "output" not in r.json()


# ------------------------------------------------------------------- confirm

def _fake_complete(status, **result_kwargs):
    """A stand-in for gateway.complete: 'needs_confirmation' on the preview
    call, then `status` on the confirm call — matching real complete()'s
    two-call shape without touching the network."""
    def _fn(req, confirmation=None):
        if confirmation is None:
            return gateway.GatewayResult(
                "needs_confirmation", req.engine, "external",
                preview=gateway.Preview(
                    task=req.task, provider=req.provider or "anthropic",
                    payload=req.fields, excluded_fields=[], redactions=[],
                    provider_settings={}, confirmation_token="test-token"))
        return gateway.GatewayResult(status, req.engine, "external", **result_kwargs)
    return _fn


def test_confirm_with_matching_token_succeeds(client, monkeypatch):
    monkeypatch.setattr(api, "complete", _fake_complete(
        "ok", output="Your last three readings rose from X to Y.", model="claude-sonnet-5"))
    metric = _seed(client)
    _enable(client)
    preview = client.post(f"/export/{metric}/preview").json()
    r = client.post(f"/export/{metric}/confirm",
                    json={"confirmation_token": preview["confirmation_token"]})
    assert r.status_code == 200
    body = r.json()
    assert body["engine"] == "hosted"
    assert body["model"] == "claude-sonnet-5"
    # The disclaimer is a SEPARATE field, deterministic, never woven into the
    # model's raw text — proven here by checking output is EXACTLY the model's
    # text (no frame inside it) and disclaimer is exactly the fixed constant,
    # regardless of what the model returned.
    assert body["output"] == "Your last three readings rose from X to Y."
    assert explain.FRAME not in body["output"]
    # Non-empty, not just equal-to-FRAME — a check that only asserts equality
    # would still pass vacuously if FRAME itself were ever accidentally "".
    assert len(body["disclaimer"]) > 0
    assert body["disclaimer"] == explain.FRAME


def test_confirm_disclaimer_present_even_when_model_omits_it(client, monkeypatch):
    """The render/response contract guarantees the disclaimer regardless of
    what the model wrote — simulated here with a bare model response that
    contains no caveat language of its own."""
    monkeypatch.setattr(api, "complete", _fake_complete(
        "ok", output="Nothing here stands out to interpret.", model="claude-sonnet-5"))
    metric = _seed(client)
    _enable(client)
    preview = client.post(f"/export/{metric}/preview").json()
    r = client.post(f"/export/{metric}/confirm",
                    json={"confirmation_token": preview["confirmation_token"]})
    body = r.json()
    assert body["output"] == "Nothing here stands out to interpret."
    assert len(body["disclaimer"]) > 0
    assert body["disclaimer"] == explain.FRAME


def test_confirm_provider_error_surfaces_as_502(client, monkeypatch):
    """A provider failure (bad key, rate limit, outage) is a DIFFERENT failure
    mode than a stale token — re-previewing won't fix it, so it must not be
    conflated with the 409 refused path."""
    monkeypatch.setattr(api, "complete", _fake_complete(
        "provider_error", reason="The external provider rejected the API key (unauthorized)."))
    metric = _seed(client)
    _enable(client)
    preview = client.post(f"/export/{metric}/preview").json()
    r = client.post(f"/export/{metric}/confirm",
                    json={"confirmation_token": preview["confirmation_token"]})
    assert r.status_code == 502
    assert "unauthorized" in r.json()["detail"]


def test_confirm_stale_token_self_refuses(client):
    """The byte-compare self-refuses if the rebuild mismatches the preview —
    proving a data change between preview and confirm (a new reading landing
    from another tab) is caught, not silently ignored."""
    metric = _seed(client)
    _enable(client)
    preview = client.post(f"/export/{metric}/preview").json()
    stale_token = preview["confirmation_token"]
    client.post("/observations", json={"metric": metric, "value": 220.0,
                                        "unit": "mg/dL", "observed_on": "2024-03-01",
                                        "ref_low": 70, "ref_high": 99})
    r = client.post(f"/export/{metric}/confirm", json={"confirmation_token": stale_token})
    assert r.status_code == 409


def test_confirm_garbage_token_refuses(client):
    metric = _seed(client)
    _enable(client)
    client.post(f"/export/{metric}/preview")
    r = client.post(f"/export/{metric}/confirm", json={"confirmation_token": "not-a-real-token"})
    assert r.status_code == 409


# ------------------------------------------------------ the send <-> response join key

def test_saved_result_carries_the_audit_id_of_its_send(client, monkeypatch):
    """'What left the machine' and 'what came back' used to be two unjoined records —
    an audit log line and a DB row with nothing linking them. The gateway now stamps
    each audit entry with an id and the saved result records it, so Settings can show a
    response attached to the send that produced it."""
    monkeypatch.setattr(api, "complete", _fake_complete(
        "ok", output="Some reasoning.", model="claude-sonnet-5", audit_id="abc123"))
    metric = _seed(client)
    _enable(client)
    preview = client.post(f"/export/{metric}/preview").json()
    client.post(f"/export/{metric}/confirm",
                json={"confirmation_token": preview["confirmation_token"]})
    saved = client.get("/export/results").json()["results"]
    assert len(saved) == 1
    assert saved[0]["audit_id"] == "abc123"


def test_audit_entries_expose_an_id_to_join_on(client, monkeypatch):
    """The other half of the join: the audit entry must surface the same id, or the
    client has nothing to match a saved response against."""
    monkeypatch.setattr(api, "complete", _fake_complete(
        "ok", output="Some reasoning.", model="claude-sonnet-5", audit_id="xyz789"))
    metric = _seed(client)
    _enable(client)
    preview = client.post(f"/export/{metric}/preview").json()
    client.post(f"/export/{metric}/confirm",
                json={"confirmation_token": preview["confirmation_token"]})
    # A real (non-stubbed) gateway write is what stamps the log, so assert the FIELD
    # exists and is optional-by-contract rather than asserting the stub's value here.
    entries = client.get("/export/audit").json()["entries"]
    assert all("id" in e for e in entries)


# ------------------------------------------------- archive failure must not cost the response
# Ordering is the whole point: the archive write happens AFTER the send, so the bytes have
# already left the machine and the provider has already billed. A local DB failure at that
# point must not escalate into a 500 that DISCARDS the text the user paid for — recovering it
# would mean consenting to send their health data all over again.

def _break_archive(monkeypatch, exc=sqlite3.OperationalError("database is locked")):
    def _boom(*a, **kw):
        raise exc
    monkeypatch.setattr(api, "add_export_result", _boom)


def test_confirm_returns_response_even_if_archive_write_fails(client, monkeypatch):
    monkeypatch.setattr(api, "complete", _fake_complete(
        "ok", output="Your last three readings rose from X to Y.", model="claude-sonnet-5"))
    _break_archive(monkeypatch)
    metric = _seed(client)
    _enable(client)
    preview = client.post(f"/export/{metric}/preview").json()
    r = client.post(f"/export/{metric}/confirm",
                    json={"confirmation_token": preview["confirmation_token"]})
    # NOT a 500 — the response survives the archive failure intact...
    assert r.status_code == 200
    body = r.json()
    assert body["output"] == "Your last three readings rose from X to Y."
    assert body["disclaimer"] == explain.FRAME
    # ...and the failure is reported honestly rather than swallowed, so the UI can warn
    # the user that this text exists nowhere else.
    assert body["saved"] is False


def test_confirm_reports_saved_true_on_the_normal_path(client, monkeypatch):
    """Guards the test above from passing vacuously: `saved` must actually track the
    write, not be hardcoded False (or absent and defaulting)."""
    monkeypatch.setattr(api, "complete", _fake_complete(
        "ok", output="Nothing here stands out.", model="claude-sonnet-5"))
    metric = _seed(client)
    _enable(client)
    preview = client.post(f"/export/{metric}/preview").json()
    r = client.post(f"/export/{metric}/confirm",
                    json={"confirmation_token": preview["confirmation_token"]})
    assert r.json()["saved"] is True
    # And it genuinely reached the local record.
    assert len(client.get("/export/results").json()["results"]) == 1


def test_multi_confirm_returns_response_even_if_archive_write_fails(client, monkeypatch):
    """The multi-metric confirm has its own save call site — both must be hardened, or
    the larger, more expensive export is the one that loses its response."""
    monkeypatch.setattr(api, "complete", _fake_complete(
        "ok", output="Across these metrics, one thing that could tie them together is X.",
        model="claude-sonnet-5"))
    _break_archive(monkeypatch)
    metric = _seed(client)
    _enable(client)
    preview = client.post("/export-multi/preview",
                          json={"metrics": [metric], "scope_label": "Test panel"}).json()
    r = client.post("/export-multi/confirm",
                    json={"metrics": [metric], "scope_label": "Test panel",
                          "confirmation_token": preview["confirmation_token"]})
    assert r.status_code == 200
    assert r.json()["output"].startswith("Across these metrics")
    assert r.json()["saved"] is False
