# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## What this is

A local, single-user app for tracking personal labs/vitals and surfacing what stands out. A Phase 1–2 Python backend (flat modules at the repo root) plus a FastAPI transport layer and a view-only React + Recharts dashboard in `frontend/`.

## Privacy, safety & data protection — project prime directive

Privacy, safety, and data protection are the #1 priority in this project,
ahead of features, convenience, and performance. This data is the user's
personal medical history. When any decision trades privacy against another
goal, privacy wins unless the user explicitly decides otherwise for that
specific case. When in doubt, choose the more private option and surface the
tradeoff to the user rather than deciding silently.

### Hard rules (never violate)
- NEVER send data to any external service (LLM API or otherwise) without the
  user's explicit, per-action confirmation in the UI.
- NEVER let personally identifying information (name, date of birth, address,
  MRN/record numbers, ordering physician, facility) leave the machine. Redact
  it before any external call — redact as early as possible in the pipeline.
- NEVER write imported or model-derived data to the database without the user
  reviewing and approving it first (review-before-save is mandatory).
- NEVER make a network call to an LLM provider silently or in the background.
  Every external handoff is user-initiated and visible.
- NEVER push, sync, back up, or otherwise place the user's DATA on GitHub or any
  cloud/remote service: `health.db` and its sidecars, `imaging_store/`,
  `imaging_archive/`, `documents_store/`, `gateway_audit.log`, `.sweep/`,
  `.env.local`. These are local-only, permanently and without exception. Every
  one is gitignored; a change that would track any of them is a charter
  violation, and so is a "temporary" copy placed anywhere a sync client can see.
- The CODE is a different question, and the answer CHANGED (2026-09-19, user
  decision). This repository was local-only with no remotes; it is now published
  under AGPL-3.0 on GitHub, and a GitHub Actions workflow deploys the static demo
  to that repo's Pages site. So a remote is now expected, not forbidden.
  **What did not change is which side of the line the data sits on.** Publishing
  the code is a deliberate, reviewed act; publishing anything from the list above
  remains prohibited, and the gitignore is the mechanism that keeps the two apart.
- **Publishing carries a second obligation that the gitignore cannot discharge:
  the user's clinical details leak through PROSE, not through files.** An audit
  before the first push found the identifiers clean — no name, DOB, MRN,
  physician or facility anywhere in the tree or in 337 commits — but found the
  owner's own medical particulars scattered through CLAUDE.md, ROADMAP.md and 20
  commit MESSAGES, as the incidental evidence of real bugs: a metric only a
  specific workup orders, a named vertebral level from a real report, a real
  study date, a real admission. Individually trivial, collectively a partial
  medical history attached to an identifiable GitHub account. So: when writing a
  doc comment or a commit message, cite the SHAPE of the data that caused a bug,
  never the user's actual clinical particulars — "a metric whose name sorts
  first", not the metric; "a vertebral level", not which one. This is the one
  privacy rule with no code enforcing it.
