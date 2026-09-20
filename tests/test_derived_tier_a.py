"""
Tier-A derived conversions — Bilirubin Indirect, Total Globulin, Non-HDL.

Three metrics a lab REPORTS but always COMPUTES from other stored results, moved to
the derived registry (proven faithful: computed == every previously-stored reading).
Same pipeline as the BUN:Cr / corrected-calcium tests, plus what's specific to this
batch: rounding is DISPLAY-side (compute_series returns the raw float — no source
rounding, so no drift into a chained derivation), Non-HDL carries a threshold that
must still fire over the computed series, the import path must refuse a derived
metric, and derived metrics now reach the cross-metric roll-ups (/overview, /timeline).
"""

from __future__ import annotations

import db
import derived

INDIRECT = ("Bilirubin Indirect", "Bilirubin Total", "Bilirubin Direct", "mg/dL")
GLOBULIN = ("Total Globulin", "Protein Total Serum/Plasma", "Albumin", "g/dL")
NON_HDL = ("Non-HDL", "Cholesterol", "HDL", "mg/dL")


def _add(conn, metric, value, unit, date):
    db.add_observation(
        conn, metric=metric, value=value, unit=unit, observed_on=date, seed_keys=()
    )


def _derived_series(conn, name):
    spec = derived.REGISTRY[name]
    return derived.compute_series(spec, db.get_joined_series(conn, spec.inputs))


# --- pure compute: the three subtractions, gaps, unit guard -------------------

def test_all_three_compute_the_subtraction(db_conn):
    for name, a, b, unit in (INDIRECT, GLOBULIN, NON_HDL):
        _add(db_conn, a, 10.0, unit, "2020-01-01")
        _add(db_conn, b, 4.0, unit, "2020-01-01")
    db_conn.commit()
    for name, a, b, unit in (INDIRECT, GLOBULIN, NON_HDL):
        series = _derived_series(db_conn, name)
        assert len(series) == 1
        assert series[0]["value"] == 6.0
        assert series[0]["unit"] == unit
        assert series[0]["id"] is None and series[0]["result_type"] == "numeric"


def test_value_is_raw_float_not_source_rounded(db_conn):
    # 7.0 - 4.3 = 2.6999999999999997 in binary float. The spec leaves precision=None,
    # so the value flows through UNROUNDED (display-side rounding handles the noise);
    # asserting the exact float proves no source rounding entered.
    _add(db_conn, GLOBULIN[1], 7.0, "g/dL", "2020-01-01")
    _add(db_conn, GLOBULIN[2], 4.3, "g/dL", "2020-01-01")
    db_conn.commit()
    assert _derived_series(db_conn, "Total Globulin")[0]["value"] == 7.0 - 4.3


def test_unpaired_date_omitted(db_conn):
    _add(db_conn, INDIRECT[1], 1.0, "mg/dL", "2020-01-01")
    _add(db_conn, INDIRECT[1], 1.2, "mg/dL", "2020-06-01")  # no direct -> omitted
    _add(db_conn, INDIRECT[2], 0.3, "mg/dL", "2020-01-01")
    db_conn.commit()
    series = _derived_series(db_conn, "Bilirubin Indirect")
    assert [r["observed_on"] for r in series] == ["2020-01-01"]


def test_unit_mismatch_omitted(db_conn):
    _add(db_conn, NON_HDL[1], 250.0, "mg/dL", "2020-01-01")
    _add(db_conn, NON_HDL[2], 1.3, "mmol/L", "2020-01-01")  # HDL wrong unit
    db_conn.commit()
    assert _derived_series(db_conn, "Non-HDL") == []


# --- Non-HDL keeps its ATP III 190 threshold over the computed series ----------

def test_non_hdl_threshold_flags_over_computed_series(client, temp_db):
    conn = db.connect(temp_db)
    _add(conn, NON_HDL[1], 250.0, "mg/dL", "2020-01-01")   # Non-HDL = 200, >= 190
    _add(conn, NON_HDL[2], 50.0, "mg/dL", "2020-01-01")
    conn.commit()
    conn.close()

    flags = client.get("/flags/Non-HDL").json()
    assert any(f["kind"] == "threshold" for f in flags)


# --- New computed metrics (values the lab doesn't print) -----------------------

def test_ast_alt_ratio_definitional(db_conn):
    # De Ritis ratio = AST / ALT, dimensionless, our chosen 2-decimal precision.
    _add(db_conn, "Aspartate Aminotransferase", 30.0, "U/L", "2020-01-01")
    _add(db_conn, "Alanine Aminotransferase", 24.0, "U/L", "2020-01-01")
    db_conn.commit()
    series = _derived_series(db_conn, "AST/ALT Ratio")
    assert len(series) == 1
    assert series[0]["value"] == round(30.0 / 24.0, 2) == 1.25
    assert series[0]["unit"] == "" and series[0]["ref_low"] is None  # bandless


