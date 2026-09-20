"""
Sub-unit 2 of the Phase B export arc — gating (CLAUDE.md "The export handoff",
ROADMAP.md #1 "PLAN OF RECORD"). No routes/UI for the export action itself yet
(sub-unit 3/4) — this pins the two gates and the structural guarantee that
summarization can't reach hosted, ahead of anything that could use them.
"""

from __future__ import annotations

import pytest

import settings


# --------------------------------------------------------- capability gate (raw key)

def test_export_enabled_defaults_off(client):
    r = client.get("/export/enabled")
    assert r.status_code == 200
    assert r.json() == {"enabled": False}


def test_export_enabled_toggles_both_ways(client):
    """A real toggle, not a one-way dismiss — turning it back off must work just
    as easily as turning it on (CLAUDE.md consent-mechanics principle)."""
    on = client.put("/export/enabled", json={"enabled": True})
    assert on.status_code == 200 and on.json() == {"enabled": True}
    assert client.get("/export/enabled").json() == {"enabled": True}

    off = client.put("/export/enabled", json={"enabled": False})
    assert off.status_code == 200 and off.json() == {"enabled": False}
    assert client.get("/export/enabled").json() == {"enabled": False}


def test_export_enabled_not_surfaced_in_settings_list(client):
    """The raw key bypasses settings.py's registry entirely — must never appear
    in GET /settings (mirrors baseline_explainer_seen's own pin)."""
    client.put("/export/enabled", json={"enabled": True})
    r = client.get("/settings")
    assert r.status_code == 200
    keys = {s["key"] for s in r.json()}
    assert "export_hosted_enabled" not in keys


# --------------------------------------------------------- provider enum (typed registry)

def test_export_provider_default_is_anthropic(db_conn):
    assert settings.resolve(db_conn, "export_provider") == "anthropic"


def test_export_provider_surfaced_in_settings_list(client):
    r = client.get("/settings")
    keys = {s["key"] for s in r.json()}
    assert "export_provider" in keys


def test_export_provider_accepts_known_values(db_conn):
    updated = settings.apply_updates(db_conn, {"export_provider": "openai"})
    by_key = {d["key"]: d for d in updated}
    assert by_key["export_provider"]["value"] == "openai"


def test_export_provider_rejects_unknown_value(db_conn):
    with pytest.raises(settings.SettingError):
        settings.apply_updates(db_conn, {"export_provider": "not-a-real-provider"})


def test_export_provider_route_rejects_unknown_value(client):
    r = client.put("/settings", json={"values": {"export_provider": "not-a-real-provider"}})
    assert r.status_code == 400


# ------------------------------------------------- structural guarantee: summarization

def test_summarizer_engine_rejects_hosted(db_conn):
    """summarizer_engine's enum has no 'hosted' option — server-side rejected
    before it's ever stored, regardless of what the export task can reach."""
    with pytest.raises(settings.SettingError):
        settings.apply_updates(db_conn, {"summarizer_engine": "hosted"})


# (The former test_explain_metric_stays_blocked_from_hosted was removed with the
# interpretation tier itself — there is no longer an explain_metric that could route
# to hosted. Summarization's structural block above is the remaining guard; the only
# task allowed to reach hosted is the export handoff, tested in test_export_gateway.py.)
