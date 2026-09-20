"""
analysis.py — the engine that decides what "stands out".

Every function is PURE: it takes plain numbers / lists and returns Flag objects.
Nothing here touches SQLite, so each check is trivial to unit-test in isolation,
and the database layer just feeds it series.

Layers (in order of value):
  Phase 1  flag_out_of_range          — value outside this result's reference range
  Phase 2  personal_baseline_z        — abnormal *for you* (ROBUST median/MAD z-score vs your own history)
  Phase 2  linear_trend               — least-squares slope, is it drifting?
  Phase 2  mann_kendall               — monotonic trend test (no linearity assumption)
  Extra    rcv_delta                  — is a jump real, or just assay + biological noise?
  Extra    clinical_threshold_crossing— did it cross a guideline cutoff (e.g. A1c 5.7)?

Design principle for the LLM layer: DETECT here (deterministic), NARRATE/REASON
there. Never let a language model compute these numbers — the restate tier
(narrate.py) only explains the flags this engine produced, and the interpretation
tier (explain.py) may reason around them and raise questions but still computes
nothing (CLAUDE.md "The interpretation tier").
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import date, datetime
from typing import Sequence

import numpy as np
from scipy import stats


@dataclass
class Flag:
    metric: str
    kind: str          # 'out_of_range' | 'personal_baseline' | 'personal_range' | 'trend' | 'delta' | 'threshold'
    severity: str      # 'info' | 'watch' | 'high'
    message: str
    detail: dict = field(default_factory=dict)   # raw numbers for the UI / LLM to render
    # ISO date of the reading this flag concerns, so the UI can map it to the
    # exact point. None for whole-series flags (trend). The pure detectors don't
    # set this — analyze_series stamps it, since that's the layer that knows each
    # reading's identity (the detectors stay numbers-in, Flag-out).
    observed_on: str | None = None


# ----------------------------------------------------------------------------- helpers

def _to_date(d) -> date:
    return d if isinstance(d, date) else datetime.strptime(d, "%Y-%m-%d").date()


def _days_from_first(dates: Sequence) -> np.ndarray:
    parsed = [_to_date(d) for d in dates]
    d0 = parsed[0]
    return np.array([(d - d0).days for d in parsed], dtype=float)


# ----------------------------------------------------------------------------- Phase 1

def _denoise(x):
    """Strip binary-float noise from a value for MESSAGE display, without changing a
    clean value's representation. A derived value is a raw float (rounding is display-
    side, so no drift enters a chained derivation), and subtraction yields e.g.
    1.2000000000000002 for what is really 1.2 — rounding to 10 places collapses that
    tail while a genuinely clean value (122.0 stays 122.0, 1.005 stays 1.005) is
    untouched. So every stored metric's message text is byte-identical; only a computed
    value's 15-digit tail is cleaned. Mirrors the client's noise-tolerant display."""
    return round(x, 10) if isinstance(x, float) else x


def flag_out_of_range(metric, value, ref_low=None, ref_high=None,
                      ref_low_operator=None, ref_high_operator=None) -> Flag | None:
    """Outside the reference range that came with the result.

    The optional bound OPERATORS make a bound strict: ref_low_operator '>' means
    in-range is value > ref_low (so value <= ref_low is out); ref_high_operator '<'
    means in-range is value < ref_high (so value >= ref_high is out). NULL — and
    the inclusive forms '>='/'<=' — keep the original value >= / <= test, so every
    existing row (all NULL operators) flags exactly as before."""
    if ref_low is not None:
        below = value <= ref_low if ref_low_operator == ">" else value < ref_low
        if below:
            return Flag(metric, "out_of_range", "watch",
                        f"{metric} is {_denoise(value)}, below the reference low of {ref_low}.",
                        {"value": value, "ref_low": ref_low, "ref_high": ref_high})
    if ref_high is not None:
        above = value >= ref_high if ref_high_operator == "<" else value > ref_high
        if above:
            return Flag(metric, "out_of_range", "watch",
                        f"{metric} is {_denoise(value)}, above the reference high of {ref_high}.",
                        {"value": value, "ref_low": ref_low, "ref_high": ref_high})
    return None


def flag_censored_out_of_range(metric, operator, bound,
                               ref_low=None, ref_low_operator=None,
                               ref_high=None, ref_high_operator=None) -> Flag | None:
    """A CENSORED reading ('<X'/'>X'/'<=X'/'>=X') vs the normal range — the ONLY
    comparison a censored reading enters (it stays out of every numeric calc).

    A '<'/'<=' reading extends DOWNWARD (value at most X); '>'/'>=' extends UPWARD
    (value at least X). The reading is flagged when its bound reaches the boundary
    in its direction of extension:
      '<' / '<='  →  X <= ref_low   →  "at or below the lower limit"
      '>' / '>='  →  X >= ref_high  →  "at or above the upper limit"

    REVISED rule (was: only flag when the whole interval is strictly outside).
    Boundary-TOUCH in the direction of extension now counts as out-of-range: for
    continuous measurements exact equality is vanishing-probability, and labs
    themselves treat a value at the limit as out — so '<=10 vs >=10' and
    '>=10 vs <=10' now flag (they were silent before). The censored operator and
    the bound's strict/inclusive operator no longer change the threshold (both
    collapse to X<=ref_low / X>=ref_high); the operator args are kept for
    interface parallelism with flag_out_of_range.

    'Silence is honest' STILL holds for genuine ambiguity — when the bound sits
    INSIDE the range or the relevant edge is absent, the data can't place the
    reading, so no flag (e.g. '<20 vs ≤10' — extends downward but its bound 20 is
    above the only (upper) edge, nothing below to compare → silent; '<8 vs [5,10]'
    — bound inside the range → silent). Wording is the same lab-range fact in
    every mode (personal-baseline mode does NOT reframe a censored reading —
    there's no personal statistic for it)."""
    if operator in ("<", "<=") and ref_low is not None and bound <= ref_low:
        return Flag(metric, "out_of_range", "watch",
                    f"{metric} is {operator}{bound}, at or below the lower limit.",
                    {"value": bound, "ref_low": ref_low, "ref_high": ref_high,
                     "censored": True, "operator": operator})
    if operator in (">", ">=") and ref_high is not None and bound >= ref_high:
        return Flag(metric, "out_of_range", "watch",
                    f"{metric} is {operator}{bound}, at or above the upper limit.",
                    {"value": bound, "ref_low": ref_low, "ref_high": ref_high,
                     "censored": True, "operator": operator})
    return None


# ----------------------------------------------------------------------------- Phase 2

# --- Personal-baseline noise gate -------------------------------------------
# A z-score is scale-free, so for a tightly-clustered metric a clinically trivial
# wiggle can still be 2+ SD from the personal mean and flag as "unusual for you".
# These gates require the deviation to ALSO be non-trivial in absolute terms
# before a personal-baseline flag stands. They only SUPPRESS statistical noise —
# a surviving flag keeps its exact wording and never implies clinical
# significance, only that the move isn't trivial spread.
#
# Primary gate (the reading carries a lab reference range): the deviation must be
# at least this fraction of the reference-range width (ref_high - ref_low). 0.25
# is tuned against real data — Albumin's noise tops out at 0.24 of range while the
# lowest genuine survivor (RDW) sits at 0.27, a clean gap that 0.25 splits.
BASELINE_RANGE_FRACTION = 0.25
# Fallback gate (no stored range): with no clinical range, the only metric-
# agnostic scale is the personal level, so gate the MOVE — require the deviation
# to be at least this fraction of the personal mean (|value - mean| / |mean|).
# This mirrors the range-fraction gate's intent (gate the move, not the spread).
#
# We deliberately do NOT gate on the coefficient of variation (sd/mean) here: CV
# asks "is the series usually flat?", which wrongly suppresses a genuine large
# jump on an otherwise-steady rangeless metric (e.g. weight holding ~82 kg then
# dropping to 75 — a 20.5 SD / 8.4% move a CV guard would silently drop).
#
# CONSERVATIVE and THINLY CALIBRATED — only one real no-range case existed to
# test against (A/G Ratio, a genuine 26.7% move we keep); there were no no-range
# NOISE examples, so without a clinical range we can't distinguish a trivial
# wiggle from a real move beyond this relative-size bar. Revisit if rangeless
# metrics start over- or under-flagging.
BASELINE_REL_MOVE_MIN = 0.05


def personal_baseline_z(metric, history, new_value,
                        z_watch=2.0, z_high=3.0, min_points=4,
                        ref_low=None, ref_high=None,
                        range_fraction=BASELINE_RANGE_FRACTION,
                        rel_move_min=BASELINE_REL_MOVE_MIN) -> Flag | None:
    """Abnormal FOR YOU. Population ranges are wide; your own distribution is
    usually tighter, so this catches values that are 'normal' for everyone but
    unusual against your personal baseline. history = prior values (exclude new).

    A bare z-score over-fires on tightly-clustered metrics, so a NOISE GATE also
    requires the deviation to be non-trivial: at least `range_fraction` of the
    reference-range width when the reading has a range, else (no range) at least
    `rel_move_min` of the personal baseline. The gate only suppresses trivial moves —
    a surviving flag keeps its exact wording and implies no clinical significance.

    ROBUST to outliers (median + MAD, not mean + SD). A single extreme reading —
    an acute AST of 850 from an injury — used to poison the old mean/SD z-score
    TWICE: it dragged the mean toward itself AND exploded the SD, which then made
    every LATER reading look 'normal' (small z), silently masking real deviations.
    The median and the median absolute deviation (MAD) barely move for one such
    point, so the baseline stays representative of the user's usual level and later
    readings still flag. MAD is scaled by 1/0.6745 so it estimates the SD for
    normally-distributed data — this keeps z_watch/z_high (2/3) on the same scale
    they had under mean/SD, so the detector's sensitivity is unchanged for
    outlier-free data (median==mean, MAD/0.6745==SD there)."""
    hist = np.asarray(history, dtype=float)
    if hist.size < min_points:
        return None                          # not enough personal history yet
    center = float(np.median(hist))
    abs_dev_hist = np.abs(hist - center)
    mad = float(np.median(abs_dev_hist))
    if mad > 0:
        robust_sd = mad / 0.6744897501960817          # MAD -> SD estimate (normal)
    else:
        # MAD is 0 when > half the history is identical; fall back to the mean
        # absolute deviation (E|X-median| = 0.7979*sigma for normal data). If THAT
        # is also 0 the history is perfectly flat — no personal spread to judge
        # against, so stay silent, exactly as the old sd==0 guard did.
        mean_ad = float(np.mean(abs_dev_hist))
        if mean_ad == 0:
            return None
        robust_sd = mean_ad / 0.7978845608028654
    z = (new_value - center) / robust_sd
    if abs(z) < z_watch:
        return None

    # Noise gate: z says "unusual for you" but not "by a meaningful amount".
    # Require the absolute deviation to clear a non-trivial bar before the flag
    # stands — range-fraction when a reference range exists, else a relative-move floor.
    abs_dev = abs(new_value - center)
    has_range = ref_low is not None and ref_high is not None and ref_high > ref_low
    if has_range:
        if abs_dev < range_fraction * (ref_high - ref_low):
            return None                      # trivial slice of the normal band
    else:
        rel_move = abs_dev / abs(center) if center else 0.0
        if rel_move < rel_move_min:
            return None                      # trivial move relative to your usual level

    severity = "high" if abs(z) >= z_high else "watch"
    direction = "above" if z > 0 else "below"
    return Flag(metric, "personal_baseline", severity,
                f"{metric} is {abs(z):.1f} SD {direction} your personal baseline "
                f"(median {center:.2f}) — may be within range yet unusual for you.",
                {"value": new_value, "z": z, "personal_center": center, "personal_spread": robust_sd})


def personal_baseline_mean(series) -> float | None:
    """The robust CENTER (MEDIAN) of a metric's NUMERIC values — the baseline the
    personal-baseline detector measures deviations against. NAME is legacy ('mean'):
    it now returns the MEDIAN, matching personal_baseline_z's switch to median/MAD
    so the displayed 'personal baseline' gridline is robust to an outlier (an acute
    spike no longer drags the line toward itself). Kept as the same name/wire field
    (`personal_baseline_mean`) to avoid churning the /chart-config + export-bundle
    contract; the value it carries is the median. Excludes censored and qualitative
    rows, exactly like every other engine computation. Returns None when the metric
    has no numeric readings. Pure; the line is the engine's number, not a frontend
    re-derivation."""
    values = [
        row["value"] for row in series
        if row.get("result_type", "numeric") == "numeric" and row.get("value") is not None
    ]
    if not values:
        return None
    return float(np.median(values))


# --- Personal-baseline mode (suggest-then-confirm) ---------------------------
# A metric chronically outside its lab range (e.g. Gilbert's bilirubin) can be
# tracked against the user's OWN baseline instead of the population range. This
# is opt-in per metric: the app SUGGESTS it for candidates (purely statistical
# trigger below), the user confirms, and the mode is then resolved in the API and
# passed into the engine as `personal_baseline_mode`.
#
# Suggestion-trigger thresholds — purely statistical: they gate when the app
# OFFERS the mode, never what counts as a flag. Tunable via the settings panel;
# these named constants are the fallback default (settings override).
PERSONAL_BASELINE_SUGGEST_MIN_FRACTION = 0.70   # > this fraction of judgeable readings out of lab range
PERSONAL_BASELINE_SUGGEST_MIN_READINGS = 5      # and at least this many such readings


def personal_baseline_candidacy(
    series, *,
    min_fraction=PERSONAL_BASELINE_SUGGEST_MIN_FRACTION,
    min_readings=PERSONAL_BASELINE_SUGGEST_MIN_READINGS,
) -> dict:
    """Is this metric chronically outside its lab range often enough to OFFER
    personal-baseline tracking (the SUGGESTION bar)? Purely statistical — counts
    and a percentage, no interpretation and no clinical judgment. A reading with
    no reference bound can't be judged in/out, so it's excluded from BOTH
    numerator and denominator of `n`/`fraction` (the same rule the masked tuning
    used). Read-only; numeric rows only.

    `numeric_count` is a SEPARATE, lower bar than `n`: `n` counts only JUDGEABLE
    readings (those carrying a ref_low/ref_high, needed for the out-of-range
    fraction), while `numeric_count` counts every numeric reading regardless of
    whether it has a range — the same denominator personal_baseline_z's history
    needs (it has no ref-bound requirement). A metric can have plenty of numeric
    readings but few judgeable ones (or vice versa); conflating the two would
    either hide a working feature or offer one that can't compute anything yet.
    Callers deciding "is the quiet per-metric link computable" should use
    numeric_count, not n."""
    numeric = _numeric_rows(series)
    judgeable = [r for r in numeric
                 if r.get("ref_low") is not None or r.get("ref_high") is not None]
    n = len(judgeable)
    out = sum(1 for r in judgeable
              if flag_out_of_range("", r["value"], r.get("ref_low"), r.get("ref_high")) is not None)
    fraction = (out / n) if n else 0.0
    return {
        "n": n,
        "out_of_range": out,
        "fraction": fraction,
        "is_candidate": n >= min_readings and fraction > min_fraction,
        "numeric_count": len(numeric),
    }


def _baseline_reframe_flags(metric, numeric, *, min_points=4) -> list[Flag]:
    """Per-reading flags for a metric IN personal-baseline mode. Each numeric
    reading is judged on an EXPANDING window (only the readings before it):

      1. trips the personal baseline -> the personal-baseline alarm (loud). The
         mode NEVER soothes a reading that breaks your pattern — this fires for an
         out-of-lab-range OR an in-range reading that deviates from your history.
      2. else outside its lab range, with enough prior history to assess -> a
         neutral 'personal_range' (info) descriptor: 'within your established
         range'.
      3. else outside its lab range but too early to assess (< min_points priors)
         -> 'personal_range' (info) stating only the lab-range fact, with NO
         'established range' claim (we don't assert what we can't verify).

    Reuses flag_out_of_range + personal_baseline_z (noise gate intact). The lab
    range is RECONTEXTUALIZED, never deleted — the frontend still shows the band
    and the bound in the message/tooltip."""
    flags: list[Flag] = []
    values = [row["value"] for row in numeric]
    for i, row in enumerate(numeric):
        prior = values[:i]
        ref_low, ref_high = row.get("ref_low"), row.get("ref_high")
        pb = personal_baseline_z(metric, prior, values[i],
                                 ref_low=ref_low, ref_high=ref_high, min_points=min_points)
        if pb is not None:                      # case 1: genuine break from your pattern
            pb.observed_on = row["observed_on"]
            flags.append(pb)
            continue
        if flag_out_of_range(metric, values[i], ref_low, ref_high,
                             row.get("ref_low_operator"), row.get("ref_high_operator")) is None:
            continue                            # within the lab range and within your pattern
        above = ref_high is not None and values[i] > ref_high
        bound_word = "above" if above else "below"
        established = len(prior) >= min_points
        if established:                         # case 2
            msg = (f"{metric} is {_fmt_num(values[i])} — {bound_word} the lab reference "
                   f"range; within your established range.")
        else:                                   # case 3 (no established-range claim)
            msg = f"{metric} is {_fmt_num(values[i])} — {bound_word} the lab reference range."
        f = Flag(metric, "personal_range", "info", msg,
                 {"value": values[i], "ref_low": ref_low, "ref_high": ref_high,
                  "established": established})
        f.observed_on = row["observed_on"]
        flags.append(f)
    return flags


def linear_trend(metric, dates, values,
                 p_threshold=0.05, min_points=4) -> Flag | None:
    """Least-squares slope over time. A value can sit inside 'normal' every time
    while quietly drifting — the trajectory is the signal."""
    if len(values) < min_points:
        return None
    days = _days_from_first(dates)
    r = stats.linregress(days, values)
    if r.pvalue > p_threshold:
        return None                          # no statistically significant trend
    slope_per_year = r.slope * 365.25
    direction = "rising" if r.slope > 0 else "falling"
    return Flag(metric, "trend", "watch",
                f"{metric} is {direction} ~{slope_per_year:+.2f} units/year "
                f"(p={r.pvalue:.3f}, r2={r.rvalue ** 2:.2f}) over {len(values)} readings.",
                {"slope_per_day": r.slope, "slope_per_year": slope_per_year,
                 "p_value": r.pvalue, "r_squared": r.rvalue ** 2})


def mann_kendall(metric, values, alpha=0.05, min_points=4) -> Flag | None:
    """Non-parametric monotonic-trend test. Doesn't assume the trend is linear;
    good companion to linear_trend for catching steady drift in either direction.
    (Tie correction omitted for brevity — fine for continuous lab values.)"""
    n = len(values)
    if n < min_points:
        return None
    v = np.asarray(values, dtype=float)
    s = sum(np.sign(v[i + 1:] - v[i]).sum() for i in range(n - 1))
    var_s = n * (n - 1) * (2 * n + 5) / 18.0
    if s > 0:
        z = (s - 1) / np.sqrt(var_s)
    elif s < 0:
        z = (s + 1) / np.sqrt(var_s)
    else:
        z = 0.0
    p = 2 * (1 - stats.norm.cdf(abs(z)))
    if p > alpha:
        return None
    direction = "increasing" if s > 0 else "decreasing"
    return Flag(metric, "trend", "watch",
                f"{metric} shows a monotonic {direction} trend (Mann-Kendall p={p:.3f}).",
                {"S": float(s), "z": float(z), "p_value": float(p)})


# ----------------------------------------------------------------------------- Extras

def rcv_delta(metric, previous, current, cv_analytical, cv_intra, z=1.96) -> Flag | None:
    """Reference Change Value: is the jump between two consecutive results bigger
    than combined analytical (assay) + within-person biological noise? cv_* are
    fractional, e.g. 0.04 == 4%. Published CVs exist for most common analytes.

    TWO-SIDED by design: z defaults to 1.96 (the two-sided 95% critical value) and
    the test below is on abs(pct), so a jump flags in EITHER direction. This is a
    deliberate choice, not incidental — for a general lab panel an unexpected DROP
    can matter as much as a rise (a falling count, a plummeting level), so we want
    both tails. A one-sided test (z=1.65) would only make sense if a single
    direction were the sole concern, which isn't true across a mixed panel. Keep
    two-sided unless a specific metric ever argues otherwise (z is a parameter, so
    a caller could override per-metric without touching this).

    Uses the SIMPLE percentage form pct = (current - previous) / previous — the
    textbook RCV approximation. The exact RCV for large swings is defined on the
    log-transformed values; the % form drifts from it as changes get big (a metric
    like Ferritin can multiply). Accepted as a known, documented boundary: for
    typical analyte movement the two agree closely, and the huge-swing cases are
    exactly the ones a human would eyeball anyway. Revisit (add the log form) only
    if a real reading ever produces a wrong fire from a large swing — do not
    pre-build it."""
    rcv = np.sqrt(2) * z * np.sqrt(cv_analytical ** 2 + cv_intra ** 2)   # fractional
    pct = (current - previous) / previous
    if abs(pct) <= rcv:            # <= : a change exactly ON the threshold does NOT fire
        return None
    direction = "increase" if pct > 0 else "decrease"
    return Flag(metric, "delta", "watch",
                f"{metric} changed {pct * 100:+.0f}% vs the prior result — a real {direction}, "
                f"beyond the ~{rcv * 100:.0f}% noise threshold.",
                {"previous": previous, "current": current, "pct_change": pct, "rcv": rcv})


def clinical_threshold_crossing(metric, previous, current, thresholds) -> list[Flag]:
    """thresholds: list of {cutoff, source, direction, boundary} dicts, e.g.
    [{'cutoff': 5.7, 'source': 'ADA', 'direction': 'up', 'boundary': 'inclusive'}].
    Flags when the latest value crosses the cutoff in the CONCERNING direction the
    previous reading hadn't. `direction` picks which way is concerning; `boundary`
    picks whether landing exactly ON the cutoff counts:
      up   + inclusive : previous <  cutoff <= current   (touch on cutoff counts)
      up   + exclusive : previous <= cutoff <  current   (must clear the cutoff)
      down + exclusive : current  <  cutoff <= previous   (touch on cutoff counts)
      down + inclusive : current  <= cutoff <  previous   (must clear the cutoff)
    The inclusive end sits on OPPOSITE operands per direction — for 'up' the
    arriving (current) end carries the <=; for 'down' it's the departing (previous)
    end — because each direction's "concerning side" is the cutoff's opposite face.

    Resilience: anything other than 'down' is treated as 'up', and a missing/
    malformed `boundary` resolves to the per-direction default (up->inclusive,
    down->exclusive) — never raises — so a legacy/absent value keeps the original
    behavior exactly. (When an edit UI can write these, that leniency must become
    closed-enum validation; tracked as a parked requirement, same as direction.)

    Per the analysis safety boundary: the flag names the guideline cutoff and its
    SOURCE (who defines it), never the condition that cutoff indicates — it
    surfaces "you crossed a recognized threshold", not a diagnosis. The message is
    direction-neutral ("crossed"), and the previous -> current arrow shows which way."""
    flags = []
    for t in thresholds:
        cutoff, source = t["cutoff"], t["source"]
        down = t["direction"] == "down"
        # boundary -> inclusive?; anything not 'inclusive'/'exclusive' falls back to
        # the per-direction default (up->inclusive, down->exclusive), matching how
        # the cast defaults an ABSENT key, so a malformed value never raises and
        # never silently flips behavior away from the legacy default.
        boundary = t["boundary"]
        if boundary in ("inclusive", "exclusive"):
            inclusive = boundary == "inclusive"
        else:
            inclusive = not down
        if down:
            crossed = (current <= cutoff < previous) if inclusive else (current < cutoff <= previous)
        else:
            crossed = (previous < cutoff <= current) if inclusive else (previous <= cutoff < current)
        if crossed:
            flags.append(Flag(metric, "threshold", "high",
                              f"{metric} crossed the {source} {cutoff} guideline threshold: "
                              f"{previous} -> {current}.",
                              {"cutoff": cutoff, "source": source,
                               "previous": previous, "current": current}))
    return flags


# --- static threshold level (the STANDING counterpart to the crossing check) --

def _concerning_thresholds(value, thresholds) -> list[dict]:
    """The thresholds whose CONCERNING side `value` currently sits on — the static
    counterpart to clinical_threshold_crossing's crossing test, using the SAME
    direction/boundary comparison (down: at/below the cutoff; up: at/above). Returns
    the matching threshold dicts (they carry cutoff + source) so callers can name them."""
    hits = []
    for t in thresholds or []:
        down = t.get("direction") == "down"
        boundary = t.get("boundary")
        inclusive = (boundary == "inclusive") if boundary in ("inclusive", "exclusive") else (not down)
        cutoff = t["cutoff"]
        on = (value <= cutoff if inclusive else value < cutoff) if down \
            else (value >= cutoff if inclusive else value > cutoff)
        if on:
            hits.append(t)
    return hits


def _guideline_phrase(hits: list[dict]) -> str:
    """'below the WHO 13.0 guideline line' (joined with 'and' for multiple). Names
    only each line's SOURCE + CUTOFF (framework-descriptive), never what being on that
    side indicates — the surface-don't-diagnose boundary."""
    return " and ".join(
        f"{'below' if t.get('direction') == 'down' else 'above'} the "
        f"{t['source']} {t['cutoff']} guideline line" for t in hits
    )


def _annotate_guideline(flag: Flag, value, thresholds) -> Flag:
    """Fold a guideline mention INTO an existing flag's message when `value` is on a
    guideline's concerning side — so an out-of-range reading that is ALSO past a
    guideline line reads '..., and below the WHO 13.0 guideline line', with NO new
    flag (no added noise). Mutates + returns the flag; a no-op when nothing is hit."""
    hits = _concerning_thresholds(value, thresholds)
    if hits:
        flag.message = f"{flag.message.rstrip('.')}, and {_guideline_phrase(hits)}."
    return flag


def flag_threshold_level(metric, value, thresholds, *, exclude_cutoffs=()) -> Flag | None:
    """STATIC threshold flag: the current `value` is on a guideline's concerning side,
    regardless of any crossing. Complements clinical_threshold_crossing (a crossing is
    a one-time event; this catches 'you're standing below the line' when no crossing
    fired). `exclude_cutoffs` drops cutoffs a crossing flag already reported this run,
    so the two never double-flag the same line. Surface-don't-diagnose: names source +
    cutoff, frames the reading against the line, never what that indicates."""
    hits = [t for t in _concerning_thresholds(value, thresholds)
            if t["cutoff"] not in exclude_cutoffs]
    if not hits:
        return None
    return Flag(metric, "threshold", "watch",
                f"{metric} is {_denoise(value)}, {_guideline_phrase(hits)}.",
                {"value": value,
                 "thresholds": [{"cutoff": t["cutoff"], "source": t["source"]} for t in hits]})


# ----------------------------------------------------------------------------- orchestrator

def analyze_series(metric, series, *, rcv_cv=None, thresholds=None,
                   personal_baseline_mode=False) -> list[Flag]:
    """Run every relevant check over one metric's series (oldest first).

    series: list of dicts with keys observed_on, value, ref_low, ref_high.
    rcv_cv: optional {'analytical': float, 'intra': float} to enable rcv_delta.
    thresholds: optional list of {cutoff, source, direction, boundary} dicts to enable threshold crossing.
    personal_baseline_mode: when True, recontextualize out-of-lab-range readings
      against the user's own baseline (see _baseline_reframe_flags). The personal-
      baseline detector keeps firing (sharpened to every reading, noise gate
      intact), so a genuine break from the pattern still alarms loudly; only the
      EXPECTED chronic out-of-range readings are reframed to neutral descriptors.

    Note: linear_trend and mann_kendall can both fire on the same steady drift;
    that's intentional redundancy here — dedupe by `kind` in the UI if you like.
    """
    flags: list[Flag] = []
    if not series:
        return flags

    # Only NUMERIC results enter any math. Censored ("<5": result_type 'censored',
    # value 5) and qualitative ("Positive": value None) are excluded — a censored
    # bound must never be treated as the bare number (that would fabricate data),
    # and a qualitative result must never break a calculation. Rows without a
    # result_type default to 'numeric', so existing numeric flagging is unchanged.
    numeric = [
        row for row in series
        if row.get("result_type", "numeric") == "numeric" and row.get("value") is not None
    ]

    # Censored readings (item 6): the ONLY check a censored reading enters — a
    # DEFINITIVE comparison to its own normal range. Runs for EVERY metric (incl. a
    # censored-only one, which returns just below), independent of the numeric math
    # and of pb mode (a censored reading has no personal baseline to reframe).
    # Ambiguous comparisons emit nothing — silence is honest.
    for row in series:
        if (row.get("result_type") == "censored" and row.get("value") is not None
                and row.get("operator")):
            if (f := flag_censored_out_of_range(
                    metric, row["operator"], row["value"],
                    row.get("ref_low"), row.get("ref_low_operator"),
                    row.get("ref_high"), row.get("ref_high_operator"))):
                f.observed_on = row["observed_on"]
                flags.append(f)

    if not numeric:
        return flags                       # qualitative/censored-only metric: no NUMERIC flags

    dates = [row["observed_on"] for row in numeric]
    values = [row["value"] for row in numeric]
    latest = numeric[-1]

    if personal_baseline_mode:
        # Reframe lab-range exceedances against your own baseline. This emits the
        # per-reading personal_range (info) / personal-baseline (loud) flags and
        # REPLACES the population-range out_of_range loop + the latest-only
        # personal-baseline check below (the reframe runs the baseline check itself,
        # expanding over every reading). Trend/RCV/threshold detectors still run.
        flags.extend(_baseline_reframe_flags(metric, numeric))
    else:
        # Out-of-range is judged per reading against THAT reading's own stored range
        # (ranges vary across readings), and each flag is stamped with its own date so
        # the chart highlights the exact point — agreeing with its stepped-band
        # segment. Rows without a range yield no flag (flag_out_of_range returns None).
        for row in numeric:
            if (f := flag_out_of_range(metric, row["value"],
                                       row.get("ref_low"), row.get("ref_high"),
                                       row.get("ref_low_operator"), row.get("ref_high_operator"))):
                f.observed_on = row["observed_on"]
                # Fold in a guideline mention when this reading is ALSO past a cited
                # line (no extra flag — just enriches the out-of-range one).
                _annotate_guideline(f, row["value"], thresholds)
                flags.append(f)

        # The latest-reading personal-baseline check (the remaining point-level
        # detectors below all describe the latest reading and carry the latest date;
        # trend detectors stay whole-series, observed_on=None).
        if (f := personal_baseline_z(metric, values[:-1], latest["value"],
                                     ref_low=latest.get("ref_low"),
                                     ref_high=latest.get("ref_high"))):
            f.observed_on = latest["observed_on"]
            flags.append(f)

    # Trend flags describe the WHOLE series, not one reading — but stamp them with
    # the latest reading's date so every flag carries a date (the UI shows one per
    # flag). This does NOT add a chart marker: MetricChart maps point markers by
    # KIND ('out_of_range' / personal_baseline / delta / threshold), and 'trend'
    # isn't among them, so a dated trend still highlights no point (its date reads
    # as "as of the latest reading").
    if (f := linear_trend(metric, dates, values)):
        f.observed_on = latest["observed_on"]
        flags.append(f)

    if (f := mann_kendall(metric, values)):
        f.observed_on = latest["observed_on"]
        flags.append(f)

    if rcv_cv and len(values) >= 2:
        if (f := rcv_delta(metric, values[-2], values[-1],
                           rcv_cv["analytical"], rcv_cv["intra"])):
            f.observed_on = latest["observed_on"]
            flags.append(f)

    if thresholds:
        # Crossing (needs two readings): the one-time "you just crossed the line" event.
        crossed_cutoffs = set()
        if len(values) >= 2:
            for f in clinical_threshold_crossing(metric, values[-2], values[-1], thresholds):
                f.observed_on = latest["observed_on"]
                flags.append(f)
                crossed_cutoffs.add(f.detail.get("cutoff"))
        # Static level: the STANDING "your latest value is on the concerning side"
        # state, for lines the crossing didn't just report (so no double-flag).
        if (lvl := flag_threshold_level(metric, values[-1], thresholds,
                                        exclude_cutoffs=crossed_cutoffs)):
            lvl.observed_on = latest["observed_on"]
            flags.append(lvl)

    return flags


# ----------------------------------------------------------------------------- historical anomalies

# Severity tiers, matching the UI's ordering — the primary, honest cross-kind
# ranking key (a 3-SD personal-baseline outranks an out-of-range, both 'watch'/
# 'high' the same way the flag list already sorts).
_SEVERITY_RANK = {"high": 0, "watch": 1, "info": 2}


def _anomaly_magnitude(flag: Flag) -> float:
    """A within-tier sort key: how far this reading deviated, on each kind's own
    NATIVE scale (we deliberately don't fake a single cross-kind unit — severity
    is the honest cross-kind comparator; this only orders flags of comparable
    severity). Pure: derived from numbers the detectors already computed, no new
    detection.

      personal_baseline -> |z| (SDs from the personal mean)
      out_of_range      -> fractional distance past the nearer bound
                           (excess / range-width, or excess / |bound| if width
                           is missing/zero)

    Other kinds (none reach here from analyze_history) fall back to 0.0.
    """
    d = flag.detail
    if flag.kind == "personal_baseline":
        return abs(d.get("z", 0.0))
    # out_of_range and its personal-baseline-mode reframe (personal_range) share
    # the same fractional-distance-past-the-bound magnitude.
    if flag.kind in ("out_of_range", "personal_range"):
        value, lo, hi = d.get("value"), d.get("ref_low"), d.get("ref_high")
        if value is None:
            return 0.0
        if hi is not None and value > hi:
            excess, bound = value - hi, hi
        elif lo is not None and value < lo:
            excess, bound = lo - value, lo
        else:
            return 0.0
        width = (hi - lo) if (lo is not None and hi is not None and hi > lo) else None
        denom = width if width else (abs(bound) if bound else None)
        return excess / denom if denom else excess
    return 0.0


# Tunables for the historical-anomaly panels (display volume only — they bound
# how MUCH is shown, never WHAT counts as an anomaly). Named as module constants
# (like CHANGES_RECENT_DAYS / the BASELINE_* gates) so a settings panel can
# read/override them; they remain the fallback default when no setting is stored.
ANOMALY_DETAIL_CAP = 10        # max readings listed per (kind, direction) group
ANOMALY_CONDENSE_THRESHOLD = 3  # group with >= this many members collapses to a summary line


def _numeric_rows(series) -> list[dict]:
    """NUMERIC-only rows, exactly like analyze_series: censored/qualitative rows
    never enter the history math (a censored bound is not a number)."""
    return [
        row for row in series
        if row.get("result_type", "numeric") == "numeric" and row.get("value") is not None
    ]


def _history_flags(metric, numeric, *, personal_baseline_mode=False, thresholds=None) -> list[Flag]:
    """The FULL (uncapped) ranked list of readings that stood out across history.
    Reuses the existing detectors (no new math): `flag_out_of_range` per reading,
    and `personal_baseline_z` with an EXPANDING window (each reading judged
    against only the history that preceded it — what was unusual for you then).

    In personal_baseline_mode the out-of-range readings are recontextualized (the
    shared _baseline_reframe_flags helper), so the history panel matches the chart:
    chronic lab-range exceedances become neutral 'within your established range'
    entries, while genuine breaks from your pattern stay loud.

    Returned ranked: severity tier (high>watch>info), then native deviation
    magnitude (|z| / fractional distance outside range) descending, then
    most-recent first. Capping is the caller's choice — kept uncapped here so the
    summary layer can count the true totals the cap would otherwise hide."""
    if personal_baseline_mode:
        flags = _baseline_reframe_flags(metric, numeric)
    else:
        flags = []
        # Out-of-range across the whole series (each reading vs its OWN stored range).
        for row in numeric:
            if (f := flag_out_of_range(metric, row["value"],
                                       row.get("ref_low"), row.get("ref_high"),
                                       row.get("ref_low_operator"), row.get("ref_high_operator"))):
                f.observed_on = row["observed_on"]
                # Fold in a guideline mention for a reading also past a cited line —
                # so a historical below-range reading reads "..., and below the WHO
                # 13.0 guideline line" in Notable readings (no separate flag).
                _annotate_guideline(f, row["value"], thresholds)
                flags.append(f)

        # Personal-baseline with an expanding window: reading i is judged only against
        # values[:i] (the readings that preceded it), so each flag reflects what was
        # unusual for you AT THAT TIME, not against the full hindsight distribution.
        values = [row["value"] for row in numeric]
        for i, row in enumerate(numeric):
            if (f := personal_baseline_z(metric, values[:i], values[i],
                                         ref_low=row.get("ref_low"),
                                         ref_high=row.get("ref_high"))):
                f.observed_on = row["observed_on"]
                flags.append(f)

    flags.sort(key=lambda f: (
        _SEVERITY_RANK.get(f.severity, 9),
        -_anomaly_magnitude(f),
        _neg_date_key(f.observed_on),
    ))
    return flags


def analyze_history(metric, series, *, max_results=ANOMALY_DETAIL_CAP,
                    personal_baseline_mode=False, thresholds=None) -> list[Flag]:
    """Surface EVERY reading that stood out across a metric's whole history,
    ranked and capped at `max_results`. Thin wrapper over `_history_flags` kept
    for callers/tests that want the flat ranked list. NUMERIC-only; read-only.
    `thresholds` (optional) folds a guideline mention into out-of-range flags."""
    numeric = _numeric_rows(series)
    if not numeric:
        return []
    return _history_flags(
        metric, numeric, personal_baseline_mode=personal_baseline_mode,
        thresholds=thresholds,
    )[:max_results]


# Descriptive phrasing per (kind, direction) — surface, never diagnose. Each
# states only WHERE the readings fell, not what that indicates.
_GROUP_PHRASE = {
    ("out_of_range", "above"): "above the reference range",
    ("out_of_range", "below"): "below the reference range",
    ("personal_baseline", "above"): "unusually high for your baseline",
    ("personal_baseline", "below"): "unusually low for your baseline",
    # Personal-baseline mode: lab-range exceedances that are consistent with the
    # user's own history (the pattern-breaks are in the personal_baseline group,
    # never here). Descriptive, never a clinical claim.
    ("personal_range", "above"): "above the lab reference range, within your established range",
    ("personal_range", "below"): "below the lab reference range, within your established range",
}


@dataclass
class AnomalyGroup:
    """A condensed summary of one (kind, direction) of historical anomalies for a
    metric. Descriptive only: deterministic counts/spans over flags the engine
    already produced — no new detection, no interpretation."""
    metric: str
    kind: str            # 'out_of_range' | 'personal_baseline'
    direction: str       # 'above' | 'below'
    severity: str        # highest severity among the group's members
    count: int           # full count of flagged readings (BEFORE the detail cap)
    total: int           # total numeric readings for the metric (the eligible pool)
    value_min: float
    value_max: float
    unit: str
    date_first: str
    date_last: str
    condensed: bool      # True when count >= condense_threshold (show summary line)
    summary: str         # deterministic plain-language summary line
    detail: list[Flag]   # the group's members, ranked, capped at max_detail


def _flag_direction(flag: Flag) -> str:
    """'above' or 'below', from the numbers the detector already computed."""
    d = flag.detail
    if flag.kind == "personal_baseline":
        return "above" if d.get("z", 0.0) > 0 else "below"
    v, hi = d.get("value"), d.get("ref_high")
    return "above" if (v is not None and hi is not None and v > hi) else "below"


def _fmt_num(x: float) -> str:
    """Compact number for display: drops needless trailing zeros (122.0 -> '122',
    keeps 1.005). Mirrors how the table renders values."""
    return f"{x:g}"


def summarize_history(metric, series, *, condense_threshold=ANOMALY_CONDENSE_THRESHOLD,
                      max_detail=ANOMALY_DETAIL_CAP, personal_baseline_mode=False,
                      thresholds=None) -> list[AnomalyGroup]:
    """Group a metric's historical anomalies by (kind, direction) and summarize
    each deterministically, so a metric with many same-kind anomalies leads with
    a digest line instead of a wall of individual warnings.

    Computed from the FULL (uncapped) flag set so counts are truthful — the
    cap-at-10 only bounds each group's expandable `detail` (the most notable
    members). A group with >= condense_threshold members is `condensed` (the UI
    shows the summary line); 1-2 members stay individual. Read-only, descriptive.

    In personal_baseline_mode the out-of-range group is reframed to the neutral
    'within your established range' wording (via _history_flags).
    """
    numeric = _numeric_rows(series)
    if not numeric:
        return []
    total = len(numeric)
    unit = numeric[-1].get("unit") or ""

    flags = _history_flags(metric, numeric,
                           personal_baseline_mode=personal_baseline_mode,
                           thresholds=thresholds)  # full, ranked

    # Group preserving ranked order within each (kind, direction) bucket.
    groups: dict[tuple[str, str], list[Flag]] = {}
    for f in flags:
        groups.setdefault((f.kind, _flag_direction(f)), []).append(f)

    out: list[AnomalyGroup] = []
    for (kind, direction), members in groups.items():
        values = [m.detail.get("value") for m in members if m.detail.get("value") is not None]
        dates = [m.observed_on for m in members if m.observed_on]
        vlo, vhi = min(values), max(values)
        d0, d1 = min(dates), max(dates)
        severity = min((m.severity for m in members), key=lambda s: _SEVERITY_RANK.get(s, 9))
        count = len(members)
        phrase = _GROUP_PHRASE.get((kind, direction), "noted")
        unit_sfx = f" {unit}" if unit else ""
        summary = (
            f"{count} of {total} reading{'s' if count != 1 else ''} {phrase} "
            f"(values {_fmt_num(vlo)}–{_fmt_num(vhi)}{unit_sfx}, {d0} to {d1})."
        )
        out.append(AnomalyGroup(
            metric=metric, kind=kind, direction=direction, severity=severity,
            count=count, total=total, value_min=vlo, value_max=vhi, unit=unit,
            date_first=d0, date_last=d1, condensed=count >= condense_threshold,
            summary=summary, detail=members[:max_detail],
        ))

    # Most notable first: severity tier, then the group's single most-deviant
    # member (detail[0] is the top-ranked member, since members preserve the
    # global severity+magnitude rank), then breadth (count) as a tiebreak. This
    # leads with the most prominent reading rather than just the largest pile.
    out.sort(key=lambda g: (
        _SEVERITY_RANK.get(g.severity, 9),
        -_anomaly_magnitude(g.detail[0]),
        -g.count,
    ))
    return out


def _neg_date_key(iso: str | None):
    """Sort key that puts the most recent date first (ascending sort, so negate).
    Dates are ISO 'YYYY-MM-DD', which sort lexicographically; map to an ordinal
    and negate. None (whole-series flags, not produced here) sorts last."""
    if not iso:
        return 1
    return -_to_date(iso).toordinal()


# ----------------------------------------------------------------------------- cross-metric overview

def current_flags(metric, series, *, personal_baseline_mode=False,
                  rcv_cv=None, thresholds=None) -> list[Flag]:
    """The flags describing a metric's CURRENT state, for the cross-metric overview:
    every whole-series flag (e.g. trend, which carries no date) plus any flag on
    the metric's most-recent reading. Reuses analyze_series VERBATIM (no new math)
    and only filters to the latest reading's date, so the overview shows 'what's
    flagged right now' rather than a metric's entire flag history. Read-only,
    descriptive — every flag's message is the engine's own."""
    flags = analyze_series(metric, series, personal_baseline_mode=personal_baseline_mode,
                           rcv_cv=rcv_cv, thresholds=thresholds)
    if not flags:
        return []
    dates = [row["observed_on"] for row in series if row.get("observed_on")]
    latest = max(dates) if dates else None
    return [f for f in flags if f.observed_on is None or f.observed_on == latest]


def rank_flags_cross_metric(flags: list[Flag]) -> list[Flag]:
    """Rank a cross-metric flag list by the SAME key the per-metric history uses:
    severity tier (high>watch>info), then native deviation magnitude, then recency.
    Pure reuse of the existing sort keys — no new comparator and no new detection."""
    return sorted(flags, key=lambda f: (
        _SEVERITY_RANK.get(f.severity, 9),
        -_anomaly_magnitude(f),
        _neg_date_key(f.observed_on),
    ))


def rank_groups_cross_metric(groups: list[AnomalyGroup]) -> list[AnomalyGroup]:
    """Rank a cross-metric AnomalyGroup list by the SAME key summarize_history uses
    within one metric: severity tier, the group's most-deviant member, then breadth
    (count). Pure reuse of the existing keys — no new comparator."""
    return sorted(groups, key=lambda g: (
        _SEVERITY_RANK.get(g.severity, 9),
        -_anomaly_magnitude(g.detail[0]),
        -g.count,
    ))


# ----------------------------------------------------------------------------- since-previous change

# Tunable: how recent a metric's LATEST reading must be for its movement to
# surface in the /changes digest. Without this, the digest re-reports stale
# months-old changes (latest-vs-previous regardless of when "latest" was). Named
# as a module constant (like BASELINE_RANGE_FRACTION / BASELINE_REL_MOVE_MIN) so a
# settings panel can read/override it rather than it being buried inline.
CHANGES_RECENT_DAYS = 30


def is_recent(observed_on, today=None, within_days=CHANGES_RECENT_DAYS) -> bool:
    """True if `observed_on` (ISO 'YYYY-MM-DD') is no older than `within_days`
    relative to `today` (defaults to date.today()). Pure/descriptive — keeps the
    changes digest to genuinely recent movement. A missing date is not recent."""
    if not observed_on:
        return False
    if today is None:
        today = date.today()
    return (today - _to_date(observed_on)).days <= within_days


@dataclass
class Change:
    """One metric's movement from its immediately previous reading to its latest.

    Descriptive only (per the analysis safety boundary): it reports THAT a value
    rose / fell / is unchanged / crossed into or out of its reference range —
    never what that movement indicates. `text` is the deterministic phrasing the
    engine computed; a narrate layer may only restate it, never add meaning.
    """
    metric: str
    status: str          # 'rose' | 'fell' | 'unchanged' | 'changed' | 'no_previous'
    category: str        # 'moved' | 'stable' | 'no_previous'  (digest grouping)
    text: str            # deterministic plain-language description
    previous: float | None = None
    current: float | None = None
    previous_display: str | None = None   # text form (covers non-numeric)
    current_display: str | None = None
    delta: float | None = None            # current - previous (numeric only)
    pct: float | None = None              # fractional change (numeric only)
    # 'newly_flagged' (was in range, now out) | 'no_longer_flagged' (reverse) |
    # None. Numeric only — reuses flag_out_of_range against each reading's range.
    flag_transition: str | None = None
    observed_on: str | None = None        # date of the latest reading


def _display(row: dict) -> str:
    """How a reading reads in the digest, by result_type. Mirrors the frontend's
    table rendering so a non-numeric change reads the same ('<5 mg/dL',
    'Positive', '133 mg/dL')."""
    rtype = row.get("result_type", "numeric")
    unit = row.get("unit") or ""
    suffix = f" {unit}" if unit else ""
    if rtype == "qualitative":
        return row.get("value_text") or ""
    if rtype == "censored":
        return f"{row.get('operator') or ''}{row.get('value')}{suffix}"
    return f"{row.get('value')}{suffix}"


def _is_numeric(row: dict) -> bool:
    return row.get("result_type", "numeric") == "numeric" and row.get("value") is not None


def _in_range(row: dict) -> bool | None:
    """Is this numeric reading within its own reference range? None if it has no
    range to judge against (so we don't claim a transition we can't see)."""
    lo, hi = row.get("ref_low"), row.get("ref_high")
    if lo is None and hi is None:
        return None
    return flag_out_of_range("", row["value"], lo, hi) is None


def latest_change(metric, series) -> Change:
    """Compare a metric's latest reading to the immediately previous one and
    describe the movement. Read-only, deterministic, no model.

    - Both numeric: rose / fell / unchanged, with delta/pct, plus a flag
      transition (newly / no-longer flagged) from each reading's own range.
    - Either reading non-numeric (censored/qualitative): TEXT comparison only —
      'changed from X to Y' with NO direction (a censored bound is never treated
      as a number), or 'unchanged' if the display text matches.
    - Fewer than two readings: 'no_previous' (nothing to compare yet).
    """
    if not series:
        return Change(metric, "no_previous", "no_previous",
                      f"{metric}: no readings yet.")
    if len(series) < 2:
        latest = series[-1]
        return Change(metric, "no_previous", "no_previous",
                      f"{metric}: only one reading so far — nothing to compare yet.",
                      current=latest.get("value"), current_display=_display(latest),
                      observed_on=latest.get("observed_on"))

    prev, latest = series[-2], series[-1]
    pd, cd = _display(prev), _display(latest)
    on = latest.get("observed_on")

    # Non-numeric on either side -> text comparison, no direction.
    if not (_is_numeric(prev) and _is_numeric(latest)):
        if pd == cd:
            return Change(metric, "unchanged", "stable",
                          f"{metric} unchanged: {cd}.",
                          previous_display=pd, current_display=cd, observed_on=on)
        return Change(metric, "changed", "moved",
                      f"{metric} changed from {pd} to {cd}.",
                      previous_display=pd, current_display=cd, observed_on=on)

    # Both numeric: direction + magnitude + range transition.
    p, c = prev["value"], latest["value"]
    delta = c - p
    pct = (delta / p) if p else None

    prev_in, cur_in = _in_range(prev), _in_range(latest)
    transition = None
    if prev_in is not None and cur_in is not None:
        if prev_in and not cur_in:
            transition = "newly_flagged"
        elif cur_in and not prev_in:
            transition = "no_longer_flagged"

    if delta == 0:
        status, category, verb = "unchanged", "stable", "unchanged at"
        body = f"{metric} unchanged at {cd}."
    else:
        status = "rose" if delta > 0 else "fell"
        category = "moved"
        pct_txt = f" ({pct * 100:+.0f}%)" if pct is not None else ""
        body = f"{metric} {status} from {pd} to {cd}{pct_txt}."

    if transition == "newly_flagged":
        body += " Now outside its reference range."
    elif transition == "no_longer_flagged":
        body += " Back within its reference range."

    return Change(metric, status, category, body,
                  previous=p, current=c, previous_display=pd, current_display=cd,
                  delta=delta, pct=pct, flag_transition=transition, observed_on=on)
