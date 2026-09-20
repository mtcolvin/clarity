"""
RCV (Reference Change Value) detector — Phase 0 pinning tests.

Written BEFORE any per-metric CV is seeded: rcv_delta is fully coded and wired
into analyze_series, but nothing seeds rcv_cv, so the detector has never fired
against real data and carried NO tests. Seeding CVs would be the first thing to
exercise it — so per this project's discipline (pin the detector against an
already-correct target BEFORE curating inputs against it, exactly as thresholds
were curated against a proven crossing detector), these tests convert "the
formula looks right" into "the formula is proven" first.

Three guarantees:
  1. FORMULA   — RCV = √2 · z · √(CV_A² + CV_I²), pinned against hand arithmetic.
  2. FIRING    — a change just under the threshold is silent, just over fires, in
                 BOTH directions (two-sided); a change exactly on it is silent.
  3. WIRING    — an rcv_cv config on a series produces a dated 'delta' flag; its
                 absence (or too few / non-numeric points) produces none.

rcv_delta takes plain numbers and analyze_series takes plain dicts, so these are
pure/hermetic — no DB, no fixtures.
"""

from __future__ import annotations

import math

from analysis import rcv_delta, analyze_series

# A fixed, hand-checkable case reused across the formula/firing tests.
CV_A = 0.03
CV_I = 0.04
# RCV = √2 · 1.96 · √(0.03² + 0.04²) = √2 · 1.96 · √0.0025 = √2 · 1.96 · 0.05
#     = 1.4142135623730951 · 1.96 · 0.05 = 0.13859292911256332  (≈ 13.86%)
RCV_EXPECTED = 0.13859292911256332


def _rcv(cv_a, cv_i, z=1.96):
    """Independent recomputation (math, not numpy) of the RCV the detector should
    produce — so the formula assertion checks the code against a SEPARATE
    implementation of the same equation, not against itself."""
    return math.sqrt(2) * z * math.sqrt(cv_a ** 2 + cv_i ** 2)


# --------------------------------------------------------------------- 1. FORMULA

def test_formula_matches_hand_arithmetic():
    """A jump big enough to fire; its reported rcv equals the hand-computed value.
    Catches a transcription error (a dropped √2, a wrong z) at the source."""
    f = rcv_delta("X", previous=100.0, current=200.0, cv_analytical=CV_A, cv_intra=CV_I)
    assert f is not None
    assert math.isclose(f.detail["rcv"], RCV_EXPECTED, rel_tol=1e-12)
    # And equals an independent recomputation of the same equation.
    assert math.isclose(f.detail["rcv"], _rcv(CV_A, CV_I), rel_tol=1e-12)


def test_z_threads_through_and_scales_the_threshold():
    """Lowering z (e.g. a one-sided 1.65) scales the threshold by exactly z_new/z_old
    — proves z is actually used, and documents that the two-sided/one-sided choice is
    a pure z swap (kept two-sided at 1.96 by design; see rcv_delta's docstring)."""
    two_sided = rcv_delta("X", 100.0, 200.0, CV_A, CV_I, z=1.96).detail["rcv"]
    one_sided = rcv_delta("X", 100.0, 200.0, CV_A, CV_I, z=1.65).detail["rcv"]
    assert math.isclose(one_sided / two_sided, 1.65 / 1.96, rel_tol=1e-12)


# --------------------------------------------------------------------- 2. FIRING

def test_just_under_threshold_is_silent_both_directions():
    """A move at 99.9% of the RCV threshold must NOT fire — up or down."""
    rcv = _rcv(CV_A, CV_I)
    up_under = 100.0 * (1 + rcv * 0.999)
    down_under = 100.0 * (1 - rcv * 0.999)
    assert rcv_delta("X", 100.0, up_under, CV_A, CV_I) is None
    assert rcv_delta("X", 100.0, down_under, CV_A, CV_I) is None


