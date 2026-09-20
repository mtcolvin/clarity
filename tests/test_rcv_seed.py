"""
RCV curation arc (#7) — the seeded rcv_cv coefficients and the coverage badge.

Phase 0 (tests/test_rcv_delta.py) pinned the DETECTOR. This pins the CURATION:
the 21 web-verified CV_I values are seeded, reach the engine, actually fire on a
real jump, and are reflected in the metrics-coverage roster's has_rcv flag — while
the deliberately-held/deferred metrics carry nothing.
"""

from __future__ import annotations

import metric_config as mc

# The 21 metrics approved for seeding (the reviewed consolidated table).
SEEDED = {
    "Hemoglobin", "Hematocrit", "Red Blood Cell Count",
    "Mean Corpuscular Hemoglobin Concentration", "Mean Corpuscular Hemoglobin",
    "Mean Corpuscular Volume", "Platelet Count", "White Blood Cell Count",
    "Lymphocyte Absolute", "Monocytes Absolute", "Neutrophils Absolute",
    "Calcium Serum/Plasma", "Albumin", "Protein Total Serum/Plasma",
    "Potassium Serum/Plasma", "Creatinine Serum/Plasma",
    "Alkaline Phosphatase Total", "Alanine Aminotransferase",
    "Aspartate Aminotransferase", "TSH", "Bilirubin Total",
}

# Deliberately NOT seeded (held ultra-tight, or deferred for no grade-A source).
NOT_SEEDED = {
    "Sodium Serum/Plasma", "Chloride Serum/Plasma",   # held: RCV below analytical noise
    "Ferritin Serum/Plasma", "Blood Urea Nitrogen",   # deferred: no grade-A source
}


# --------------------------------------------------------------- SEED registry

def test_exactly_the_approved_21_are_seeded():
    have = {m for m, cfg in mc.SEED.items() if "rcv_cv" in cfg}
    assert have == SEEDED


def test_held_and_deferred_carry_no_rcv():
    for m in NOT_SEEDED:
        assert "rcv_cv" not in mc.SEED.get(m, {}), f"{m} must not carry rcv_cv"


def _assert_frac(cv):
    """One {analytical, intra} band: fractions <1 with analytical = 0.5*intra."""
    assert set(cv) == {"analytical", "intra"}
    assert 0 < cv["intra"] < 1 and 0 < cv["analytical"] < 1
    assert abs(cv["analytical"] - cv["intra"] / 2) < 1e-9


def test_rcv_cv_shape_and_desirable_spec():
    """Every seeded rcv_cv is {analytical, intra} fractions with analytical =
    0.5*intra (the desirable-spec convention). For the three sex-KEYED leukocyte
    metrics (#18 Phase 2) each SEX entry has that shape."""
    for m in SEEDED:
        cv = mc.SEED[m]["rcv_cv"]
        if m in mc._RCV_CVI_PERCENT_BY_SEX:                 # sex-keyed: {male, female}
            assert set(cv) == set(mc._RCV_CVI_PERCENT_BY_SEX[m])
            for band in cv.values():
                _assert_frac(band)
        else:
            _assert_frac(cv)


def test_white_cell_rcv_is_sex_keyed_from_verified_values():
    """#18 Phase 2: WBC/monocytes/neutrophils carry a sex-KEYED rcv_cv (male+female,
    NO default -> null/'other' omits RCV), with the CV_I verified from Coşkun 2018
    Table 2. The male values are what the old flat seed used (mislabeled 'pooled')."""
    expected = {  # (male CV_I%, female CV_I%) read from the primary-source PDF
        "White Blood Cell Count": (7.96, 12.82),
        "Monocytes Absolute": (11.07, 15.33),
        "Neutrophils Absolute": (11.60, 20.09),
    }
    for m, (male_cvi, female_cvi) in expected.items():
        cv = mc.SEED[m]["rcv_cv"]
        assert set(cv) == {"male", "female"}   # no 'default' -> null/other -> no rcv
        assert cv["male"]["intra"] == round(male_cvi / 100, 6)
        assert cv["female"]["intra"] == round(female_cvi / 100, 6)


