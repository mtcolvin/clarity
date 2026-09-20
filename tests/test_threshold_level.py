"""
#1 — static threshold-LEVEL detector + the guideline mention folded into
out-of-range flags.

`flag_threshold_level` complements `clinical_threshold_crossing`: the crossing is a
one-time "you just crossed the line" event; the level flag is the STANDING "your
latest value is on the concerning side" state (fires when no crossing did). And
`_annotate_guideline` folds a guideline mention INTO an out-of-range flag when the
reading also passes a cited line — no separate flag, so no added noise. Both name
source + cutoff only (surface-don't-diagnose).
"""

from __future__ import annotations

import analysis
from analysis import Flag


def _thr(cutoff, direction="down", boundary=None, source="WHO"):
    b = boundary or ("exclusive" if direction == "down" else "inclusive")
    return {"cutoff": cutoff, "source": source, "direction": direction, "boundary": b}


def _num(*vals, lo=None, hi=None):
    """Numeric series rows, oldest first, auto-dated."""
    return [{"observed_on": f"2024-01-{i + 1:02d}", "value": v, "unit": "g/dL",
             "ref_low": lo, "ref_high": hi, "result_type": "numeric"} for i, v in enumerate(vals)]


# --- flag_threshold_level -----------------------------------------------------

def test_level_fires_below_no_crossing():
    f = analysis.flag_threshold_level("Hemoglobin", 12.0, [_thr(13.0)])
    assert f is not None and f.kind == "threshold"
    assert "below the WHO 13.0 guideline line" in f.message


def test_level_silent_above_for_down():
    assert analysis.flag_threshold_level("Hemoglobin", 14.0, [_thr(13.0)]) is None


def test_level_up_direction():
    f = analysis.flag_threshold_level("LDL", 200.0, [_thr(190, direction="up", source="ACC/AHA")])
    assert f is not None and "above the ACC/AHA 190 guideline line" in f.message


def test_level_boundary_inclusive_vs_exclusive():
    assert analysis.flag_threshold_level("m", 13.0, [_thr(13.0, boundary="inclusive")]) is not None
    assert analysis.flag_threshold_level("m", 13.0, [_thr(13.0, boundary="exclusive")]) is None


def test_level_excludes_crossed_cutoffs():
    # A cutoff the crossing already reported this run is suppressed (no double-flag).
    assert analysis.flag_threshold_level("m", 12.0, [_thr(13.0)], exclude_cutoffs={13.0}) is None


# --- guideline annotation on an out_of_range flag -----------------------------

def test_annotate_appends_when_on_concerning_side():
    f = Flag("Hemoglobin", "out_of_range", "watch",
             "Hemoglobin is 12.0, below the reference low of 13.4.", {})
    analysis._annotate_guideline(f, 12.0, [_thr(13.0)])
    assert f.message.endswith("and below the WHO 13.0 guideline line.")


def test_annotate_noop_without_hit():
    orig = "Hemoglobin is 14.0, below the reference low of 15.0."
    f = Flag("Hemoglobin", "out_of_range", "watch", orig, {})
    analysis._annotate_guideline(f, 14.0, [_thr(13.0)])
    assert f.message == orig


# --- analyze_series wiring ----------------------------------------------------

def test_series_level_flag_and_annotated_out_of_range():
    # Both readings below ref_low AND below WHO — no crossing (both already below);
    # each out_of_range gets the guideline mention, and the latest gets the level flag.
    flags = analysis.analyze_series("Hemoglobin", _num(12.5, 12.2, lo=13.4, hi=18.0),
                                    thresholds=[_thr(13.0)])
    assert "threshold" in [f.kind for f in flags]
    oor = [f for f in flags if f.kind == "out_of_range"]
    assert oor and all("below the WHO 13.0 guideline line" in f.message for f in oor)


def test_series_crossing_and_level_do_not_double_flag():
    # previous above, latest below -> a crossing fires; the level flag is suppressed
    # for that same cutoff, so there's exactly ONE threshold flag.
    flags = analysis.analyze_series("Hemoglobin", _num(14.0, 12.0, lo=13.4, hi=18.0),
                                    thresholds=[_thr(13.0)])
    thr = [f for f in flags if f.kind == "threshold"]
    assert len(thr) == 1 and "crossed" in thr[0].message


# --- history path (Notable readings) ------------------------------------------

def test_history_annotates_out_of_range():
    groups = analysis.summarize_history("Hemoglobin", _num(12.5, 15.0, 12.0, lo=13.4, hi=18.0),
                                        thresholds=[_thr(13.0)])
    oor = [g for g in groups if g.kind == "out_of_range"]
    assert oor
    msgs = [f.message for g in oor for f in g.detail]
    assert any("below the WHO 13.0 guideline line" in m for m in msgs)


def test_history_no_thresholds_unchanged():
    # Without thresholds, out_of_range messages carry no guideline mention.
    groups = analysis.summarize_history("Hemoglobin", _num(12.5, 12.0, lo=13.4, hi=18.0))
    msgs = [f.message for g in groups for f in g.detail]
    assert msgs and not any("guideline line" in m for m in msgs)
