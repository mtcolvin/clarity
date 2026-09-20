"""
NLR (Neutrophil-Lymphocyte Ratio) — a derived metric that is a DELIBERATE, DOCUMENTED
EXCEPTION to the charter's "clinically standard" bar (ROADMAP #6 candidate ledger).

Mathematically it is a clean definitional ratio (Neutrophils Absolute ÷ Lymphocyte
Absolute, both 10*9/L → dimensionless), so the compute path is the same as BUN:Cr /
AST:ALT. What is SPECIFIC to NLR is the `advisory`: a warning-level notice that this is
not a standard test (no accepted reference range; a research/prognostic marker). These
tests pin BOTH the compute AND that the exception is isolated — NLR carries an advisory,
every other derived metric carries none, so the standard is intact.
"""

from __future__ import annotations

import db
import derived

NLR_NAME = "NLR (Neutrophil-Lymphocyte Ratio)"
NEUT, LYMPH, U = "Neutrophils Absolute", "Lymphocyte Absolute", "10*9/L"


def _add(conn, metric, value, unit, date):
    db.add_observation(
        conn, metric=metric, value=value, unit=unit, observed_on=date, seed_keys=()
    )


def _nlr_series(conn):
    spec = derived.REGISTRY[NLR_NAME]
    return derived.compute_series(spec, db.get_joined_series(conn, spec.inputs))


# --- pure compute: the ratio, precision, gaps, guards -------------------------

def test_nlr_is_the_ratio_rounded_to_two_decimals(db_conn):
    _add(db_conn, NEUT, 7.0, U, "2020-01-01")
    _add(db_conn, LYMPH, 2.0, U, "2020-01-01")
    _add(db_conn, NEUT, 5.0, U, "2020-06-01")   # 5/3 = 1.6666… -> 1.67 (precision=2)
    _add(db_conn, LYMPH, 3.0, U, "2020-06-01")
    db_conn.commit()
    series = _nlr_series(db_conn)
    assert [(r["observed_on"], r["value"]) for r in series] == [
        ("2020-01-01", 3.5),
        ("2020-06-01", 1.67),
    ]
    assert all(r["unit"] == "" and r["id"] is None for r in series)


def test_nlr_unpaired_date_omitted(db_conn):
    _add(db_conn, NEUT, 6.0, U, "2020-01-01")
    _add(db_conn, NEUT, 6.0, U, "2020-06-01")   # no lymphocyte that day -> omitted
    _add(db_conn, LYMPH, 2.0, U, "2020-01-01")
    db_conn.commit()
    assert [r["observed_on"] for r in _nlr_series(db_conn)] == ["2020-01-01"]


def test_nlr_unit_mismatch_omitted(db_conn):
    _add(db_conn, NEUT, 6.0, U, "2020-01-01")
    _add(db_conn, LYMPH, 2.0, "10*3/uL", "2020-01-01")  # numerically equal, but not the required unit
    db_conn.commit()
    assert _nlr_series(db_conn) == []


def test_nlr_zero_lymphocyte_omitted(db_conn):
    # A 0 lymphocyte count -> ZeroDivisionError (ArithmeticError) -> the date is omitted
    # (a gap), never a crash or a fabricated value.
    _add(db_conn, NEUT, 6.0, U, "2020-01-01")
    _add(db_conn, LYMPH, 0.0, U, "2020-01-01")
    db_conn.commit()
    assert _nlr_series(db_conn) == []


# --- the exception is isolated: NLR warns, every standard metric does not ------

def test_only_nlr_carries_an_advisory(db_conn):
    """NLR is the ONE documented exception; the 'clinically standard' bar stays intact
    for every other derived metric (all of which carry no advisory)."""
    assert derived.REGISTRY[NLR_NAME].advisory  # non-empty
    assert "not a standard lab test" in derived.REGISTRY[NLR_NAME].advisory.lower()
    others = [d for name, d in derived.REGISTRY.items() if name != NLR_NAME]
    assert others  # guard against a vacuous pass
    assert all(d.advisory is None for d in others)


def test_nlr_trend_is_flagged_through_the_engine(client, temp_db):
    """The whole point of surfacing NLR: a notable movement IS flagged. NLR carries no
    threshold/band, but the engine's DEFAULT trend detectors run over the computed series,
    so a steady rise produces a `trend` flag on /flags/NLR — the 'eyeball this' signal.
    (Descriptive movement only — no threshold, no reference-range judgment.)"""
    conn = db.connect(temp_db)
    # Neutrophils climb while lymphocytes hold → NLR rises monotonically.
    for i, month in enumerate(range(1, 10)):
        _add(conn, NEUT, 3.0 + 0.4 * i, U, f"2020-{month:02d}-01")
        _add(conn, LYMPH, 2.0, U, f"2020-{month:02d}-01")
    conn.commit()
    conn.close()

    flags = client.get(f"/flags/{NLR_NAME}").json()
    assert any(f["kind"] == "trend" for f in flags), "a rising NLR should be trend-flagged"
    # No reference-range judgment is possible (NLR is bandless / thresholdless).
    assert not any(f["kind"] in ("out_of_range", "threshold") for f in flags)


def test_metrics_route_surfaces_nlr_advisory(client, temp_db):
    conn = db.connect(temp_db)
    _add(conn, NEUT, 6.0, U, "2020-01-01")
    _add(conn, LYMPH, 2.0, U, "2020-01-01")
    conn.commit()
    conn.close()

    rows = client.get("/metrics").json()
    nlr = [r for r in rows if r["metric"] == NLR_NAME]
    assert nlr, "NLR should appear once both inputs have readings"
    assert nlr[0]["derived"] is True
    assert nlr[0]["derived_advisory"]
    assert "not a standard lab test" in nlr[0]["derived_advisory"].lower()
    # A standard derived metric carries no advisory (exception stays isolated).
    for r in rows:
        if r.get("derived") and r["metric"] != NLR_NAME:
            assert r["derived_advisory"] is None
