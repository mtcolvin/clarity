"""
Multi-metric export (CLAUDE.md "Hypothesis floating & multi-metric scope"): export a SET
of metrics — a panel, a user-selected set, or the full picture — as one bundle
{metrics:[per-metric bundle...], scope}, through the SAME gated/previewed/confirmed chain
as the single-metric export. Preview tests hit the REAL gateway (no send happens until a
confirm with a matching token), so they stay hermetic.
"""

from __future__ import annotations

import api
import db
import gateway


def _seed_panel(client):
    cid = client.post("/collections", json={"completed_on": "2024-08-12",
                                            "volume_ml": 1750.0}).json()["id"]
    for m, unit, v in [("Copper 24h", "ug/24h", 40), ("Creatinine 24h", "mg/24h", 1200)]:
        r = client.post("/observations", json={"metric": m, "value": v, "unit": unit,
                                               "observed_on": "2024-08-12",
                                               "collection_id": cid})
        assert r.status_code == 200
    return cid


def _enable(client):
    assert client.put("/export/enabled", json={"enabled": True}).status_code == 200


def test_multi_bundle_allowlist_invariant(db_conn):
    """A future top-level field in the multi bundle must fail HERE, not silently ship.

    Measured against the FULL-PICTURE bundle, which is the maximal shape: the allowlist
    has to cover every key the assembler can emit. The plain (metrics-only) bundle is
    checked separately below — it must stay a strict subset, i.e. context is opt-in."""
    db.add_observation(db_conn, "A", 1, "x", "2024-01-01")
    db.add_observation(db_conn, "B", 2, "x", "2024-01-01")
    db_conn.commit()
    full = api._assemble_export_multi(db_conn, ["A", "B"], "set", include_context=True)
    assert set(gateway._ALLOWLISTS["export_metrics"]) == set(full.keys())


def test_multi_bundle_without_context_is_metrics_only(db_conn):
    """Data minimization: a panel or ad-hoc selection sends the metric half and nothing
    else, exactly as it did before the full-picture context existed."""
    db.add_observation(db_conn, "A", 1, "x", "2024-01-01")
    db_conn.commit()
    bundle = api._assemble_export_multi(db_conn, ["A"], "set")
    assert set(bundle.keys()) == {"metrics", "scope"}


def test_panel_endpoint_resolves_collection_siblings(client):
    _seed_panel(client)
    body = client.get("/metrics/Copper 24h/panel").json()
    assert set(body["panel"]) == {"Copper 24h", "Creatinine 24h"}
    # a spot (non-collection) metric has NO panel (nothing shares a collection with it)
    client.post("/observations", json={"metric": "Sodium", "value": 140, "unit": "mmol/L",
                                       "observed_on": "2024-08-12"})
    assert client.get("/metrics/Sodium/panel").json()["panel"] == []


def test_multi_preview_gated_off_by_default(client):
    r = client.post("/export-multi/preview", json={"metrics": ["Copper 24h"]})
    assert r.status_code == 403  # capability disabled by default (gate before anything else)


def test_multi_preview_shape_and_pii_clean(client):
    _seed_panel(client)
    _enable(client)
    r = client.post("/export-multi/preview",
                    json={"metrics": ["Copper 24h", "Creatinine 24h"], "scope_label": "Copper panel"})
    assert r.status_code == 200
    body = r.json()
    assert body["task"] == "export_metrics"
    assert body["confirmation_token"]
    assert body["excluded_fields"] == [] and body["redactions"] == []  # PII-clean by construction
    payload = body["payload"][0]
    assert sorted(payload.keys()) == ["metrics", "scope"]
    assert len(payload["metrics"]) == 2 and payload["scope"] == "Copper panel"
    # each entry is a full per-metric bundle
    assert "readings" in payload["metrics"][0] and "engine_findings" in payload["metrics"][0]


def test_multi_preview_unknown_metric_404(client):
    _seed_panel(client)
    _enable(client)
    r = client.post("/export-multi/preview",
                    json={"metrics": ["Copper 24h", "No Such Metric"]})
    assert r.status_code == 404


def test_multi_preview_empty_is_422(client):
    _enable(client)
    assert client.post("/export-multi/preview", json={"metrics": []}).status_code == 422


def test_bundle_includes_qualitative_readings(db_conn):
    """A qualitative result IS a reading — it must appear in the export bundle (with its
    text display), not be dropped for lacking a numeric value ('0 of 0' bug)."""
    db.add_observation(db_conn, "Copper Qual", None, "", "2024-08-12",
                       result_type="qualitative", value_text="Not applicable",
                       normal_text="Negative")
    db_conn.commit()
    bundle = api._assemble_export_bundle(db_conn, "Copper Qual")
    assert bundle["n_readings"] == 1
    r0 = bundle["readings"][0]
    assert r0["display"] == "Not applicable" and r0["result_type"] == "qualitative"
    assert r0["in_range"] is None  # no numeric in/out for a qualitative result


def test_multi_confirm_saves_result(client, monkeypatch):
    """A confirmed export's model response is saved locally and surfaced at /export/results
    (Settings → External export shows it beside the send audit)."""
    from test_export_routes import _fake_complete
    monkeypatch.setattr(api, "complete",
                        _fake_complete("ok", output="One possibility to discuss with your clinician…",
                                       model="claude-sonnet-5"))
    _seed_panel(client)
    _enable(client)
    r = client.post("/export-multi/confirm", json={
        "metrics": ["Copper 24h", "Creatinine 24h"], "scope_label": "Copper panel",
        "confirmation_token": "test-token"})
    assert r.status_code == 200
    results = client.get("/export/results").json()["results"]
    assert len(results) == 1
    assert results[0]["scope"] == "Copper panel"
    assert set(results[0]["metrics"]) == {"Copper 24h", "Creatinine 24h"}
    assert results[0]["output"] == "One possibility to discuss with your clinician…"
    assert results[0]["model"] == "claude-sonnet-5"


def test_multi_preview_dedupes_metrics(client):
    _seed_panel(client)
    _enable(client)
    r = client.post("/export-multi/preview",
                    json={"metrics": ["Copper 24h", "Copper 24h", "Creatinine 24h"]})
    assert r.status_code == 200
    assert len(r.json()["payload"][0]["metrics"]) == 2  # de-duped
