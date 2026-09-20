"""
metric_config.py — per-metric DETECTOR config: the DEFINITIONS layer.

The per-metric counterpart of settings.py. settings.py covers GLOBAL, scalar,
one-value-per-key display knobs (defaults imported from analysis.py constants);
this module covers PER-METRIC, composite-key (metric, key) detector config whose
values are STRUCTURED (a thresholds list, an RCV dict) and whose "defaults" are
data, not code constants. Kept separate so neither charter muddies the other, and
so it isn't confused with metric_settings (personal-baseline mode) in db.py.

The config a metric resolves to is splatted as **kwargs into analyze_series /
current_flags, so every registered key name is EXACTLY an engine kwarg
(`thresholds`, `rcv_cv`) — the splat is byte-for-byte what the former hardcoded
api.METRIC_CONFIG dict produced. db.py stores raw TEXT (JSON for the structured
values); this module casts on read. A metric with no rows resolves to {} —
handled by the engine exactly like the old "not in METRIC_CONFIG" fallback.

Resolution: there is no per-key code default here (unlike settings) — an absent
key simply isn't passed, and the engine's own kwarg default (no thresholds,
rcv_cv=None) backstops it. SEED below is the SOURCE OF TRUTH; the metric_config
table is a runtime CACHE of it — seed_defaults RE-APPLIES every SEED entry on
every startup via UPSERT, so an existing row IS overwritten (see its docstring).
"""

from __future__ import annotations

import json
from dataclasses import dataclass
from typing import Callable

import db


@dataclass(frozen=True)
class MetricConfigDef:
    """One known config key. `cast` types the stored TEXT on read; `dump` is the
    inverse, used when seeding. Both are JSON round-trips for the structured
    values we have today (a thresholds list, an rcv_cv dict).

    `display_only` marks a key that is NOT an analyze_series kwarg — it's stored
    and seeded through the normal path, but `_cast_raw` filters it OUT of the
    dict that `get_config` splats into the engine, so it can never reach detection
    (the same engine-vs-display separation thresholds get via get_thresholds_detailed,
    here made explicit for a display-ONLY key with no engine shape at all). Such a
    key is read by its own dedicated reader (e.g. get_methodology_note)."""
    key: str                          # an analyze_series kwarg name UNLESS display_only
    cast: Callable[[str], object]     # raw TEXT (JSON) -> typed value
    dump: Callable[[object], str]     # typed value -> TEXT (for seeding)
    display_only: bool = False        # True -> excluded from the engine kwarg splat


def _default_boundary(direction: str) -> str:
    """The boundary-inclusivity an entry resolves to when it carries no explicit
    `boundary` key, derived from its direction so absent reproduces the original
    hardcoded behavior EXACTLY: an 'up' crossing was inclusive on the arriving
    (current) end, a 'down' crossing exclusive on it. So up -> 'inclusive',
    anything else (i.e. 'down') -> 'exclusive'."""
    return "exclusive" if direction == "down" else "inclusive"


def _threshold_pairs(raw: str) -> list:
    """Parse a stored `thresholds` value into the ENGINE shape: a list of
    {cutoff, source, direction, boundary} dicts (what clinical_threshold_crossing
    consumes). NAMING NOTE: historically this emitted [cutoff, source] pairs, then
    [cutoff, source, direction] triples; it now emits dicts (named keys, swap-proof
    as fields grew). The rename to e.g. `_threshold_specs` is DEFERRED to keep this
    a focused commit — renaming would ripple to the get_config / all_configs call
    sites; the name is kept as-is for now.

    Handles BOTH the obsolete `[cutoff, source]` shape AND the structured
    `{cutoff, source, definition, direction?, boundary?}` dict shape, so the engine
    and its call sites are untouched across the shape migration. `direction`
    defaults to 'up' when absent; `boundary` defaults per-direction via
    _default_boundary, so every legacy row and every un-touched seed keeps the
    original crossing behavior EXACTLY (up+inclusive / down+exclusive). The rich
    fields (definition + per-source full_name/url) are read separately by
    get_thresholds_detailed for display."""
    out = []
    for item in json.loads(raw):
        if isinstance(item, dict):
            direction = item.get("direction", "up")
            out.append({"cutoff": item["cutoff"], "source": item["source"],
                        "direction": direction,
                        "boundary": item.get("boundary", _default_boundary(direction)),
                        # sex tag carried through for _cast_raw to filter on, then
                        # STRIPPED before the engine sees it (an untagged line -> None,
                        # applies to everyone). #18: sex-aware detection.
                        "sex": item.get("sex")})
        else:
            out.append({"cutoff": item[0], "source": item[1], "direction": "up",
                        "boundary": _default_boundary("up"), "sex": None})
    return out


# The registry — the recognized per-metric config keys. `thresholds` is the only
# one any metric uses today; `rcv_cv` is registered so the key is recognized and
# ready (nothing seeds it yet — no behavior change). Both names match the
# analyze_series kwargs they're splatted into.
CONFIG: list[MetricConfigDef] = [
    # thresholds: engine shape is a list of [cutoff, source]; stored shape may be
    # that (legacy) or the new list-of-dicts (cast collapses both to pairs).
    MetricConfigDef(key="thresholds", cast=_threshold_pairs, dump=json.dumps),
    # rcv_cv: {"analytical": float, "intra": float} to enable rcv_delta.
    MetricConfigDef(key="rcv_cv", cast=json.loads, dump=json.dumps),
    # methodology_note: DISPLAY-ONLY per-metric prose (#9) — "read alongside X",
    # "this is a computed approximation of Y", "state-dependent". NOT an engine
    # kwarg (display_only=True excludes it from get_config's splat), so it can
    # never reach analyze_series. Stored as bare TEXT (a plain scalar string, not
    # a structured JSON value), so cast/dump are identity; read via
    # get_methodology_note, which returns the raw stored text.
    MetricConfigDef(key="methodology_note", cast=str, dump=str, display_only=True),
]

BY_KEY: dict[str, MetricConfigDef] = {d.key: d for d in CONFIG}


