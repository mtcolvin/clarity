"""
Export-bundle assembler tests (explain.py).

Covers the deterministic pieces the export handoff depends on: the assembler bundle
shape + code-computed gap_to_cutoff, the fixed-key spread guard, the proximity-band
skip matrix + degenerate-scale guard (proximity_skip is a retained pure utility),
the gateway allowlist for the export task, and the FRAME disclaimer constant. The
former local interpretation tier (explain_metric -> Ollama) and its /explain route
were removed as dead code, so those tests are gone.
"""

from __future__ import annotations

import explain
import gateway
from analysis import Flag


# --- helpers ------------------------------------------------------------------

def _series(*rows):
    """Minimal numeric series rows (oldest first)."""
    return [
        {"observed_on": d, "value": v, "unit": "mg/dL",
         "ref_low": lo, "ref_high": hi, "result_type": "numeric"}
        for (d, v, lo, hi) in rows
    ]


def _thr(cutoff):
    return {"cutoff": cutoff, "source": "SRC", "definition": "def", "status_note": None}


# --- assembler shape ----------------------------------------------------------

def test_assemble_shape():
    series = _series(("2024-01-01", 100.0, 70.0, 140.0),
                     ("2024-06-01", 120.0, 70.0, 140.0))
    flags = [Flag("m", "out_of_range", "watch", "msg", {"value": 120.0})]
    bundle = explain.assemble_explain_context(
        "m", "mg/dL", series, flags, [_thr(150)], 110.0, None, None, False)
    # Every top-level key present, methodology_note present even when None.
    for k in ("metric", "unit", "n_readings", "readings", "engine_findings",
              "cited_thresholds", "personal_baseline_mean", "methodology_note",
              "latest_change", "personal_baseline_mode"):
        assert k in bundle
    assert bundle["methodology_note"] is None
    assert bundle["n_readings"] == 2
    assert len(bundle["readings"]) == 2
    # engine_findings carry the detail stats alongside the fixed keys.
    assert bundle["engine_findings"][0]["value"] == 120.0


def test_full_series_sent_by_default():
    """The DEFAULT is now the FULL series — no truncation. The old 12-reading cap
    existed to bound what a small LOCAL model saw; truncating history is actively
    wrong for a longitudinal export, where the trend IS the thing being sent."""
    rows = [(f"2024-{m:02d}-01", float(m), 0.0, 100.0) for m in range(1, 13)] \
        + [("2025-01-01", 99.0, 0.0, 100.0)]  # 13 readings
    series = _series(*rows)
    bundle = explain.assemble_explain_context(
        "m", "mg/dL", series, [], [], None, None, None, False)
    assert bundle["n_readings"] == 13
    assert len(bundle["readings"]) == 13          # nothing dropped
    assert bundle["readings"][0]["value"] == 1.0  # oldest survives
    assert bundle["readings"][-1]["value"] == 99.0


def test_explicit_cap_still_honored():
    """The parameter remains so a caller can bound a payload deliberately — and when
    it does, it keeps the MOST RECENT window."""
    rows = [(f"2024-{m:02d}-01", float(m), 0.0, 100.0) for m in range(1, 13)] \
        + [("2025-01-01", 99.0, 0.0, 100.0)]
    bundle = explain.assemble_explain_context(
        "m", "mg/dL", _series(*rows), [], [], None, None, None, False, max_readings=5)
    assert bundle["n_readings"] == 13   # true total still reported
    assert len(bundle["readings"]) == 5
    assert bundle["readings"][-1]["value"] == 99.0


# ------------------------------------------------------- system instruction (recency)

def test_system_instruction_carries_todays_date():
    """Rule 1 ('read the CURRENT state') is unenforceable without an anchor: from
    reading dates alone the model can't tell last week from two years ago."""
    text = explain.system_instruction("2026-07-23")
    assert "2026-07-23" in text
    assert text.startswith(explain.EXPLAIN_SYSTEM)  # rules kept intact, date appended


def test_system_instruction_without_date_is_the_base_prompt():
    assert explain.system_instruction() == explain.EXPLAIN_SYSTEM
    assert explain.system_instruction("") == explain.EXPLAIN_SYSTEM


def test_system_instruction_keeps_the_protective_rules():
    """The persona/verbosity changes must not have loosened the rules that PROTECT —
    no treatment advice, hedged possibilities, and 'nothing stands out' still valid.
    These are charter requirements (CLAUDE.md 'The export handoff'), not prose taste."""
    text = explain.EXPLAIN_SYSTEM
    assert "Do NOT suggest, recommend, or imply any treatment" in text
    assert "never a conclusion" in text
    assert "Nothing here stands out to interpret." in text
    assert "hedged candidate" in text
    # And the point cap the user asked to drop is genuinely gone.
    assert "AT MOST the two or three" not in text


def test_gap_to_cutoff():
    series = _series(("2024-01-01", 130.0, 70.0, 200.0))
    bundle = explain.assemble_explain_context(
        "m", "mg/dL", series, [], [_thr(190)], None, None, None, False)
    cited = bundle["cited_thresholds"][0]
    assert cited["latest_value"] == 130.0
    assert cited["gap_to_cutoff"] == 130.0 - 190  # signed