def test_ast_alt_zero_alt_omitted(db_conn):
    _add(db_conn, "Aspartate Aminotransferase", 30.0, "U/L", "2020-01-01")
    _add(db_conn, "Alanine Aminotransferase", 0.0, "U/L", "2020-01-01")
    _add(db_conn, "Aspartate Aminotransferase", 40.0, "U/L", "2020-02-01")
    _add(db_conn, "Alanine Aminotransferase", 20.0, "U/L", "2020-02-01")
    db_conn.commit()
    assert [r["observed_on"] for r in _derived_series(db_conn, "AST/ALT Ratio")] == ["2020-02-01"]


def test_calculated_osmolality_formula_and_units(db_conn):
    # 2*Na + glucose/18 + BUN/2.8, whole mOsm/kg; a wrong-unit input is skipped.
    _add(db_conn, "Sodium Serum/Plasma", 140.0, "mmol/L", "2020-01-01")
    _add(db_conn, "Glucose Serum/Plasma", 90.0, "mg/dL", "2020-01-01")
    _add(db_conn, "Blood Urea Nitrogen", 14.0, "mg/dL", "2020-01-01")
    db_conn.commit()
    series = _derived_series(db_conn, "Calculated Osmolality")
    assert len(series) == 1
    assert series[0]["value"] == round(2 * 140 + 90 / 18 + 14 / 2.8, 0) == 290.0
    assert series[0]["unit"] == "mOsm/kg"


def test_calculated_osmolality_unit_guard(db_conn):
    _add(db_conn, "Sodium Serum/Plasma", 140.0, "mmol/L", "2020-01-01")
    _add(db_conn, "Glucose Serum/Plasma", 5.0, "mmol/L", "2020-01-01")  # wrong unit
    _add(db_conn, "Blood Urea Nitrogen", 14.0, "mg/dL", "2020-01-01")
    db_conn.commit()
    assert _derived_series(db_conn, "Calculated Osmolality") == []


# --- A/G Ratio: division that composes on the stored analytes ------------------

def test_ag_ratio_divides_globulin_and_rounds_to_one_decimal(db_conn):
    # A/G = Albumin / (Total Protein - Albumin), computed from the STORED analytes
    # (globulin inline, at full precision), dimensionless, one decimal.
    _add(db_conn, "Albumin", 4.0, "g/dL", "2020-01-01")
    _add(db_conn, "Protein Total Serum/Plasma", 7.0, "g/dL", "2020-01-01")  # globulin 3.0
    db_conn.commit()
    series = _derived_series(db_conn, "A/G Ratio")
    assert len(series) == 1
    assert series[0]["value"] == round(4.0 / 3.0, 1) == 1.3   # 1 decimal
    assert series[0]["unit"] == "" and series[0]["id"] is None
    assert series[0]["ref_low"] is None and series[0]["ref_high"] is None  # lab reports no band


def test_ag_ratio_zero_globulin_omitted(db_conn):
    # Total Protein == Albumin -> globulin 0 -> division undefined -> date omitted, no crash.
    _add(db_conn, "Albumin", 5.0, "g/dL", "2020-01-01")
    _add(db_conn, "Protein Total Serum/Plasma", 5.0, "g/dL", "2020-01-01")
    _add(db_conn, "Albumin", 4.0, "g/dL", "2020-02-01")
    _add(db_conn, "Protein Total Serum/Plasma", 7.0, "g/dL", "2020-02-01")
    db_conn.commit()
    series = _derived_series(db_conn, "A/G Ratio")
    assert [r["observed_on"] for r in series] == ["2020-02-01"]


# --- band-as-data: the reference band travels with the draw --------------------

def test_band_applied_when_unit_matches(db_conn):
    _add(db_conn, INDIRECT[1], 1.5, "mg/dL", "2020-01-01")   # total
    _add(db_conn, INDIRECT[2], 0.3, "mg/dL", "2020-01-01")   # direct -> indirect 1.2
    db.set_derived_reference_range(db_conn, "Bilirubin Indirect", "2020-01-01", 0.0, 1.0, "mg/dL")
    db_conn.commit()
    spec = derived.REGISTRY["Bilirubin Indirect"]
    ranges = db.get_derived_reference_ranges(db_conn, "Bilirubin Indirect")
    series = derived.compute_series(spec, db.get_joined_series(db_conn, spec.inputs), ranges)
    assert series[0]["ref_low"] == 0.0 and series[0]["ref_high"] == 1.0


