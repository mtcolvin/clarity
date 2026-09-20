"""
explain.py — the deterministic per-metric bundle assembler for the EXPORT handoff.

Sibling to narrate.py. `assemble_explain_context` builds a rich, deterministically-
assembled bundle (readings, the engine's finished findings, cited thresholds, trend
statistics) that api.py's /export routes hand to a hosted model under the charter's
gated, per-send-confirmed flow (CLAUDE.md "The export handoff"). It also owns the
shared system instruction (EXPLAIN_SYSTEM) and disclaimer frame (FRAME) that handoff
sends.

It does NO detection and NO math: every number, threshold, and statistic is computed
upstream and arrives finished in the bundle; the model is NEVER the source of a number
the UI presents as authoritative. This module touches no SQL and calls no provider —
the caller (api.py) gathers the substrate, and the hosted call runs from api.py through
the privacy gateway (gateway.py).

History: this file WAS the local interpretation tier (an on-demand Ollama reasoning
pass). That tier was removed as dead code — its UI trigger was gone and its engine gate
(summarizer-engine is a closed in_program-only enum, but explain_metric required
'ollama') made it unreachable — and the assembler it built was repurposed as the export
payload. `proximity_skip` is retained as a clean, tested pure utility (currently with no
caller; a future interpretation tier could reuse it); `_proximity_scale` still backs the
bundle's gap-to-cutoff.
"""

from __future__ import annotations

from analysis import Flag

# NO default cap on readings placed in the bundle — `max_readings=None` sends the FULL
# series. The old default of 12 existed to bound what a SMALL LOCAL model saw; that
# rationale did not survive the move to a strong external model on per-send consent
# (ROADMAP #1 recon §5 flagged exactly this: "revisit rather than reuse as-is"), and
# truncating history is actively wrong for a tool whose purpose is longitudinal reading —
# a trend is the thing being exported. The parameter remains so a caller can still bound
# a payload deliberately; `n_readings` still carries the true total either way.

# Proximity band (see CLAUDE.md "The interpretation tier"). A quarter of the
# clinical scale is "near enough to mention" — the SAME bar and rationale as
# analysis.BASELINE_RANGE_FRACTION (0.25). Kept a separate constant on purpose: the
# noise gate and this band are the same *idea* but must be tunable independently
# (changing the detector's gate must not silently move the model-skip band).
PROXIMITY_FRACTION = 0.25

EXPLAIN_SYSTEM = """You are reasoning with the depth of an experienced physician who reads results like these every day, with specialist familiarity across cardiology, neurology, hematology, endocrinology, nephrology, hepatology, and immunology. You are helping someone understand their own lab and vital results before a visit with their clinician. Bring that depth: read the bundle the way a specialist would — noticing what a PATTERN across these values suggests to someone who knows the territory, not merely which values fall outside a printed range.

You are given a STRUCTURED bundle of pre-computed facts about ONE OR MORE of their metrics: for each metric, its readings over time, the deterministic engine's findings (out-of-range, trend, personal-baseline, threshold-crossing) with their statistics, any cited guideline thresholds with the issuing source's own definition and the latest value's distance from each, the personal-baseline mean, a methodology note, and the latest change.

Your job: explain what stands out and — where the data supports it — FLOAT POSSIBLE EXPLANATIONS the person can raise with their clinician, both ones that tie patterns across several metrics together and ones a single metric points to. This is to help them ask better questions, not to answer them.

Rules — follow all of them:
1. READ THE CURRENT STATE. The question is what is true NOW. Weight the most recent readings most heavily. A value that was abnormal in the past and has since returned to normal is RESOLVED HISTORY — raise it only where it bears on the present picture (a trend still unfinished, a value drifting back toward a line, a pattern that recurs). Do not re-narrate a past episode, and never present an old abnormality as a current finding. Where a metric's readings cluster around one historical event, say what the CURRENT values show, not what happened then. If a metric's most recent reading is itself old, treat it as stale data rather than a present-day fact, and say so.
2. Ground everything in the DATA shown. You MAY use general medical knowledge to connect the facts and suggest what a pattern could mean, but every claim must anchor to a specific number, finding, trend, threshold, or relationship visible in the bundle — never to a metric's name alone, and never to a value that isn't there.
3. Never state a number, cutoff, or threshold that is not in the bundle. Do not compute, estimate, or round to new numbers; use the exact figures given.
4. You MAY relate the metrics to each other and point out patterns the engine did not flag — a value approaching a cited threshold, a deviation from a baseline, a relationship named in a methodology note, or several metrics moving together — when they are visible in the data.
5. Any explanation is a POSSIBILITY to raise with a clinician, never a conclusion. Phrase it that way ("one thing that could tie these together is ...; it may be worth asking your clinician whether ...") and, where the data supports more than one, offer alternatives rather than converging on a single confident answer. You genuinely cannot know what is actually going on — say so. Specialist depth means sharper, better-grounded possibilities; it does not mean a verdict.
6. You MAY name a condition or mechanism, but ONLY as a hedged candidate to discuss — never as a statement that the person HAS it, and never as a definitive finding. When unsure, prefer describing the pattern to naming a condition.
7. Do NOT suggest, recommend, or imply any treatment, medication, dose, or supplement — that is for the clinician only. Hypotheses to discuss, yes; what to do about them, no.
8. If the data is unremarkable — nothing flagged, nothing approaching a threshold, no pattern that connects — SAY SO plainly ("Nothing here stands out to interpret."). Reporting that nothing stands out is a correct, complete, and valued answer; do NOT manufacture concern or reach for something to say.
9. Report every point the data genuinely supports — do not ration them to a fixed number. Lead with what matters most in the CURRENT picture, and where several findings plausibly share one thread, group them under that thread instead of listing them separately. Let length follow the data: brief when the picture is quiet, fuller when there is genuinely more to say. Prefer specific references to the data over general commentary, and do not pad.
10. Close with a brief note that this is to help prepare questions for a clinician, not to replace one, and that any possibility you raise is exactly that — a possibility to discuss, not a diagnosis. (Belt-and-suspenders only — the app appends its own fixed disclaimer separately regardless of what you write here.)"""


