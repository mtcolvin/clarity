"""
/baseline-explainer tests — the one-time global personal-baseline explainer flag.

Pure additive backend: a raw settings-table key (baseline_explainer_seen),
stored via db.get_setting/set_setting directly (see api.BASELINE_EXPLAINER_SEEN_KEY),
bypassing settings.py's typed SettingDef registry entirely — a one-shot "has the
user seen this" boolean isn't a tunable knob. Global state, not per-metric.
"""

from __future__ import annotations


def test_defaults_to_not_seen(client):
    """Nothing persisted yet -> seen: False."""
    r = client.get("/baseline-explainer")
    assert r.status_code == 200
    assert r.json() == {"seen": False}


def test_dismiss_marks_seen(client):
    r = client.post("/baseline-explainer/dismiss")
    assert r.status_code == 200
    assert r.json() == {"seen": True}


def test_get_reflects_dismissal(client):
    client.post("/baseline-explainer/dismiss")
    r = client.get("/baseline-explainer")
    assert r.status_code == 200
    assert r.json() == {"seen": True}


def test_dismiss_is_idempotent(client):
    """Dismissing twice stays seen: True, no error."""
    first = client.post("/baseline-explainer/dismiss")
    second = client.post("/baseline-explainer/dismiss")
    assert first.status_code == 200
    assert second.status_code == 200
    assert first.json() == {"seen": True}
    assert second.json() == {"seen": True}


def test_not_surfaced_in_settings_list(client):
    """The raw key bypasses settings.py's registry entirely, so it must never
    appear in GET /settings (which only iterates settings.SETTINGS)."""
    client.post("/baseline-explainer/dismiss")
    r = client.get("/settings")
    assert r.status_code == 200
    keys = {s["key"] for s in r.json()}
    assert "baseline_explainer_seen" not in keys