# Per-source citation metadata, joined onto each threshold for the Reference-
# thresholds UI. `full_name` is the organization; `guideline` names the specific
# document (so a link can read "View KDIGO 2024 CKD Guideline"); `url` points at
# the source organization's OFFICIAL guideline page (not a third-party explainer).
# A source not listed here degrades gracefully (full_name falls back to the
# acronym, no url) — add an entry when a metric using that source is curated.
SOURCES: dict[str, dict] = {
    "KDIGO": {
        "full_name": "Kidney Disease: Improving Global Outcomes",
        "guideline": "2024 CKD Guideline",
        "url": "https://kdigo.org/guidelines/ckd-evaluation-and-management/",
    },
    "ACC/AHA": {
        "full_name": "American College of Cardiology / American Heart Association",
        "guideline": "2026 Guideline on the Management of Dyslipidemia",
        # 2026 ACC/AHA/multisociety Dyslipidemia guideline (Circulation/JACC, March
        # 2026); retires + replaces the 2018 Blood Cholesterol guideline. DOI permalink
        # (canonical/permanent) resolves 302 to the full guideline in Circulation;
        # used over the direct ahajournals URL because that host stays behind
        # Cloudflare (automated checks get a 403 bot-challenge). The LDL-C >=190
        # high-intensity-statin / Class I / treat-regardless-of-risk threshold is
        # RETAINED in 2026 — verified via multiple non-blocked secondaries (incl. the
        # NLA, a co-authoring society) + the guideline's own management-group structure
        # (>=190 = "severe hypercholesterolemia"). ahajournals.org/jacc.org primary
        # docs STILL return Cloudflare 403 to automated fetch, so 190-retention rests
        # on secondary verification (same posture as ATP III's labels), not a
        # primary-source read. "ACC/AHA" stays the short-form label (still an ACC/AHA
        # Joint Committee report, same multisociety structure as 2018).
        "url": "https://doi.org/10.1161/CIR.0000000000001423",
    },
    "ATP III": {
        "full_name": "NCEP Adult Treatment Panel III (Third Report)",
        "guideline": "2002 Cholesterol Guidelines",
        # NHLBI .gov at-a-glance — not Cloudflare-protected, so verifiable. ATP III
        # is the foundational, still-recognized triglyceride classification; the
        # 2026 ACC/AHA guideline keeps the same 150 / 500 boundaries but its exact
        # category-label vocabulary couldn't be web-verified (Cloudflare), so ATP III
        # (whose labels ARE verified) is cited per the seed-only-what's-verified rule.
        "url": "https://www.nhlbi.nih.gov/files/docs/guidelines/atglance.pdf",
    },
    "IOM": {
        "full_name": "Institute of Medicine (now National Academy of Medicine)",
        "guideline": "2011 Dietary Reference Intakes for Calcium and Vitamin D",
        "url": "https://www.nationalacademies.org/publications/13050",
    },
    "Endocrine Society": {
        "full_name": "Endocrine Society",
        "guideline": "2011 Vitamin D Deficiency Clinical Practice Guideline",
        # Cites the 2011 doc that DEFINED the 30 ng/mL cutoff. The 2024 update
        # (which RETIRED it) is named in the threshold definition prose, not here:
        # the SOURCES shape stays single-url on purpose (see the curation-discipline
        # note in CLAUDE.md — don't add a retirement_url field until a SECOND
        # substantively-retired case justifies generalizing the shape). DOI permalink.
        "url": "https://doi.org/10.1210/jc.2011-0385",
    },
    "AUA": {
        "full_name": "American Urological Association",
        "guideline": "2018 Evaluation and Management of Testosterone Deficiency Guideline (reaffirmed 2024)",
        # auanet.org guideline page fetches cleanly (NOT Cloudflare-blocked, unlike
        # ahajournals/acc), and shows the "Reviewed and Validity Confirmed 2024"
        # status — a "living/reaffirmed" citation (see CLAUDE.md taxonomy). DOI
        # 10.1016/j.juro.2018.03.115 (-> jurology.com) is the backup.
        "url": "https://www.auanet.org/guidelines-and-quality/guidelines/testosterone-deficiency-guideline",
    },
    "ADA": {
        "full_name": "American Diabetes Association",
        "guideline": "Standards of Care in Diabetes (2026), §2 Diagnosis",
        # Diabetes Care 49(Suppl 1):S27–S49 (2026). DOI permalink (canonical; resolves
        # to diabetesjournals.org; the Standards' §2 is dcYY-S002 each year). LIVING/
        # CURRENT — the 2026 Standards are the in-force ADA guideline (web-verified).
        "url": "https://doi.org/10.2337/dc26-S002",
    },
    "ASH": {
        "full_name": "American Society of Hematology",
        "guideline": "Iron-deficiency diagnosis guidance (unified ferritin threshold)",
        # SOFT source tag (recorded deliberately). ASH's IDA-diagnosis clinical practice
        # guideline is in DRAFT / public-comment (2025), and its draft thresholds are
        # sub-population-specific (≤30 ng/mL menstruating/pregnant, ≤20 ng/mL general) —
        # NOT a single unified number. The seed's "unified 30" framing rests primarily on
        # Pasricha et al. (Lancet 2021) + broad lab adoption; ASH is the institutional
        # anchor. URL is ASH's official iron-deficiency hub (stable; the draft PDF moves).
        "url": "https://www.hematology.org/iron-deficiency-initiative",
    },
    "AACE/ATA": {
        "full_name": "American Association of Clinical Endocrinologists / American Thyroid Association",
        "guideline": "Clinical Practice Guidelines for Hypothyroidism in Adults (2012)",
        # Garber et al., Endocrine Practice 18(6):988–1028 (2012); cosponsored AACE+ATA.
        # DOI permalink resolves to endocrinepractice.org (web-verified). The reference-
        # range edges (~0.4 low / ~4.5 high) and the overt-vs-subclinical split at TSH 10
        # are this framework's; the 4.5 upper edge is acknowledged-contested (see the TSH
        # seed). 2012 doc not re-checked for reaffirmation — living/current (category a).
        "url": "https://doi.org/10.4158/EP12280.GL",
    },
    "Endocrine Society (2023)": {
        "full_name": "Endocrine Society",
        "guideline": "Treatment of Hypercalcemia of Malignancy in Adults: "
                     "An Endocrine Society Clinical Practice Guideline (2023)",
        # Distinct key from "Endocrine Society" (the 2011 Vitamin D entry): the SOURCES
        # registry is single-url per key, and this is a DIFFERENT Endocrine Society
        # document. Rather than generalize the shape, the key is disambiguated by year
        # (curation decision — revisit generalizing SOURCES only if a third same-org
        # case appears). El-Hajj Fuleihan et al., J Clin Endocrinol Metab 2023;108(3):
        # 507–528. DOI permalink. Source is malignancy-context; the mild/moderate/severe
        # grading is applied here as a general reference (each line's status_note =
        # "caveated" + definition prose says so).
        "url": "https://doi.org/10.1210/clinem/dgac621",
    },
    "ESE": {
        "full_name": "European Society of Endocrinology",
        "guideline": "Clinical Guideline: Treatment of Chronic Hypoparathyroidism "
                     "in Adults (2015)",
        # Bollerslev et al., Eur J Endocrinol 2015;173(2):G1–G20. DOI permalink. A
        # REVISED 2025 version exists (10.1093/ejendo/lvaf222), but the <8.0 mg/dL
        # symptomatic-hypocalcemia treatment figure traces to the original 2015
        # guideline — cite 2015 as primary (same "cite the doc that DEFINED the number"
        # discipline as the Endocrine Society vitamin-D entry).
        "url": "https://doi.org/10.1530/EJE-15-0628",
    },
    "AHA/CDC": {
        "full_name": "American Heart Association / U.S. Centers for Disease Control and Prevention",
        "guideline": "Markers of Inflammation and Cardiovascular Disease "
                     "(Pearson et al., Circulation 2003;107:499–511)",
        # The foundational 2003 CDC/AHA statement that defined the hs-CRP relative-risk
        # tertiles (<1 / 1–3 / >3 mg/L). Citation-status (c) stale-but-correct (CLAUDE.md
        # taxonomy): the document is 2003 and not restated by a newer dedicated AHA/CDC
        # inflammation statement, but the tertile VALUES remain in common clinical use
        # (verified 2026-07 via the freely-accessible PMC secondary PMC2639398, which cites
        # it and the tertiles directly; ahajournals is Cloudflare-blocked to tooling but
        # resolves in a browser, and pubmed.ncbi.nlm.nih.gov/12551878 is a freely-accessible
        # alternate). The 2019 ACC/AHA cholesterol guideline's hs-CRP >=2.0 "risk-enhancer"
        # is a DIFFERENT line/framework and is deliberately NOT seeded (avoids conflating two
        # frameworks — same discipline as HDL 40 vs the 40/50 metabolic-syndrome split).
        "url": "https://www.ahajournals.org/doi/10.1161/01.cir.0000052939.59093.45",
    },
    "WHO": {
        "full_name": "World Health Organization",
        "guideline": "Guideline on Haemoglobin Cutoffs to Define Anaemia in "
                     "Individuals and Populations (2024)",
        # WHO's official publications landing page (ISBN 978-92-4-008854-2, 5 Mar 2024;
        # who.int is not Cloudflare-blocked, fetches cleanly). The 2024 guideline
        # REAFFIRMED the adult cutoffs (Hgb <130 g/L men, <120 g/L non-pregnant women)
        # — a living/reaffirmed citation (CLAUDE.md taxonomy category b): the guideline
        # group considered a higher male cutoff (135 g/L) but RETAINED 130 given
        # evidence uncertainty. Only the adult sex-specific lines are seeded (see the
        # Hemoglobin SEED); children/pregnancy cutoffs aren't modelled here.
        "url": "https://www.who.int/publications/i/item/9789240088542",
    },
}


