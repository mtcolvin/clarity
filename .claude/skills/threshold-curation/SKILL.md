---
name: threshold-curation
description: Verification and curation rules for the guideline cutoffs seeded in metric_config.py — the four citation-status categories, the source + cutoff labelling rule, the context-only metric category, and the record of investigated-and-declined skip decisions. Use when adding, re-verifying, or removing a clinical threshold, or when metric_config.py comments reference the "CLAUDE.md taxonomy" or a "curation note".
---

# Threshold curation discipline

Moved out of the root CLAUDE.md: this is the discipline for ONE task (curating a
guideline cutoff), not something every session needs resident. `metric_config.py`'s
comments reference it by name, so a session working there will find it.

Durable verification + curation rules for the guideline cutoffs seeded in
`metric_config.py` (its comments reference this section as "CLAUDE.md taxonomy",
"curation note", and the creatinine "skip-entry"). This is the *stable
discipline*; the forward "curate metric X next" work lives in `ROADMAP.md` (#8).

Each seeded cutoff keeps the analysis-safety discipline: the gridline label is
**source + cutoff only** (e.g. `KDIGO 60`), **never a condition label**, and the
`definition` names the source's OWN framework vocabulary (see the analysis-safety
clarification above), never an interpretation of the user's reading.

**Citation status — four categories (not all "current"/"stale" citations are equal).**
Verification places each curated cutoff into one:
- (a) *living/current* — the issuing document stands and hasn't been re-checked.
- (b) *living/reaffirmed* — the issuing body recently and explicitly revalidated it
  (the **strongest** status; e.g. AUA's 2018 testosterone guideline, "Reviewed and
  Validity Confirmed 2024"; and WHO's 2024 haemoglobin-cutoffs guideline, which
  explicitly RETAINED the adult anaemia cutoffs 130/120 g/L after considering a
  higher male cutoff — the Hemoglobin sex-variant seed).
- (c) *stale-but-correct* — the document was superseded but the threshold value is
  retained (the LDL 2018→2026 case).
- (d) *substantively retired* — the issuing body withdrew the threshold itself (the
  Endocrine Society's 30 ng/mL vitamin D case — its 2024 guideline retired the
  category thresholds outright).
- (e) *living/current per secondary verification* (cross-cutting) — the document is
  current and retention is verified by multiple independent non-blocked sources
  (typically including co-authoring bodies of the guideline), but the primary text
  wasn't read directly because tooling is blocked. Acceptable when the secondaries
  include co-authors; less acceptable when they are only tertiary summaries. This is
  the norm for cardiovascular sources (ACC, AHA, ACC/AHA Multisociety) that are
  routinely Cloudflare-blocked to automated tooling (the LDL 190 / 2026 ACC/AHA
  Dyslipidemia case). The definition prose must reflect the category (name a
  reaffirmation year, or state a withdrawal), framework-as-subject throughout.

**SOURCES shape note.** Keep the per-source registry single-url. Do NOT add a
`retirement_url` field until a SECOND substantively-retired case justifies
generalizing the shape (today only the Endocrine Society vitamin-D case; its 2024
retirement is named in the threshold definition prose, not a structured field).

**Context-only metric category.** Some metrics have NO robust single-authority
threshold to seed — and never will, because an isolated value doesn't resolve on
its own (a high BUN can be GI bleed + dehydration with healthy kidneys). These are
"context-only": CHARTED and given a per-metric methodology note (#9) that points at
what to read them alongside, but NEVER flagged by a threshold. This is a recognized
category, not a gap — the note is the graceful home for the deferral. It recurs
(electrolytes, LFTs, iron studies — see `ROADMAP.md` #9 Tier 3). DISTINCT from a
skip-decision (below): a skip-decision declines a threshold that COULD exist for a
specific reason; a context-only metric has no single-authority threshold to decline.

**Skip-decisions — investigated, declined (NOT forgotten):**
- **Glucose Serum/Plasma — fasting 100/126** — ADA 100/126 are *fasting-specific*
  (random/non-fasting glucose uses different cutoffs); individual draws' fasting
  state couldn't be confirmed, so seeding would misapply to non-fasting readings.
  Distinct from the casual `≥200` line now seeded (see `ROADMAP.md` #8) — different
  lines, not a reversal. Revisit if draw protocols are documented or readings are
  fasting-flagged.
- **C-Reactive Protein** — investigated as hs-CRP (AHA/CDC 1/3 mg/L tertiles); four
  signals (the censored `<5` floor, the 0–10 mg/L acute-phase reference range, the
  plain "C-Reactive Protein" name, both values being `<5`) confirm a *standard*
  (low-sensitivity) assay, which has no recognized chronic-disease-risk cutoffs.
  The STANDARD `C-Reactive Protein` metric therefore **stays note-only** (no risk
  cutoffs). **REVISIT DONE (2026-07-20):** the user added a true hs-CRP assay, so a
  SEPARATE metric `C-Reactive Protein High Sensitivity` now carries the AHA/CDC
  tertiles `<1 / 1–3 / >3 mg/L` (Pearson et al., Circulation 2003;107:499–511;
  `SOURCES["AHA/CDC"]`, citation-status (c) stale-but-correct — the 2003 values remain
  in common use, primary Cloudflare-blocked, PMC/PubMed secondary-verified). Definitions
  name the framework's own low/average/high relative-risk categories only. The 2019
  ACC/AHA hs-CRP ≥2.0 "risk-enhancer" is a different framework and is deliberately NOT
  seeded (surfaced in the metric's methodology note instead).
- **Creatinine Serum/Plasma** — no fixed guideline cutoff (its range is sex/
  muscle-mass dependent and the detector has no sex field to vary a cutoff on). Its
  kidney-function signal is covered by the eGFR/KDIGO entry (age/sex-normalized).
  Revisit only if a sex-aware threshold mechanism is added, or raw creatinine must
  surface independently of eGFR.
- **BUN (Blood Urea Nitrogen)** — context-only; no robust single-authority threshold
  (a high BUN can be GI bleed + dehydration with healthy kidneys — no value resolves
  on its own). Charted, never flagged; gets a methodology note, not a threshold. The
  signal is now recovered as the derived BUN:Cr ratio (`derived.py`, #6 — DONE;
  a dimensionless computed metric that replaced the formerly-stored one).