def test_just_over_threshold_fires_both_directions():
    """A move at 100.1% of the RCV threshold MUST fire — up or down — and label the
    direction correctly (the two-sided guarantee: a real drop is caught, not only a
    rise)."""
    rcv = _rcv(CV_A, CV_I)
    up_over = 100.0 * (1 + rcv * 1.001)
    down_over = 100.0 * (1 - rcv * 1.001)

    up = rcv_delta("X", 100.0, up_over, CV_A, CV_I)
    assert up is not None
    assert "increase" in up.message
    assert up.detail["pct_change"] > 0

    down = rcv_delta("X", 100.0, down_over, CV_A, CV_I)
    assert down is not None
    assert "decrease" in down.message
    assert down.detail["pct_change"] < 0


def test_exactly_on_threshold_is_silent():
    """abs(pct) == rcv returns None (the `<=` in the code): a change landing exactly
    on the noise threshold is treated as noise, not signal."""
    rcv = _rcv(CV_A, CV_I)
    on = 100.0 * (1 + rcv)   # pct == rcv (to within FP)
    assert rcv_delta("X", 100.0, on, CV_A, CV_I) is None


def test_flag_shape():
    """The Flag carries the kind/severity and the raw numbers the UI/LLM renders."""
    f = rcv_delta("Creatinine", previous=1.0, current=2.0, cv_analytical=CV_A, cv_intra=CV_I)
    assert f.kind == "delta"
    assert f.severity == "watch"
    assert f.detail["previous"] == 1.0
    assert f.detail["current"] == 2.0
    assert set(f.detail) == {"previous", "current", "pct_change", "rcv"}


# --------------------------------------------------------------------- 3. WIRING

def _num(date, value):
    """A minimal numeric observation dict with NO ref range — so flag_out_of_range
    stays silent and (with only 2 points, below the trend/baseline min of 4) the
    ONLY detector that can fire is rcv_delta. Lets a test assert on 'delta' in
    isolation."""
    return {"observed_on": date, "value": value, "result_type": "numeric"}


def _deltas(flags):
    return [f for f in flags if f.kind == "delta"]


def test_analyze_series_fires_delta_when_configured():
    """An rcv_cv config + a jump beyond the threshold → exactly one 'delta' flag,
    stamped with the LATEST reading's date (so the chart can map it to the point)."""
    series = [_num("2024-01-01", 100.0), _num("2024-02-01", 200.0)]
    flags = analyze_series("X", series, rcv_cv={"analytical": CV_A, "intra": CV_I})
    deltas = _deltas(flags)
    assert len(deltas) == 1
    assert deltas[0].observed_on == "2024-02-01"


def test_analyze_series_no_delta_without_config():
    """The gate: no rcv_cv → the detector never runs, even on the same big jump."""
    series = [_num("2024-01-01", 100.0), _num("2024-02-01", 200.0)]
    assert _deltas(analyze_series("X", series)) == []
    assert _deltas(analyze_series("X", series, rcv_cv=None)) == []


def test_analyze_series_no_delta_with_one_point():
    """len(values) >= 2 gate: a single reading can't have a prior to compare to."""
    series = [_num("2024-01-01", 100.0)]
    assert _deltas(analyze_series("X", series, rcv_cv={"analytical": CV_A, "intra": CV_I})) == []


def test_analyze_series_ignores_non_numeric_points():
    """RCV compares the two most recent NUMERIC values. A censored reading (value
    kept as the bound number) must never enter the comparison — otherwise a small
    real move (100→101, silent) followed by a censored 200 would fabricate a fire."""
    series = [
        _num("2024-01-01", 100.0),
        _num("2024-02-01", 101.0),   # +1% — well under threshold, silent
        {"observed_on": "2024-03-01", "value": 200.0, "result_type": "censored", "operator": ">"},
    ]
    assert _deltas(analyze_series("X", series, rcv_cv={"analytical": CV_A, "intra": CV_I})) == []
