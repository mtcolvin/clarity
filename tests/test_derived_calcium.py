"""
Derived-metric tests — #6 Phase 1, Calcium Corrected.

Covers the three load-bearing pieces of the derived pipeline against a synthetic
DB: the same-draw JOIN (db.get_joined_series — pairs shared dates, excludes
unpaired ones), the pure COMPUTE (derived.compute_series — a value per paired date,
a date missing an input OMITTED entirely, and the unit-guard SKIP that omits a
mismatched-unit draw rather than computing a wrong number), and the API surface
(picker injection + read passthrough + the write-block).
"""

from __future__ import annotations

import db
import derived

CA = "Calcium Serum/Plasma"
ALB = "Albumin"
SPEC = derived.REGISTRY["Calcium Corrected"]


def _add(conn, metric, value, unit, date):
    db.add_observation(
        conn, metric=metric, value=value, unit=unit, observed_on=date, seed_keys=()
    )


def _derived_series(conn):
    """Reproduce api.resolve_series' derived path at the db+derived layer."""
    joined = db.get_joined_series(conn, SPEC.inputs)
    return derived.compute_series(SPEC, joined)


def test_join_pairs_shared_dates_only(db_conn):
    _add(db_conn, CA, 9.0, "mg/dL", "2020-01-01")   # paired
    _add(db_conn, CA, 9.4, "mg/dL", "2020-06-01")   # Ca-only -> not a pair
    _add(db_conn, ALB, 4.4, "g/dL", "2020-01-01")   # paired
    _add(db_conn, ALB, 4.0, "g/dL", "2019-01-01")   # Albumin-only -> not a pair
    db_conn.commit()

    joined = db.get_joined_series(db_conn, SPEC.inputs)
    assert [j["observed_on"] for j in joined] == ["2020-01-01"]  # inner join
    assert joined[0]["inputs"][CA]["value"] == 9.0
    assert joined[0]["inputs"][ALB]["value"] == 4.4


def test_compute_values_and_omits_unpaired(db_conn):
    _add(db_conn, CA, 9.0, "mg/dL", "2020-01-01")
    _add(db_conn, CA, 9.4, "mg/dL", "2020-06-01")   # albumin missing here -> omitted
    _add(db_conn, ALB, 4.4, "g/dL", "2020-01-01")
    db_conn.commit()

    series = _derived_series(db_conn)
    # Only the paired date is a data point; the unpaired calcium date is omitted
    # entirely (not a null gap), so the chart connects the points it has.
    assert [r["observed_on"] for r in series] == ["2020-01-01"]
    assert series[0]["value"] == 9.0 + 0.8 * (4.0 - 4.4)   # 8.68
    assert series[0]["id"] is None and series[0]["unit"] == "mg/dL"
    assert series[0]["result_type"] == "numeric"


def test_unit_guard_omits_mismatched_unit(db_conn):
    # Albumin stored in g/L (not the required g/dL): the formula's constants assume
    # g/dL, so this draw is OMITTED, never computed into a wrong value.
    _add(db_conn, CA, 9.0, "mg/dL", "2020-01-01")
    _add(db_conn, ALB, 44.0, "g/L", "2020-01-01")
    db_conn.commit()

    series = _derived_series(db_conn)
    assert series == []


def test_api_injection_read_and_write_block(client, temp_db):
    # Lifespan (schema init) has already run by the time the client fixture yields;
    # build the inputs on the same synthetic DB the routes read.
    conn = db.connect(temp_db)
    _add(conn, CA, 9.0, "mg/dL", "2020-01-01")
    _add(conn, ALB, 4.4, "g/dL", "2020-01-01")
    conn.commit()
    conn.close()

    metrics = client.get("/metrics").json()
    cc = [m for m in metrics if m["metric"] == "Calcium Corrected"]
    assert cc and cc[0]["derived"] is True and cc[0]["derived_description"]

    obs = client.get("/observations/Calcium Corrected").json()
    assert len(obs) == 1 and obs[0]["id"] is None and obs[0]["value"] == 8.68

    # Write-block: a derived metric can't be added (409), and flags still resolve.
    w = client.post("/observations", json={
        "metric": "Calcium Corrected", "value": 9.0,
        "unit": "mg/dL", "observed_on": "2021-01-01",
    })
    assert w.status_code == 409
    assert client.get("/flags/Calcium Corrected").status_code == 200


def test_derived_absent_until_both_inputs_present(client, temp_db):
    conn = db.connect(temp_db)
    _add(conn, CA, 9.0, "mg/dL", "2020-01-01")  # calcium only, no albumin
    conn.commit()
    conn.close()

    names = [m["metric"] for m in client.get("/metrics").json()]
    assert "Calcium Corrected" not in names  # needs BOTH inputs to appear