# Seed content — guideline cutoffs surfaced as chart gridlines (labelled
# "<source> <cutoff>") plus, in the NEW structured shape, a per-threshold
# `definition`. Labels and definitions are SOURCE + number / descriptive of the
# source's own framework only, never a condition label, per the analysis safety
# boundary.
#   hba1c         — ADA A1c cutoffs 5.7 / 6.5, kept in the OBSOLETE [cutoff, source]
#                   shape ON PURPOSE: no matching metric (never renders), and it
#                   exercises the cast's backward-compat path. Reshape when an ADA
#                   metric is concretely curated (its definitions need care to stay
#                   non-condition-labelled).
#   Estimated GFR — KDIGO GFR category boundaries, NEW structured shape with
#                   definitions. KDIGO 2024 CKD Guideline (web-verified). Boundaries
#                   unchanged from 2012. Descriptive framework boundaries only —
#                   full KDIGO staging is Cause-GFR-Albuminuria.
#   LDL Calculated — ACC/AHA single decision cutoff 190 mg/dL (verified: LDL-C
#                   ≥190 → high-intensity statin, Class I, no risk calculation).
#                   Citation refreshed to the 2026 ACC/AHA Dyslipidemia guideline,
#                   which retires + replaces the 2018 Blood Cholesterol guideline and
#                   RETAINS 190 (≥190 = "severe hypercholesterolemia" management group);
#                   retention secondary-verified (primary docs Cloudflare-blocked — see
#                   the SOURCES["ACC/AHA"] note). Only 190 is seeded — the risk-
#                   stratified 70/100 targets diverge across guidelines, so they're
#                   skipped (same discipline as eGFR).
SEED: dict[str, dict] = {
    "hba1c": {"thresholds": [[5.7, "ADA"], [6.5, "ADA"]]},
    # NOTE: Creatinine (Creatinine Serum/Plasma) is intentionally NOT seeded — its
    # absence is a decision, not an oversight. Serum creatinine has no fixed guideline
    # cutoff (its range is sex/muscle-mass-dependent, and the detector has no sex field
    # to vary a cutoff on, so a raw cutoff would mis-flag by sex). Its kidney-function
    # signal is covered by the eGFR entry below, which is age/sex-normalized. (See the
    # creatinine skip-entry in CLAUDE.md's "Threshold curation discipline" section.)
    # boundary on the eGFR cutoffs is "exclusive" as a SAFE DEFAULT pending KDIGO
    # boundary-side curation — NOT a prose-confirmed reading. The KDIGO category
    # labels ("Defines the boundary between Gx and Gy") name the gridline but don't
    # state which side owns the cutoff value, so which category an exact-on-cutoff
    # reading belongs to is unverified here. Distinct from the deficiency entry
    # below, whose "at or above … adequate" prose DOES confirm exclusive. Revisit
    # when the KDIGO boundary convention is curated (citation-status discipline).
    "Estimated GFR": {"thresholds": [
        {"cutoff": 60, "source": "KDIGO", "direction": "down", "boundary": "exclusive",
         "definition": "Defines the boundary between G2 (mildly decreased) and G3a "
                       "(mildly to moderately decreased) in KDIGO's GFR classification."},
        {"cutoff": 30, "source": "KDIGO", "direction": "down", "boundary": "exclusive",
         "definition": "Defines the boundary between G3b (moderately to severely "
                       "decreased) and G4 (severely decreased) in KDIGO's GFR classification."},
        {"cutoff": 15, "source": "KDIGO", "direction": "down", "boundary": "exclusive",
         "definition": "Defines the boundary between G4 (severely decreased) and G5 "
                       "(kidney failure) in KDIGO's GFR classification."},
    ],
        "methodology_note": "Itself an estimate, computed from creatinine, age, and sex "
                            "(CKD-EPI equation) — the flip side of the creatinine note."},
    "LDL Calculated": {"thresholds": [
        {"cutoff": 190, "source": "ACC/AHA",
         "definition": "Defines the threshold at or above which ACC/AHA recommends "
                       "high-intensity statin therapy regardless of ASCVD "
                       "(atherosclerotic cardiovascular disease) risk score."},
    ],
        "methodology_note": "A calculated value (Friedewald equation), not directly "
                            "measured. Becomes unreliable at high triglycerides or very "
                            "low LDL. Direct LDL measurement is the reference standard "
                            "this approximates."},
    # Non HDL — ATP III defines three risk-stratified non-HDL goals (<130 / <160 /
    # <190, each set 30 mg/dL above the corresponding LDL goal). Only the least-
    # stringent (190, the 0-1 risk-factor line) is seeded: it's the one boundary that
    # holds regardless of cardiovascular-risk category. The stricter goals require a
    # risk-factor assessment the app doesn't perform, and drawing all three would
    # imply a staging the app can't do — the definition surfaces them in prose instead.
    "Non-HDL": {"thresholds": [
        {"cutoff": 190, "source": "ATP III",
         "definition": "Defines the boundary at or above which non-HDL cholesterol "
                       "falls outside ATP III's least-stringent secondary goal (its "
                       "non-HDL goal of <190 mg/dL, set 30 mg/dL above the LDL goal "
                       "for individuals with 0-1 risk factors). ATP III sets stricter "
                       "non-HDL goals (<160, <130) for higher cardiovascular-risk "
                       "categories that depend on risk-factor assessment the app does "
                       "not perform; this surfaces the single risk-independent boundary."},
    ]},
    # HDL — ATP III's categorical low-HDL cutoff <40 mg/dL, sex-independent (the
    # 40/50 male/female split is population-average context, not ATP III's clinical
    # classification, which applies one cutoff to all adults). Down-direction: low is
    # concerning. The protective >=60 "negative risk factor" line is intentionally NOT
    # seeded — it's good-not-concerning, and the detector would misfire flagging it;
    # deferred to the parked protective/reference-threshold feature.
    "HDL": {"thresholds": [
        {"cutoff": 40, "source": "ATP III", "direction": "down", "boundary": "exclusive",
         "definition": "Defines the level below which ATP III categorically classifies "
                       "HDL cholesterol as 'low' (<40 mg/dL) - a single cutoff ATP III "
                       "applies to all adults, not a sex-specific range. ATP III treats "
                       "low HDL as an independent cardiovascular risk factor; it sets no "
                       "HDL-raising target and identifies HDL >=60 mg/dL as a 'negative' "
                       "(protective) risk factor, so only the low boundary is surfaced here."},
    ]},
    # Triglycerides — ATP III categorical cutoffs 150 / 500 mg/dL (web-verified;
    # 200 skipped, the modern framework treats 150–499 as one band). Fasting-
    # conventional. Definitions name ATP III's own LEVEL labels (borderline-high /
    # very high), never a condition; the pancreatitis clause is ATP III/AHA's stated
    # management rationale for the 500 cutoff, framework-as-subject.
    "Triglycerides": {"thresholds": [
        {"cutoff": 150, "source": "ATP III",
         "definition": "Defines the boundary at or above which ATP III classifies "
                       "triglycerides as borderline-high (its 150–199 mg/dL category); "
                       "below 150 is normal in ATP III's framework."},
        {"cutoff": 500, "source": "ATP III",
         "definition": "Defines the boundary at or above which ATP III classifies "
                       "triglycerides as very high (≥500 mg/dL) — at this level, "
                       "ATP III/AHA identifies acute pancreatitis prevention as the "
                       "primary management focus."},
    ]},
    # Total cholesterol (observed metric "Cholesterol") - ATP III's sex-independent
    # classification: 200 borderline-high / 240 high (the 200-239 band). Both bands
    # apply to everyone, so both cutoffs are seeded - the genuine multi-band case like
    # Triglycerides (unlike Non-HDL's risk-stratified goals, where only the single
    # risk-independent boundary is surfaced). Up-direction (higher = concerning).
    "Cholesterol": {"thresholds": [
        {"cutoff": 200, "source": "ATP III",
         "definition": "Defines the boundary at or above which ATP III classifies "
                       "total cholesterol as 'borderline high' (its 200-239 mg/dL "
                       "category); below 200 is 'desirable' in ATP III's framework. "
                       "This cutoff is the same for men and women."},
        {"cutoff": 240, "source": "ATP III",
         "definition": "Defines the boundary at or above which ATP III classifies "
                       "total cholesterol as 'high' (>=240 mg/dL), the most severe "
                       "of its three total-cholesterol categories."},
    ]},
    # C-Reactive Protein High Sensitivity — the AHA/CDC hs-CRP relative-cardiovascular-
    # risk tertiles (<1 low / 1–3 average / >3 high mg/L; Pearson 2003). This is the
    # SEPARATE hs-CRP metric: the STANDARD CRP assay stays note-only with NO risk cutoffs
    # (its Tier-3 methodology note records why), and this seed is the charter's recorded
    # "revisit only with a true hs-CRP assay" condition finally being met. Up-direction
    # (higher = a higher risk category). 1 inclusive (>=1 enters 'average'), 3 exclusive
    # (>3 enters 'high'), matching <1 / 1–3 / >3. Definitions name the framework's OWN
    # category labels, never the user's value; the gridline label stays "AHA/CDC 1" /
    # "AHA/CDC 3". Unit mg/L (the tertiles are defined in mg/L). Attaches to a metric
    # named EXACTLY "C-Reactive Protein High Sensitivity".
    "C-Reactive Protein High Sensitivity": {"thresholds": [
        {"cutoff": 1, "source": "AHA/CDC", "direction": "up", "boundary": "inclusive",
         "definition": "Defines the boundary at or above which the AHA/CDC hs-CRP "
                       "framework places a value in its 'average' relative-"
                       "cardiovascular-risk category rather than 'low' (the framework's "
                       "categories are <1 mg/L low, 1–3 mg/L average, >3 mg/L high; "
                       "Pearson et al. 2003)."},
        {"cutoff": 3, "source": "AHA/CDC", "direction": "up", "boundary": "exclusive",
         "definition": "Defines the boundary above which the AHA/CDC hs-CRP framework "
                       "places a value in its 'high' relative-cardiovascular-risk "
                       "category (>3 mg/L) rather than 'average'."},
    ],
        "methodology_note": "A high-sensitivity CRP assay, distinct from the standard "
                            "CRP tracked as a separate metric. The AHA/CDC framework "
                            "treats a value above ~10 mg/L as likely transient rather "
                            "than a stable baseline and recommends repeat testing — "
                            "averaging two measurements taken at least 2 weeks apart — "
                            "to establish one. (The 2019 ACC/AHA cholesterol guideline "
                            "separately treats hs-CRP >=2.0 mg/L as a risk-enhancing "
                            "factor; that is a different framework and is not seeded here.)"},
    # Vitamin D 25-Hydroxy — TWO thresholds from two frameworks measuring different
    # things: IOM 20 ng/mL (population-level bone-health adequacy, CURRENT) and the
    # Endocrine Society's 2011 30 ng/mL (clinical sufficiency for at-risk patients).
    # The 30 cutoff is a "substantively retired" citation (see CLAUDE.md curation note):
    # the Endocrine Society's 2024 guideline WITHDREW these category thresholds, so the
    # definition states that in past/present tense. Targets the TOTAL 25-OH metric, not
    # the D2/D3 fractions. Stored unit ng/mL (20 = 50 nmol/L, 30 = 75 nmol/L). Labels
    # stay source + cutoff; the retirement nuance lives in the definition prose.
    "Vitamin D 25-Hydroxy": {"thresholds": [
        {"cutoff": 20, "source": "IOM", "direction": "down", "boundary": "exclusive",
         "definition": "Defines the serum 25(OH)D level (50 nmol/L) at or above which "
                       "the Institute of Medicine considers vitamin D adequate for bone "
                       "health across the general population — a population-level adequacy "
                       "threshold derived from bone-health outcomes, not a clinical target "
                       "for an individual."},
        {"cutoff": 30, "source": "Endocrine Society", "direction": "down", "boundary": "exclusive",
         "status_note": "substantively retired",
         "definition": "Defines the level (75 nmol/L) at or above which the 2011 Endocrine "
                       "Society guideline classified vitamin D as 'sufficient' for at-risk "
                       "patients in clinical care (labeling 20–29 ng/mL 'insufficient') — a "
                       "more stringent standard than IOM's population-level adequacy "
                       "threshold. The Endocrine Society's 2024 guideline retired these "
                       "category thresholds and declined to endorse any specific 25(OH)D "
                       "threshold for sufficiency or deficiency."},
    ]},
    # Testosterone Total by LC-MS/MS — AUA single cutoff 300 ng/dL (web-verified;
    # 2018 guideline, "Reviewed and Validity Confirmed 2024" — a living/reaffirmed
    # citation, see CLAUDE.md taxonomy). The definition SURFACES AUA's two-early-
    # morning-draws protocol caveat: AUA grades that protocol higher (Strong/Grade A)
    # than the bare cutoff (Moderate/Grade B), so a single non-morning reading below
    # 300 isn't diagnostic on its own. Stored unit ng/dL (no nmol/L conversion).
    # SEX-GATED (#18 Phase 2): sex="male" — AUA's cutoff is a male reference framework,
    # so the line shows/flags ONLY for a male profile and is hidden for female/other/
    # null (where a male cutoff can't be confirmed to apply). This is the first curated
    # sex-variant; gating is more honest than the previous show-regardless-with-a-prose-
    # caveat. The definition's "in adult men" still names AUA's framework (framework-as-
    # subject) — accurate, now structurally enforced rather than prose-only.
    "Testosterone Total by LC-MS/MS": {"thresholds": [
        {"cutoff": 300, "source": "AUA", "direction": "down", "boundary": "inclusive",
         "status_note": "caveated", "sex": "male",
         "definition": "Defines the threshold at or below which AUA evaluates "
                       "testosterone as potentially low in adult men, per its 2018 "
                       "guideline (reaffirmed 2024). AUA's diagnostic framework requires "
                       "two separate early-morning measurements — testosterone varies "
                       "through the day (morning levels are highest) and between draws — "
                       "so a single non-morning reading is not diagnostic on its own."},
    ],
        "methodology_note": "Depends on SHBG (sex hormone-binding globulin); free "
                            "testosterone is the more direct bioavailable measure. See "
                            "the threshold note for the single-morning-draw caveat."},
    # Glucose Serum/Plasma — ADA random/symptomatic diabetes-diagnosis criterion
    # (≥200 mg/dL with classic symptoms or hyperglycemic crisis), Standards of Care
    # 2026 §2. FASTING-INDEPENDENT, so it applies regardless of draw state — distinct
    # from the fasting 100/126 cutoffs, which stay deliberately UNSEEDED (fasting state
    # isn't certifiable from stored draws; see CLAUDE.md "Threshold curation discipline").
    "Glucose Serum/Plasma": {"thresholds": [
        {"cutoff": 200, "source": "ADA", "direction": "up", "boundary": "inclusive",
         "definition": "Defines the level at or above which a random (non-fasting) "
                       "plasma glucose, with classic symptoms of hyperglycemia or "
                       "hyperglycemic crisis, meets the ADA criterion for diagnosing "
                       "diabetes. This is the symptomatic/random line; it does not "
                       "depend on fasting state. (The fasting 100/126 cutoffs remain "
                       "deliberately unseeded — fasting state isn't certifiable from "
                       "stored draws.)"},
    ],
        "methodology_note": "Interpretation depends on fasting state. The seeded ≥200 "
                            "line is the random/symptomatic threshold; fasting-specific "
                            "cutoffs (100/126) are deliberately unseeded since fasting "
                            "state isn't certifiable from stored draws."},
    # Ferritin Serum/Plasma — single low (iron-deficiency) line at 30 ng/mL: the
    # unified sex-independent lower limit increasingly adopted over older, lower
    # sex-specific cutoffs. SOFT source tag (ASH): the "30 unified" basis is mainly
    # Pasricha et al. (Lancet 2021) + lab adoption (ASH's draft is sub-population-
    # specific — see SOURCES["ASH"]). The iron-OVERLOAD upper bound is intentionally
    # omitted (that's where the sex split lived). Down-direction: low is concerning.
    "Ferritin Serum/Plasma": {"thresholds": [
        {"cutoff": 30, "source": "ASH", "direction": "down", "boundary": "exclusive",
         "status_note": "soft-source",
         "definition": "Defines the level below which serum ferritin indicates iron "
                       "deficiency, using the unified sex-independent threshold "
                       "increasingly adopted in place of older, lower sex-specific "
                       "limits. Iron deficiency can be present at this level without "
                       "anemia."},
    ]},
    # Hemoglobin — WHO's sex-specific anaemia cutoffs (#18 Phase 2; the first SEX-VARIANT
    # threshold where the CUTOFF VALUE differs by sex, not just visibility): <13.0 g/dL
    # adult men, <12.0 g/dL non-pregnant women (130/120 g/L). REAFFIRMED by WHO's 2024
    # guideline (living/reaffirmed, category b — see SOURCES["WHO"]). Down-direction
    # (low = anaemia); boundary EXCLUSIVE (WHO defines anaemia as BELOW the cutoff, so
    # a reading exactly at 13.0/12.0 is not anaemic). Each line is SEX-TAGGED: a male
    # profile sees the 13.0 line, a female the 12.0, and a null/'other' profile sees
    # NEITHER (WHO's cutoff is inherently sex-specific and can't be picked without sex).
    # The female line is the NON-PREGNANT cutoff (no pregnancy field; the definition
    # says so). Framework-as-subject, naming WHO's own anaemia classification — same
    # latitude as the ADA-diabetes / ASH-iron-deficiency seeds — a population-level
    # threshold, not an individual diagnosis. Hemoglobin already carries rcv_cv (merged
    # in by the RCV injection loop's setdefault, like TSH holds thresholds + rcv_cv).
    # Hematocrit is NOT seeded: WHO defines anaemia by haemoglobin, not Hct (no single-
    # authority Hct cutoff; the ~39/36% figures are derived ≈3×Hgb).
    "Hemoglobin": {"thresholds": [
        {"cutoff": 13.0, "source": "WHO", "direction": "down", "boundary": "exclusive",
         "sex": "male",
         "definition": "Defines the haemoglobin concentration below which WHO classifies "
                       "anaemia in adult men (130 g/L), reaffirmed in WHO's 2024 "
                       "haemoglobin-cutoffs guideline. A population-level threshold for "
                       "assessing anaemia, not an individual clinical diagnosis."},
        {"cutoff": 12.0, "source": "WHO", "direction": "down", "boundary": "exclusive",
         "sex": "female",
         "definition": "Defines the haemoglobin concentration below which WHO classifies "
                       "anaemia in non-pregnant adult women (120 g/L), reaffirmed in WHO's "
                       "2024 haemoglobin-cutoffs guideline. Pregnancy uses different WHO "
                       "cutoffs (not modelled here). A population-level threshold, not an "
                       "individual clinical diagnosis."},
    ]},
    # TSH — three graded AACE/ATA reference lines. 0.4 (low edge, hyperthyroid
    # direction) and 4.5 (high edge → subclinical hypothyroid) bracket the reference
    # range; 10 is the well-anchored overt-hypothyroid line. The 4.5 upper edge is
    # CONTESTED (proposed limits ~4.0–4.5, some argue lower) and free-T4-dependent —
    # flagged in prose pending #15's solid/dashed (confidence) encoding. Framework-as-
    # subject: these name AACE/ATA's reference-range structure, never a diagnosis.
    "TSH": {"thresholds": [
        {"cutoff": 0.4, "source": "AACE/ATA", "direction": "down", "boundary": "exclusive",
         "definition": "Lower limit of the reference range; values below point toward "
                       "thyroid overactivity (hyperthyroid direction) and warrant "
                       "correlation with free T4."},
        {"cutoff": 4.5, "source": "AACE/ATA", "direction": "up", "boundary": "inclusive",
         "render_style": "dashed", "status_note": "contested",
         "definition": "Upper limit of the reference range; values above are commonly "
                       "classified as subclinical hypothyroidism. This boundary is "
                       "debated (proposed limits span ~4.0–4.5, some argue lower) and "
                       "depends on free T4 — a soft, contested line."},
        {"cutoff": 10, "source": "AACE/ATA", "direction": "up", "boundary": "inclusive",
         "definition": "At or above this level, an elevated TSH with low free T4 "
                       "characterizes overt hypothyroidism. Well-anchored and far less "
                       "contested than the reference-range edge."},
    ]},
    # Calcium Corrected — the first DERIVED metric's thresholds (#6 Phase 2). Seeding
    # a virtual metric works through the normal path: set_metric_config mints a
    # config-only `metrics` row (no observations), which stays out of every
    # observation-backed list — verified benign. Four lines across two directions
    # (one low, three high — same mixed-direction shape as TSH). Both frameworks are
    # MANAGEMENT/treatment guidelines, not general-population diagnostic floors, so all
    # four carry status_note="caveated" and framework-as-subject prose says so. The low
    # line's boundary is "exclusive" as the safe default (per the eGFR precedent — the
    # guideline says "below 8.0", so exact 8.0 isn't itself the trigger); the high lines
    # are inclusive band-entries except >14 (strict) -> "exclusive". NOTE: with data
    # near ~9.7, the 10/12/14 lines all sit far above and trip the domain cap, clamping
    # to the top edge together — a rail-collision the current ThresholdRail doesn't yet
    # stagger (logged as a ROADMAP follow-up; not a seeding blocker).
    "Calcium Corrected": {"thresholds": [
        {"cutoff": 8.0, "source": "ESE", "direction": "down", "boundary": "exclusive",
         "status_note": "caveated",
         "definition": "Below this, the ESE hypoparathyroidism guideline recommends "
                       "considering treatment for symptomatic hypocalcemia — a "
                       "management threshold, not a general-population diagnostic floor."},
        {"cutoff": 10, "source": "Endocrine Society (2023)", "direction": "up",
         "boundary": "inclusive", "status_note": "caveated",
         "definition": "Defines the boundary of mild hypercalcemia per the Endocrine "
                       "Society's hypercalcemia-of-malignancy guideline — a malignancy-"
                       "context severity grading, applied here as a general reference; "
                       "treat as caveated rather than a universal diagnostic cutoff."},
        {"cutoff": 12, "source": "Endocrine Society (2023)", "direction": "up",
         "boundary": "inclusive", "status_note": "caveated",
         "definition": "Defines the boundary between mild and moderate hypercalcemia "
                       "per the Endocrine Society's hypercalcemia-of-malignancy guideline "
                       "— a malignancy-context severity grading, applied here as a "
                       "general reference; treat as caveated rather than a universal "
                       "diagnostic cutoff."},
        {"cutoff": 14, "source": "Endocrine Society (2023)", "direction": "up",
         "boundary": "exclusive", "status_note": "caveated",
         "definition": "Above this, the Endocrine Society's hypercalcemia-of-malignancy "
                       "guideline classifies severe hypercalcemia — a malignancy-context "
                       "severity grading, applied here as a general reference; treat as "
                       "caveated rather than a universal diagnostic cutoff."},
    ]},
    # Methodology notes (#9, Tier 1) — DISPLAY-ONLY per-metric prose for metrics
    # whose interpretation depends on another. These carry NO thresholds by design:
    # BUN and Creatinine were deliberate seed-skips (no single-authority / no sex-aware
    # cutoff — see CLAUDE.md "Threshold curation discipline"), and Calcium moved to the
    # derived Calcium Corrected metric (#6). The note is the graceful home for that
    # deferral — it says "read alongside X" instead of silently omitting the metric.
    # methodology_note is display_only in CONFIG, so it seeds/stores through the normal
    # path but never reaches the engine. Prose is descriptive / method-as-subject and
    # non-diagnostic — the same surface-don't-diagnose boundary as threshold definitions.
    "Blood Urea Nitrogen": {
        "methodology_note": "Context-only; interpret with creatinine and the "
                            "BUN:Creatinine ratio. Not independently flagged.",
    },
    "Creatinine Serum/Plasma": {
        "methodology_note": "Read alongside eGFR; level depends on sex and muscle "
                            "mass, not renal function alone.",
    },
    "Calcium Serum/Plasma": {
        "methodology_note": "Interpret with albumin; corrected calcium is derived "
                            "(see Calcium Corrected). Ionized calcium is the "
                            "gold-standard measure this approximates.",
    },
    # Methodology notes (#9, Tier 3) — the "context-only metric" category (see
    # CLAUDE.md "Threshold curation discipline"): isolated values that mislead
    # without the rest of their panel. Three clusters: iron studies, the LFT panel,
    # and standard (non-hs) CRP. All note-only (no thresholds). Names are the DB's
    # stored names (e.g. "Unsat. Iron Binding Capacity", "Alanine Aminotransferase",
    # "Aspartate Aminotransferase", "Alkaline Phosphatase Total"), not the common
    # abbreviations. Prose stays descriptive / method-as-subject — how to read the
    # panel, not what the user's value means.
    # --- Iron studies cluster ---
    "Iron Serum/Plasma": {
        "methodology_note": "Fluctuates with diurnal rhythm and recent dietary "
                            "intake; interpret alongside TIBC, transferrin "
                            "saturation, and ferritin rather than in isolation.",
    },
    "Total Iron Binding Capacity": {
        "methodology_note": "Reflects transferrin's iron-carrying capacity; read "
                            "alongside serum iron and % saturation, not as a "
                            "standalone value.",
    },
    "Iron % Saturation": {
        "methodology_note": "Calculated from iron and TIBC; the most direct single "
                            "indicator of iron status in this panel, but still read "
                            "alongside ferritin for storage status.",
    },
    "Transferrin": {
        "methodology_note": "The carrier protein TIBC estimates; largely redundant "
                            "with TIBC when both are drawn — interpret together, not "
                            "as independent signals.",
    },
    "Transferrin Percent": {
        "methodology_note": "Same measure as Iron % Saturation, reported via "
                            "transferrin directly rather than via TIBC; read the two "
                            "as equivalent, not additive evidence.",
    },
    "Unsat. Iron Binding Capacity": {
        "methodology_note": "The unbound portion of TIBC (TIBC − serum iron); read "
                            "as part of the same panel, not independently.",
    },
    # --- LFT panel ---
    "Alkaline Phosphatase Total": {
        "methodology_note": "Elevated by liver, bone, and placental sources alike; "
                            "interpret alongside GGT (to localize to liver) and the "
                            "rest of the panel, not alone.",
    },
    "Alanine Aminotransferase": {
        "methodology_note": "More liver-specific than AST; read the ALT:AST ratio "
                            "and trend together rather than either value in "
                            "isolation.",
    },
    "Aspartate Aminotransferase": {
        "methodology_note": "Comes from both liver and muscle tissue; read alongside "
                            "ALT (more liver-specific) and CK to see which source the "
                            "pattern fits, not in isolation.",
    },
    "Bilirubin Total": {
        "methodology_note": "Read alongside the direct/indirect split; the total "
                            "alone doesn't localize the pattern — the fractionation "
                            "is what distinguishes it.",
    },
    "Bilirubin Direct": {
        "methodology_note": "The conjugated (direct) fraction is read against the "
                            "indirect fraction and total — the split is what "
                            "localizes the pattern; the direct value alone doesn't. "
                            "Not interpreted in isolation.",
    },
    "Bilirubin Indirect": {
        "methodology_note": "The unconjugated (indirect) fraction is read against the "
                            "direct fraction and total — the split is what localizes "
                            "the pattern; the indirect value alone doesn't. Not "
                            "interpreted in isolation.",
    },
    # --- CRP (standard, not hs-CRP) ---
    "C-Reactive Protein": {
        "methodology_note": "This is the standard assay, not high-sensitivity CRP "
                            "(hs-CRP); no cardiovascular-risk cutoffs are seeded here "
                            "since those require the hs-CRP assay specifically.",
    },
}