def system_instruction(as_of: str | None = None) -> str:
    """The system instruction actually sent, = EXPLAIN_SYSTEM plus today's date.

    Rule 1 (read the CURRENT state) is unenforceable without it: reading dates alone,
    the model cannot tell whether the latest reading is from last week or two years
    ago, so it cannot judge what is 'current' or call a stale series stale. The date
    is ambient context, not user data — it carries nothing about the person — and it
    rides the INSTRUCTION rather than the payload deliberately: putting it in the
    bundle would repeat it once per metric in the preview (176 times on a full-picture
    export) and would perturb the confirmation token at every midnight boundary."""
    if not as_of:
        return EXPLAIN_SYSTEM
    return (
        f"{EXPLAIN_SYSTEM}\n\n"
        f"Today's date is {as_of}. Judge recency against it — including for a metric "
        f"whose most recent reading is itself long past."
    )

# Appended in code (never model-generated) — the interpretation-tier equivalent of
# narrate.DISCLAIMER, deliberately distinct wording (this tier reasons; the restate
# tier only restates).
FRAME = (
    "This is an automated interpretation to help you prepare questions for your "
    "clinician — not a diagnosis or medical advice. Any possible explanation it "
    "raises is a possibility to discuss with your clinician, not a conclusion, and it "
    "never recommends treatment. It reasons over the data shown above."
)


def _numeric(series: list[dict]) -> list[dict]:
    return [
        r for r in series
        if r.get("result_type", "numeric") == "numeric" and r.get("value") is not None
    ]


def _in_range_hint(row: dict) -> bool | None:
    """A plain inclusive in/out hint for the bundle (context for the model, NOT a
    flag — the exact out-of-range semantics live in engine_findings). None when the
    reading has no numeric value or no bound to judge against (e.g. a qualitative result)."""
    v = row.get("value")
    lo, hi = row.get("ref_low"), row.get("ref_high")
    if v is None or (lo is None and hi is None):
        return None
    return (lo is None or v >= lo) and (hi is None or v <= hi)


def _reading_display(row: dict) -> str:
    """The human display of a reading, per result type — so a qualitative or censored
    result is REPRESENTED in the export (a 'Not applicable'/'Positive'/'<5' IS a reading),
    not dropped for lacking a numeric value. Mirrors the table's per-type rendering."""
    rt = row.get("result_type", "numeric")
    if rt == "qualitative":
        return row.get("value_text") or ""
    v = row.get("value")
    if rt == "censored":
        return f"{row.get('operator', '')}{v}"
    return "" if v is None else str(v)


