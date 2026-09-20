"""
Qualitative results are unitless and exempt from the one-unit-per-metric rule
(db.get_metric_unit / add_observation / list_metrics_with_units). The real case:
urine glucose reported as a dipstick 'Negative' (qualitative, no unit) on one
report and as a quantitative mg/dL number on another — the SAME test, one metric.
A qualitative reading must NOT lock the metric to a blank unit and block the
numeric one; numeric-vs-numeric unit consistency must still be enforced.
"""

from __future__ import annotations

import pytest

import db


def _qual(conn, metric, text, date):
    return db.add_observation(conn, metric=metric, value=None, unit="", observed_on=date,
                              result_type="qualitative", value_text=text)


def _num(conn, metric, value, unit, date):
    return db.add_observation(conn, metric=metric, value=value, unit=unit, observed_on=date,
                              result_type="numeric")


# --------------------------------------------------------------------- get_metric_unit

def test_qualitative_only_metric_has_no_canonical_unit(db_conn):
    _qual(db_conn, "Urine Glucose", "Negative", "2024-01-01")
    _qual(db_conn, "Urine Glucose", "Trace", "2024-02-01")
    assert db.get_metric_unit(db_conn, "Urine Glucose") is None


def test_unit_comes_from_numeric_not_a_later_qualitative(db_conn):
    _num(db_conn, "Urine Glucose", 50.0, "mg/dL", "2024-01-01")
    _qual(db_conn, "Urine Glucose", "Negative", "2024-03-01")  # later, but unitless
    assert db.get_metric_unit(db_conn, "Urine Glucose") == "mg/dL"


# --------------------------------------------------------------------- add_observation

def test_numeric_reading_joins_a_qualitative_only_metric(db_conn):
    """The reported bug: a metric with only qualitative readings must accept a first
    numeric reading with a real unit, establishing that unit."""
    _qual(db_conn, "Urine Glucose", "Negative", "2024-01-01")
    new_id = _num(db_conn, "Urine Glucose", 50.0, "mg/dL", "2024-06-01")  # ICU numeric
    assert new_id
    assert db.get_metric_unit(db_conn, "Urine Glucose") == "mg/dL"


def test_qualitative_reading_joins_a_numeric_metric(db_conn):
    """The reverse also works: a unitless 'Negative' can be added to a mg/dL metric
    without a unit clash."""
    _num(db_conn, "Urine Glucose", 50.0, "mg/dL", "2024-06-01")
    assert _qual(db_conn, "Urine Glucose", "Negative", "2024-01-01")
    assert db.get_metric_unit(db_conn, "Urine Glucose") == "mg/dL"


def test_numeric_unit_consistency_still_enforced(db_conn):
    """The protection that MATTERS is intact: two numeric readings can't disagree
    on the unit."""
    _num(db_conn, "Glucose", 90.0, "mg/dL", "2024-01-01")
    with pytest.raises(db.UnitMismatchError):
        _num(db_conn, "Glucose", 5.0, "mmol/L", "2024-02-01")


def test_dimensionless_numeric_unit_still_respected(db_conn):
    """A NUMERIC dimensionless reading's '' IS a real unit (a ratio), unlike a
    qualitative blank — so a mg/dL reading still can't join a dimensionless metric."""
    _num(db_conn, "Some Ratio", 1.2, "", "2024-01-01")   # dimensionless numeric
    with pytest.raises(db.UnitMismatchError):
        _num(db_conn, "Some Ratio", 5.0, "mg/dL", "2024-02-01")


# --------------------------------------------------------------------- list_metrics_with_units

def test_metrics_list_reports_numeric_unit_and_null_for_qualitative_only(db_conn):
    _qual(db_conn, "Urine Color", "Yellow", "2024-01-01")          # qualitative-only
    _num(db_conn, "Sodium", 140.0, "mmol/L", "2024-01-01")         # numeric
    _num(db_conn, "Urine Glucose", 50.0, "mg/dL", "2024-06-01")
    _qual(db_conn, "Urine Glucose", "Negative", "2024-01-01")      # mixed
    by = {r["metric"]: r["unit"] for r in db.list_metrics_with_units(db_conn)}
    assert by["Urine Color"] is None          # only qualitative -> no unit (form won't lock)
    assert by["Sodium"] == "mmol/L"
    assert by["Urine Glucose"] == "mg/dL"     # the numeric unit, not the qualitative blank


def test_metrics_ROUTE_ok_with_qualitative_only_metric(client):
    """Regression: the /metrics ROUTE (MetricInfo serialization) must accept a NULL
    unit for a qualitative-only metric — a required-str `unit` field 500'd the whole
    route on the real DB (which has qualitative-only metrics). The db-level test above
    didn't catch it because it never went through the response model."""
    r = client.post("/observations", json={
        "metric": "HIV", "value": None, "unit": "", "observed_on": "2024-01-01",
        "result_type": "qualitative", "value_text": "Negative"})
    assert r.status_code == 200
    m = client.get("/metrics")
    assert m.status_code == 200
    hiv = next(x for x in m.json() if x["metric"] == "HIV")
    assert hiv["unit"] is None