# --- RCV (Reference Change Value) coefficients — #7 RCV curation arc ----------
# Within-subject biological-variation CV_I (PERCENT) per metric, web-verified
# against BIVAC grade-A sources: the EuBIVAS summary (Carobene et al., Clin Chem
# Lab Med 2021 — chemistry/endocrine) and the EuBIVAS-protocol CBC study (Coşkun
# et al., Clin Chem Lab Med 2018 — hematology). ONE CV_I per metric — the
# reviewed, approved table. The analytical CV is DERIVED as 0.5 × CV_I (the
# desirable-specification convention: what a well-performing lab should achieve,
# applied uniformly since a given lab's own analytical CV is unobtainable). Both
# are stored as FRACTIONS in the rcv_cv dict ({"analytical", "intra"}), which
# analyze_series splats into rcv_delta to enable Reference-Change-Value detection
# (a jump beyond combined analytical + biological noise). The engine is unchanged
# — this is pure curated data, exactly like the threshold seeds. The detector was
# pinned by tests BEFORE any of this was seeded (see tests/test_rcv_delta.py).
#
# DELIBERATELY NOT SEEDED (full rationale in ROADMAP.md #7's RCV curation arc):
#   • Sodium / Chloride — CV_I (0.53% / 0.98%) is below achievable analytical
#     precision, so RCV would flag measurement noise, not physiology. HELD.
#   • Ferritin / Urea (BUN) / bicarbonate (CO2) / RDW-CV — no BIVAC grade-A
#     source (RDW-CV: the source reports the distinct RDW-SD). DEFERRED.
#   • Any metric with <5 numeric readings (iron studies, Vit D/B12, T4 Free, …)
#     — below the data floor; its CV_I is the same whenever added later.
# _RCV_CVI_PERCENT below holds the sex-INDEPENDENT metrics (one CV_I for everyone).
# The three leukocyte params whose within-subject CV_I differs significantly by sex —
# WBC, monocytes, neutrophils — moved to _RCV_CVI_PERCENT_BY_SEX (#18 Phase 2, sex-
# keyed). Their CV_I was VERIFIED directly from the primary source's Table 2 (Coşkun
# 2018, read from the PDF, 2026-07-14): the old flat values (7.96/11.08/11.60) were
# the MALE column all along — mislabeled "sex-pooled" — so this refinement KEEPS male,
# ADDS the female band, and corrects monocytes (11.08 -> 11.07). Lymphocytes stay flat
# here (its CV_I does NOT differ by sex per the same table, combined 9.81 ≈ seeded 9.82).
_RCV_CVI_PERCENT: dict[str, float] = {
    # Hematology (Coşkun 2018, n=30, BIVAC-compliant)
    "Hemoglobin": 2.74,
    "Hematocrit": 2.82,
    "Red Blood Cell Count": 2.77,
    "Mean Corpuscular Hemoglobin Concentration": 0.97,
    "Mean Corpuscular Hemoglobin": 0.75,
    "Mean Corpuscular Volume": 0.72,
    "Platelet Count": 7.22,
    "Lymphocyte Absolute": 9.82,  # sex-independent CV_I (WBC/monocytes/neutrophils -> by-sex)
    # Chemistry / endocrine (EuBIVAS summary, n≈85–91, BIVAC grade A)
    "Calcium Serum/Plasma": 1.81,
    "Albumin": 2.5,
    "Protein Total Serum/Plasma": 2.6,
    "Potassium Serum/Plasma": 3.92,
    "Creatinine Serum/Plasma": 4.4,
    "Alkaline Phosphatase Total": 5.3,
    "Alanine Aminotransferase": 9.3,
    "Aspartate Aminotransferase": 9.5,
    "TSH": 18.9,
    "Bilirubin Total": 20.9,
}