def test_band_ignored_on_unit_mismatch(db_conn):
    _add(db_conn, INDIRECT[1], 1.5, "mg/dL", "2020-01-01")
    _add(db_conn, INDIRECT[2], 0.3, "mg/dL", "2020-01-01")
    # A band stored in the wrong unit must never be coerced onto the mg/dL series.
    db.set_derived_reference_range(db_conn, "Bilirubin Indirect", "2020-01-01", 0.0, 1.0, "umol/L")
    db_conn.commit()
    spec = derived.REGISTRY["Bilirubin Indirect"]
    ranges = db.get_derived_reference_ranges(db_conn, "Bilirubin Indirect")
    series = derived.compute_series(spec, db.get_joined_series(db_conn, spec.inputs), ranges)
    assert series[0]["ref_low"] is None and series[0]["ref_high"] is None


def test_computed_only_date_charts_with_blank_band(db_conn):
    # A date the metric is COMPUTED for but that carries no captured lab band honestly
    # charts with a BLANK band (a gap) — a computed value doesn't manufacture a range.
    # First draw has a captured band, the second (input-only) draw does not.
    for d in ["2020-01-01", "2020-06-01"]:
        _add(db_conn, INDIRECT[1], 1.5, "mg/dL", d)
        _add(db_conn, INDIRECT[2], 0.3, "mg/dL", d)
    db.set_derived_reference_range(db_conn, "Bilirubin Indirect", "2020-01-01", 0.0, 1.0, "mg/dL")
    db_conn.commit()
    spec = derived.REGISTRY["Bilirubin Indirect"]
    ranges = db.get_derived_reference_ranges(db_conn, "Bilirubin Indirect")
    series = derived.compute_series(spec, db.get_joined_series(db_conn, spec.inputs), ranges)
    bands = {r["observed_on"]: (r["ref_low"], r["ref_high"]) for r in series}
    assert bands["2020-01-01"] == (0.0, 1.0)          # came with a lab band
    assert bands["2020-06-01"] == (None, None)        # computed-only -> blank band


# --- import path: captures a derived metric's BAND, never a stored value --------

def test_captured_band_rides_the_computed_series_and_out_of_range_fires(client, temp_db):
    """BAND-AS-DATA: a derived metric's reference band is real, lab-specific data
    captured per date, joined onto the COMPUTED series on read. Written through the db
    layer — the PDF-import route that used to capture it is gone (see ROADMAP
    "Dropped"), but the band mechanism it fed is unchanged and still the thing that
    keeps Bilirubin Indirect's out_of_range flags working after conversion."""
    conn = db.connect(temp_db)
    _add(conn, INDIRECT[1], 1.5, "mg/dL", "2020-01-01")   # total
    _add(conn, INDIRECT[2], 0.3, "mg/dL", "2020-01-01")   # direct -> indirect 1.2
    db.set_derived_reference_range(
        conn, "Bilirubin Indirect", "2020-01-01", 0.0, 1.0, "mg/dL")
    conn.commit()
    conn.close()

    # The band rides the COMPUTED series (id=null), and 1.2 > 1.0 flags out_of_range.
    obs = client.get("/observations/Bilirubin Indirect").json()
    assert obs[0]["id"] is None and obs[0]["ref_low"] == 0.0 and obs[0]["ref_high"] == 1.0
    flags = client.get("/flags/Bilirubin Indirect").json()
    assert any(f["kind"] == "out_of_range" for f in flags)


def test_a_derived_metric_cannot_be_stored(client, temp_db):
    """A computed metric has no stored rows by construction — storing one would shadow
    the computed value. The write endpoints refuse it (409). This is the surviving half
    of the removed import route's derived-row guard."""
    res = client.post("/observations", json={
        "metric": "Non-HDL", "value": 200.0, "unit": "mg/dL",
        "observed_on": "2020-01-01", "result_type": "numeric"})
    assert res.status_code == 409
    assert "computed metric" in res.json()["detail"]



# --- cross-metric parity: /overview and /timeline include derived metrics ------

def test_overview_includes_derived_threshold_flag(client, temp_db):
    conn = db.connect(temp_db)
    _add(conn, NON_HDL[1], 250.0, "mg/dL", "2020-01-01")   # Non-HDL 200 >= 190
    _add(conn, NON_HDL[2], 50.0, "mg/dL", "2020-01-01")
    conn.commit()
    conn.close()

    ov = client.get("/overview").json()
    assert any(f["metric"] == "Non-HDL" and f["kind"] == "threshold"
               for f in ov["current"])


def test_timeline_lists_derived_reading_and_counts_notable(client, temp_db):
    conn = db.connect(temp_db)
    _add(conn, NON_HDL[1], 250.0, "mg/dL", "2020-01-01")
    _add(conn, NON_HDL[2], 50.0, "mg/dL", "2020-01-01")
    conn.commit()
    conn.close()

    lab = [e for e in client.get("/timeline").json()
           if e["kind"] == "lab" and e["date"] == "2020-01-01"]
    assert lab
    readings = lab[0]["detail"]["readings"]
    non_hdl = [r for r in readings if r["metric"] == "Non-HDL"]
    assert non_hdl and non_hdl[0]["notable"] is True  # 200 >= ATP III 190
