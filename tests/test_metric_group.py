"""
Metric GROUP label (db.set_metric_group + PUT /metrics/{m}/group).

A purely presentational picker cluster (an <optgroup>, e.g. a lipid panel).
Display-only: touches no identity/match key and no reading, freely set/cleared. Derived
metrics already cluster under "Computed metrics", so the route refuses them (409).
"""

from __future__ import annotations

import db


def _num(conn, metric, value, unit, date):
    return db.add_observation(conn, metric=metric, value=value, unit=unit,
                              observed_on=date, result_type="numeric")


def _group_of(conn, metric):
    return next(m["metric_group"] for m in db.list_metrics_with_units(conn)
                if m["metric"] == metric)


# --------------------------------------------------------------------- db layer

def test_set_and_report_group(db_conn):
    _num(db_conn, "pH Panel Test", 7.38, "", "2024-01-01")
    assert db.set_metric_group(db_conn, "pH Panel Test", "Lipid Panel") is True
    assert _group_of(db_conn, "pH Panel Test") == "Lipid Panel"


def test_clear_group(db_conn):
    _num(db_conn, "pCO2 Panel Test", 40.0, "mmHg", "2024-01-01")
    db.set_metric_group(db_conn, "pCO2 Panel Test", "Lipid Panel")
    # '' clears it back to ungrouped (None).
    assert db.set_metric_group(db_conn, "pCO2 Panel Test", "") is True
    assert _group_of(db_conn, "pCO2 Panel Test") is None


def test_whitespace_only_clears(db_conn):
    _num(db_conn, "Lactate Panel Test", 1.2, "mmol/L", "2024-01-01")
    db.set_metric_group(db_conn, "Lactate Panel Test", "Lipid Panel")
    assert db.set_metric_group(db_conn, "Lactate Panel Test", "   ") is True
    assert _group_of(db_conn, "Lactate Panel Test") is None


def test_group_does_not_touch_readings(db_conn):
    _num(db_conn, "Sodium Panel Test", 140.0, "mmol/L", "2024-01-01")
    db.set_metric_group(db_conn, "Sodium Panel Test", "Lipid Panel")
    rows = db.get_series(db_conn, "Sodium Panel Test")
    assert len(rows) == 1
    assert rows[0]["value"] == 140.0 and rows[0]["unit"] == "mmol/L"


def test_unknown_metric_returns_false(db_conn):
    assert db.set_metric_group(db_conn, "Nonexistent", "X") is False


# --------------------------------------------------------------------- route

def test_route_sets_group(client):
    client.post("/observations", json={
        "metric": "pO2 Panel Test", "value": 95.0, "unit": "mmHg",
        "observed_on": "2024-01-01", "result_type": "numeric"})
    r = client.put("/metrics/pO2 Panel Test/group", json={"group": "Lipid Panel"})
    assert r.status_code == 200
    assert r.json()["group"] == "Lipid Panel"
    # /metrics surfaces it as `group`.
    info = next(m for m in client.get("/metrics").json() if m["metric"] == "pO2 Panel Test")
    assert info["group"] == "Lipid Panel"


def test_route_clears_group(client):
    client.post("/observations", json={
        "metric": "Glucose Panel Test", "value": 90.0, "unit": "mg/dL",
        "observed_on": "2024-01-01", "result_type": "numeric"})
    client.put("/metrics/Glucose Panel Test/group", json={"group": "Lipid Panel"})
    r = client.put("/metrics/Glucose Panel Test/group", json={"group": ""})
    assert r.status_code == 200 and r.json()["group"] is None
    info = next(m for m in client.get("/metrics").json() if m["metric"] == "Glucose Panel Test")
    assert info["group"] is None


def test_route_unknown_metric_404(client):
    assert client.put("/metrics/Nope/group", json={"group": "X"}).status_code == 404


def test_route_derived_metric_rejected(client):
    """A computed metric already groups under 'Computed metrics' — refused (409)."""
    r = client.put("/metrics/Calcium Corrected/group", json={"group": "X"})
    assert r.status_code == 409