def test_white_cell_rcv_resolves_per_profile_sex(db_conn):
    """End-to-end: the engine config carries the profile-sex band for a sex-keyed
    metric, and omits rcv_cv entirely for a null profile (no default)."""
    import db
    db.link_seed_keys(db_conn, mc.SEED.keys())
    mc.seed_defaults(db_conn)
    db_conn.commit()
    db.update_profile(db_conn, sex="male", date_of_birth=None)
    assert mc.get_config(db_conn, "Neutrophils Absolute")["rcv_cv"]["intra"] == round(11.60 / 100, 6)
    db.update_profile(db_conn, sex="female", date_of_birth=None)
    assert mc.get_config(db_conn, "Neutrophils Absolute")["rcv_cv"]["intra"] == round(20.09 / 100, 6)
    db.update_profile(db_conn, sex=None, date_of_birth=None)
    assert "rcv_cv" not in mc.get_config(db_conn, "Neutrophils Absolute")


def test_merges_preserve_existing_config():
    """Seeding rcv_cv must not clobber a metric's threshold or methodology entry."""
    assert "thresholds" in mc.SEED["TSH"]                       # kept its 3 lines
    assert "methodology_note" in mc.SEED["Creatinine Serum/Plasma"]
    assert "methodology_note" in mc.SEED["Bilirubin Total"]


# --------------------------------------------------------- reaches the engine

def test_seeded_rcv_reaches_get_config(db_conn):
    """After seeding a fresh DB, a seeded metric's engine config carries rcv_cv
    (so analyze_series will actually run rcv_delta); a held one does not."""
    import db
    db.link_seed_keys(db_conn, mc.SEED.keys())
    mc.seed_defaults(db_conn)
    db_conn.commit()
    assert "rcv_cv" in mc.get_config(db_conn, "Potassium Serum/Plasma")
    assert "rcv_cv" not in mc.get_config(db_conn, "Sodium Serum/Plasma")


def test_rcv_fires_end_to_end_via_flags(client):
    """The whole stack: two potassium readings a clear >12% RCV apart produce a
    'delta' flag through /flags — the first real RCV fire on live data, not just
    the unit-level detector test."""
    for d, v in [("2024-01-01", 4.0), ("2024-02-01", 5.2)]:   # +30%, well past ~12%
        r = client.post("/observations", json={
            "metric": "Potassium Serum/Plasma", "value": v, "unit": "mmol/L",
            "observed_on": d, "ref_low": 3.5, "ref_high": 5.1})
        assert r.status_code == 200
    flags = client.get("/flags/Potassium Serum/Plasma").json()
    assert any(f["kind"] == "delta" for f in flags), "RCV delta flag did not fire"


def test_small_change_does_not_fire(client):
    """A potassium move well under the ~12% RCV stays silent — the threshold works,
    not just 'any change flags'."""
    for d, v in [("2024-01-01", 4.00), ("2024-02-01", 4.10)]:  # +2.5%, under RCV
        client.post("/observations", json={
            "metric": "Potassium Serum/Plasma", "value": v, "unit": "mmol/L",
            "observed_on": d, "ref_low": 3.5, "ref_high": 5.1})
    flags = client.get("/flags/Potassium Serum/Plasma").json()
    assert not any(f["kind"] == "delta" for f in flags)


# ------------------------------------------------------------- coverage badge

def test_metrics_coverage_has_rcv_flag(client):
    """/metrics-coverage reports has_rcv per metric: true for a seeded metric,
    false for one with no rcv_cv."""
    client.post("/observations", json={
        "metric": "Potassium Serum/Plasma", "value": 4.2, "unit": "mmol/L",
        "observed_on": "2024-01-01", "ref_low": 3.5, "ref_high": 5.1})
    client.post("/observations", json={
        "metric": "Sodium Serum/Plasma", "value": 140, "unit": "mmol/L",
        "observed_on": "2024-01-01", "ref_low": 135, "ref_high": 145})
    rows = {r["metric"]: r for r in client.get("/metrics-coverage").json()}
    assert rows["Potassium Serum/Plasma"]["has_rcv"] is True
    assert rows["Sodium Serum/Plasma"]["has_rcv"] is False