# Inject rcv_cv into SEED — setdefault MERGES with any existing entry (TSH keeps
# its thresholds; Creatinine/Calcium/the LFTs keep their methodology notes) and
# mints a fresh SEED entry for a metric that had none. Stored as fractions, with
# the analytical CV as the desirable-spec 0.5 × CV_I.
for _metric, _cvi in _RCV_CVI_PERCENT.items():
    SEED.setdefault(_metric, {})["rcv_cv"] = {
        "analytical": round(_cvi / 200, 6),
        "intra": round(_cvi / 100, 6),
    }

# Sex-KEYED CV_I (#18 Phase 2) — the three leukocyte params with a significant sex
# difference in within-subject BV. Values read DIRECTLY from Coşkun 2018 Table 2 (the
# CVI column, male & female). No "default" key: for a null/'other' profile the noise
# band genuinely can't be picked, so rcv_delta is OMITTED there (defer-don't-fudge) —
# a male profile gets the male band, a female profile the female band. The engine still
# receives a plain {analytical, intra} dict (resolved by _resolve_rcv_cv); it never
# learns sex. See ROADMAP #18 Phase 2 and CLAUDE.md's Profile Exception 2.
_RCV_CVI_PERCENT_BY_SEX: dict[str, dict[str, float]] = {
    "White Blood Cell Count": {"male": 7.96, "female": 12.82},
    "Monocytes Absolute": {"male": 11.07, "female": 15.33},
    "Neutrophils Absolute": {"male": 11.60, "female": 20.09},
}