- The deterministic engine (analysis.py) does ALL detection and math. Two halves
  of this stay HARD boundaries, not style choices: a model never COMPUTES a number
  the app presents, and never overrides what the engine FLAGS. Models may narrate
  or extract; and in the clearly-labeled interpretation tier ONLY (see "The
  interpretation tier" under the analysis safety boundary) a model may REASON about
  the engine's own findings and raise data-supported questions — still computing no
  number, still not deciding what the engine flagged.

### Data minimization & the privacy gateway
- All outbound LLM calls route through a single gateway/proxy layer — one
  chokepoint where redaction, provider settings, and logging are enforced, so
  privacy is never reimplemented per-feature.
- The gateway sends the minimum data needed for the task and nothing more.
- When calling a hosted provider, use API-tier access with training disabled
  and the shortest available retention. (Note: true zero-retention is an
  enterprise arrangement; the realistic individual posture is no-training +
  short auto-deletion. Don't claim more than that.)
- Prefer, in order: in-program (no model) > local model > hosted API with
  redaction. Only escalate when the more private option can't do the job, and
  say so.
- Not every hosted task's privacy guarantee has to be redaction-based. A task
  assembled only from non-PII COLUMNS (never the name/DOB/MRN/physician/facility
  columns, never raw imported text) may rest its guarantee on that structural
  cleanliness plus a **faithful, complete, unredacted preview** and per-action
  consent instead. But structural cleanliness is **column-level, not
  content-level**: it guarantees WHICH columns are read, not that the free-text
  CONTENTS of the fields it does read are identifier-free — a parser can inject an
  identifier into an otherwise-safe field (a lab report's practice/department/
  physician header glued onto a metric name — an OBSERVED case, see "The export
  handoff"). So for such a task the **preview is the load-bearing control** — the
  thing that actually catches injected identifier text before it leaves — NOT the
  column choice, and NOT the regex scrub (which catches only known patterns). This
  is a second, deliberate mechanism under the SAME gateway chokepoint and the SAME
  transparency requirements above (show exactly what will be sent, before it
  leaves) — not a loophole around them. See "The export handoff" under Analysis
  safety boundary for the one task that currently uses it.
- PII masking — in the app AND in build/diagnostic tooling — must be
  **allowlist-based**: show only known-safe fields, mask everything else by
  default. Never denylist-based (enumerating PII patterns to strip), which
  inevitably misses cases (a middle-initial name, a credential line). This
  applies to the **assistant's own conversation context** too — tool output is
  sent to the model API, so masking must happen before real user data (e.g. a
  scanned lab PDF) is printed — not just to the app's outbound calls.

### Transparency to the user (always)
- Before any external handoff, show the user (a) that data is about to leave
  the machine, (b) exactly what will be sent, and (c) what was redacted.
- Always label which engine produced a result: in-program/deterministic vs
  local model vs hosted LLM. The user should never have to guess whether a
  model touched their data.
- Wherever the architecture supports multiple options (extraction engine,
  summarizer model, provider), surface that choice in the UI as a visible
  dropdown or clearly labeled placeholder — so the user can see and control
  what is swappable, rather than it being hidden in config.

### When adding any new feature
- State its data-handling posture up front: what data, where it goes, what's
  redacted, which engine.
- Default to the most private viable option; present alternatives as opt-in.
- If a feature can't meet these rules, stop and raise it with the user rather
  than working around them.

## Analysis safety boundary — surface, never diagnose

This app helps the user SEE patterns in their own health data. It must never
cross from surfacing data into rendering medical judgment. This boundary is a
prime directive, like the privacy charter; when a feature could drift across it,
it stops on the safe side.

### Hard rules (never violate)
- The app SURFACES and DESCRIBES; it never DIAGNOSES. It may say a value is out
  of range, trending, unusual for the user, or changed — never what condition
  that indicates, what it's "caused by," or what the user "has." (ONE scoped,
  opt-in exception — a labeled model interpretation tier that reasons over the
  engine's own findings and raises questions — is defined in "The interpretation
  tier" below; it still names no condition and states no cause.)
- No clinical conclusions, risk scores framed as medical assessments, treatment
  suggestions, or medication advice. Computation on the user's numbers is fine;
  interpretation of what those numbers mean for their health is for a clinician.
- Every notable finding is framed as "this stands out — discuss with your
  doctor," never as an answer. The tool sharpens the questions the user brings
  to a professional; it does not replace one. The interpretation tier extends
  this exactly: it turns findings — and data-supported patterns the engine did
  not flag — into specific questions to ask, never answers.
- The deterministic engine computes facts (out of range, slope, z-score,
  delta, what changed). Two model tiers may use them under different licenses:
  the RESTATE tier (narrate.py) may ONLY restate those facts in plain language and
  adds no interpretation; the INTERPRETATION tier (explain.py — see "The
  interpretation tier" below) may reason about them and raise data-supported
  questions. Neither tier computes a number or invents a cause/diagnosis the
  engine did not produce — and the model is never the SOURCE of a number the UI
  presents as authoritative (every shown cutoff/value/statistic renders from code
  beside the model's block).
- Correlation/association between metrics, if ever shown, must be presented as
  "these moved together," never as causation, and never as a clinical inference.
- Cross-metric SYNTHESIS — combining several values into an overall assessment
  ("these together suggest X") — IS diagnosis. It is therefore an explicit,
  deliberate decision, NEVER slid into by default (e.g. because correlation
  plumbing already exists). The descriptive tier (correlation — "these moved
  together") is allowed; the synthesis tier is not, unless the user deliberately
  decides otherwise for a specific case. **The user HAS made that deliberate
  decision for ONE specific case: the export path** (external model, opt-in,
  previewed, per-send consent) — where hedged cross-metric (and single-metric)
  HYPOTHESIS FLOATING is now allowed, framed as possibilities to raise with a
  clinician, no treatment advice (see "Hypothesis floating & multi-metric scope"
  under "The export handoff"). This carve-out is app-vs-external and
  possibility-vs-conclusion: the **APP** never synthesizes into an assessment; the
  external model the user chose to send to may, under consent, float a hedged
  possibility. Everywhere else — every local/deterministic layer — synthesis stays
  forbidden.
- Derived/computed values are HONEST about missing inputs. Where an input a
  derived metric needs is absent for a given draw, the derived value is UNDEFINED
  for that date and the date is OMITTED entirely — never fabricated, and never
  emitted as a null/zero point. The chart connects the points it has, exactly as
  for any metric with irregular draw dates; a same-day-missing input is just "no
  reading," not a special gap (an explicit line-break was considered and rejected
  as over-emphasizing it). Shipped in #6 (corrected calcium; BUN:Cr ratio) —
  BUN:Cr also guards a 0-denominator draw as UNDEFINED (omitted, never a crash).
  Extended (#6, Tier A) to three "reported-but-always-computed" metrics — Bilirubin
  Indirect (Total − Direct), Total Globulin (Total Protein − Albumin), and Non-HDL
  (Total Cholesterol − HDL) — plus A/G Ratio (Albumin ÷ (Total Protein − Albumin) — a
  division that COMPOSES on the stored analytes since the derived Globulin metric has
  no rows to join; computes globulin inline at full precision, `precision=1` like BUN:Cr).
  Each proven faithful (computed == every previously-stored reading, zero mismatch)
  before its stored rows were deleted. Two more computed metrics the lab doesn't print
  were then ADDED (no stored rows superseded): AST/ALT Ratio (De Ritis) and Calculated
  Osmolality (formula disclosed in its caption). **NLR (Neutrophil-Lymphocyte Ratio =
  Neutrophils Abs ÷ Lymphocyte Abs, dimensionless) is a DELIBERATE, DOCUMENTED EXCEPTION
  to the charter's "clinically standard" bar** — mathematically a clean definitional
  identity (safe to compute), but a research/prognostic marker with NO accepted reference
  range that the lab does not report. It is surfaced opt-in and made HONEST by a new
  `advisory` field on `DerivedMetric` (set for NLR ONLY; null for every standard derived
  metric, so the bar stays intact): a warning-level notice, rendered PROMINENTLY (amber
  `.metrics__advisory` box, ⚠ + "Not a standard test.", above the muted caption — not as
  the muted caption) via `MetricInfo.derived_advisory` on `/metrics`, stating it is not a
  standard test and is a personal-trend signal only. NLR carries no reference band and no
  clinical threshold, but the engine's DEFAULT detectors still run over its computed series
  — `trend` (linear/Mann-Kendall) and personal-baseline flags DO fire on a notable
  movement, which is the intended "flag a trend worth eyeballing" behavior and stays
  surface-don't-diagnose (a trend flag describes MOVEMENT, names no condition, judges
  against no normal range — `out_of_range` can't fire without a band, no threshold is
  seeded). The advisory says exactly this ("a flag here means 'look at this change,' not
  'this value is high or low'"). Sibling PLR stays parked. **What CAN be derived is governed by a
  "definition vs convention" rule** (stated in full in ROADMAP.md #6): a UNIVERSAL
  definition (globulin = total protein − albumin everywhere; any pure ratio) is always
  safe; a lab-specific CONVENTION (Anion Gap ±K, LDL Friedewald/Martin-Hopkins, QTc
  Bazett/Fridericia, the iron panel) stays STORED when the lab REPORTS it (deriving would
  contradict the record, and a code formula can't self-heal on a lab switch the way
  band-as-data self-heals a range) — but IS derivable when the lab does NOT report it,
  provided the formula is disclosed (Calculated Osmolality, corrected calcium). Two design
  points came out of the conversion batch:
  - **Rounding is DISPLAY-side; floats are PRESERVED.** A derived value flows through
    unrounded (compute_series `precision=None`), so no rounding drift enters a chained
    derivation (e.g. a future A/G Ratio ÷ globulin). The client rounds for display via
    `format.js`'s noise-tolerant decimal detection (`decimalsOf` collapses a binary-
    float tail like `2.6999999999999997` → `2.7`), and any server-generated flag
    MESSAGE denoises its value in-engine (`analysis._denoise`, round-to-10, which leaves
    every clean stored value's text byte-identical). BUN:Cr stays the ONE source-rounded
    exception — its DIVISION has genuinely infinite decimals no display rule can infer.
  - **A derived metric's reference band is BAND-AS-DATA, not computed.** The band CANNOT
    be faithfully computed from the inputs' bands: the inputs are correlated (direct is
    part of total; albumin part of total protein), so interval arithmetic is systematically
    too wide and can go negative (e.g. Indirect = [0.2,1.3] − [0.0,0.4] = [−0.2,1.3] vs the
    lab's real 0.0–1.0). So the band is treated as what it is — genuine, lab-specific, time-
    varying DATA that travels WITH the draw, exactly like a stored metric's range: captured
    per date at import (the range kept, the value discarded — the value is computed on read)
    into the new `derived_reference_range` table, and joined into the computed series by
    `compute_series`. When the lab changes its interval the next import updates the band
    automatically; a date with no captured band charts without one (honest — none was
    reported). This is what keeps Bilirubin Indirect's out_of_range flags after conversion
    (its 0.0–1.0 band rides the computed series), and it's the answer to "what if my lab's
    range changes" — nothing, the band follows the report. Derived metrics also now reach
    the cross-metric roll-ups (/overview, /timeline) at parity with stored ones.

### The interpretation tier (clinical-context reasoning) — a scoped, opt-in exception

> **Implementation status (ROADMAP #16):** the LOCAL implementation of this tier
> (`explain.py`'s `explain_metric` → the gateway's `ollama` engine, the `/explain`
> route, `InterpretationPanel.jsx`) was **removed as dead code** — its UI trigger was
> gone and its engine gate made it unreachable. The RULES below are NOT retired: they
> are the charter for any model that reasons over the engine's findings, and they
> govern the LIVE instance today — "The export handoff" (hosted), which applies them
> UNCHANGED. `explain.py`'s deterministic bundle assembler survives as that handoff's
> payload. This section stands as the design contract; a future local re-implementation
> would have to meet it in full.

The hard rules above govern the app's default: describe, don't interpret. There
is exactly ONE sanctioned exception — a per-metric, on-demand, opt-in
*interpretation tier* that may reason about the user's own data and raise
questions. It is loosened here deliberately (not silently), and it is bounded by
the structure below. If a feature can't meet every bound, it is not this tier and
the hard rules apply unchanged.

**Two tiers, structurally separate.**
- The GROUNDED tier is deterministic and unchanged: cited facts — guideline
  thresholds with their sources' own definitions, the engine's flag messages,
  values, trend statistics — render from CODE (the chart legend, the flag list,
  the methodology note, the deterministic summary). The model does not produce
  these.
- The INTERPRETATION tier is the model's entire output, rendered as ONE
  wholesale-labeled block, visually distinct, beneath the deterministic summary.
  There is no per-sentence grounding — the whole block is "model reasoning," by
  construction.

**The retained hard invariant (a rendering/labeling guarantee).** The model is
never the SOURCE of a number the UI presents as authoritative. Every cutoff,
value, and statistic shown as fact renders from code beside the model's block;
the interpretation tier is prose *around* those facts, explicitly labeled as
reasoning. This is a guarantee about what the UI presents as authoritative — NOT
a claim that the model never types a wrong number inside its own labeled block.

**Scope of reasoning.** The tier may explain the significance of the engine's
flagged findings AND raise a concern the engine did NOT flag — but ONLY from a
pattern present in the assembled data (a value approaching a cited threshold, a
deviation from the personal baseline, a relationship named in the methodology
note, a trend statistic). It never reasons from the metric's name or outside
knowledge, and it computes no new number.

**Framing guard — questions, not conclusions.** Anything the engine did not flag
is surfaced as a question to ask a clinician ("it may be worth asking whether …"),
never as a conclusion that something is wrong. This is accuracy, not just caution:
the model genuinely cannot know whether an unflagged pattern matters. The tier
names no condition, suggests no treatment, and states no cause — the hard rules on
conclusions, treatment, and diagnosis hold inside it.

**"Nothing stands out" is a valid, preferred answer.** On unremarkable data the
tier says so plainly rather than manufacture concern. Surfacing nothing is a
success, not a failure — this directly counters a small model's tendency to invent
significance to seem useful, and is treated as a safety property, not a UX detail.

**Privacy posture (design contract).** Were this tier re-implemented locally it must
be a LOCAL model ONLY, on-demand, never routing to a hosted provider — the deterministic
engine still doing all detection and math, the model computing nothing. (When it was
implemented, `explain_metric()`'s own hardcoded engine check enforced this, independent
of what "The export handoff" can reach; that guard is gone with the removed code, but
the requirement stands for any future local build.)

**Scope is single-metric (Phase 1).** Cross-metric synthesis remains a separate,
deliberate decision (see the cross-metric synthesis hard rule above) and is NOT
part of this tier.

### The export handoff (external-model reasoning) — a second, gated exception

A SECOND, separate loosening of the local-only stance above — deliberate and
reviewed, exactly like "The interpretation tier," not a silent drift. It exists
ALONGSIDE the interpretation tier, not instead of it: the interpretation tier
above stays local-only, unchanged. The export handoff is a different, occasional,
explicit, per-action user choice to hand the SAME kind of deterministically-
assembled per-metric bundle (`explain.assemble_explain_context` — see #16) to a
strong EXTERNAL model instead.

**What's actually being loosened.** The privacy charter's hard rule — never send
data externally without explicit, per-action confirmation — already permitted
this; nothing is newly ALLOWED here, a real provider is finally WIRED and the
export path (gateway tasks `explain_metric` / `export_metrics`) is allowed to
reach `gateway._hosted_call`. (The export path is now the ONLY hosted task: the
PDF-import cleanup pass that briefly shared this chokepoint went with the PDF
importers — see ROADMAP "Dropped".) This does NOT touch `narrate.py`'s summarizer —
**summarization stays local-only**, structurally gated: `summarizer_engine` is a
closed, server-validated enum with no `hosted` option (an out-of-allowlist value is
rejected before it's ever stored). The export handoff doesn't call the summarizer —
it calls the bare assembler (`explain.assemble_explain_context`) plus
`gateway.complete(engine="hosted")` directly, a separate code path, so no setting
change can accidentally route summarization through a hosted engine. (The local
interpretation tier that once ALSO used the `explain_metric` task — with its own
`!= ollama` guard — was removed as dead code, ROADMAP #16; the export path is now the
task's only caller.)

**Privacy footing — "Model A": structural cleanliness + a faithful preview +
consent, NOT redaction.** The export bundle is assembled ONLY from
`observations`/`flags`/`thresholds` — it never READS the name/DOB/MRN/physician/
facility columns. That structural cleanliness is real but **column-level, not
content-level**: it guarantees which columns are read, NOT that the free-text
CONTENTS of the fields it does read are identifier-free. The metric NAME is the
clear case — it is user-controlled free text (`explain.py`'s bundle carries
`"metric": metric`, allowlisted by the gateway and sent verbatim). This is not
hypothetical: the since-removed PDF importer was **OBSERVED gluing a lab report's
practice/department header onto a metric name** (an observed case where a lab's
department/practice header was prefixed to the test name — a physician-practice
string, which the charter's hard rule names explicitly). **That importer is gone; the hazard is NOT** — a metric name is still
free text, now typed by the user or carried in from an older import, and a name
pasted off a report header lands in the payload exactly the same way. So the
"by construction" claim does NOT extend to "the payload can contain no
identifier," and this task's guarantee does NOT rest on the payload being
identifier-free — it rests on the **faithful, complete preview + per-send consent**
(below), which is the control that actually catches such text before it leaves.
The regex `_scrub` is belt-and-suspenders, not the primary defense: it caught a
`Dr. Roe`-style name but matches nothing for a department header (the charter
already concedes regex can't catch arbitrary names — which is exactly why Model A
leans on consent, not scrubbing depth). Two tests hold this honest:
`tests/test_export_gateway.py` shows the CLEAN case (a real `analyze_series()`
bundle produces zero redactions/exclusions), and `tests/test_export_metric_name.py`
pins the LOAD-BEARING fact — that the bundle's `metric` field is free text reaching
the preview verbatim, the scrub misses an injected department header, so a future
refactor can't quietly drop the preview on the strength of a by-construction claim.
The original `summarize_labs`/`extract_labs` hosted tasks lean on redaction
(allowlist + regex scrub) because THEIR source is raw-ish imported text; the export
task can't redact an arbitrary injected name any better, so it relies on the
preview instead.

**Consent mechanics — the principle.** Health data leaves the machine via this
task ONLY through all three of: (1) a persisted, TOGGLEABLE enable-gate (off by
default, and just as easy to turn back off as to turn on — a standing capability
switch, never a one-way unlock), (2) a per-send preview that faithfully shows the
COMPLETE outbound content — every reading, finding, and threshold, never a
summary and never a hash, (3) explicit confirmation that must match exactly what
was previewed. The preview is read BEFORE consent, not after — the review IS the
safety mechanism here, so there is nothing to consent to if the user can't
actually read what they're approving. This is why "faithful and complete" is a
hard requirement on the preview render, not a nice-to-have, and why the
enable-gate being reversible is part of the same principle: consent that can be
granted must be just as easy to withdraw.

**The preview also shows the INSTRUCTION, not only the data** (`Preview.instruction` →
`ExportPreviewOut.instruction` → a collapsed block in `ExportPanel`). The system prompt
is static developer text carrying none of the user's information, so it is deliberately
NOT part of the confirmation token (which binds the DATA — folding the prompt in would
invalidate in-flight previews on a prompt edit, for no privacy gain). It is surfaced
because it is HALF of what the provider receives and it shapes the entire answer: a user
who reviews only the payload cannot tell why a response reads as it does — the observed
case being "why does it always come back with exactly two points?", which was a prompt
rule (a since-removed at-most-two-or-three cap), invisible on the review screen. Note the
asymmetry that makes this a transparency rule rather than a privacy one: the data half is
the *privacy* control (reviewed before egress), the instruction half is the
*interpretability* control (reviewed to understand the output).

**The protective rules hold for a stronger model — with TWO deliberately loosened on
the export path (user-approved).** Most of the interpretation tier's hard rules apply
UNCHANGED to the export handoff's external response: **no TREATMENT or medication advice**;
"nothing stands out" is a valid and preferred answer; the response is one wholesale-labeled
block (grounded facts render from code) labeled with the ACTUAL provider and model, never a
generic "AI"; a capable model does not earn a looser ruleset for the rules that protect —
the rule does the protecting, not the model's location or weakness. But **TWO rules are
DELIBERATELY loosened on the export path ONLY** — see "Hypothesis floating" immediately
below: (1) the model MAY apply general medical knowledge (not only the bundle's own facts)
to connect the data, and (2) it MAY name a condition or mechanism as a HEDGED POSSIBILITY to
raise with a clinician. This is a user-approved loosening of surface-don't-diagnose, scoped
to the external, consented, previewed export path; the app itself never diagnoses.

**Hypothesis floating & multi-metric scope — the deepest deliberate loosening (export path
ONLY, user-approved).** On the export path — the EXTERNAL model, opt-in, faithfully
previewed, per-send confirmed — the model MAY float POSSIBLE EXPLANATIONS that connect the
exported data (across several metrics, a panel/collection, a user-selected set, the full
health picture, OR a single metric that genuinely points somewhere — multiple metrics are
not required for an insight), and MAY name a condition or mechanism as a candidate to
discuss. This is the whole point: surfacing a possible explanation buried in the data so the
user can raise it with their clinician. It is a deliberate, documented loosening of the
surface-don't-diagnose prime directive, bounded so it stays "a possibility to discuss," not
"a verdict":
- It is the EXTERNAL model on explicit per-send consent — NEVER the deterministic engine or
  any LOCAL layer, which stay surface-don't-diagnose unchanged. **The app itself never
  diagnoses; only the model the user chose to send to, when they send, may hypothesize.**
- Every explanation is a POSSIBILITY, hedged, plural where the data supports alternatives —
  "one thing that could tie these together is X; another is Y — worth asking your clinician,"
  NEVER "you have X." It states uncertainty and does not converge on a single confident answer.
- It is GROUNDED in the actual data pattern shown, not a hunch from nothing; if nothing
  connects, "nothing stands out" remains a valid, valued answer (no manufactured concern).
- **NO treatment or medication advice** — this line does NOT loosen. Hypotheses to discuss,
  yes; what to do about them, no (that stays in the Prohibited list, clinician-only).
- Wholesale-labeled "model reasoning — possibilities to raise with a clinician, not a
  diagnosis," and the CODE-APPENDED disclaimer (FRAME) is the real backstop — belt-and-
  suspenders with the prompt, since the prompt is now the load-bearing framing guard.
- The privacy chain is UNCHANGED and MORE load-bearing at scale: a bigger payload (a panel,
  or the full picture) means the faithful PREVIEW must stay reviewable (grouped, counted —
  not an endless raw dump) or "review before you send" degrades; same allowlist / scrub /
  consent / audit. The model is still never the SOURCE of a number the UI shows as
  authoritative.

**The provider bar — provider-agnostic, stated once.** Any provider the export
handoff reaches must meet the SAME requirement already stated above under "Data
minimization & the privacy gateway": API-tier access that contractually excludes
training and uses the shortest available retention. That bar is stated there
ONCE and not repeated per-provider here — naming a specific vendor or a specific
retention duration in this charter would go stale the moment that vendor's
policy changes, and a stale safety document is worse than a general one. The
current provider choice, its researched terms, and the discipline for
re-verifying them at build time live in ROADMAP.md's "PLAN OF RECORD," kept out
of this charter deliberately so the safety rule can't go stale.

### The full-picture export (whole-record context) — a THIRD scoped exception

The export handoff above sends METRICS. The **full-picture** export — and ONLY it —
also sends the rest of the record: the profile, conditions, medications, timeline
events, imaging studies, and the radiology report text. It is the same gated /
previewed / per-send-confirmed chain, the same `export_metrics` gateway task, and the
same hypothesis-floating licence; what changed is the payload's breadth, which is a
privacy decision and so is written down here rather than assumed.

**Why breadth, not scope creep.** A lab value read without context is read blind: a
creatinine trend means something different on a drug that raises it, an out-of-range
result three days after a procedure is not the same finding as one out of nowhere, and
a report is the only document that says what an image MEANT. The metric bundle
structurally cannot carry any of that. Assembled by **`picture.py`** (pure, no SQL, no
provider — sibling to `explain.py`), merged into the multi-metric bundle as sibling
top-level keys that the gateway allowlist names **individually** (`profile`,
`conditions`, `medications`, `events`, `imaging`, `reports`) — deliberately not one
opaque `context` blob, which would make the filter vacuous for the whole addition.

**OFF by default.** `include_context` is false unless the caller sets it, so a single
metric, a panel, or an ad-hoc selection sends exactly what it sent before — data
minimization: a copper panel does not need the medication list. Only
`FullPictureExport` turns it on.

**Three footings, not one — do not conflate them.**
- **DB half (profile / conditions / medications / events)** — Model-A structural
  cleanliness, read from named columns. The **date of birth is READ and NEVER COPIED**:
  `picture.assemble_profile` consumes it to compute `age_years` and emits no DOB, so no
  code path here can place one in a payload (pinned end-to-end by
  `tests/test_full_picture_export.py`). **Biological sex and age DO leave** on this path
  — a user decision, medically load-bearing, and neither is on the charter's PII list;
  the DOB itself is, and stays. Free-text `notes` fields ride along and are exactly what
  the preview exists to let the user read first.
- **Imaging half** — rides `dicom_store`'s EXISTING display allowlist (StudyDate /
  StudyDescription / Modality / BodyPartExamined / counts). Every PII tag a DICOM header
  carries is excluded by never being read. The study UID is not carried either (it
  identifies the exam to this machine and means nothing to a model).
- **Prose half — NO structural footing, and it does not pretend to have one.** A
  radiology report is one block of prose with no fields: an allowlist has nothing to
  select and regex cannot catch an arbitrary clinician's name (the charter already
  concedes this). So the control is **HUMAN REDACTION AT THE CHOKEPOINT**: `GET
  /export/drafts` hands the prose to the panel as EDITABLE drafts, the user edits or
  clears them, and the edited strings are what get previewed, tokenized, and sent. The
  server **never re-reads the report file** when assembling — re-reading would silently
  undo the redaction while every other check still passed, which is why a test pins it.
  Emptying a report excludes it entirely. Be honest about the residual risk: this control
  is only as good as the user's reading of their own text, which is weaker than a
  structural guarantee and is why it is opt-in, per-send, and never a default for any
  other export.
  **This covers the DB's free text too, not just reports.** A condition note reading
  "benign, per Dr. Rossi" is the same class of problem as a report naming its
  radiologist — shorter, but no more automatically checkable — so `notes` (conditions,
  medications, events) and an event's `title` are editable in the SAME box, by the same
  mechanism (`RowTextIn` → `_apply_text_overrides`). They were briefly not, which was
  where a build stopped rather than a decision: report prose was redactable at the moment
  of consent while a note could only be fixed by leaving the export flow to go edit the
  record, and that friction is exactly what stops someone redacting. What is NOT editable
  is deliberate: a condition name, a drug name, a dose are **vocabulary, not prose** —
  the model needs them to mean anything, and `_EDITABLE_TEXT` is an allowlist, so a
  client naming an unlisted column is ignored rather than trusted (pinned by a test —
  the editor exists to REMOVE text before a send, not to become a back door for changing
  what a record says). Edits are **per-send and never written back**: the stored record is
  untouched (also pinned), and whitespace-only counts as cleared (`picture._prose`), since
  a box holding one space looks empty to the person who emptied it.

**The scrub now reaches prose — but only prose.** `gateway._PROSE_FIELDS` names the
free-text keys (`text`, `notes`, `title`, `metric`) that the belt-and-suspenders regex
follows into nested structures. The depth limit is correctness, not laziness: applying
those patterns to every nested string would corrupt the data, because `observed_on` IS a
"date" match and a value that stringifies to five digits IS a "zip" match — a blanket
recursion would redact the readings the export exists to send. Known cost inside prose: a
comparison exam date reads as `[REDACTED:date]`, since the pattern that catches a stray
date of birth cannot tell the two apart. Privacy wins that trade. A task declaring no
prose fields scrubs exactly as before.

### Clarification — naming a source's own framework vocabulary is descriptive
Describing how a SOURCE ORGANIZATION labels the ranges of its OWN classification
is descriptive of that framework — it is NOT a clinical claim about the user's
reading, so it's allowed. The line is *who/what the statement is about*: the
source's framework (OK) vs the user's value (not OK). This governs all threshold
curation (see the `metric_config` threshold shape).
- YES: "Defines the boundary between G3a (mildly to moderately decreased) and G3b
  (moderately to severely decreased) in KDIGO's GFR classification." (names
  KDIGO's labels for KDIGO's categories — about the framework)
- NO: "Your reading is mildly to moderately decreased." (interprets the user's value)
- NO: "Below this line, kidney function is decreased." (asserts a state)
- NO: condition names as labels ("CKD", "prediabetes") — those are diagnoses, not
  framework vocabulary; gridline/definition labels stay source + cutoff + the
  source's own category names only.

### When adding any analysis feature
- State what it computes and confirm it stays descriptive by default. An
  interpretive feature is permitted ONLY as the labeled two-tier interpretation
  tier defined below (deterministic cited facts + a clearly-labeled model
  reasoning block, framed as questions); anything beyond that structure still
  stops for review.
- Prefer extending proven deterministic logic (range checks, z-scores, trends)
  over statistically fragile inference, especially on a personal-scale dataset
  where small-sample patterns can mislead.
- If a feature can't stay on the surface-don't-diagnose side AND can't fit the
  sanctioned interpretation-tier structure, stop and raise it with the user
  rather than building toward diagnosis.

## Date format — YYYY-MM-DD everywhere a date is shown

Every place in the app that displays a SPECIFIC date — a date the user reads to
know when something happened (a reading's date, a condition onset, a medication
start/end, an event, a timeline entry) — renders it as **`YYYY-MM-DD`**. This
one format is unambiguous (no US-vs-international day/month confusion),
machine-readable, sortable, and visually consistent across the whole app. Dates
are already STORED this way (SQLite ISO-8601), so display compliance is just
"show the stored string, don't reformat it."

### The one exception
- **Natural-language PERIOD labels** — a label that names a SPAN of time rather
  than a specific date — may stay in natural language: e.g. the Timeline's
  monthly group headers ("March 2026"), a "Q2 2026" summary period, or a time
  AXIS's scale ticks ("Mar 2026" / "2026" at calendar boundaries). These describe
  a range, not a point, so `YYYY-MM-DD` would be wrong (an axis tick at the
  January boundary isn't "2026-01-01", it's the month/year mark).

### Why this is a charter (not just a convention)
Dates surface in dozens of places and every future feature will show more. With
no explicit rule, formats drift — `Apr 15, 2026` in one view, `4/15/2026` in
another, `2026-04-15` in a third. Making the rule explicit and reviewable is what
keeps it from drifting; a new date display that isn't `YYYY-MM-DD` (and isn't a
period label) is a charter violation to catch in review.

### Out of scope (not "date displays")
- **Native date-entry controls** (`<input type="date">`) — these are for ENTRY,
  not reading back; the browser renders the picker in its own locale and the
  value is stored/submitted as ISO. Don't try to restyle them.
- **Relative-time language** ("in the last 30 days", "since your last reading")
  isn't a specific date and is unaffected.

## Screenshots of the UI — use the harness, never the live app

Verifying a UI change means looking at it, and a screenshot of this app is a
picture of the user's medical record — which then lives wherever that screenshot
went (an assistant's tool output, a bug report, a chat). This happened twice:
once on the imaging viewer, where a scanned requisition carries a name, MRN and
DOB **burned into the pixels** that no allowlist can reach, and once on the
Timeline, where an intended network stub silently missed (the app calls
`127.0.0.1`, the stub matched `localhost`) and the real entries rendered instead.

The first fix was a warning in `frontend/CLAUDE.md`. It named one page, and the
next slip was on a different one — a note is not a control. The control is:

```bash
.venv/Scripts/python.exe verify/ui_shots.py --out shots     home:/ metrics:/metrics profile:/profile?tab=immunizations
.venv/Scripts/python.exe verify/ui_shots.py --out shots rail:/metrics:.metric__rail
.venv/Scripts/python.exe verify/ui_shots.py --dark --out shots timeline:/timeline
```

It seeds **synthetic DICOM slices** too (from pydicom's own bundled sample, restamped
into one 24-slice series), so the IMAGING page — the one whose burned-in PII caused
this harness to exist — can be reviewed without pointing a browser at the real
store. It seeds the **radiology report** that rides on that study and the **scanned
documents** as well (both shared with demo mode, `synthetic.py`), because the DOCUMENTS
page is otherwise empty whatever it is pointed at — which left it reviewable only
against the real record, the one thing this harness exists to make unnecessary. Deep-link a study to reach the viewer itself:
`--out shots "viewer:/imaging?study=ecf2e8f25b5d"` (the id is the sha1 of the seed's
fixed study UID, so it doesn't move). Without pydicom the folder stays empty and the
page shows its honest "no studies" state.

`--dark` emulates `prefers-color-scheme: dark`, which is all the app's default
"system" theme choice needs to resolve; `--pref KEY=VALUE` (repeatable) seeds a
localStorage view preference before the page loads, e.g.
`--pref ht-chart-scale=log`. Both exist for the same reason: a view that depends
on a browser-local preference could otherwise only be checked against the REAL
record — the one thing this harness exists to make unnecessary.

`verify/ui_shots.py` starts its OWN backend and Vite against a temp directory —
`HEALTH_DB`, `HEALTH_IMAGING_DIR`, `HEALTH_IMAGING_ARCHIVE`, `HEALTH_DOCUMENTS_DIR`
and `GATEWAY_AUDIT_LOG` all point inside it — seeds invented records, shoots, and
tears the whole thing down. There is no real record present to capture, whatever
page it is pointed at and however the wiring goes wrong. It asserts the env
before starting anything AND re-checks from outside that the backend is serving
the synthetic set, because the second slip was precisely a stub that looked
right and wasn't. Its one production dependency is `HEALTH_DEV_ORIGINS` (api.py),
which ADDS a CORS origin because the harness Vite runs off :5173.

**Enforced, not just documented:** `.claude/hooks/block_raw_screenshots.py` is a
PreToolUse hook that refuses any Bash/PowerShell command that both takes a
browser screenshot and names a live app origin (`:5173`/`:8000`). It stays out of
the way of the harness (its ports, its filename, an explicit `HEALTH_DB=`) and of
everything that isn't a screenshot. **Its interpreter path in
`.claude/settings.json` is ABSOLUTE on purpose**: it was relative (`.venv/Scripts/
python.exe`), which resolves against whatever directory the shell happens to be
in — so a single `cd frontend/src` made the interpreter unfindable, and a
PreToolUse hook that fails to START is non-blocking, i.e. the guard was silently
OFF while still appearing to be configured. A safety control that can be disabled
by a `cd` is not a control.

**When you need to check something against the REAL data**, read the DOM as text
(`page.inner_text`, `eval_on_selector_all`) and report only the fact you needed —
a text assertion answers "does this render correctly" without moving a picture of
the record anywhere.

## Commands

**Quick start (Windows):** double-click **`start.bat`** in the project root. It launches the backend and frontend in their own titled windows ("Clarity API" / "Clarity Frontend"), waits until both ports are actually listening, then opens the browser to http://localhost:5173. If a server is already running on its port it's left alone (no duplicate). The script only *starts* the servers — close the two windows yourself when done. It runs the same commands shown below (uvicorn without `--reload`, plain `npm run dev`); the manual steps are the underlying detail.

```bash
# Activate the venv (Python 3.13, on PATH as .venv)
.venv\Scripts\activate          # PowerShell / cmd

# Dependencies (pinned)
pip install -r requirements.txt

# Run the end-to-end smoke test (builds in-memory DB, seeds, prints flags)
python demo.py

# Run the API (interactive docs at http://127.0.0.1:8000/docs)
uvicorn api:app --reload

# Frontend dashboard (run the API first; Vite dev server at :5173)
cd frontend && npm install && npm run dev

# Frontend smoke probe — mounts every page in jsdom under StrictMode against the
# running API (GET-only) and fails on a crash/blank/stuck-loading page. See Testing.
cd frontend && npm run smoke
```

**Demo mode — `demo.bat`.** Shows the app to someone else without putting a real medical
history on the screen. It is a different **STORE**, not a different view: the launcher points
`HEALTH_DB`, `HEALTH_IMAGING_DIR`, `HEALTH_IMAGING_ARCHIVE`, `HEALTH_DOCUMENTS_DIR` and
`GATEWAY_AUDIT_LOG` at
`demo_store/` (gitignored, built on first run by `python -m demo_store_setup`) and starts the
app there on **ports 8001/5174**, so a demo can run beside the real instance and the URL itself
says which one you are looking at. The real record isn't hidden from the process — it is
unreachable by it, the same argument and mechanism as `verify/ui_shots.py`.

**There are FIVE real data sources, not four, and the fifth is a file rather than a store.**
`gateway_audit.log` (`$GATEWAY_AUDIT_LOG`, repo root by default) holds the VERBATIM payload of
every external send — real readings and findings, and on a full-picture send the report prose
and condition notes too — and Settings → External export renders it back under "External
sends". The demo launcher set the four `HEALTH_*` paths and left this one alone, so a demo
window served the REAL send history (observed: 20 entries, payloads and all) under a badge
saying the record was invented — the precise lie demo mode exists to prevent, on the one page
someone might click while the screen is turned around. `verify/ui_shots.py` had the same gap,
which would have put those payloads into a screenshot from the harness whose whole promise is
that it cannot. Both now redirect it, `demo_store_setup` refuses a real audit path alongside
the real stores, and a test reads BOTH launchers and asserts all five assignments — batch and
a subprocess-spawning script are otherwise unreachable by the suite, and a missing variable
there fails silently, as data on a screen.

**The invented record must be UNLIKE the real one — not merely stored apart from it.** The
first seed was written to look plausible, and plausible-for-this-project meant
plausible-for-this-user: it carried the real record's conditions, its medications and
roughly its demographics, and five generated documents elaborated all of it into prose.
That is worse than showing nothing, because a demo that mirrors the real history discloses
it while BOTH parties believe it is invented — the viewer takes it for fiction, the owner
takes the screen for safe, and nobody corrects either of them. All the store isolation
above is worthless if the contents are a copy. The demo person is therefore a DIFFERENT
PERSON in demographics and in history (currently: female, born 1979, 64 in — hypothyroidism
on levothyroxine, and an iron deficiency treated and resolved in 2024). **This is the one
control here that cannot be automated**: verifying "unlike the real record" in code would
require reading the real record, which is the access the feature exists to avoid. It is a
human rule, kept honest by being written down and by ASKING rather than assuming. What the
tests can pin — and do — is that the record is internally coherent as one person's history,
since assembling plausible details one at a time is how the first version came to resemble
its owner.

**The invented record covers DOCUMENTS too, and it has to.** `synthetic.seed_documents`
writes five scanned documents (a specialist consultation, two clinic notes, a laboratory
report, a discharge summary) as PDF + text sidecar + manifest, and `seed_reports` writes the
`reportFile.pdf` a real imaging disc files beside its `report.txt`. Without them the
Documents page showed ONE item whose reader said "No PDF for this document" — a page that
reads as broken, on one of the better features here. The reader deliberately shows the SCAN
and only the scan, so a demo document has to BE a scan: pages are rendered with Pillow (a
core dependency already, and its BUNDLED font, so the pages come out identical on any
machine) and wrapped in a PDF. The prose is invented but deliberately AGREES with the seeded
chart — the TSH excursion and the ferritin recovery the notes discuss are the ones `seed_db`
writes as shaped series (`_STORIES`) — which is what makes the demo one story rather than
several unrelated ones, and gives full-text search something true to find. A test pins that
agreement, so a change to either half that silently contradicts the other fails.

A masking toggle in the UI was **considered and rejected**: it leaves the real data inside the
running process (one route that forgets to mask and you are demonstrating what you meant to
hide), and it cannot work at all for the parts that matter most — a DICOM slice can carry a
name burned into its PIXELS and a radiology report is prose. `synthetic.py` holds the invented
record (deterministic, so the demo looks the same every time), and its DICOM generator is
shared with the screenshot harness.

The demo frontend finds the demo backend through **`frontend/.env.demo`** and
`npm run dev -- --mode demo`, not through a shell variable. It was a shell variable, and it
did not work: `set VAR=value && cmd` in a batch file stores the value **with a trailing
space**, so every request went to `http://127.0.0.1:8001 /metrics` and the demo came up
unable to load anything. A mode-specific env file takes priority over `.env` and has no
quoting to get wrong (verified: `vite build --mode demo` bakes in the 8001 base).

**A demo window that is talking to a REAL backend says so in red.** `MODE === 'demo'` is a
build-time fact about how the window was started; `GET /demo` is a fact about the store the
backend is on. When the first is true and the second is false, the strip becomes an alarm
instead of a reassurance — because that combination is exactly what a mistyped API base
produces, and its silent form is a real record on screen, unlabelled, in front of the room
you invited. The flag is THREE-state (null = not asked yet), so the alarm can't flash during
the fetch: an alarm that cries wolf once is one nobody reads the second time.

The ordinary notice is a **badge in the app header** beside the app name (it was a full-width strip, which cost viewport height on the imaging page); the MISMATCH alarm above stays a full-width strip, because a real record on screen unlabelled deserves an interruption rather than a badge. **Both are driven by a marker INSIDE the database** (`synthetic.MARKER_KEY` →
`GET /demo` → `DemoBanner`), never by an env var or a build flag. The direction of failure is
the whole reason: a launcher-set flag could say "demo" while the process was open on the real
record, and that is the lie that invites you to turn the screen around. A marker travels with
the data it describes. `demo_store_setup` also refuses to seed over any real store path, or
over an existing database that isn't marked. The screenshot harness stamps its own store too,
so every shot carries the badge — a synthetic store that denied being one is the exact
dishonesty this exists to prevent.

**Publishing the demo — `build_static_demo.py`.** Turns the demo store into a folder of
static files: it starts a throwaway backend against `demo_store/`, captures every GET
route the frontend uses, and builds the frontend in `static` mode so `API_BASE` points at
the snapshot. The published result has no backend, so it cannot be attacked, cannot drift,
and costs nothing to host; writes are refused client-side (`STATIC_DEMO` in `api.js`).

**Published via `.github/workflows/demo.yml`** to THIS repo's GitHub Pages site, never
into the personal site's repository — the site links to it, so the demo is never part of
that site's build. The workflow seeds the demo store during the run (it is gitignored and
not in the repo), so no committed record exists for it to publish; it runs the suite, then
serves the built artifact and mounts every page against it before deploying, because every
earlier step can pass and still yield a site that is blank in a browser. Requires
Settings -> Pages -> Source: GitHub Actions, once.

**Two things the published build needs that a local one does not**, both found by serving
the artifact from a subdirectory: Vite's `base` is `'./'` in `static` mode (a project Pages
site serves from `/<repo>/`, so root-absolute `/assets/...` resolves against the domain
root and 404s into a blank page), and the router is `HashRouter` there (a static host has
no SPA fallback, so `/metrics` is a 404 from the file server; `#/metrics` is one document
plus a fragment, and refresh, back and deep links keep working without a `404.html`
redirect shim). Both are gated on `STATIC_DEMO`; dev and the normal build are untouched.

It carries the SAME two-stage safety argument as `verify/ui_shots.py`, for the stronger
reason that its output is published: it asserts all five store paths (the audit log
included) are inside `demo_store/` BEFORE starting anything, then re-checks FROM OUTSIDE
that the backend it started answers `GET /demo -> demo:true` — a marker that lives in the
database and so cannot be faked by a mis-pointed process.

Two details are load-bearing. **The route -> filename function exists twice** — Python in
the crawler, JavaScript in `frontend/src/snapshot.js` — so `tests/test_static_demo_key.py`
executes the JS against the Python and requires identical output; a drift would raise
nothing and simply 404 into empty pages. The name is a slug plus a djb2 hash rather than a
mirror of the URL because three metrics here contain a SLASH (`AST/ALT Ratio`) and sixteen
contain spaces, which would make correctness depend on how a given static host treats
`%2F` and `%20`. And **`python -m http.server` is not adequate to preview it**: its listen
backlog is 5, so a page opening parallel requests gets connections REFUSED, which reaches
the client as "fetch failed" and reads as a broken demo. `--serve` runs the same server
with a 128-deep queue. Both facts were found by running the smoke probe against the built
artifact, which it can now do (`VITE_STATIC_DEMO=1`, pointed at the served snapshot).

**Secrets — `.env.local` (gitignored, project root).** The export handoff's
provider key (`ANTHROPIC_API_KEY`) lives in `.env.local`, loaded into the
**backend process only** at API startup (`env_local.py`, called from `api.py`'s
lifespan; existing env vars win over the file). It is deliberately NOT a global
Windows env var: a global key would be inherited by every process on the
machine — including Claude Code, which would then bill coding sessions to the
metered API instead of the user's subscription. Scoping the key to the app's
process is the mechanism that keeps "only this project's export sends use the
API." The gateway still reads the key from `os.environ` at call time; values
are never logged, stored in the DB, or returned by any API response.

Testing: **`pytest`** (~421 tests under `tests/`, hermetic — the hosted-provider tests mock the HTTP layer, no live API key needed) plus **`sweep.py`** (deterministic GET-endpoint snapshot diffing against a local baseline in `.sweep/` — the refactor-safety harness). `demo.py` remains the quick end-to-end smoke check — it seeds three series each crafted to trip a different detector, so a regression shows up as missing/changed flag output. **Throwaway-DB safety:** `api.DB_PATH = os.environ.get("HEALTH_DB", "health.db")` — read before lifespan, so a verification/test backend can set `HEALTH_DB` elsewhere and be *physically unable* to touch the real medical DB (the gap that once let a temp backend write into `health.db`); `sweep.py` and `tests/conftest.py` rebind `api.DB_PATH` after import and are unaffected by the default. **Frontend: `cd frontend && npm run smoke`** — the third harness, covering what the other two structurally can't. `pytest` tests Python and `sweep.py` diffs API responses; a React crash (one uncaught error unmounts the whole tree to a white page) passes **both `vite build` and `eslint`**, which is exactly how the `details onToggle` crash shipped. The probe (`frontend/probe/`, jsdom + the app's own React) mounts **every** page **under StrictMode** — non-negotiable: the first version ran without it and PASSED on the broken code, because React's eager-state optimisation happened to run the updater while the event was still live — clicks the disclosure/tab/expand controls plus each `<select>`, and fails a page that throws, blanks, stays on "Loading…", or renders its error branch. Two things it gets right that are easy to get wrong: assertions measure the **routed page** (`main.app`), never the root — the ~700-char app shell renders regardless, so a root-length check reports PASS on nine pages that are all still spinning (observed); and click targets are **re-queried after every click**, since a re-render detaches a list captured up front (observed: silently one click per page). It drives the **real local backend, GET-only** — enforced centrally in `probe/env.js`, so no click can mutate the medical DB (verified: DELETE/POST → 405, zero rows written) — because real response shapes are the whole point; synthetic fixtures agree with the code by construction, which is how a shape bug hides. Backend must be running (exits 2 with instructions if not). `PROBE_DUMP=metrics npm run smoke` prints one page's markup. It proves a page renders and survives interaction, **never that it looks right** — still eyeball visual changes in the browser.

No linter is configured beyond `npm run lint` (eslint); `npm run build` type-checks nothing but catches syntax/import errors.

## Architecture

The core design rule is **DETECT deterministically, NARRATE later**. All flagging math lives in `analysis.py` as pure functions; the narrate layer (`narrate.py`) only explains `Flag` objects this engine already produced — never computes the numbers itself.

Strictly-separated layers, each independently testable:

- **`schema.sql` / `db.py`** — persistence only, knows nothing about analysis. **It is the ONLY module that runs SQL** — `aliases.py` was the last holdout (its seeder read the `metrics` table directly; it now calls `db.get_metric_alias`), and a test enforces the rule by scanning every root module for `.execute(`, so the boundary can't quietly leak again. The key modeling decision: labs and vitals share one shape, so *all* numeric measurements live in a single `observations` time-series table (`metric`, `value`, `unit`, `observed_on`, plus the reference range). Every chart and every analysis function therefore runs over one uniform structure. `conditions` (status, no value) and `events` (dated, no value) are separate tables. Reference ranges (`ref_low`/`ref_high`) are stored **per result on purpose** — they vary by lab, age, and sex. One unit per metric is a data-integrity invariant enforced here: `add_observation`/`update_observation` reject a unit that disagrees with the metric's existing unit (its most recent NON-qualitative reading's, via `get_metric_unit`) by raising `UnitMismatchError` — so the rule holds for every writer, not just the API. The first (non-qualitative) reading of a new metric establishes its unit; edits check against the metric's *other* readings (so a sole reading's unit can still be corrected). **QUALITATIVE readings are EXEMPT from the unit rule** — a qualitative result (`'Negative'`, `'Yellow'`) is inherently unitless, so its blank unit is the ABSENCE of a unit, NOT a dimensionless unit choice (unlike a numeric ratio, whose `''` IS a real unit). So `get_metric_unit` ignores qualitative rows when deciding the canonical unit, `add_observation` skips the unit check for a qualitative reading being added, and `list_metrics_with_units` reports the latest non-qualitative unit (NULL for a qualitative-only metric — the form then doesn't lock it). This lets a metric hold BOTH a dipstick `'Negative'` and a quantitative `mg/dL` reading of the same test (the urine-glucose case); numeric-vs-numeric unit consistency is untouched (two numerics with different units still conflict). **A metric's unit can be RELABELED** across all its non-qualitative readings via `db.set_metric_unit` (`PUT /metrics/{m}/unit`, `UnitModal.jsx` "Edit unit"): a pure LABEL change (values stored as entered, NOT converted) — for casing fixes (`mg/dl`→`mg/dL`) or equivalent units (`EU/dL`→`mg/dL`, 1:1 for urobilinogen); a genuine conversion needs the values edited too. Qualitative rows are left unitless; a derived metric's unit is fixed by its computation (rejected, 409). **Results aren't only numeric:** a `result_type` column (`'numeric' | 'qualitative' | 'censored'`) distinguishes three shapes, enforced by DB CHECK constraints — *numeric* (`value` set), *qualitative* (`value` NULL, `value_text` set, e.g. `'Positive'`; unit `''`), and *censored* (`value` set **plus** an `operator` `'<' '>' '<=' '>='`, e.g. `<5` keeps the number 5 so it's never confused with the bare 5). `value` is therefore nullable. A `normal_text` column holds the **expected-normal** for qualitative results (e.g. `'Negative'`, `'Yellow'`); numeric/censored use `ref_low`/`ref_high` for that (a censored result's normal is itself a numeric bound). `init_db` **migrates** an old observations table (one lacking `result_type`) by rebuilding it — rename-old, recreate from `schema.sql`, copy rows defaulting `result_type='numeric'`, drop-old — since SQLite can't relax `value NOT NULL` via `ALTER`; `normal_text` is then added with a plain additive `ALTER ... ADD COLUMN` (no rebuild). Existing rows become `'numeric'` with value/unit intact and `normal_text` null.
- **Timed collections (`collections` table, e.g. 24-hour urine).** A spot draw is a POINT in time; a timed collection spans a PERIOD and yields several analytes sharing one total **volume / duration / dates**. Modeled like `documents` — the provenance an observation points back to: `observations.collection_id → collections.id` (nullable), so volume/duration/start are stored **once** on the collection, never duplicated onto every analyte row. Each analyte stays a normal `observations` row whose **value is the per-period RATE** (the *unit* carries the period, e.g. `mg/24h`) and whose `observed_on` is the collection's **completion date**; its per-24h reference band rides band-as-data. **The collection metadata is CONTEXT, not a detector input** — it lives in the `collections` table, not the series row, so it structurally can't reach `analyze_series` (which reads only value/observed_on/ref/result_type); the rate value flags normally. CRUD in `db.py` (`add/get/list/update/delete_collection`; `list_collections` carries `n_readings`, and `list_collection_readings` → `GET /collections/{id}/readings` lists one collection's analytes for the Collections tab's expandable row — a READ returning the SAME row shape a series row has, so the client formats an analyte with the reading formatter it already has, and deliberately NOT folding the collection's own metadata onto each analyte, which is the duplication this table exists to avoid); **delete of a non-empty collection is REFUSED** (`CollectionInUseError` → 409, like the rename merge-refusal) — remove/reassign its readings first. Entry is **create-first**: make the collection, then add analytes referencing it (the add form's "Timed collection" selector fixes the reading's date to the completion date). *Migration:* the FK column adds via a plain additive ALTER — SQLite enforces a nullable `REFERENCES` added this way, so no table rebuild. (ROADMAP #11: Phase 1+2 done; Phase 3 display badges + PDF/threshold curation deferred.)
- **Metric identity & display aliases (`metrics` registry).** **`metric_id` IS the match key** — the metric's identity; `observations`/`metric_config`/`metric_settings` all key off it, so naming is pure presentation. The registry row carries **two LABELS that both resolve to that id, neither of which is the key**: **`name`** — the verbose label, the lab's own wording (also the segment used in per-metric URLs, for stable human-readable routes) — and **`alias`** — an optional shorthand **display label** (NULL ⇒ show `name`). Ingest matches an incoming name against **both** labels (`resolve_ingest_id` → id), so the verbose wording and the shorthand tie back to the same metric. **Setting an alias ADDS a label; it never replaces the verbose one** — which matters because the lab's wording is what a future PDF import arrives as, and it must stay resolvable or that import would mint a duplicate. (Corollary + known gap: `rename_metric` REPLACES `name`, i.e. it *drops* the old label, so a later import under the old lab wording would no longer resolve — which is exactly why the UI offers "Display name" (alias) instead of Rename.) This is *why* the verbose suffixes are kept, not noise: `Serum/Plasma` / `Whole Blood` are the **specimen matrix** (the same analyte is genuinely measured in urine, whole blood, or by a glucometer, with different ranges), a method like `by LC-MS/MS` / `by Equilibrium Dialysis` distinguishes assays that can legitimately coexist (free testosterone has ≥3 methods), and `Alkaline Phosphatase **Total**` distinguishes the sum from its isoenzymes. **Ingest de-dup (enforced, `db.get_or_create_metric`):** an incoming name resolves to an existing metric by exact canonical name → then by **normalized** (case-folded, whitespace-collapsed) canonical **or alias** match (`resolve_ingest_id`) → and only then mints. So importing/typing `BUN` or `blood urea nitrogen` attaches to `Blood Urea Nitrogen` instead of duplicating; the exact fast-path runs first so every existing exact caller is byte-identical. Normalization is deliberately conservative (no punctuation-stripping/reordering) so distinct analytes — `Vitamin E (Alpha-tocopherol)` vs `(Gamma-tocopherol)` — never collapse. **Fuzzy `did you mean` (advisory, never auto-applied):** `db.suggest_metrics` scores existing name/alias against an incoming name (difflib) so a same-analyte-different-wording case is *surfaced* before it duplicates; the user chooses. `db.set_metric_alias` refuses (`AliasConflictError` → 409) an alias colliding with another metric's name or alias (a partial-unique index covers alias-vs-alias; the cross-column check is in code). Curated defaults live in **`aliases.py`** (`ALIASES` map + `seed_aliases`, run at startup) and are applied **only where `alias IS NULL`** — a user's own display name is never clobbered (unlike the blunt `metric_config` re-seed), because an alias is user-editable. **Derived (computed) metrics are aliasable too but through a SEPARATE path** — they live in the `derived.py` REGISTRY, not `metrics`, and must NOT enter ingest/suggest (you never import a computed value), so a derived alias is **display-ONLY, never a match key**: a curated default (`DerivedMetric.display_name`, e.g. NLR→"NLR") plus a user override in the tiny `derived_alias` table (`db.get_derived_aliases`/`set_derived_alias`). `PUT /metrics/{m}/display-name` branches on `is_derived`; the derived branch does a UI-clarity collision check (`api._derived_alias_conflict`) but no `metrics`-table write. *Migration note:* the alias **column** is in `schema.sql`'s CREATE TABLE (fresh DBs) but its **index** is created in `init_db` — an existing DB hits CREATE-TABLE-IF-NOT-EXISTS as a no-op, so the column doesn't exist yet during `executescript` and indexing it there would fail. **Metric GROUP (picker clustering, display-only):** a third registry label, `metric_group` (nullable, no index/uniqueness — many metrics share one), is a purely presentational cluster the picker renders as an `<optgroup>` (e.g. an arterial blood-gas panel). Like the alias it touches **no identity/match key and no reading** — set/cleared via `db.set_metric_group` (`PUT /metrics/{m}/group`, `GroupModal.jsx` "Group"), surfaced on `/metrics` as `MetricInfo.group`. This **generalizes** the two former hardcoded picker groups: `MetricPicker` renders ungrouped metrics first, then one optgroup per distinct user group (alphabetical), then the automatic "Timed collections (24h)" and "Computed metrics" groups. Precedence when a metric could fall in several: derived (Computed) > explicit user group > collection > ungrouped — the explicit choice wins over automatic collection grouping. Derived metrics already cluster under "Computed metrics", so the route refuses them (409). Column added additively (guarded `ALTER` in `init_db`, mirroring `alias`); also in `schema.sql`'s CREATE TABLE for fresh DBs.
- **`analysis.py`** — pure functions taking plain numbers/lists and returning `Flag` dataclasses (`metric`, `kind`, `severity`, `message`, `detail`). Touches no SQLite. `analyze_series(metric, series, ...)` is the orchestrator that runs every relevant check over one metric's series (oldest first). **Only NUMERIC results enter any math:** `analyze_series` filters to `result_type == 'numeric'` rows up front, so censored (`"<5"` — its value 5 is *never* treated as a number; that would fabricate data) and qualitative (`"Positive"`) results are excluded from trends, Mann-Kendall, personal-baseline z-scores, RCV deltas, and the *numeric* out-of-range check. The ONE comparison a censored reading does enter is `flag_censored_out_of_range`: a `<`/`<=` reading (extends downward) flags **"at or below the lower limit"** when its bound `X <= ref_low`; a `>`/`>=` reading (extends upward) flags **"at or above the upper limit"** when `X >= ref_high`. A boundary TOUCH in the direction of extension counts as out-of-range (exact equality is vanishing-probability for a continuous measure, and labs treat a value at the limit as out); the censored operator and the bound's strict/inclusive operator don't change this threshold. It stays **silent on genuine ambiguity** — when the bound sits inside the range or the relevant edge is absent (e.g. `<20` vs `≤10`), the data can't place the reading. Rows without a `result_type` default to `'numeric'`, so existing numeric flagging is unchanged; a qualitative-only metric simply yields no flags (no qualitative flagging in this build).
- **`gateway.py`** — the **privacy gateway**: the single chokepoint for every LLM call (the charter's mandated gateway). **It is the ONLY module allowed to call a model provider** (local or external); narrate/api/future imports must route through `complete(req, confirmation=None)` and never call a provider directly. Stdlib only; imports nothing from analysis/narrate/db. The caller picks an *engine* and the gateway maps it to a destination from a fixed registry it **enforces**: `in_program` → **local** (friction-free — runs the caller's `local_runner`; logged + engine-labelled, nothing leaves the machine); `hosted` → **external** (full machinery). (The `ollama` local engine was removed with the dead interpretation tier — ROADMAP #16.) The external path is **structured-only**: it accepts `fields: list[dict]` (never raw text — a raw document cannot be sent, so hosted extraction-from-raw-text is impossible by design) and builds the outbound payload by **inclusion against a per-task allowlist** (`_ALLOWLISTS`; lab = `{metric, value, unit, ref_low, ref_high}`) — anything not allowlisted is excluded by construction, not stripped — then runs a **belt-and-suspenders regex scrub** (email/SSN/phone/MRN/date/address/physician/zip; primary defense is still the allowlist, since regex can't catch arbitrary names). With no `confirmation` it returns a **preview** (`Preview`: exact payload to send, `excluded_fields`, `redactions`, `provider_settings`, `confirmation_token = sha256(payload)`) and **does not send**; it only sends when re-called with a `confirmation` token that matches the previewed bytes (else refused) — so **no silent/background external call** is possible. Provider settings (API tier, training disabled, shortest retention) are enforced in one place; the real external call is **wired**: `_hosted_call` dispatches per provider — `_anthropic_call` POSTs to Anthropic's real `/v1/messages` (model `claude-sonnet-5`; `ANTHROPIC_API_KEY` read from `os.environ` at call time, loaded from the gitignored `.env.local` at API startup — see "Secrets" under Commands), and an unwired provider (e.g. `openai`, still an enum option) fails honestly rather than pretending to work. Provider failures (401/402/429/5xx/network, and a `stop_reason "max_tokens"` truncation guard) map to categorized `HostedCallError`s → a distinct `provider_error` gateway status (routes: 502), deliberately separate from `refused` (409) because the recoveries differ (re-send vs re-preview). Every call appends to a **local-only, gitignored audit log** (`gateway_audit.log`; external entries record the payload sent verbatim + provider/settings). `GatewayResult.engine`/`destination` give the UI its engine label.
- **`narrate.py`** — the optional "narrate" half. Turns a finished `list[Flag]` into plain language and nothing more: no detection, no math, no SQL; it imports only the `Flag` *type* (analysis.py never imports it back) **and routes its one model call through `gateway.py` — it never calls a provider itself**. Narration is now **template-only**: the deterministic `TemplateSummarizer` runs through the gateway's `in_program` local path, stitching `Flag.message` text into prose — nothing leaves the machine and it can't invent anything. The former swappable local-Ollama option (`OllamaSummarizer`, the `ollama` engine) was **REMOVED** as a QoL cleanup — it added a model dependency (and an availability probe, a floating `$OLLAMA_MODEL` tag, and a fallback path) for a rephrase the template already does on-device; the summarizer is therefore on-device-only. `summarize_with_engine(flags, engine)` keeps its signature so the caller's plumbing is unchanged — `api.py` still resolves the persisted `summarizer_engine` setting and passes it in — but every value maps to the template; it returns a `SummaryResult` (`engine="in_program"` always; `model`/`fallback_reason` retained-but-always-null so `SummaryOut`'s shape is stable). The fixed disclaimer is appended in code, never model-generated. The `summarizer_engine` setting persists (a closed, server-validated enum — `settings._coerce` rejects an out-of-allowlist value) with **`in_program` as its only option**; it's no longer surfaced in the UI (the Settings "Narration" tab was removed with the Ollama option). A hosted summarizer remains deliberately **never** an option — a standing charter position: the ONLY hosted task is the **export handoff** (`ExportPanel.jsx` + `/export` routes); summarization is NOT among them and stays structurally local-only (the enum has no `hosted` value). **Note:** the gateway's `ollama` engine has now been **REMOVED** (ROADMAP #16), along with the dead local interpretation tier it solely served — `explain.py`'s `explain_metric`, the `/explain` route + `ExplainOut`, and `InterpretationPanel.jsx`. The gateway's local path is `in_program`-only; `explain.py` keeps only its deterministic bundle assembler (`assemble_explain_context`), which the export handoff uses.
- **`dicom_store.py`** — local DICOM imaging viewer support, sibling to `reports.py` in posture. **Privacy: 100% local, no external path by construction.** DICOM headers carry PatientName/DOB/PatientID(MRN)/ReferringPhysicianName/InstitutionName — the charter's forbidden-to-leave PII — and a medical image can't be reliably de-identified (PII can be BURNED INTO the pixels), so this feature reads a local imaging folder, renders pixels to PNG **on the server**, and NEVER touches the gateway or the network (a hosted image read is charter-prohibited outright, same reasoning as OCR). Metadata is surfaced by an **ALLOWLIST** (`_SAFE_STUDY_TAGS` = StudyDate/StudyDescription; `_SAFE_SERIES_TAGS` = Modality/SeriesDescription/BodyPartExamined/SeriesNumber/Rows/Columns) — only those tags are ever read into a dict, so every PII tag is excluded *by never being read*, not stripped (the charter's allowlist-not-denylist rule; pinned by `tests/test_dicom_imaging.py`, which proves the sample files' real PatientName never appears in the output). `scan_studies` walks `IMAGING_DIR` (`$HEALTH_IMAGING_DIR`, default `imaging_store/`, gitignored like health.db), groups files into **study → series → ordered slices** by DICOM UID (so filenames / missing `.dcm` extensions don't matter — a hospital CD's `IM000001` files just work), and caches on a cheap stat-only folder signature (file count + newest mtime) so scrolling slices doesn't re-parse. **The scan cache is PER-PARTITION** — one entry per immediate subfolder of the store (plus `"."` for loose root files), persisted in `imaging_store/.scan-cache.json` (gitignored, disposable, `_CACHE_VERSION` 3). This matches how the store actually grows: each imported disc is its own folder and never changes again, whereas a single whole-store signature made ANY change invalidate EVERYTHING — a 6th disc re-read the 13,000 files of the first five, a cost that climbed with every import (20 s → 65 s over five discs). Now an untouched folder is reused verbatim and only the new one is read (measured: full rebuild 58 s, restart-from-cache 0.48 s, new folder added 1.3 s reading exactly its own files). Two structural points make it safe: the cache stores each partition's **unflattened instance list**, and ordering/flattening/non-image filtering happen in `_finalize` **after** partitions are merged by study/series id — so a study or series spanning two folders still comes out as ONE correctly-ordered series, not two half ones (pinned by a test; the full real store was verified byte-identical to a single whole-store scan, file paths and frame indices included). `render_slice` applies HU rescale (RescaleSlope/Intercept), window/level (the file's own default window, or a `WINDOW_PRESETS` center/width — brain/soft-tissue/bone/lung), and MONOCHROME1 inversion, then PNG-encodes via Pillow. `public_studies` strips internal keys (`_slices`, which holds local file paths) so no path leaves the server. Deps `pydicom`+`Pillow` (in core `requirements.txt`); `available()` reports false and the route degrades honestly if absent, like OCR extras. Exposed via `GET /imaging/studies` (allowlisted tree + presets) and `GET /imaging/series/{id}/slice/{n}?wc=&ww=` (PNG, `Cache-Control: no-store`); frontend is `ImagingPage.jsx` (study/series picker → black stage `<img>` + slice slider + window presets + allowlisted metadata). Each study in the picker is a native `<details>`, **collapsed by default** (six studies × 94 series made the sidebar a long scroll; collapsed it's a short index, each row carrying the date, description and a series/image count) — with the study holding the CURRENT selection auto-opened, so the picker always shows what the stage is displaying (a timeline deep link selects a series before the user has opened anything). An explicit user toggle always wins over that auto-open, and picking a series pins its study open. JPEG2000-compressed DICOM needs an extra decoder (pylibjpeg-openjpeg); uncompressed/RLE render with pydicom+Pillow alone. **Non-image objects are filtered out** — a Presentation State (PR) / Key Object Selection (KO) / Structured Report carries no pixels and no Rows/Columns, so `scan_studies` requires both; **colour** slices (RGB secondary captures — a scanned requisition embedded as DICOM) render straight to RGB, skipping window/level. **Keyboard/mouse follow PACS convention** (RadiAnt/Sectra/MicroDicom): wheel scrubs the stack, ↑↓←→ step one slice, PgUp/PgDn ±10, Home/End first/last, `1..N` window presets, `0` the file's default. **Measurement**: `PixelSpacing` ([row_mm, col_mm] — physical geometry, allowlist-safe) rides each series; DISTANCE (2 clicks → mm/cm) and ANGLE (3 clicks, vertex in the middle → degrees) render on an SVG overlay whose `viewBox` is image-pixel space (so it maps 1:1 at any display size). Points are converted to millimetre space BEFORE the math, so both are correct for non-square pixels; distance falls back to "px (uncalibrated)" honestly when the modality supplies no spacing. A measurement is scoped to ONE slice and clears on slice/mode change (a line lingering over different anatomy would misrepresent it); both are plain geometric facts computed in code, no interpretation. **Window/level DRAG** (horizontal = width, vertical = center, up = brighter) is the standard radiologist gesture and the only practical way to work a modality whose values aren't the Hounsfield units the CT presets assume; it starts from `default_window` (the file's own WindowCenter/Width, surfaced per series) and is throttled since each step is a server re-render. Drag is active only when no measure mode is on, so clicks stay unambiguous. **ROI statistics** (`roi_stats` → `GET /imaging/series/{id}/slice/{n}/roi?x&y&w&h`): mean/SD/min/max in the modality's real units (`_value_units` — the file's `RescaleType`, else `HU` for CT, else `raw`), pixel count, and physical area. Computed SERVER-side from the file's own pixel data + rescale, because the client only holds a windowed PNG whose grey levels have lost the real values — a mean taken from those would be a fiction. Descriptive measurement only, the same footing as distance/angle: what the pixels ARE, never what they mean. Refuses colour images (statistics are meaningless on RGB, 400), clamps an off-edge rectangle rather than erroring, and is pinned by a test comparing against the region read independently with pydicom. **Rendering follows the DICOM VOI LUT spec.** `_apply_voi` implements PS3.3 C.11.2.1: the DEFAULT `LINEAR` function is defined over **(w − 1) centred on (c − 0.5)**, not `c ± w/2` — the latter is the separate `LINEAR_EXACT` function, and using it shifted renders by up to **4 of 255 grey levels** versus a conforming viewer (the error scales as 1/w, so it was invisible at bone w=2000 and worst at brain w=80). An explicit `VOILUTFunction` (`SIGMOID`, `LINEAR_EXACT`) is honoured when present. **`PixelPaddingValue` is respected** (PS3.3 C.7.5.1.1.2): those pixels lie OUTSIDE the reconstructed field of view and are not measurements — 7 CT series in this library declare it, padding ~21% of a slice at −3024 HU. They render BLACK rather than as data, are excluded from a data-derived default window, and are **excluded from ROI statistics** — on a real region straddling the field edge, including them made the mean wrong by ~1500 HU (−2457 reported vs −968 true) with a fabricated −3024 minimum. `n_excluded` reports how many were dropped; an all-padding region is refused rather than answered. **Out-of-field pixels are ALSO detected when the file declares nothing** — relying on the tag alone left most of this library unprotected: one whole study (10 series) fills 21–72% of every slice with a **−2048 HU sentinel and no `PixelPaddingValue` at all**, and several reformats use −1024/−8192. A second rule catches these: on a genuine CT image, any value below **−1500 HU (`_HU_OUT_OF_FIELD`)** is out-of-field, because the HU scale puts air at −1000 and nothing real lies beneath (this library's lowest legitimate values, air noise, reach ~−1050 — so the floor keeps ~450 HU of headroom, pinned by a test). Two guards keep it honest: it applies only to **CT Image Storage** SOP classes, never a **Secondary Capture** stored with `Modality=CT` (a dose-report screenshot here has 13.5% of its pixels below the floor across 209 distinct values — that's picture content, and masking it would black out the screenshot); and the anatomy is untouched (verified pixel-identical at every window). Measured effect: an ROI straddling the field edge reported a mean wrong by **584 HU** with a fabricated −2048 minimum, and at a wide window the sentinel region rendered as **grey 62** instead of black. **This is a deliberate, non-spec-mandated inference** — DICOM leaves values outside the reconstruction circle UNDEFINED, so drawing them black is the honest reading, but note the visible consequence: at an extreme window a naive viewer lights that region grey and this one keeps it black. **Display scaling is chosen by MEASUREMENT, not assumption** (`crisp` in ImagingPage): almost every series here displays BELOW native resolution (512² axials at 58–96%, sagittal reformats at 15–25%), and nearest-neighbour minification DROPS samples — at 20% scale it keeps ~1 pixel in 5, so a 1–2px fracture line can vanish. So minifying uses smooth/averaging and only magnifying uses `pixelated` (where interpolation would invent detail never acquired). **Window presets are CT-ONLY, gated on UNITS not modality.** `WINDOW_PRESETS` are Hounsfield-unit windows, and HU is an absolute calibrated scale (air −1000, water 0, dense bone ~+1000) that exists only for CT — MR signal is arbitrary and sequence/scanner-dependent, so a "bone 500/2000" window there renders a near-black frame while implying a calibration that doesn't exist. Each series therefore carries `value_units` (the file's `RescaleType`, else `HU` for CT, else `raw`) and the client offers presets — and their `1..N` keyboard shortcuts — only when it matches `presets_units`; otherwise it shows a "drag to window" hint (drag is relative, so it needs no calibration). Gating on UNITS rather than `Modality == "CT"` is deliberate and was vindicated on real data: 5 CT series in this library report `RescaleType US` ("unspecified" — derived reconstructions that lost HU calibration), so a modality check would have wrongly offered presets for them. Same honesty family as "px (uncalibrated)" for a missing `PixelSpacing`. **Zoom/pan** — ctrl+wheel or `+`/`−` zoom about the cursor (plain wheel stays slice-scrub, the stronger convention), shift/middle-drag pans, `R` resets; the transform sits on the frame so the SVG overlay scales WITH the image and annotations stay glued to their anatomy. **Cine** — `space` or the Play button auto-advances (looping), cheap because the prefetch cache is already running ahead. **Undecodable pixels** (compressed transfer syntax with no decoder installed) raise `PixelDecodeError` → **415** with an actionable message naming `pip install pylibjpeg pylibjpeg-openjpeg`, surfaced as an overlay on the stage rather than a blank frame or a 500. **Window/level is applied in the BROWSER, not the server** (`GET /imaging/series/{id}/frame/{n}` →
`dicom_store.frame_payload` → `frontend/src/dicom/frame.js`). The route sends one self-describing
blob per slice — `[4-byte LE header length][JSON header][pixel bytes][packed out-of-field mask]` —
carrying the file's OWN stored integers plus slope/intercept, the VOI function, the MONOCHROME1
flag and the default window; the client applies all of it and writes greys to the canvas. This is
what every conventional viewer does (RadiAnt, Horos, Weasis; Cornerstone/OHIF on the web) and it
deletes a whole apparatus that existed only because a cached PNG was window-SPECIFIC: the
whole-series preload, its drag gate, the `winKey` cache invalidation and the ~22/s throttle are
gone, because a window change is now a redraw of bytes already in memory. Four details are
load-bearing. (1) The VOI arithmetic now exists TWICE, so `tests/test_frame_payload.py` EXECUTES
the JavaScript (via node) over the same inputs as `_apply_voi` and requires the greys to agree —
a divergence here would be a subtly wrong grey on a medical image, which is the kind of bug
nobody notices and everybody trusts. (2) The header is PADDED so the pixels start 8-byte aligned:
a JS typed array cannot be viewed at an arbitrary offset, so without it the payload worked or
failed on the PARITY of a description of itself (observed: the square test series rendered, the
tall one reported an undecodable slice, same code path). (3) The out-of-field mask is sent
EXPLICITLY, one bit per pixel — it is not derivable from the pixels alone (it depends on
PixelPaddingValue, the SOP class and the HU floor rule) and a sentinel written into the pixel data
could collide with real values. (4) The cache is bounded by BYTES (values are ~512 KB per 512²
slice against ~70 KB as PNG), not by a frame count. Colour slices and any pixel width the route
declines answer 404 and fall back to the PNG route, which is honest: window/level is a grayscale
concept. Both routes still send `Cache-Control: no-store`. One pre-existing lie surfaced and was
fixed with it: on a series that declares no window the viewer SHOWED "W 400 · L 40" (a hardcoded
guess) while the server rendered the data-derived window instead — the client now takes the
window the frame declares, so the readout states what is actually on screen.

**Prefetching follows the CURSOR'S BLOCK, not the cursor** (`PREFETCH_CHUNK`), and forward-only
during playback (`PREFETCH_PLAYING`, 64 ≈ 3 s at 20/s). Keyed on `index` with a debounce, a
running cine — a new index every 50 ms — cleared the timer before it ever fired, so playback
prefetched NOTHING and fetched every frame on demand: observed as a stutter on the 406-slice
largest series in this library. Two related things fell out of the same investigation: the PNG-fallback
branch resolved its `ready` the moment `src` was assigned, so a prefetched fallback frame
"completed" without having fetched anything (it awaits `img.decode()` now), and the byte budget
is sized (320 MB) so this record's largest series fits WHOLE — 406 × 544 KB = 226 MB — which is
what lets a cine loop run from memory after one pass instead of evicting the frames it is about
to return to. Measured server-side cost of a frame on that series: **7.4 ms median** (p90 9.3),
i.e. ~68/s serially and ~400/s across the six workers, against a 20/s cine — the server was
never the constraint.

**Cine is paced by requestAnimationFrame against a clock**, not by `setInterval`. Measured
first, which is what pointed at the pacing: the client-side render costs **1.13 ms/frame**
(0.29 LUT + 0.79 paint + 0.05 alloc, benchmarked on a 512² Int16 frame) against a 50 ms budget
at 20/s — so a stutter was never the drawing. `setInterval` callbacks are COALESCED under load
and accumulate drift, so the GAPS came out uneven even with every frame present; rAF is already
synchronised to the compositor. The deadline is carried forward rather than reset, so a display
that can't keep up drops a slice instead of slowing the loop, and it is clamped one interval
behind so a backgrounded tab doesn't fast-forward to catch up on time nobody watched. Two
smaller things went with it: the annotation-clearing effect ran `setPoints([])` on every slice
change, and a fresh array always changes the reference — a SECOND render pass per frame, for
nothing (it uses no-op-when-empty updaters now); and `frame.js` caches the LUT and the RGBA
buffer one deep, since both depend on the window and the canvas size rather than on which slice
you are looking at. `renderFrame` also tolerates a missing or stub 2D context (jsdom, which the
smoke probe runs the real pages in, returns one whose `createImageData` yields undefined) —
nothing to draw on is not worth taking a page down for.

**Smooth scrubbing**: slices render to a `<canvas>` (which holds the previous frame until the next decodes — an `<img>` src swap flashes blank) fed by an in-memory `Map` of decoded frames that prefetches ±10/±4 around the cursor and evicts farthest-first at 64. The cache is in JS memory ON PURPOSE: the slice endpoint sends `Cache-Control: no-store` so rendered medical images never persist in the browser's disk cache, which means smoothness cannot come from HTTP caching. A window change invalidates every cached frame (each was rendered at a specific window), so the cache clears on window/series change and prefetch pauses mid-drag. **The whole-series preload is SUSPENDED while a W/L drag is in progress, and that — not render speed — is what made window/level feel slow.** Measured: one slice renders in ~13 ms server-side (2 ms read + 6 ms rescale/VOI + 2 ms PNG) and round-trips in 18–20 ms when nothing competes; but every blob is window-SPECIFIC, so each drag step threw the whole series away and restarted a **9.4 s** refetch (984-slice series), and the one slice the user was waiting on then queued behind hundreds of background requests through the browser's ~6 connections per origin. Interactive latency by concurrent preload workers: **0 → 18 ms median / 20 ms worst; 2 → 26/446; 4 → 37/847; 6 → 73/2208** — i.e. any concurrent preload destroys the tail, which is why the fix is a drag GATE (`wlDragging` state, set on pointer-down, cleared on pointer-up) rather than a lower concurrency. In-flight preload fetches are also **aborted** (`AbortController`) on cancel — dropping a `cancelled` flag alone left up to `PRELOAD_CONCURRENCY` requests still holding connections. Resuming is cheap: the effect re-running doesn't revoke blobs, so the loop skips what's already cached. `WL_THROTTLE_MS` is 45 (≈22 updates/s) now that the budget is actually free. Still-known wart: scrubbing *during* a post-drag preload contends the same way (the 2208 ms tail) — not addressed. **Timeline integration**: `timeline.build_imaging_entries` emits one `kind="imaging"` entry per study at its `StudyDate`, linking to `/imaging?study=<id>` (the viewer preselects that study's first series). **The radiology report rides ON that entry** (`detail["reports"]` → opaque id + formats), rendered as a link inside it — NOT as an entry of its own. A report isn't a separate dated event that happens to share a date; it is the written half of the same exam, and splitting them into two rows made one thing look like two. (An earlier build did emit a separate `kind="report"` entry; it was folded in at the user's direction.) A study whose disc carried no report gets an empty list, so the client needs no special case. No report prose enters the timeline — only the id and formats — pinned by a test asserting the body never appears in `/timeline`. **`tests/conftest.py` has autouse fixtures pointing BOTH `IMAGING_DIR` and `reports.ARCHIVE_DIR` at empty temp folders for every test** — without them, any `/timeline` test would read the user's REAL medical images and any `/reports` test their REAL radiology reports (prose carrying their name and DOB), which is both a hermeticity bug and exactly the ambient data-flow the privacy charter exists to prevent. **A caution the local-only posture makes safe but reviewers should know:** a scanned-form series can carry identifiers BURNED INTO the pixels (facility name, patient/provider fields) — the app never transmits them, but anyone screenshotting a rendered slice into an external context (including an assistant's own tool output) is moving PII the allowlist cannot reach.
- **`reports.py`** — local radiology-report access, sibling to `dicom_store` in posture. **Privacy: 100% local, no external path by construction.** An imaging CD carries the radiologist's written report (`other_content/<accession>/report.txt|.htm|reportFile.pdf`) beside the images, and **that text exists nowhere in the DICOM data** — the only SR objects on these discs are radiation-dose reports, not interpretations — so without this the one document saying what the images MEAN was invisible to the app. It reads `ARCHIVE_DIR` (`$HEALTH_IMAGING_ARCHIVE`, default `imaging_archive/`, gitignored), never touches the gateway/network/DB, and a report enters an outbound payload ONLY through the deliberately-built path described in "The full-picture export" below — the user opts in, and the text they send is text they EDITED in the preview, never the file on disk (`reports.py` itself still never touches the gateway or the network; `api._approved_reports` takes the edited string from the request and re-reads nothing). Everywhere else a report is local-only, and the accession-derived `id` never enters a payload at all. **Deliberately NOT allowlist-filtered, unlike DICOM metadata** — an allowlist selects known-safe FIELDS, and a report has no fields: it is one block of prose, opening with the patient's name/DOB/facility, whose clinical content is the entire point. Masking it would destroy the thing the user came to read, so the **local-only boundary is the protection here, not redaction**. The **accession number IS treated as an identifier** (the charter names record numbers explicitly): used ONLY as an internal join key, never returned — callers get an opaque `id` (`sha1[:12]` of it), and local file paths stay server-side, both pinned by tests. **Linking is by accession, and it has to be**: the archive and the image store do NOT agree on folder names (the first disc is `cd1` in the archive, `cd-import` in the store) and one exam can span two discs (one study here covers cd2 AND cd3, which is why both carry the same report — deduplicated into one entry with `n_discs: 2`), so a folder-name join would be wrong on both counts. `_accession_to_study` reads `AccessionNumber` — one header per study, 6 reads — which is deliberately outside `dicom_store`'s display allowlist and therefore lives here, in the module that needs it, rather than widening that allowlist. Text is read **on demand** (the list route never pulls clinical prose), preferring the disc's own `report.txt` and falling back to stripping tags from `report.htm`; encodings are tried utf-8 → cp1252 → latin-1 (real discs here are cp1252). Exposed via `GET /reports` (metadata), `GET /reports/{id}` (extracted text), `GET /reports/{id}/pdf` (the original bytes, `Cache-Control: no-store` for the same reason rendered slices use it), plus `report_ids` on each `/imaging/studies` study so the viewer can link to it. Frontend is `DocumentsPage.jsx`, which merges BOTH local sources — the imaging-disc radiology reports and `docstore.py`'s split hospital record — into ONE list (newest first, undated last), with a per-type filter and full-text search. **THE READER SHOWS THE SCAN AND ONLY THE SCAN.** The PDF is embedded inline; the OCR transcription is *never rendered*. That reverses the first build, which made the transcription the default view and put the PDF behind a button — i.e. showed the reader the LOSSY DERIVATIVE first (a vertebral level like `L3` transcribes as `13`) with the authoritative copy one click away. There is no "Original PDF" link either: the PDF is already on screen, so a button opening the same bytes in a tab was a second route to what you are looking at. **TRANSLATION WAS REMOVED ENTIRELY** (module, routes, tests, `requirements-translate.txt`) at the user's direction — it was a second error layer stacked on OCR, and its `available()` probe was also what made the first Documents load after a restart block for ~10 s. So OCR text now has exactly ONE consumer: **search** (`GET /documents/search?q=`, spanning both stores, ~11 ms over the whole 420 KB corpus — no index, which would be machinery for something already instant). Search is **two-pass**: exact (always accent-insensitive) and, ONLY if that finds nothing, a fallback that folds OCR-confusable glyphs (`1/i/|→l`, `0→o`, `5/$→s`, `8→b`) and flags its results `approximate`. The ordering is the design: folding buys about one extra document across real queries, but `50`→`so` and `12`→`lz` will match English prose once English records land — a recall gain not worth a permanent precision cost, but worth having when the alternative is nothing. Folding is length-preserving, so snippets are always cut from the ORIGINAL text, never the comparison form. A snippet is styled as a quiet **locator** into the scan, not as the document's content. The search control sits on the RIGHT and starts collapsed to a magnifier (it is occasional; 51 documents browse fine without it); expanding hides the type filter, since while searching, relevance order replaces type order and both controls would fight over the list. Closing clears the query — a live filter behind a collapsed icon would hide why the list is short.

- **`picture.py`** — the deterministic CONTEXT assembler for the full-picture export (see "The full-picture export" above). Sibling to `explain.py` and pure in the same way: it takes already-fetched rows and returns a dict — no SQL, no provider, no network (api.py gathers the substrate, the gateway does the sending). Shapes the profile / conditions / medications / events / imaging / report halves into the top-level keys the `export_metrics` allowlist names individually. The **date of birth is consumed, never copied**: `assemble_profile` computes `age_years` from it and emits no DOB, so the exclusion is structural rather than a filter someone could forget to apply. `assemble_reports` takes only the user's EDITED text (handed in by the caller) and reads no file — the one part of the payload whose privacy rests on human review rather than construction. `assemble_imaging` consumes `dicom_store.public_studies()`, whose tags are already allowlisted, so no PII tag is read here either.
- **`demo.py`** — wires `db` + `analysis` together against an in-memory DB.
- **`api.py`** — FastAPI transport layer. Contains **no analysis math and no SQL**: it translates HTTP ↔ `db` calls and serializes `Flag` dataclasses. Per-request SQLite connections come from a `get_conn` dependency that reuses `db.connect(check_same_thread=False)` (so `row_factory` and the `foreign_keys` pragma stay consistent); `init_db` runs once on startup against `health.db`. Endpoints: `POST /observations`, `PUT /observations/{id}` (edit), `DELETE /observations/{id}`, `GET /observations/{metric}` (raw series passthrough of `get_series`, now including each row's `id`), `GET /flags/{metric}`, `GET /summary/{metric}` (narrates the same flags via `narrate.summarize_with_engine`, returning `{summary, engine}`; no math in the route), `GET /metrics` (returns `{metric, unit}` per metric — the current unit being the most recent reading's — so the form can lock units). Readings are entered **one at a time through `POST /observations`** — the bulk PDF-import routes were removed (see ROADMAP "Dropped"). POST and PUT both map the UNIQUE(metric, observed_on) `IntegrityError` **and** `db.UnitMismatchError` to a 409 (duplicate vs. unit-conflict, distinguished by the detail message); PUT/DELETE on an unknown id → 404. Per-metric detector config (thresholds/rcv_cv passed into `analyze_series`) lives in the **`metric_config` SQLite table** read via the `metric_config.py` registry (`get_config(conn, metric)` → typed kwargs; `all_configs` for the timeline pass), seeded on startup from the former hardcoded values — the routes no longer hold a `METRIC_CONFIG` dict. CORS is scoped to the Vite dev origin (`localhost`/`127.0.0.1:5173`), GET/POST/PUT/DELETE, no wildcard.

- **Immunizations** (`immunizations` table, a Profile tab) — the vaccination record. A dated fact with no value and no status, closest in shape to `events`, and like conditions/medications entirely standalone: nothing here is analysed, charted or flagged (pinned by a test asserting that adding one changes neither `/metrics` nor `/timeline`). Columns: `vaccine` (required), `administered_on`, `dose_label`, `amount`, `site`, `lot`, `notes`. **`dose_label` and `amount` are two DIFFERENT facts** and a record can carry either, both or neither: dose_label says WHICH dose in a series ("Dose 1", "Booster", "2025-26 season"), amount says HOW MUCH went in ("0.5 mL"). One "dose" column would have to hold both, which is unsortable and answers two questions at once. `amount` is free text WITH its unit, like an observation's — 0.5 mL and 0.25 mL are both real vaccine volumes and the record prints the unit, so a bare number would throw away half of what it says. Added by a guarded additive ALTER in `init_db`, like every other late column. Two decisions worth keeping: **`administered_on` is NULLABLE and undated records sort LAST** — a childhood shot recalled from a paper card is a real record with no date, inventing one would put a fabricated point in the record, and SQLite's NULL-first default would otherwise float exactly those to the top (`ORDER BY administered_on IS NULL, administered_on DESC`); and **`dose_label` is FREE TEXT, not a dose number** — encoding a schedule would mean knowing each vaccine's schedule and judging whether a record is complete, which is a clinical judgment this app doesn't make. CRUD in `db.py` (`list/add/update/delete_immunization`) → `GET/POST /immunizations`, `PUT/DELETE /immunizations/{id}`; a blank date string is normalized to null by `ImmunizationIn` so an emptied field doesn't store `""`. **On the Timeline**: `timeline.build_immunization_entries` emits one `kind="immunization"` entry per record THAT HAS A DATE, linking to `/profile?tab=immunizations` (the tab owns editing). An UNDATED record is deliberately OMITTED — the same rule a condition with no onset follows: the Timeline places things in time, and inventing a date (created_at, today, a guessed year) would put a fabricated point on the line; the record stays fully readable on its tab. The `lot` number rides in `detail` but never in the entry title — it identifies a manufactured batch and is noise on a timeline. **NOT in the full-picture export**: adding it would widen the `export_metrics` payload and the gateway allowlist, which is a privacy decision for the user to make deliberately, not a side effect of building the record.

- **Profile section** (`/profile` route, top-level nav entry just before Settings) — permanent personal reference data, split across two tables. `profile` is a **singleton**: `CHECK (id = 1)` enforces exactly one row at the DB level, so `update_profile` UPSERTs on `id=1` (race-free, no check-then-insert); it holds `sex` (biological sex for medical-reference context, nullable, CHECK-constrained to `'male'|'female'|'other'`) and `date_of_birth` (ISO). `profile_history` is **append-only** for time-varying physical measurements: each row is `(field ∈ {'weight','height'}, value, unit, recorded_on)` — an update is a NEW row and the "current value" is the latest by `recorded_on` (served by the `(field, recorded_on DESC)` index). `unit` is required and stored **as entered** (lb/kg, in/cm — no conversion), the same honesty as `observations`. Both tables are created additively via `IF NOT EXISTS` (no migration code). `api.py` exposes `GET/PUT /profile` (singleton + current weight/height in one response), `POST /profile/measurements`, `GET /profile/history/{field}`, `PUT /profile/measurements/{id}`, `DELETE /profile/measurements/{id}`; the enum/strict-ISO-date constraints are enforced server-side in the Pydantic validators. **`field` is NOT editable on that PUT** (absent from `MeasurementUpdateIn`, and `db.update_profile_measurement` never writes it): weight and height are different quantities, so a row moving between them would silently change what two charts show — a mistyped field means delete + re-add, the same rule a reading's `result_type` follows. Editing corrects a row IN PLACE, which is not a break with append-only: the table stays append-only for NEW measurements (each save is a new row, the latest is current); it simply isn't immutable, and before this a mistyped weight could only be fixed by deleting the row and losing its date with it. `ProfilePage.jsx` renders sex (radio + Clear), DOB (with a **display-only** client-side age, never stored/sent), and a Weight + Height section each (prominent current value, inline toggle add-form reused via `MeasurementForm`, history with per-row edit + two-step delete, beside the chart). **Boundary discipline (this build):** Profile data is **local-only**. Apart from two deliberate, documented exceptions it feeds **NO** analysis, flag, or detection logic and never enters the analysis engine. **Exception 1 (display-only):** the current **weight** is shown on the Home page (`ProfileSummary`) and weight history is **charted** as a plain line — `WeightChart` reuses `MetricChart` with **no flags/thresholds** (the data shape is mapped from `profile_history`; height is not charted) — on both the Home page and inside the Profile page's Weight section. This is a *chart of the stored values only*: weight is still never run through detectors, z-scores, trends, or `analyze_series`, so the detect-side boundary holds. **Exception 2 (sex-aware detection, #18 — the first profile field to ENTER detection):** the profile's biological **`sex`** (ONLY sex — DOB stays out, weight/height stay display-only) selects which curated detector config applies. The crossing is confined to the config LAYER — `metric_config.get_config` / `get_thresholds_detailed` / `all_configs` read the profile sex and resolve sex-variant thresholds / `rcv_cv`; the deterministic ENGINE still receives only plain numbers and never learns sex. This is an **INTERNAL analysis boundary**, deliberately loosened here in the same spirit as "The interpretation tier" and "The export handoff" — and, as of #18, an INTERNAL one only. (**SUPERSEDED for the export path:** this line used to read "NOT a privacy-egress one: `sex` never leaves the machine." That is no longer true — the user decided sex and AGE ride the full-picture export; see "The full-picture export" below. It remains true of every other path: no detector, chart, or non-full-picture export sends it, and the **date of birth never leaves under any option**.) A sex-tagged threshold shows/flags only when it matches the profile sex (a null/`'other'` sex sees only untagged lines); `rcv_cv` may become sex-keyed with a `default` fallback. Analysis-safety is unchanged: a sex-specific cutoff stays surface-don't-diagnose ("relative to [sex]'s reference framework," source + cutoff + framework vocabulary, curated with #8's discipline) — gating a line is *more* honest than showing-it-regardless-with-a-caveat, not a new diagnosis or a new number the engine sources. **Phase 1 shipped the SEAM with ZERO behavior change** (proven: sex-independent config resolves identically for male/female/null/other, and the full 717-endpoint sweep was byte-identical with no variant seeded). **Phase 2 seeded two curated variants:** (1) `Testosterone Total by LC-MS/MS`'s AUA 300 line is now `sex: "male"` — shown/flagged only for a male profile; (2) the three sex-differing leukocyte `rcv_cv`s (WBC/monocytes/neutrophils) are now sex-keyed (male/female CV_I from Coşkun 2018, no `default` → null/'other' omits RCV for those three). (3) **WHO hemoglobin anaemia thresholds** — two sex-tagged lines on `Hemoglobin` (`<13.0 g/dL` male / `<12.0 g/dL` non-pregnant female, 130/120 g/L; `SOURCES["WHO"]`, 2024-reaffirmed): the first sex-variant where the cutoff VALUE differs by sex, and the first #18 change VISIBLE on a male profile's chart (the 13.0 gridline draws). **HDL was INVESTIGATED & DECLINED** (its 40 is ATP III's sex-independent low-HDL line; the 40/50 split is ATP III's metabolic-syndrome criterion, a different framework — not a valid sex-variant). This remains **foundation-only** otherwise: no derived calculations yet. Future, focused builds will reference it when concretely needed (e.g. BMI from weight + height, CKD-EPI eGFR recomputation from age/sex, age-adjusted contexts).

### Detectors (in `analysis.py`)

| Function | Catches |
|---|---|
| `flag_out_of_range` | value outside this result's reference range |
| `personal_baseline_z` | abnormal *for you* — ROBUST z-score (median + MAD, not mean + SD) vs your own history, so a single acute outlier can't drag the baseline toward itself or inflate the spread and mask later readings (catches values normal for the population but unusual for you) |
| `linear_trend` | least-squares slope drifting over time, even while every value stays in range |
| `mann_kendall` | monotonic trend, no linearity assumption |
| `rcv_delta` | a jump bigger than combined assay + biological noise (Reference Change Value) |
| `clinical_threshold_crossing` | latest value crossed a guideline cutoff the previous hadn't (e.g. A1c 5.7) |
| `flag_threshold_level` | latest value is STANDING on a guideline cutoff's concerning side (the static counterpart to the crossing — catches "you're below the line" when no crossing fired; suppressed for any cutoff a crossing already reported this run) |

`linear_trend` and `mann_kendall` both emit `kind="trend"` and can fire on the same drift — that redundancy is intentional; dedupe by `kind` at the UI layer if needed. `rcv_delta` and `clinical_threshold_crossing` are opt-in via `analyze_series`'s `rcv_cv=` and `thresholds=` kwargs. When `thresholds=` is passed, `flag_threshold_level` also runs (both emit `kind="threshold"`), and **`_annotate_guideline` folds a guideline mention INTO an `out_of_range` flag** whose reading is also past a cited line — in `analyze_series` AND the history path (`_history_flags`/`summarize_history` now take `thresholds=`) — so a below-range reading reads "…, and below the WHO 13.0 guideline line" in Notable readings, with **no separate flag** (no added noise). All of it is source + cutoff naming only (surface-don't-diagnose).

## Conventions

- A flag means "look at this," never a diagnosis — it's a prompt for a clinician conversation, not a replacement.
- Dates are ISO strings `'YYYY-MM-DD'` throughout.
- Use `connect(':memory:')` for tests, a file path to persist; `init_db` is idempotent (`IF NOT EXISTS`).
- New detectors should follow the existing pattern: pure function, return `Flag | None` (or `list[Flag]`), and get wired into `analyze_series`.
- **A green test suite proves the CODE, not the running SERVER.** `uvicorn` runs without `--reload` (see `start.bat`), so a source change does NOT reach a backend process that's already up — and `start.bat` leaves an already-listening port alone, so re-running it won't replace a stale server either. Before browser-verifying any backend change, **restart the backend** (fully close the old window / kill the process on `:8000`); a seed/detector change especially won't show until then. This has caused multiple phantom "bugs" (a route 404, an empty disclaimer, a threshold line not drawing) that were only a stale process serving old code. Same for the Vite dev server on `:5173` — a zombied instance serves stale assets; kill and restart if HMR looks wrong.

## Guidance that lives elsewhere (loaded on demand, not in every session)

- **`frontend/CLAUDE.md`** — the React/Recharts layer: `MetricChart`'s band/precision/
  threshold-rail rules, the entry form's result-type branching, `ObservationTable`, the
  chart-gating rule. Loads automatically when working under `frontend/`.
- **`.claude/skills/threshold-curation/SKILL.md`** — the durable verification + curation
  discipline for the guideline cutoffs seeded in `metric_config.py`: the four
  citation-status categories, the source + cutoff labelling rule, the context-only metric
  category, and the investigated-and-declined skip decisions (glucose fasting cutoffs,
  standard CRP, creatinine, BUN). `metric_config.py`'s comments reference this by the
  names "CLAUDE.md taxonomy", "curation note" and "the creatinine skip-entry" — they all
  mean this skill now.
- **`ROADMAP.md`** — what's planned, active, deferred and dropped, plus a per-session
  record of what shipped and why. Not auto-loaded; read it when picking up new work.

## Roadmap (not yet built)

The project's forward plan and roadmap live in **`ROADMAP.md`** — the single
source of truth for what's planned, active, deferred, and dropped, plus the
reasoning behind each item. This file keeps only charters, conventions, and
architecture (stable); `ROADMAP.md` holds the not-yet-built work (churns slowly).
