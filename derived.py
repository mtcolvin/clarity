"""Derived (computed) metrics — pure, no SQL, no model.

Mirrors analysis.py's role: deterministic functions over plain numbers. A derived
metric is COMPUTED ON READ from other measured metrics — it is never stored (no
fabricated observation rows), never run through a model, and never user-edited.
The deterministic engine (analysis.py) still does ALL detection over the computed
series, so the detect-side safety boundary holds: this module only DERIVES a value
labs don't print, it does not decide what's noteworthy.

Shipped derived metrics: albumin-corrected calcium (with Phase 2 thresholds); the
BUN:Creatinine ratio (a bare, dimensionless line — no thresholds; interpretive BUN:Cr
ranges stay deferred); and four "reported-but-always-computed" conversions —
Bilirubin Indirect (Total − Direct), Total Globulin (Total Protein − Albumin),
Non-HDL (Total Cholesterol − HDL, carrying its ATP III 190 threshold), and A/G Ratio
(Albumin ÷ (Total Protein − Albumin) — a division composing on the stored analytes),
plus two NEW computed metrics the lab doesn't print (no stored rows superseded): AST/ALT
Ratio (De Ritis, a definitional identity) and Calculated Osmolality (a DISCLOSED-formula
convention, per the "definition vs convention" rule in ROADMAP.md #6). ONE metric — NLR
(Neutrophil-Lymphocyte Ratio) — is a DELIBERATE, DOCUMENTED EXCEPTION to the charter's
"clinically standard" bar: a research/prognostic marker with no accepted reference range,
surfaced opt-in and made honest by an `advisory` warning that it is not a standard test
(see its spec, and CLAUDE.md "Derived metrics" / ROADMAP #6). This module
owns the registry + the pure compute; the same-draw JOIN is db.get_joined_series
(persistence), and the read-side wiring (resolve_series, resolve_derived_series for
the cross-metric roll-ups, /metrics injection, write-block) is api.py.

Rounding is DISPLAY-side: compute_series returns raw floats (precision=None) so no
drift enters a chained derivation; the client's format.js rounds for display. The one
exception is BUN:Cr, whose division has genuinely infinite decimals and so pins
precision=2 at the source (see its spec).
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Callable


@dataclass(frozen=True)
class DerivedMetric:
    name: str                       # the virtual metric name (as it appears in the picker)
    inputs: list[str]               # source metric names; inputs[0] is the PRIMARY (drives gaps)
    unit: str                       # unit of the computed value
    requires_units: dict[str, str]  # each input's REQUIRED unit — the formula assumes these
    compute: Callable[..., float]   # positional args in `inputs` order -> the derived value
    description: str                # short "computed from ..." caption for the UI
    display_name: str | None = None # OPTIONAL curated default DISPLAY alias (a friendlier
    #                                 short label than the verbose `name`, e.g. NLR). Unlike
    #                                 a stored metric's alias this is display-ONLY — a derived
    #                                 metric is never imported/added, so it's not an ingest
    #                                 match key. The user can override it (db.derived_alias);
    #                                 null ⇒ show `name` unless the user sets one.
    advisory: str | None = None     # OPTIONAL warning-level notice, rendered prominently
    #                                 (not the muted caption). Set ONLY for a metric that is
    #                                 a DELIBERATE, documented EXCEPTION to the charter's
    #                                 "clinically standard" bar — a research/prognostic value
    #                                 with no established reference range. The advisory is the
    #                                 mechanism that keeps surfacing it honest: it warns, in
    #                                 the UI, that this is not a standard test. Null for every
    #                                 standard derived metric (the bar is otherwise intact).
    precision: int | None = None    # decimals to round the computed value to (None = no
    #                                 rounding). A DIVISION result carries float noise
    #                                 (15.2941…) the display clamps to 4 meaningless
    #                                 decimals — round at the source so the table (raw
    #                                 value), chart, and tooltip all agree on one honest
    #                                 precision. Non-division metrics (corrected calcium)
    #                                 stay None: their arithmetic is already short.


# Albumin-corrected calcium = Ca + 0.8 * (4.0 - albumin). The 0.8 and 4.0 constants
# assume calcium in mg/dL and albumin in g/dL (the target-normal albumin); computing
# on any other units would fabricate a WRONG number, so requires_units is enforced as
# a hard guard (a mismatched-unit draw yields a gap, never a value).
CORRECTED_CALCIUM = DerivedMetric(
    name="Calcium Corrected",
    inputs=["Calcium Serum/Plasma", "Albumin"],
    unit="mg/dL",
    requires_units={"Calcium Serum/Plasma": "mg/dL", "Albumin": "g/dL"},
    compute=lambda ca, alb: ca + 0.8 * (4.0 - alb),
    description="Computed from Calcium + Albumin (Ca + 0.8 × (4.0 − albumin)); "
                "not measured. Only shown for draws that have both — a date missing "
                "either isn't a data point.",
)

# BUN:Creatinine ratio = BUN / Creatinine. Both inputs must be in mg/dL — the same
# unit — so the ratio is genuinely DIMENSIONLESS (unit=""), never "Ratio". This is
# the deferred home for the "context-only" BUN signal (a lone BUN doesn't resolve;
# its kidney-vs-prerenal signal lives in the ratio). Ships as a bare line, no
# thresholds/citations (Phase 1, exactly like corrected calcium) — the interpretive
# BUN:Cr ranges stay deferred to keep it on the surface-don't-diagnose side. Replaces
# the formerly-STORED "BUN/Creatinine Ratio" metric: the computed value reproduces the
# lab's reported ratio faithfully, so nothing is lost by computing it on read.
BUN_CREATININE_RATIO = DerivedMetric(
    name="BUN/Creatinine Ratio",
    inputs=["Blood Urea Nitrogen", "Creatinine Serum/Plasma"],
    unit="",
    requires_units={"Blood Urea Nitrogen": "mg/dL", "Creatinine Serum/Plasma": "mg/dL"},
    compute=lambda bun, cr: bun / cr,
    description="Computed from BUN ÷ Creatinine (both mg/dL); dimensionless, not "
                "measured. Only shown for draws that have both — a date missing "
                "either isn't a data point.",
    precision=2,  # 2 decimals — clean, and drops the raw division's float noise.
)

# --- Tier A conversions: metrics a lab REPORTS but always COMPUTES from other
# stored results, so nothing is lost by computing them on read (proven faithful —
# computed == every previously-stored reading, zero mismatch). All three are pure
# subtraction on same-unit inputs (no divide-by-zero), and all leave precision=None:
# the raw float flows through unrounded (no drift, and a future chained derivation
# like A/G Ratio ÷ globulin gets full precision), with the DISPLAY rounding handled
# client-side by format.js's noise-tolerant decimal detection. Contrast BUN:Cr above,
# whose DIVISION has genuinely infinite decimals and so still rounds at the source.

# Indirect (unconjugated) bilirubin is never directly measured — it is DEFINED as
# total minus direct, exactly what the lab reports. Same unit (mg/dL) on both inputs.
BILIRUBIN_INDIRECT = DerivedMetric(
    name="Bilirubin Indirect",
    inputs=["Bilirubin Total", "Bilirubin Direct"],
    unit="mg/dL",
    requires_units={"Bilirubin Total": "mg/dL", "Bilirubin Direct": "mg/dL"},
    compute=lambda total, direct: total - direct,
    description="Computed from Bilirubin Total − Bilirubin Direct (mg/dL); the "
                "unconjugated fraction is not directly measured. Only shown for draws "
                "that have both — a date missing either isn't a data point.",
)

# Total globulin is a classic computed value: total protein minus albumin. Same
# unit (g/dL) on both inputs. (Converting this GAINS coverage — draws that reported
# protein + albumin but no separate globulin now yield the value.)
TOTAL_GLOBULIN = DerivedMetric(
    name="Total Globulin",
    inputs=["Protein Total Serum/Plasma", "Albumin"],
    unit="g/dL",
    requires_units={"Protein Total Serum/Plasma": "g/dL", "Albumin": "g/dL"},
    compute=lambda protein, albumin: protein - albumin,
    description="Computed from Total Protein − Albumin (g/dL); not directly measured. "
                "Only shown for draws that have both — a date missing either isn't a "
                "data point.",
)

# Non-HDL cholesterol = total cholesterol minus HDL. Same unit (mg/dL). Carries its
# own ATP III 190 threshold (seeded in metric_config under this same name), so as a
# derived metric it flags exactly like Calcium Corrected — the config resolves by
# name over the computed series.
NON_HDL = DerivedMetric(
    name="Non-HDL",
    inputs=["Cholesterol", "HDL"],
    unit="mg/dL",
    requires_units={"Cholesterol": "mg/dL", "HDL": "mg/dL"},
    compute=lambda cholesterol, hdl: cholesterol - hdl,
    description="Computed from Total Cholesterol − HDL (mg/dL); not directly measured. "
                "Only shown for draws that have both — a date missing either isn't a "
                "data point.",
)

# A/G Ratio = Albumin ÷ Globulin. Globulin is itself derived (Total Protein − Albumin)
# and has no stored rows to join, so A/G derives from the two STORED analytes directly —
# computing globulin INLINE at full float precision (Albumin ÷ (Total Protein − Albumin)),
# never from a rounded globulin, which is exactly the drift-free chaining float preservation
# buys. DIMENSIONLESS (unit="" — both inputs g/dL, so the ratio is unitless; not the lab's
# "Ratio" label). A DIVISION like BUN:Cr, so it is the display-round exception: precision=1
# (the lab reports A/G to one decimal — verified faithful at 1 decimal on every shared draw).
# A 0-denominator draw (Total Protein == Albumin) raises ZeroDivisionError (an ArithmeticError)
# → compute_series omits that date (a gap), never a crash. The lab reported NO reference band
# for A/G, so it charts bandless unless a future report carries one (band-as-data captures it).
A_G_RATIO = DerivedMetric(
    name="A/G Ratio",
    inputs=["Albumin", "Protein Total Serum/Plasma"],
    unit="",
    requires_units={"Albumin": "g/dL", "Protein Total Serum/Plasma": "g/dL"},
    compute=lambda albumin, protein: albumin / (protein - albumin),
    description="Computed from Albumin ÷ Globulin, where Globulin = Total Protein − "
                "Albumin (both g/dL); dimensionless, not directly measured. Only shown "
                "for draws that have both — a date missing either isn't a data point.",
    precision=1,  # 1 decimal — the lab's reported A/G precision; drops the division float noise.
)

# --- New derived metrics: standard values a lab DOESN'T print, computed from inputs
# the user has. Distinct from the conversions above (those replaced a stored metric);
# these have no stored rows to supersede — they simply appear once their inputs exist.
# Both chart bandless (the lab reports no reference range for a value it doesn't print).

# AST:ALT (De Ritis) ratio — a DEFINITIONAL identity (just AST ÷ ALT, both U/L, so
# dimensionless), the same safe category as BUN:Cr. Recovers the signal the ALT
# methodology note already points at ("read the ALT:AST ratio and trend together"). A
# DIVISION, so precision is pinned (2 decimals — our choice, since no lab reports it to
# match; the interpretive De Ritis cutoffs stay deferred, surface-don't-diagnose). An
# ALT of 0 → ZeroDivisionError → that date omitted, never a crash.
AST_ALT_RATIO = DerivedMetric(
    name="AST/ALT Ratio",
    inputs=["Aspartate Aminotransferase", "Alanine Aminotransferase"],
    unit="",
    requires_units={"Aspartate Aminotransferase": "U/L", "Alanine Aminotransferase": "U/L"},
    compute=lambda ast, alt: ast / alt,
    description="Computed from AST ÷ ALT (the De Ritis ratio; both U/L); dimensionless, "
                "not reported by the lab. Only shown for draws that have both — a date "
                "missing either isn't a data point.",
    precision=2,  # 2 decimals — our chosen precision (the lab reports no AST:ALT to match).
)

# Calculated (estimated) serum osmolality — a CONVENTION, not a definition (several
# published formulas exist, e.g. some add potassium or use slightly different divisors),
# but on a value the lab DOESN'T report, so — exactly like corrected calcium — it's
# derivable as long as the chosen formula is DISCLOSED (in the caption below). The US-
# standard form 2·Na + glucose/18 + BUN/2.8 assumes Na in mmol/L and glucose/BUN in
# mg/dL (the /18 and /2.8 convert those to mmol/L); requires_units enforces that so a
# mismatched-unit draw is skipped, never miscomputed. Whole-number precision (mOsm/kg),
# as calculated osmolality is conventionally reported.
CALCULATED_OSMOLALITY = DerivedMetric(
    name="Calculated Osmolality",
    inputs=["Sodium Serum/Plasma", "Glucose Serum/Plasma", "Blood Urea Nitrogen"],
    unit="mOsm/kg",
    requires_units={"Sodium Serum/Plasma": "mmol/L", "Glucose Serum/Plasma": "mg/dL",
                    "Blood Urea Nitrogen": "mg/dL"},
    compute=lambda na, glucose, bun: 2 * na + glucose / 18 + bun / 2.8,
    description="Estimated as 2×Na + glucose/18 + BUN/2.8 (Na mmol/L; glucose, BUN "
                "mg/dL) — the standard US calculated-osmolality formula; other variants "
                "exist (e.g. adding potassium). A convention, not a measured value, and "
                "not reported by the lab. Only shown for draws with all three inputs.",
    precision=0,  # whole mOsm/kg — the conventional reporting precision for calc. osmolality.
)

# NLR — Neutrophil-to-Lymphocyte Ratio = Neutrophils Absolute ÷ Lymphocyte Absolute
# (both 10*9/L, so dimensionless). Mathematically it is a clean DEFINITIONAL identity,
# the same safe category as BUN:Cr / AST:ALT — it can't contradict the record. But it is
# a DELIBERATE, DOCUMENTED EXCEPTION to the charter's "clinically standard" bar (ROADMAP
# #6 candidate ledger): NLR is a research / prognostic inflammation marker, NOT an
# established diagnostic test — the lab doesn't report it and there is no accepted
# reference range. Surfacing it is opt-in-by-decision and made HONEST by the `advisory`
# below, which warns in the UI that this is not a standard test and is a personal-trend
# signal only. No reference BAND and no clinical THRESHOLD (a value-vs-cutoff judgment
# would need a reference NLR has none of). But the engine's DEFAULT detectors still run
# over the computed series — deliberately: linear_trend / Mann-Kendall (and
# personal_baseline_z) fire on a notable movement, which is exactly the "flag a trend
# worth eyeballing" this metric is for. That stays surface-don't-diagnose: a trend flag
# describes MOVEMENT ("rising over N readings"), names no condition, and judges against no
# normal range (out_of_range can't fire without a band; no threshold is seeded). Sibling
# PLR stays parked (weaker standing, redundant as an inflammation proxy). A DIVISION, so
# precision is pinned (2 decimals — our choice, no lab value to match); a 0 lymphocyte
# count → ZeroDivisionError → that date omitted, never a crash.
NLR = DerivedMetric(
    name="NLR (Neutrophil-Lymphocyte Ratio)",
    display_name="NLR",  # the verbose name is self-documenting; the picker shows this
    inputs=["Neutrophils Absolute", "Lymphocyte Absolute"],
    unit="",
    requires_units={"Neutrophils Absolute": "10*9/L", "Lymphocyte Absolute": "10*9/L"},
    compute=lambda neut, lymph: neut / lymph,
    description="Computed from Neutrophils Absolute ÷ Lymphocyte Absolute (both 10⁹/L); "
                "dimensionless, not reported by the lab. Only shown for draws that have "
                "both — a date missing either isn't a data point.",
    advisory="This is not a standard lab test. The neutrophil-to-lymphocyte ratio is a "
             "research / prognostic inflammation marker — your lab does not report it and "
             "there is no established reference range for it. The app treats it as a "
             "personal TREND only: it will flag a notable rise or fall across your own "
             "readings (a movement worth a look), but it never judges the value against a "
             "normal range, because none exists. A flag here means “look at this change,” "
             "not “this value is high or low.” Bring any pattern to your clinician rather "
             "than reading it on its own.",
    precision=2,  # 2 decimals — our chosen precision (the lab reports no NLR to match).
)

REGISTRY: dict[str, DerivedMetric] = {
    CORRECTED_CALCIUM.name: CORRECTED_CALCIUM,
    BUN_CREATININE_RATIO.name: BUN_CREATININE_RATIO,
    BILIRUBIN_INDIRECT.name: BILIRUBIN_INDIRECT,
    TOTAL_GLOBULIN.name: TOTAL_GLOBULIN,
    NON_HDL.name: NON_HDL,
    A_G_RATIO.name: A_G_RATIO,
    AST_ALT_RATIO.name: AST_ALT_RATIO,
    CALCULATED_OSMOLALITY.name: CALCULATED_OSMOLALITY,
    NLR.name: NLR,
}


def is_derived(metric: str) -> bool:
    """True iff `metric` is a computed/virtual metric (not stored, not writable)."""
    return metric in REGISTRY


def available(present_metrics: set[str]) -> list[DerivedMetric]:
    """Derived metrics whose EVERY input has at least one reading — so the picker
    offers a derived metric only when it can actually be computed."""
    return [d for d in REGISTRY.values() if all(m in present_metrics for m in d.inputs)]


def _row(observed_on: str, value: float, unit: str,
         ref_low: float | None = None, ref_high: float | None = None) -> dict:
    """One observation-shaped row (matching db.get_series's shape). id is None — a
    derived row has no stored id. The VALUE is always computed; the reference band
    (ref_low/ref_high) is band-as-data — filled from the captured, lab-reported band
    for this date when one exists (see compute_series), else null (charts with no band,
    which is honest — none was reported)."""
    return {
        "id": None,
        "observed_on": observed_on,
        "value": value,
        "unit": unit,
        "ref_low": ref_low,
        "ref_high": ref_high,
        "result_type": "numeric",
        "value_text": None,
        "operator": None,
        "normal_text": None,
        "ref_low_operator": None,
        "ref_high_operator": None,
    }


def compute_series(spec: DerivedMetric, joined_rows: list[dict],
                   ref_ranges: dict[str, dict] | None = None) -> list[dict]:
    """Compute the derived series as observation-shaped rows, oldest first — ONE row
    per date where the value is computable, and nothing else.

    A date is OMITTED (not emitted as a gap) when it isn't in `joined_rows` (an input
    wasn't drawn that day) OR its inputs fail the unit/numeric guards — in every case
    there simply is no derived value there, so it isn't a data point. The chart then
    connects the points it has, exactly like any metric with irregular draw dates; a
    same-day-missing date reads as "no reading," not a manufactured break. The unit
    guard still means a mismatched-unit draw is skipped, never computed into a wrong
    number. `joined_rows` come from db.get_joined_series(spec.inputs) (inner join —
    paired dates only, oldest first).

    `ref_ranges` (band-as-data): {date: {"ref_low", "ref_high", "unit"}}, the reference
    bands captured from the lab's reports (db.get_derived_reference_ranges). Applied
    PER-DATE: a band shows only on a date whose value came WITH a lab-reported range
    (captured at import). A date the metric was COMPUTED for but the lab didn't report a
    range (e.g. a globulin value on a draw that printed protein+albumin only) honestly
    charts with a BLANK band — the reference range genuinely wasn't reported there, and a
    computed value doesn't manufacture one. A band is applied ONLY when its unit matches
    the derived metric's unit — a mismatched-unit band is ignored (never coerced), so the
    row charts with no band rather than a wrong one. Kept as a parameter (not a db call)
    so this stays a pure function — api.resolve_series fetches and passes it."""
    ref_ranges = ref_ranges or {}
    out = []
    for jr in joined_rows:
        rows = jr["inputs"]
        ok = True
        args = []
        for m in spec.inputs:
            r = rows[m]
            if r.get("unit") != spec.requires_units[m]:
                ok = False
                break
            if (r.get("result_type") or "numeric") != "numeric" or r.get("value") is None:
                ok = False
                break
            args.append(r["value"])
        if ok:
            try:
                val = spec.compute(*args)
            except ArithmeticError:
                # e.g. a 0 denominator (BUN:Cr) — the value is UNDEFINED there, so
                # the date is omitted (a gap), never fabricated or crashed on.
                continue
            if spec.precision is not None:
                val = round(val, spec.precision)
            band = ref_ranges.get(jr["observed_on"])
            lo = hi = None
            if band and band.get("unit") == spec.unit:
                lo, hi = band.get("ref_low"), band.get("ref_high")
            out.append(_row(jr["observed_on"], val, spec.unit, ref_low=lo, ref_high=hi))
    return out
