"""
hs-CRP threshold seed (#8 curation): the AHA/CDC hs-CRP relative-risk tertiles
<1 / 1-3 / >3 mg/L (Pearson et al., Circulation 2003), seeded on the SEPARATE
"C-Reactive Protein High Sensitivity" metric. Verifies the SEED/SOURCES content
and that the engine flags on the concerning side via the seeded cutoffs.
"""

from __future__ import annotations

import json

import analysis
import metric_config as mc

METRIC = "C-Reactive Protein High Sensitivity"


def _engine_thresholds():
    """The SEED entry cast to the engine shape (what analyze_series consumes)."""
    return mc._threshold_pairs(json.dumps(mc.SEED[METRIC]["thresholds"]))


def _series(*vals):
    return [{"observed_on": f"2024-0{i + 1}-01", "value": v, "unit": "mg/L",
             "result_type": "numeric"} for i, v in enumerate(vals)]


# --------------------------------------------------------------------- seed content

def test_seed_has_the_two_tertile_cutoffs():
    thr = mc.SEED[METRIC]["thresholds"]
    assert {t["cutoff"] for t in thr} == {1, 3}
    assert all(t["source"] == "AHA/CDC" and t["direction"] == "up" for t in thr)
    # 1 enters 'average' (>=1, inclusive); 3 enters 'high' (>3, exclusive).
    by = {t["cutoff"]: t for t in thr}
    assert by[1]["boundary"] == "inclusive"
    assert by[3]["boundary"] == "exclusive"


def test_source_registry_entry():
    src = mc.SOURCES["AHA/CDC"]
    assert "American Heart Association" in src["full_name"]
    assert src["url"].startswith("https://")
    assert "2003" in src["guideline"]


def test_definitions_name_framework_not_the_users_value():
    """Definitions describe the AHA/CDC framework's own categories, never assert a
    state about the reading (surface-don't-diagnose)."""
    defs = " ".join(t["definition"] for t in mc.SEED[METRIC]["thresholds"]).lower()
    assert "framework" in defs and "category" in defs
    # No second-person / your-value language.
    assert "your" not in defs and "you " not in defs


def test_standard_crp_has_no_risk_cutoffs():
    """The standard CRP assay stays note-only (its #9 Tier-3 methodology note exists,
    but it must have NO threshold risk cutoffs — those apply only to the hs metric)."""
    std = mc.SEED.get("C-Reactive Protein", {})
    assert "thresholds" not in std          # note-only; no risk cutoffs
    assert "methodology_note" in std        # the Tier-3 note is still there


# --------------------------------------------------------------------- engine firing

def test_high_reading_flags_via_seeded_cutoff():
    thr = _engine_thresholds()
    flags = analysis.analyze_series(METRIC, _series(0.8, 4.5), thresholds=thr)
    kinds = {f.kind for f in flags}
    assert "threshold" in kinds
    assert any("AHA/CDC 3" in f.message for f in flags if f.kind == "threshold")


def test_low_reading_does_not_flag_thresholds():
    """A value in the 'low' band (<1) trips neither tertile line — e.g. the user's
    own hs-CRP of 0.02 sits well below both, so the gridlines draw but nothing fires."""
    thr = _engine_thresholds()
    flags = analysis.analyze_series(METRIC, _series(0.02, 0.03), thresholds=thr)
    assert not any(f.kind == "threshold" for f in flags)