for _metric, _by_sex in _RCV_CVI_PERCENT_BY_SEX.items():
    SEED.setdefault(_metric, {})["rcv_cv"] = {
        _sex: {"analytical": round(_cvi / 200, 6), "intra": round(_cvi / 100, 6)}
        for _sex, _cvi in _by_sex.items()
    }


# --- #18 sex-aware detection: resolve which curated numbers apply to a profile's
# biological sex. The CROSSING of profile data into detection is confined to these
# helpers + the resolvers below; the engine still receives only plain thresholds/
# rcv_cv and never learns sex (see CLAUDE.md's Profile charter exception). sex never
# leaves the machine — this is an INTERNAL analysis boundary, not a privacy-egress one.

def _sex_applies(line_sex: str | None, profile_sex: str | None) -> bool:
    """A threshold/variant tagged for a specific sex applies ONLY when the profile
    sex matches; an untagged line (line_sex None) applies to everyone. So a null or
    'other' profile sex sees ONLY untagged lines — a sex-specific number can't be
    confirmed to apply, which is exactly today's behavior (no line is sex-tagged
    yet)."""
    return line_sex is None or line_sex == profile_sex


def _resolve_rcv_cv(val: object, sex: str | None) -> object | None:
    """Resolve a stored rcv_cv value to the flat {analytical, intra} the engine wants.
    BACKWARD-COMPATIBLE: a flat dict (today's shape — has 'analytical'/'intra')
    applies to everyone and passes through unchanged. A sex-keyed dict
    ({'male': {...}, 'female': {...}, 'default': {...}}) picks the profile sex's
    entry, else 'default'; if neither matches, returns None so the kwarg is OMITTED
    (no rcv_delta) rather than guessing a sex's noise band."""
    if not isinstance(val, dict):
        return val
    if "analytical" in val or "intra" in val:
        return val  # flat — applies to all
    if sex is not None and sex in val:
        return val[sex]
    return val.get("default")


