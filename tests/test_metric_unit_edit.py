"""
Metric-level unit RELABEL (db.set_metric_unit + PUT /metrics/{m}/unit).

A pure label change across all a metric's numeric/censored readings — NOT a value
conversion. For casing fixes ('mg/dl'->'mg/dL') and equivalent units ('EU/dL'->
'mg/dL'). Qualitative readings are unitless and untouched; derived metrics are fixed.
"""

from __future__ import annotations

import db


def _num(conn, metric, value, unit, date):
    return db.add_observation(conn, metric=metric, value=value, unit=unit,
                              observed_on=date, result_type="numeric")


def _qual(conn, metric, text, date):
    return db.add_observation(conn, metric=metric, value=None, unit="", observed_on=date,
                              result_type="qualitative", value_text=text)


# --------------------------------------------------------------------- db layer

def test_relabels_all_numeric_readings(db_conn):
    _num(db_conn, "Urobilinogen", 0.2, "EU/dL", "2024-01-01")
    _num(db_conn, "Urobilinogen", 0.4, "EU/dL", "2024-02-01")
    n = db.set_metric_unit(db_conn, "Urobilinogen", "mg/dL")
    assert n == 2
    assert db.get_metric_unit(db_conn, "Urobilinogen") == "mg/dL"
    # Values are UNTOUCHED — a relabel, not a conversion.
    vals = sorted(r["value"] for r in db.get_series(db_conn, "Urobilinogen"))
    assert vals == [0.2, 0.4]


def test_qualitative_rows_untouched(db_conn):
    _num(db_conn, "Urine Glucose", 50.0, "mg/dl", "2024-06-01")
    _qual(db_conn, "Urine Glucose", "Negative", "2024-01-01")
    db.set_metric_unit(db_conn, "Urine Glucose", "mg/dL")   # fix casing
    rows = {r["result_type"]: r["unit"] for r in db.get_series(db_conn, "Urine Glucose")}
    assert rows["numeric"] == "mg/dL"
    assert rows["qualitative"] == ""      # qualitative stays unitless


def test_unknown_metric_returns_zero(db_conn):
    assert db.set_metric_unit(db_conn, "Nonexistent", "mg/dL") == 0


# --------------------------------------------------------------------- route

def test_route_relabels(client):
    for d, v in [("2024-01-01", 0.2), ("2024-02-01", 0.4)]:
        assert client.post("/observations", json={
            "metric": "Urobilinogen", "value": v, "unit": "EU/dL",
            "observed_on": d, "result_type": "numeric"}).status_code == 200
    r = client.put("/metrics/Urobilinogen/unit", json={"unit": "mg/dL"})
    assert r.status_code == 200
    assert r.json()["readings_relabeled"] == 2
    # /metrics now reports the new unit.
    unit = next(m["unit"] for m in client.get("/metrics").json() if m["metric"] == "Urobilinogen")
    assert unit == "mg/dL"


def test_route_unknown_metric_404(client):
    assert client.put("/metrics/Nope/unit", json={"unit": "mg/dL"}).status_code == 404


def test_route_qualitative_only_metric_404(client):
    """Only qualitative readings -> nothing to relabel (unitless) -> 404."""
    client.post("/observations", json={
        "metric": "HIV", "value": None, "unit": "", "observed_on": "2024-01-01",
        "result_type": "qualitative", "value_text": "Negative"})
    assert client.put("/metrics/HIV/unit", json={"unit": "x"}).status_code == 404


def test_route_derived_metric_rejected(client):
    """A computed metric's unit is fixed by its formula — relabel is refused (409)."""
    r = client.put("/metrics/Calcium Corrected/unit", json={"unit": "x"})
    assert r.status_code == 409