def _proximity_scale(numeric: list[dict]) -> float | None:
    """Clinical scale for threshold proximity: the latest reading's reference-range
    width when two-sided (primary — stable per-reading, the same scale the noise
    gate uses); else the numeric value span when > 0 (data scale); else None
    (degenerate: a single reading with a one-sided/absent range, or all-identical
    values)."""
    lr = numeric[-1]
    lo, hi = lr.get("ref_low"), lr.get("ref_high")
    if lo is not None and hi is not None and hi > lo:
        return hi - lo
    vals = [r["value"] for r in numeric]
    span = max(vals) - min(vals)
    return span if span > 0 else None


def proximity_skip(flags: list[Flag], thresholds_detailed: list[dict],
                   numeric: list[dict]) -> bool:
    """Band gate — skip the model (render the deterministic 'nothing notable' line)
    ONLY when we can AFFIRMATIVELY confirm the data is unremarkable: zero engine
    findings AND (no cited thresholds, OR the nearest cited cutoff is farther than
    PROXIMITY_FRACTION of the clinical scale). When in doubt — a cutoff within the
    band, or a degenerate scale we can't measure against — do NOT skip: run and let
    the model apply its own 'nothing stands out' rule. Pure; no divide-by-zero (the
    degenerate scale returns None and short-circuits to run)."""
    if flags:
        return False
    if not numeric:
        return True                                  # nothing numeric to interpret
    cuts = [t["cutoff"] for t in thresholds_detailed if t.get("cutoff") is not None]
    if not cuts:
        return True                                  # no findings, no thresholds -> featureless
    scale = _proximity_scale(numeric)
    if scale is None:
        return False                                 # can't confirm far -> run
    latest = numeric[-1]["value"]
    nearest_gap = min(abs(latest - c) for c in cuts)
    return (nearest_gap / scale) > PROXIMITY_FRACTION


def assemble_explain_context(metric, unit, series, flags, thresholds_detailed,
                             personal_baseline_mean, methodology_note, latest_change,
                             personal_baseline_mode, max_readings=None) -> dict:
    """Gather the deterministic substrate for ONE metric into the model bundle
    (recon §2). Pure — takes already-computed inputs, no SQL. gap_to_cutoff is
    computed HERE (code), so the model can reason about 'approaching X' using only a
    number we handed it. methodology_note is ALWAYS present (null if none) so rule 3
    of the prompt (reason from methodology relationships) is never left unsupported.

    Each engine finding is `{**f.detail, kind, severity, message}` — the fixed keys
    come LAST so a detector's detail dict can never clobber them (defended by
    test_finding_keys_survive_spread, which trips if a future detector adds a
    colliding detail key)."""
    numeric = _numeric(series)
    latest_val = numeric[-1]["value"] if numeric else None
    # Readings shown to the model include EVERY result type (a qualitative/censored result
    # IS a reading), each with a per-type `display`; the numeric-only STATS (findings,
    # thresholds, proximity) still run over `numeric` only. n_readings counts all rows.
    # max_readings=None (the default) sends the FULL series — see the constant note above.
    recent = series if max_readings is None else series[-max_readings:]
    return {
        "metric": metric,
        "unit": unit,
        "n_readings": len(series),
        "readings": [
            {"observed_on": r["observed_on"], "value": r.get("value"),
             "display": _reading_display(r),
             "result_type": r.get("result_type", "numeric"),
             "ref_low": r.get("ref_low"), "ref_high": r.get("ref_high"),
             "normal_text": r.get("normal_text"),
             "in_range": _in_range_hint(r)}
            for r in recent
        ],
        "engine_findings": [
            {**f.detail, "kind": f.kind, "severity": f.severity, "message": f.message}
            for f in flags
        ],
        "cited_thresholds": [
            {"cutoff": t.get("cutoff"), "source": t.get("source"),
             "definition": t.get("definition"), "status_note": t.get("status_note"),
             "latest_value": latest_val,
             "gap_to_cutoff": (latest_val - t["cutoff"])
                              if (latest_val is not None and t.get("cutoff") is not None)
                              else None}
            for t in thresholds_detailed
        ],
        "personal_baseline_mean": personal_baseline_mean,
        "methodology_note": methodology_note,
        "latest_change": (
            {"status": latest_change.status, "pct": latest_change.pct,
             "flag_transition": latest_change.flag_transition,
             "previous_display": latest_change.previous_display,
             "current_display": latest_change.current_display}
            if latest_change is not None else None
        ),
        "personal_baseline_mode": personal_baseline_mode,
    }