def _profile_sex(conn) -> str | None:
    """The profile's biological sex ('male'|'female'|'other') or None if unset. The
    ONE profile field that enters detection (#18). Read here, inside the config layer,
    so the four detection call sites and /chart-config stay unchanged — they already
    pass conn, and the engine still never sees sex."""
    return (db.get_profile(conn) or {}).get("sex")


def _cast_raw(raw_by_key: dict[str, str], sex: str | None = None) -> dict:
    """Cast one metric's raw {key: text} rows into a typed config dict, skipping
    any key not in the registry and any value that won't parse — a malformed
    stored value must never break detection (same resilience as settings.resolve,
    which falls back rather than raising).

    `sex` selects sex-variant config (#18): sex-tagged thresholds are filtered to
    the matching sex (then the tag is stripped so the engine shape is byte-identical),
    and a sex-keyed rcv_cv is resolved to its matching entry. sex None (the default,
    and the null/'other'-profile case) reproduces today's behavior exactly."""
    out: dict = {}
    for key, raw in raw_by_key.items():
        d = BY_KEY.get(key)
        # Skip unregistered keys AND display-only ones: this dict is splatted as
        # **kwargs into analyze_series, so a display-only key (methodology_note)
        # must never appear here or the engine gets an unexpected kwarg. Its value
        # is surfaced by a dedicated reader (get_methodology_note) instead.
        if d is None or d.display_only:
            continue
        try:
            value = d.cast(raw)
        except (TypeError, ValueError):  # json.JSONDecodeError is a ValueError
            continue
        if key == "thresholds":
            # Filter sex-tagged lines to the profile sex, then STRIP the sex tag so
            # the engine dict is exactly {cutoff, source, direction, boundary} as before.
            value = [{k: v for k, v in t.items() if k != "sex"}
                     for t in value if _sex_applies(t.get("sex"), sex)]
        elif key == "rcv_cv":
            value = _resolve_rcv_cv(value, sex)
            if value is None:
                continue  # no matching sex-variant and no default -> omit the kwarg
        out[key] = value
    return out


