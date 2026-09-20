"""
Derived-metric tests — #6, BUN/Creatinine Ratio.

Same pipeline as the corrected-calcium tests (same-draw JOIN + pure COMPUTE +
API injection/read/write-block), specialized to the dimensionless ratio: unit is
"" (both inputs mg/dL, so the ratio has no unit), and an added guard covers a
0-denominator draw being OMITTED (undefined math -> a gap, never a crash).
"""

from __future__ import annotations

import db
import derived

BUN = "Blood Urea Nitrogen"
CR = "Creatinine Serum/Plasma"
SPEC = derived.REGISTRY["BUN/Creatinine Ratio"]


def _add(conn, metric, value, unit, date):
    db.add_observation(
        conn, metric=metric, value=value, unit=unit, observed_on=date, seed_keys=()
    )


def _derived_series(conn):
    joined = db.get_joined_series(conn, SPEC.inputs)
    return derived.compute_series(SPEC, joined)


def test_compute_dimensionless_ratio_and_omits_unpaired(db_conn):
    _add(db_conn, BUN, 15.0, "mg/dL", "2020-01-01")
    _add(db_conn, BUN, 18.0, "mg/dL", "2020-06-01")   # creatinine missing -> omitted
    _add(db_conn, CR, 1.0, "mg/dL", "2020-01-01")
    db_conn.commit()

    series = _derived_series(db_conn)
    assert [r["observed_on"] for r in series] == ["2020-01-01"]
    assert series[0]["value"] == 15.0          # honest float ratio, no rounding
    assert series[0]["unit"] == ""             # dimensionless
    assert series[0]["id"] is None and series[0]["result_type"] == "numeric"


def test_value_rounded_to_two_decimals(db_conn):
    # 17 / 1.11 = 15.3153... -> a raw float the display would clamp to 4 noise
    # decimals; the spec's precision=2 rounds it at the source to 15.32.
    _add(db_conn, BUN, 17.0, "mg/dL", "2020-01-01")
    _add(db_conn, CR, 1.11, "mg/dL", "2020-01-01")
    db_conn.commit()

    series = _derived_series(db_conn)
    assert series[0]["value"] == 15.32


def test_unit_guard_omits_mismatched_unit(db_conn):
    # Creatinine in umol/L (not mg/dL): the ratio would be meaningless, so omit it.
    _add(db_conn, BUN, 15.0, "mg/dL", "2020-01-01")
    _add(db_conn, CR, 88.0, "umol/L", "2020-01-01")
    db_conn.commit()

    assert _derived_series(db_conn) == []


def test_zero_denominator_omitted_not_crashed(db_conn):
    # A creatinine of 0 makes the ratio UNDEFINED — that date is omitted (a gap),
    # and the series still computes for the valid date rather than crashing.
    _add(db_conn, BUN, 15.0, "mg/dL", "2020-01-01")
    _add(db_conn, CR, 0.0, "mg/dL", "2020-01-01")
    _add(db_conn, BUN, 20.0, "mg/dL", "2020-02-01")
    _add(db_conn, CR, 0.8, "mg/dL", "2020-02-01")
    db_conn.commit()

    series = _derived_series(db_conn)
    assert [r["observed_on"] for r in series] == ["2020-02-01"]
    assert series[0]["value"] == 25.0


def test_api_injection_read_and_write_block(client, temp_db):
    conn = db.connect(temp_db)
    _add(conn, BUN, 15.0, "mg/dL", "2020-01-01")
    _add(conn, CR, 1.0, "mg/dL", "2020-01-01")
    conn.commit()
    conn.close()

    metrics = client.get("/metrics").json()
    r = [m for m in metrics if m["metric"] == "BUN/Creatinine Ratio"]
    assert r and r[0]["derived"] is True and r[0]["derived_description"]
    assert r[0]["unit"] == ""

    obs = client.get("/observations/BUN/Creatinine Ratio").json()
    assert len(obs) == 1 and obs[0]["id"] is None and obs[0]["value"] == 15.0

    # Write-block: a derived metric can't be added (409); flags still resolve.
    w = client.post("/observations", json={
        "metric": "BUN/Creatinine Ratio", "value": 15.0,
        "unit": "", "observed_on": "2021-01-01",
    })
    assert w.status_code == 409
    assert client.get("/flags/BUN/Creatinine Ratio").status_code == 200


def test_derived_absent_until_both_inputs_present(client, temp_db):
    conn = db.connect(temp_db)
    _add(conn, BUN, 15.0, "mg/dL", "2020-01-01")  # BUN only, no creatinine
    conn.commit()
    conn.close()

    names = [m["metric"] for m in client.get("/metrics").json()]
    assert "BUN/Creatinine Ratio" not in names