def test_gap_to_cutoff_none_without_numeric():
    # Qualitative-only series -> no numeric latest -> gap is None (no crash).
    series = [{"observed_on": "2024-01-01", "value": None, "unit": "",
               "result_type": "qualitative", "value_text": "Positive"}]
    bundle = explain.assemble_explain_context(
        "m", "", series, [], [_thr(5)], None, None, None, False)
    assert bundle["cited_thresholds"][0]["gap_to_cutoff"] is None


def test_finding_keys_survive_spread():
    """The fixed keys (kind/severity/message) must never be clobbered by a detail
    dict. Two guards: (1) no CURRENT detector puts a reserved key in detail;
    (2) even a synthetic collision loses to the fixed keys (spread order)."""
    # (1) tripwire — a real analysis run must not carry reserved keys in any detail.
    import analysis
    real = analysis.analyze_series(
        "Glucose", _series(("2024-01-01", 100.0, 70.0, 99.0),
                            ("2024-02-01", 210.0, 70.0, 99.0)),
        thresholds=[{"cutoff": 200, "source": "ADA", "direction": "up",
                     "boundary": "inclusive"}])
    for f in real:
        assert not ({"kind", "severity", "message"} & set(f.detail)), \
            f"detector put a reserved key in detail: {f.detail}"
    # (2) synthetic collision: fixed keys win.
    clash = Flag("m", "trend", "watch", "REAL",
                 {"kind": "CLOBBER", "severity": "CLOBBER", "message": "CLOBBER"})
    bundle = explain.assemble_explain_context(
        "m", "", _series(("2024-01-01", 1.0, 0.0, 10.0)), [clash], [], None, None,
        None, False)
    fnd = bundle["engine_findings"][0]
    assert fnd["kind"] == "trend" and fnd["severity"] == "watch" and fnd["message"] == "REAL"


# --- proximity scale + skip matrix -------------------------------------------

def test_proximity_scale_two_sided():
    numeric = _series(("2024-01-01", 130.0, 70.0, 200.0))
    assert explain._proximity_scale(numeric) == 130.0  # 200 - 70


def test_proximity_scale_value_span_fallback():
    # One-sided ref (no width) but multiple readings -> value span.
    numeric = [{"observed_on": "2024-01-01", "value": 10.0, "ref_low": 5.0, "ref_high": None,
                "result_type": "numeric"},
               {"observed_on": "2024-02-01", "value": 40.0, "ref_low": 5.0, "ref_high": None,
                "result_type": "numeric"}]
    assert explain._proximity_scale(numeric) == 30.0  # 40 - 10


def test_proximity_scale_degenerate_none():
    # Single reading, one-sided ref -> no width, span 0 -> None (no divide-by-zero).
    numeric = [{"observed_on": "2024-01-01", "value": 66.0, "ref_low": 40.0,
                "ref_high": None, "result_type": "numeric"}]
    assert explain._proximity_scale(numeric) is None


def test_skip_far_no_findings():
    # LDL-like: latest 119, cutoff 190, refW 129 -> 0.55 > 0.25 -> SKIP.
    numeric = _series(("2024-01-01", 119.0, 61.0, 190.0))
    assert explain.proximity_skip([], [_thr(190)], numeric) is True


def test_run_near_threshold():
    # latest 165, cutoff 190, refW 129 -> 0.19 < 0.25 -> RUN.
    numeric = _series(("2024-01-01", 165.0, 61.0, 190.0))
    assert explain.proximity_skip([], [_thr(190)], numeric) is False


def test_run_with_findings():
    numeric = _series(("2024-01-01", 119.0, 61.0, 190.0))
    flag = Flag("m", "trend", "watch", "msg", {})
    assert explain.proximity_skip([flag], [_thr(190)], numeric) is False


def test_run_degenerate_scale():
    # Single reading, one-sided ref -> scale None -> RUN (can't confirm far).
    numeric = [{"observed_on": "2024-01-01", "value": 196.0, "ref_low": None,
                "ref_high": 200.0, "result_type": "numeric"}]
    # (ref one-sided upper only -> width None since ref_low missing) -> degenerate
    assert explain._proximity_scale(numeric) is None
    assert explain.proximity_skip([], [_thr(200)], numeric) is False


def test_skip_no_thresholds_no_findings():
    numeric = _series(("2024-01-01", 42.0, 10.0, 90.0))
    assert explain.proximity_skip([], [], numeric) is True


# --- gateway allowlist --------------------------------------------------------

def test_gateway_allowlist_has_explain():
    assert "explain_metric" in gateway._ALLOWLISTS


# --- FRAME constant (the disclaimer the export handoff appends) ---------------

def test_frame_constant_is_nonempty():
    """FRAME is appended by the export handoff's result rendering; a downstream
    .endswith(FRAME) check would pass vacuously if it were ever emptied, so pin
    that the constant itself has real content."""
    assert len(explain.FRAME) > 0