def get_config(conn, metric: str) -> dict:
    """All recognized detector config for `metric` as a typed dict, e.g.
    {"thresholds": [[5.7, "ADA"], [6.5, "ADA"]]}. Empty dict if the metric has no
    rows — the engine handles that exactly like the old METRIC_CONFIG.get(metric,
    {}). Intended to be splatted: analyze_series(metric, series, **get_config(...)).

    Sex-aware (#18): reads the profile sex from `conn` and resolves sex-variant
    config accordingly. A metric with no sex-variants (every metric today) resolves
    identically regardless of sex."""
    return _cast_raw(db.get_metric_config(conn, metric), _profile_sex(conn))


def all_configs(conn) -> dict[str, dict]:
    """Every metric's typed config as {metric: config_dict}, in one pass. Mirrors
    get_config per metric; metrics with no rows are simply absent (so a caller's
    `.get(metric, {})` falls back to {}, unchanged). Used to hand the timeline
    builder a plain snapshot, keeping it a pure function of its inputs.

    Sex-aware (#18): resolves the profile sex ONCE and applies it to every metric's
    config (one profile read for the whole pass, not per-metric)."""
    sex = _profile_sex(conn)
    return {m: _cast_raw(raw, sex) for m, raw in db.list_all_metric_config(conn).items()}


def get_thresholds_detailed(conn, metric: str) -> list[dict]:
    """A metric's thresholds as RICH dicts {cutoff, source, definition, render_style,
    status_note} — for the chart-config endpoint / the Reference-thresholds UI.
    `render_style` ('solid'|'dashed', default 'solid') is presentational; `status_note`
    (a closed line-confidence label, default None) is explanatory — DISPLAY-only fields
    the engine never reads (get_config / _threshold_pairs ignore them by construction).
    Parses both the new structured shape and the obsolete [cutoff, source] shape (no
    definition -> ''; the display fields default). Empty list if none. SEPARATE from
    get_config (which returns the engine-shape pairs): one stored value, two readers —
    engine vs display.

    Sex-aware (#18): a sex-tagged line is shown only when it matches the profile sex
    (same filter the engine reader uses), so a gated line is hidden from the chart for
    the non-matching sex rather than shown-regardless-with-a-caveat. Untagged lines
    (every line today) show for everyone, so this is a no-op until a variant is seeded."""
    raw = db.get_metric_config(conn, metric).get("thresholds")
    if raw is None:
        return []
    try:
        data = json.loads(raw)
    except (TypeError, ValueError):
        return []
    sex = _profile_sex(conn)
    out: list[dict] = []
    for item in data:
        if isinstance(item, dict):
            if not _sex_applies(item.get("sex"), sex):
                continue
            out.append({"cutoff": item.get("cutoff"), "source": item.get("source"),
                        "definition": item.get("definition", ""),
                        "render_style": item.get("render_style", "solid"),
                        "status_note": item.get("status_note")})
        else:
            out.append({"cutoff": item[0], "source": item[1], "definition": "",
                        "render_style": "solid", "status_note": None})
    return out


def get_methodology_note(conn, metric: str) -> str | None:
    """A metric's DISPLAY-ONLY methodology note (#9), or None if it has none.

    Curated per-metric prose for a metric whose interpretation depends on another
    (e.g. BUN → "interpret with creatinine"), or that is a computed approximation,
    or is state-/method-dependent. Reads the stored value RAW (like
    get_thresholds_detailed bypasses _cast_raw) — the note is stored as bare TEXT,
    so it's returned as-is. DISPLAY-only: this is descriptive, never a detection
    input, and the engine never sees it (methodology_note is display_only in CONFIG,
    so get_config filters it out of the analyze_series splat)."""
    return db.get_metric_config(conn, metric).get("methodology_note")


def seed_defaults(conn) -> None:
    """Re-seed every metric in SEED on every lifespan startup (blunt REPLACE).

    The SEED dict is the SOURCE OF TRUTH; the metric_config table is a runtime
    CACHE of it. On every startup, any metric in SEED gets its row replaced (via
    set_metric_config's UPSERT) — so editing the SEED (a cutoff, a source, a
    definition's wording) and restarting is all it takes for the table to reflect
    it. Metrics NOT in SEED are untouched.

    Trade-off (recorded deliberately): there's no edit UI today, so "the SEED
    wins" is the simplest predictable semantic. When an edit UI is built, this
    logic will need to distinguish seeded-from-curation rows (safe to overwrite)
    from edited-by-user rows (must NOT be clobbered) — e.g. via a provenance flag.
    Until then, blunt re-seed is intentional."""
    for metric, cfg in SEED.items():
        # The SEED dict key is the IMMUTABLE seed_key. Resolve it to the metric's
        # CURRENT display name so a renamed metric is re-seeded under its live name
        # (not the stale SEED-literal), leaving no orphan config row. Falls back to
        # the literal key for an unlinked seed_key (defensive — all 9 resolve today).
        name = db.resolve_by_seed_key(conn, metric) or metric
        for key, value in cfg.items():
            db.set_metric_config(conn, name, key, BY_KEY[key].dump(value),
                                 seed_keys=SEED.keys())
