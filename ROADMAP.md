# Clarity — ROADMAP

> **Status:** this file is the SOLE SOURCE OF TRUTH for the project's plan and roadmap. Content: the canonical 14 items (original numbering preserved) + #15, the ACTIVE-NOW seeds work, and decisions from the threshold-curation session.
> **Persistence:** RESOLVED — the roadmap lives here, not in `CLAUDE.md`. `CLAUDE.md`'s "Roadmap (not yet built)" section is now just a pointer here; `CLAUDE.md` keeps only charters, conventions, and architecture. (The stable threshold-curation *discipline* — the citation-status taxonomy and skip-decision rationales, which code comments reference — stays in `CLAUDE.md` under "Threshold curation discipline"; this file holds only the forward curation work.)
> **Layer discipline:** `CLAUDE.md` = charters + conventions (stable). ROADMAP (this file) = features-not-yet-built (churns slowly). Handoff doc = session in-flight state, bugs, parked refactors (ephemeral). Bugs and refactor-candidates do NOT enter the numbered list.

---

## ACTIVE NOW
*(Phase B: the #1/#2 export arc SHIPPED IN FULL, phases (a)→(d) — `f3dc917`
(a: privacy-foundation proof) + `8205d7d` (charter) → `28b487e`/`91a7adb`/
`0e29785` (b: gating, routes, ExportPanel) → `66b6ae2` (c: real Anthropic
`_hosted_call`, first-send ceremony completed) → `2836820` (d: deterministic
disclaimer + visual tier boundary). #1, #2, and #16's open UI-role question
are all CLOSED below; carry-forward details in "Done this session." The
**audit-log reader** SHIPPED as the arc's follow-on — `GET /export/audit` +
a "Recent external sends" section on Settings (the #1 recon's finding-#4
nice-to-have), reading `gateway_audit.log`'s external entries verbatim,
deliberately NOT gated by `export_hosted_enabled` (history stays reviewable
after revoking). Building it surfaced and fixed real TEST POLLUTION of the
transparency log: every pytest run had been appending fake external-send
entries to the real `gateway_audit.log` (nothing redirected it); conftest
now isolates `gateway._AUDIT_LOG` per test, pinned by a test. Historical
fake entries (paired `summarize_labs` test entries, self-demo placeholder
entries) remain in the log — surfaced to the user, not silently rewritten.
SINCE (2026-07-14/15): #4 shipped (qualitative timeline strip); #6 shipped
(BUN:Cr derived ratio, + Tier A: Bilirubin Indirect / Total Globulin / Non-HDL
converted stored→derived with DISPLAY-side rounding + BAND-AS-DATA reference bands,
derived metrics now reach /overview + /timeline, computed metrics blocked in the
+Add form, A/G Ratio converted, and two NEW computed metrics added — AST/ALT Ratio
+ Calculated Osmolality — under a crystallized "definition vs convention" rule); #18 shipped IN FULL (sex-aware
detection — Phase 1 seam + Phase 2's three curated variants: Testosterone gating,
white-cell RCV sex-keying, WHO hemoglobin); #16 CLOSED OUT (the dead local
interpretation tier + gateway `ollama` engine REMOVED); #17 fixed (a mis-typed reading). Plus a
static threshold-level detector, uniform table decimals, and the `HEALTH_DB`
throwaway-DB safety valve.
**The actionable board is now essentially clear** — remaining items are all
gated on new data (#5 correlation, #8 curation, RCV extensions), deferred by
decision (#7 config UI, more #6 derived), or the optional scaffolding-prune
refactor. Next real work comes from new inputs or a new user decision, not a
queued item.)*

---

## Plan of record: Phase A (deterministic insight) → Phase B (export handoff)

**The framing:** this app's job is to REVEAL STRUCTURE in the user's own
longitudinal data — deterministically, locally, on the device. It does not, and
under this plan will not, take on the MEANING layer itself (what the structure
implies). That layer is handed off, explicitly and on request, to a strong
EXTERNAL model that the user brings — the app hands off a structured picture, not
a diagnosis.

- **Phase A — deterministic insight (current focus).** Reveal more structure in
  the app itself, no model involved: **#5** cross-metric correlation (see the
  data-viability recon accompanying this plan), **#4** qualitative timeline strip,
  and a personal-baseline-visualization extension (not yet a numbered item — scope
  TBD when picked up). All of this stays 100% local/deterministic, consistent with
  every existing detector.
- **Phase B — export handoff.** Once Phase A's structure exists, hand it off: **#1**
  the external-handoff preview/confirmation UI, **#2** wiring a real provider into
  `gateway._hosted_call`, then an export feature that reuses the **repurposed**
  `explain.assemble_explain_context` bundle (see **#16**) as its payload — sent to
  a strong external model, under the SAME allowlist → scrub → preview → confirm →
  audit chain the gateway already enforces. The interpretation tier's inline
  local-model UX is explicitly NOT the Phase B deliverable; its assembler is.
  **SCOPING LOCKED (2026-07-09) — the full arc is now a phased, reviewable plan
  of record; see the "PLAN OF RECORD (approved, full arc)" block under #1 below**
  for the privacy model ("Model A"), provider choice, gating shape, the
  `ExportPanel`/`InterpretationPanel` split, the charter touchpoint, and the
  (a)→(d) phase breakdown with the phase-(c) first-send verification ceremony.
  **SHIPPED: all four phases (a)–(d) landed 2026-07-09 → 2026-07-13; see #1/#2
  for the closure record.**

**Don't-foreclose filter (governs sequencing of BOTH phases):** this is built for
a single user today, but decisions should not needlessly foreclose a possible
future multi-user product. Prefer work that survives unchanged into that future
(deterministic detectors, the gateway's privacy chain, per-metric config) over
work that would need to be redone. Defer items whose cost is specifically
MULTI-USER-shaped and premature for a single-user product — **#13** (desktop
packaging) and **#14** (self-hosted multi-machine server) — until the multi-user
goal actually firms up; building them now would be paying a cost the single-user
product doesn't need yet, for a future that isn't committed.

---

## Roadmap — not yet built

**1. External-handoff preview/confirmation UI** *(DONE — shipped in full, phases (a)–(d), commits `f3dc917` → `2836820`)* — the gateway's hosted preview + per-action confirmation flow, surfaced as `ExportPanel.jsx` + stateless `POST /export/{metric}/preview`/`/confirm` routes, gated by `export_hosted_enabled` (two-way toggle) + `export_provider` (typed enum), with the real Anthropic provider wired (#2 / phase (c)) and the response side disclaimed + tier-labeled (phase (d)). Carry-forward implementation details: "Done this session" below. The recon + PLAN OF RECORD that follow are retained as the arc's design record — the plan was executed as locked.
> ▸ **Recon (Phase B kickoff, report-only — NOT yet the scoping plan):** mapped the built gateway machinery (`gateway.py`) against what a preview/confirm UI must drive, with the eventual export consumer (#16's repurposed `explain.assemble_explain_context` bundle) kept in view throughout.
> ▸ **1. The confirm-token round-trip, exact shape.** Preview: `complete(LLMRequest(task, engine="hosted", fields), confirmation=None)` → `GatewayResult(status="needs_confirmation", preview=Preview(task, provider, payload, excluded_fields, redactions, provider_settings, confirmation_token))`. Confirm: the SAME `LLMRequest` (same `fields`) plus `confirmation=<token>` — the gateway RE-DERIVES payload+token from whatever `fields` arrive at confirm time and compares byte-for-byte; a mismatch (stale token, or the underlying data changed between preview and confirm) self-refuses, never sends. Self-defending, but it means a route must either round-trip the original `fields` back at confirm time, or the server must cache "what fields this token belongs to" between calls — pick one for #1's scoping (the export-route proposal in #3 below sidesteps this).
> ▸ **2. Preview content — the privacy-critical check, and a real gap found.** `Preview.payload` IS the full allowlisted+scrubbed data (`list[dict]`), not a hash — `confirmation_token` is a separate sha256 purely for round-trip binding. So the mechanism is right: a UI CAN show the literal outbound content before sending. **BUT:** `_build_payload`'s allowlist and `_scrub`'s PII regex both operate ONLY on top-level string values of each row (`_scrub_value` returns non-strings — including nested lists/dicts — untouched, no recursion). The `explain_metric` task's bundle (`assemble_explain_context`'s return dict, passed as `fields=[bundle]`) nests `readings`/`engine_findings`/`cited_thresholds` as lists of dicts with their OWN sub-fields (and `engine_findings` splats each `Flag.detail` — an arbitrary per-detector dict never vetted against any allowlist) — none of that nested content is filtered or scrubbed today. Already self-flagged in `gateway.py`'s `explain_metric` allowlist comment as a gap "if a real external provider is ever wired" — Phase B's export MUST close it (generalize `_build_payload`/`_scrub` to recurse, or pre-flatten/vet the bundle's nested fields into an explicitly-allowlisted shape) BEFORE `explain_metric`/any export task is ever routed through `engine="hosted"`. **The single most important finding of this recon.**
> ▸ **3. No API route exists yet — confirmed.** Zero routes in `api.py` call `gateway.complete` with `engine="hosted"`; the only "external" hits are an unrelated Ollama-reachability-probe comment. `narrate.py`/`explain.py` (the only two `gateway.complete` callers today) both hardcode `engine="in_program"`/`"ollama"` only. No test exercises the hosted round-trip via HTTP either — only `gateway.py`'s own `__main__` demo runs it, manually, outside pytest. **Proposal (not decided):** every existing LLM-touching route in this app is TASK-SPECIFIC (`/summary`, `/explain` — never a generic "run any task" endpoint); match that with task-specific routes for export (e.g. `POST /export/{metric}/preview`, `POST /export/{metric}/confirm`) that rebuild `fields` server-side from `assemble_explain_context(metric, ...)` on BOTH calls — sidesteps the stateless-vs-cache question in #1 above (the route, not the client or a server cache, is the source of truth for what `fields` a token belongs to; a data change between preview and confirm self-detects via the gateway's own token mismatch). A fully generic `/external/preview`+`/external/confirm` pair stays possible to factor out later if a second hosted consumer appears, but isn't justified by one.
> ▸ **4. Audit trail — local JSONL, no UI surface today.** `_audit()` appends one line per call to `gateway_audit.log` (gitignored, path via `$GATEWAY_AUDIT_LOG`). Local calls log `{ts, task, engine, destination:"local", model}` (no payload — nothing left the machine). External calls log ONLY on a successful confirmed send (`status="ok"`; a bare preview or a refused/mismatched confirm is never audited) and DO include the full payload: `{ts, task, engine, provider, destination:"external", payload, provider_settings, redactions}` — the log is already a durable local record of exactly what was sent, verbatim. Nothing reads it back today (no route, no parsing). Not required for #1's MVP (the preview-before-send moment satisfies the charter's transparency rule on its own) but a natural low-cost follow-on: a Settings-page "recent external sends" reader over the `destination:"external"` lines. Proposed as nice-to-have, not core scope.
> ▸ **5. Export-case size/shape — agnostic today, two flagged stress points for later.** The preview/confirm chain (`_canonical`/`_token`/`_scrub`) is fully payload-agnostic — no size limit, no shape check beyond the allowlist. Today's single-metric bundle caps at `MAX_READINGS=12` (`explain.py`), but that cap exists to bound what the LOCAL small model sees — its rationale doesn't automatically carry over to a strong EXTERNAL model; revisit rather than reuse as-is. Flagged, not designed: (a) a confirm dialog rendering hundreds/thousands of rows verbatim (multi-metric or whole-history export) stops reading as "review before you send" — would need a summarized/grouped preview, not a raw JSON dump; (b) more metrics/readings bundled means proportionally more surface area for the nested-scrub gap in #2 above to matter.
> ▸ **6. Settings gating — current mechanism + three options, not decided.** Today hosted is doubly unreachable: `summarizer_engine`'s `SettingDef.options` is a closed, server-validated enum with no `hosted` entry (`settings._coerce` rejects anything outside `options`), AND `explain.py`'s `explain_metric()` independently hardcodes `if engine != "ollama": unavailable` — it doesn't even consult a setting. For the export feature specifically (a distinct, occasional, explicit action, not a standing engine preference): **(a) a new persisted setting** (`export_hosted_enabled`, or a provider enum once #2 wires a vendor), matching the `summarizer_engine` pattern — but a standing "enabled" flag is itself something to weigh against the charter's "every external handoff is user-initiated and visible" bar; **(b) per-send confirm only**, no standing setting — the preview/confirm flow IS the entire gate every time, maximally literal to the charter, but leaves no settings-level home for provider config once #2 lands; **(c) both** — a settings-level capability/provider toggle (satisfies "surface that choice in the UI... rather than hidden in config") PLUS the mandatory per-action confirm on every send regardless (the setting only gates whether the option appears, never bypasses confirmation). (c) is the closest parallel to how `summarizer_engine` already works (persisted choice + separate per-request behavior).
> ▸ **CORRECTION (post-recon, now locked) — recon finding #2's "single most important finding" is SUPERSEDED, not confirmed.** On the corrected footing below, `_scrub`'s non-recursion into nested fields is NOT a gap to fix — it's moot by design. The export bundle is PII-clean BY CONSTRUCTION (`assemble_explain_context` is assembled only from `observations`/`flags`/`thresholds`, never from name/DOB/MRN/physician/facility columns), so the privacy guarantee rests on structural cleanliness + a faithful FULL preview + per-send consent, not on scrub depth. What genuinely needed doing was narrower than first flagged: a backend invariant test (allowlist keys == bundle keys, so a future bundle field can't silently ride along unreviewed) plus the FRONTEND actually rendering the full nested payload faithfully. See Phase (a)/(b) in the plan below.
> ▸ **PLAN OF RECORD (approved 2026-07-09, full arc — Phase (a) is the only phase under active build; (b)–(d) are locked scope, not yet started):**
>   - **Privacy model = "Model A":** PII-clean-by-construction + faithful full preview + per-send consent — NOT automated redaction. The regex `_scrub` stays wired (harmless, consistent with the one-chokepoint pattern) but is inert-but-harmless for this task; the guarantee is architectural + consent-based. Phase (a) PROVES the PII-clean claim with a test (`_scrub` fires zero redactions on a real assembled bundle) rather than just asserting it.
>   - **Provider: pluggable, Anthropic default.** Verified against each vendor's own current docs (2026-07; re-verify at build time — Anthropic's own policy moved as recently as June 2026). Both Anthropic and OpenAI exclude standard (non-enterprise) API data from training by default, no opt-in needed — a wash. Retention is the deciding axis at the solo-API-key tier: Anthropic ~7 days vs. OpenAI ~30 days, and NEITHER offers self-serve Zero Data Retention without an enterprise sales contract — a hard ceiling, honestly documented rather than glossed over. `_hosted_call` becomes a small provider registry (`ProviderConfig`: id/label/api_key_env/endpoint/model/training_note/retention_note/call), env vars named per each vendor's own convention (`ANTHROPIC_API_KEY`/`OPENAI_API_KEY`, not app-invented names). `Preview.provider_settings` shows the REAL per-provider training/retention text, replacing the old generic hardcoded `_PROVIDER_SETTINGS` dict.
>   - **External model gets the SAME rules as the local tier, not weaker ones.** Same hard rules (no diagnosis/cause/treatment, "nothing stands out" a valid/preferred answer, questions not conclusions) and the SAME latitude to raise a data-supported concern the engine didn't flag. The rule protects, not the model's location — a stronger model is better-behaved under identical rules, not more dangerous under looser ones.
>   - **Gating, matched to precedent, not forced into one shape:** `export_provider` → a normal typed `SettingDef` enum (matches `summarizer_engine`'s existing shape exactly: closed, server-validated via `_coerce`, gets a radio UI for free). `export_hosted_enabled` → the RAW boolean-setting path via `db.get_setting`/`set_setting` (matches `suggestion_dismissed`/`baseline_explainer_seen`: a one-shot capability flag, not a tunable knob), its own small route pair, never surfaced in `GET /settings`. Both gates apply on EVERY send — the setting only gates whether the option appears; it never substitutes for the per-action confirm.
>   - **`explain.py`'s `explain_metric()` stays untouched — `/explain` (local interpretation) is unaffected.** The new export routes call the bare `assemble_explain_context()` assembler directly plus `gateway.complete(engine="hosted")` themselves — a separate call path sharing only the assembler, not a shared function with an engine branch. Summarization (`narrate.py`) and interpretation (`explain.py`) stay local-only, unchanged, confirmed.
>   - **`ExportPanel.jsx` is a NEW component, distinct from `InterpretationPanel`** (the #16 repurposed, dead-inline local tier) — two separately labeled surfaces (local/free/always-on-demand/weaker model vs. external/costly/explicit-confirm/stronger model), no engine ambiguity per the charter's labeling rule. Renders only when `export_hosted_enabled` is true.
>   - **Charter: additive "The export handoff" subsection**, sibling to "The interpretation tier" — leaves the existing local-only clause visibly intact, documents the redaction-based-hosted (`summarize_labs`/`extract_labs`) vs. structurally-clean-full-preview-consent-hosted (`explain_metric`/export) distinction, and fills in the real per-provider training/retention numbers once wired (replacing the abstract "don't claim more than that" placeholder language with the actual 7-day/30-day figures).
>   - **Phasing:**
>     - **(a) Nested-preview-gap fix + PII-clean proof** — backend only, no route, no UI, NO EGRESS POSSIBLE. The allowlist-completeness pin test + the zero-redactions-on-a-real-bundle proof.
>     - **(b) Routes + gating + charter + the FULL `ExportPanel` UI** — `_hosted_call` stays the placeholder throughout, so the entire preview→confirm→"send" round trip is buildable and browser-verifiable with ZERO real egress possible (the send returns the fixed placeholder string).
>     - **(c) Pluggable `_hosted_call` + the real provider (Anthropic default)** — the first actual off-machine send. Special scrutiny (see the first-send verification ceremony immediately below) — smallest phase in code, largest in review weight.
>     - **(d) Response-side: two-tier labeling, real provider/model naming, verifying (b)'s UI against a REAL response** — smaller than a fresh build; the UI skeleton already shipped in (b).
>   - **Phase (c) first-send verification ceremony (locked, FIRST-SEND-ONLY — not a standing practice):** (1) a dry run with a TRIVIAL/junk payload first, proving the pipe itself (auth, response shape, retention-relevant headers, no error) with no real health data crossing; (2) on the FIRST real bundle send, capture what actually left the machine and byte-compare it against what the preview showed — proving the last inch, that the real `_hosted_call` didn't alter, duplicate, or mis-log the previewed payload; (3) after that one proven send, drop the capture step and rely on the gateway's STANDING token byte-compare (already enforced on every send, preview vs. confirm) going forward. This ceremony verifies the new code path once — it is not a permanent per-send overhead.

**2. Wire a real hosted provider into `gateway._hosted_call`** *(DONE — shipped as #1's Phase (c), commit `66b6ae2`)* — `_hosted_call` dispatches per provider: `_anthropic_call` POSTs to the real `/v1/messages` (model `claude-sonnet-5`, verified live against `GET /v1/models`; `ANTHROPIC_API_KEY` read from env at call time), and an unwired provider (e.g. `openai`, still an enum option) fails honestly rather than pretending to work. Provider failures (401/402/429/5xx/network) map to categorized `HostedCallError`s → a distinct `provider_error` gateway status (routes: 502), deliberately separate from `refused` (409) because the recoveries differ (re-send vs re-preview). The first-send verification ceremony ran ONCE as locked — dry-run junk payload, then a byte-compare of the first real send against its preview — and the capture step is now dropped per plan (the standing token byte-compare remains on every send).

**3. Optional LLM-cleanup pass for PDF import** *(SHIPPED 2026-07-20 — **REMOVED 2026-09-19** with the PDF importers it served; see "Dropped: the PDF importers" below)* — routed the structured draft (never the raw PDF) through the gateway's external path to tidy names/units. It was the project's only hosted task besides the export handoff.
> ▸ **Why it went:** the cleanup pass existed solely to tidy `pdf_import`'s draft rows. With the importer removed there is no draft to clean, so the task, its routes, its allowlist entry and its UI went with it rather than lingering as a hosted egress path with no caller. The export handoff is once again the ONLY task that can reach `gateway._hosted_call` — a smaller external surface, which is the right direction for a repo that's going public.
> ▸ **What it proved, worth keeping:** a hosted task can be given a *structured* (non-prose) response contract — a positional JSON array parsed server-side, with a malformed or mis-aligned reply failing as a clean 502 rather than being applied. If a future importer wants a cleanup pass, that shape is in git history at `archive/pdf-extractors`.

**4. Qualitative timeline strip below the chart** *(DONE — `QualitativeTimeline.jsx`, mounted in `MetricsPage.jsx`)* — horizontal strip aligned to the time axis for Positive/Negative/Yellow/… results with no Y value. (Censored values already render as arrows on the main chart; this strip is for qualitative / no-Y-value results.)

**5. Cross-metric correlation** *(DATA-GATED — explicit trip condition below, not yet met)* — surface metrics that move together; strictly association, never causation. Defer until enough data to be meaningful.
> ▸ This is the *descriptive* tier of the "look at the whole picture" goal — safe IF it states correlation and never cause. The *synthesis* tier ("these values together suggest X") is diagnosis and is explicitly NOT this item — it stays a deliberate charter decision, never slid into because the correlation plumbing exists.
> ▸ **Data-viability recon (Phase A kickoff):** measured against the real DB, not assumed. **n=12 is a HARD CEILING** — no metric in the dataset has more than 12 numeric readings, ever, so no pair can exceed n=12 regardless of alignment. Of 1,953 possible pairs among the 63 metrics with ≥2 numeric readings, 1,606 share ≥1 date, but only **16 pairs reach n≥12** (the ceiling itself) and **zero pairs reach n≥20** — the loose defensible floor for reporting a correlation at all (n≥30 is the comfortable floor). **The Fisher-z reality:** at n=12 (the dataset's best case), a TRUE r=0.50 has a 95% CI of approximately **[−0.10, +0.83]** — statistically indistinguishable from zero. Computing and displaying a point-estimate r on this data would be confident-but-wrong, not a modest first cut.
> ▸ **The same-draw confound (independent of sample size — flag for whenever this IS built):** shared dates are dominated by two panels drawn together every time (CBC; CMP/BMP+LFT) — among pairs with ≥5 shared dates, the median shared/min(nA,nB) ratio is 1.00 (52% are *fully* co-ordered), and the ≥8-shared pool draws from only 34 distinct metrics, essentially C(34,2) recombinations of two lab panels. A correlation among panel-mates conflates "these two analytes relate" with "these were measured at the same visit under the same fasting state/illness" — a real confound to surface in the eventual UI, separate from the n-ceiling problem above.
> ▸ **Concrete trip condition:** revisit #5 when ANY metric pair reaches **n≥20 shared independent draws** (re-run the same pair-coverage query against the live DB). **The build is cheap when viable** — the same-date pairing logic (`db.get_joined_series`, built for #6) already does the hard part; #5 later is "wire an existing join + a stats call," not a fresh build. The deferral is about DATA, not effort — do not re-litigate as "just build it" without re-checking the trip condition first.

**6. Derived/calculated metrics** *(NINE INSTANCES DONE — conversions of stored metrics: corrected calcium, BUN:Cr ratio, Tier A: Bilirubin Indirect / Total Globulin / Non-HDL, A/G Ratio; NEW computed-not-stored: AST/ALT Ratio, Calculated Osmolality; and NLR — a DOCUMENTED EXCEPTION to the "clinically standard" bar, surfaced with a prominent warning advisory; more instances open)* — compute standard recognized values labs don't print (ratios, etc.) as their own metric; clinically standard only, except where a value is surfaced as an explicit labeled exception (NLR — see the candidate ledger).

> ▸ **The "definition vs convention" rule (crystallized 2026-07-16, drives what CAN be derived).** A derived metric is safe ONLY when its computed value can't CONTRADICT the user's own lab report. Three cases: **(1) definitional identity** — the formula is universal (globulin *is* Total Protein − Albumin at every lab; indirect bili *is* Total − Direct; ratios like BUN:Cr, A/G, AST:ALT) → always safe to derive. **(2) convention on a value the lab REPORTS** (Anion Gap ±K, LDL Friedewald/Martin-Hopkins/Sampson, QTc Bazett/Fridericia, the iron panel's measured-vs-computed direction) → **keep STORED, do NOT derive**: deriving would print a number that competes with the medical record, and the formula is baked in code so it can't self-heal on a lab switch (unlike band-as-data, which self-updates the RANGE but not the FORMULA). Anion Gap was VERIFIED 10/10 faithful to the no-K form on current data yet still declined on this rule (a lab change to the +K form would silently diverge). LDL is data-CONFIRMED unfaithful (0/1 vs Friedewald — the lab uses a different equation). **(3) convention on a value the lab does NOT report** (corrected calcium's Payne formula; Calculated Osmolality) → derivable IF the chosen formula is DISCLOSED in the caption (nothing to contradict; the disclosure is the honesty). NLR/PLR are clean ratios but HELD as not-yet-"clinically standard" (prognostic/research markers).
> ▸ **Candidate ledger (the audit outcome — what's left, backburnered, or declined).** The computed-metric audit is essentially exhausted; every remaining candidate sits in one of three buckets, recorded here so none is silently forgotten or re-litigated without cause.
> > **SHIPPED as a DOCUMENTED EXCEPTION to the "clinically standard" bar (2026-07-16):**
> > • **NLR — Neutrophil-to-Lymphocyte Ratio** (Neutrophils Absolute ÷ Lymphocyte Absolute, dimensionless; both present, n=9). A user decision: surface it, but NOT by lowering the bar — as an explicit, labeled exception TO the bar (the bar stays intact for everything else). Math is a clean definitional identity (`precision=2`, 0-lymphocyte → gap). What makes surfacing it honest is a new **`advisory`** field on `DerivedMetric` (set for NLR ONLY, null for every standard metric): a warning-level notice, rendered PROMINENTLY (amber `.metrics__advisory` box with ⚠ + "Not a standard test.", ABOVE the muted caption — not as it), surfaced via `MetricInfo.derived_advisory` on `/metrics`, stating it is not a standard test, has no reference range, and is a personal-TREND signal only. **The app DOES flag a notable trend in it** (a follow-on decision — "flag it if there's a trend that should be eyeballed"): NLR carries no threshold/band, but the engine's DEFAULT detectors already run over its computed series, so `trend` (linear/Mann-Kendall) and personal-baseline flags fire on a real movement — surfaced on /flags/NLR like any metric. This stays surface-don't-diagnose: a trend flag describes MOVEMENT ("rising over N readings"), names no condition, and makes no value-vs-normal-range judgment (`out_of_range` can't fire without a band; no threshold seeded). The advisory says exactly this ("a flag here means 'look at this change,' not 'this value is high or low'"). Documented in CLAUDE.md ("Derived metrics"), `derived.py` (module docstring + spec), and here. Tests: `tests/test_derived_nlr.py` (compute/precision/gap/unit-guard/zero-lymphocyte + the advisory is isolated to NLR + a rising series is trend-flagged through /flags + the `/metrics` route surfaces the advisory). Sweep re-promoted 727→732 (5 NLR endpoints + /metrics + /overview + /timeline; every change NLR-attributable, body-free verified).
> > **On the backburner** (clean definitional ratios, computable from inputs the user HAS — held ONLY on the charter's "clinically standard" bar, a ~2-line add if that bar is later judged met):
> > • **PLR — Platelet-to-Lymphocyte Ratio** (Platelet Count ÷ Lymphocyte Absolute; both present, n=9). Same logic that made NLR a bar EXCEPTION rather than a standard metric, with weaker standing and redundant with NLR as an inflammation proxy — so it stays parked rather than shipped even under the advisory mechanism. Revisit only if concretely wanted.
> > **Deferred — needs data that isn't in the DB yet** (feasible the moment it appears; re-check before building):
> > • **eAG — Estimated Average Glucose** (28.7·A1c − 46.7, ADA/ADAG). The `hba1c` metric exists but has **n=0 numeric readings** — no A1c data to compute from. Trip: any hba1c reading.
> > • **MAP — Mean Arterial Pressure** (DBP + (SBP−DBP)/3). No systolic/diastolic **blood-pressure metrics exist** in the data at all. Trip: BP readings entered.
> > • **Reticulocyte Production Index / corrected retic** — needs a reticulocyte count (absent; Hematocrit is present). Trip: reticulocyte readings.
> > **Decided AGAINST — lab-reported CONVENTIONS, keep STORED** (deriving would print a number competing with the medical record; the code formula can't self-heal on a lab switch — see the definition-vs-convention rule above). NOT to be revisited as "just compute it":
> > • **Anion Gap** — the ±potassium convention. VERIFIED 10/10 faithful to Na−(Cl+CO₂) on current data, still declined: if the user switches to a +K lab, the derived value would silently sit ~4 below the new reports (K ≈ 4 mmol/L), and nothing captures the formula change. Stored already follows each report's own convention per draw.
> > • **LDL Calculated** — Friedewald vs Martin-Hopkins vs Sampson. Data-**CONFIRMED unfaithful**: your LDL does NOT match Friedewald (0/1). Modern labs mostly use Martin-Hopkins (a lookup-table equation); a Friedewald recompute would contradict your report. Only derivable if the lab's actual equation were known and implemented.
> > • **QTc** — Bazett vs Fridericia (vs Framingham/Hodges). Matches Bazett on the single available reading (n=1 — no real evidence), and it's an ECG-interval domain apart from the lab-centric app.
> > • **Iron panel — Iron % Saturation, UIBC, Transferrin Percent** — the values are internally consistent (`TIBC = Iron + UIBC` holds 4/4, `Sat = Iron/TIBC` 2/2), so they'd reproduce faithfully *today*. Declined on **provenance**: only two of {Iron, TIBC, UIBC} are independent, and which the analyzer MEASURES vs COMPUTES is unknowable from the numbers — deriving UIBC when the lab measured it would relabel a measured value as computed. Plus thin n (2–4).
> > **Shipped derived metrics carry NO expected-range band** — A/G Ratio (lab reported none — verified `(None,None)`), AST/ALT Ratio (no single-authority reference range; the De Ritis ratio is interpretive), Calculated Osmolality (its clinical role is the *osmolal gap* reference, not judgment against a normal band; the ~275–295 mOsm/kg figure is broadly cited but not single-authority), and NLR (no accepted reference range at all — the whole point of its advisory). Bandless is the honest default, not a gap; a curated band for any would need the same source-verification discipline as a threshold (#8).
> ▸ **DONE — corrected calcium (`816fa22` Phase 1, `c08864e` Phase 2):** `Calcium Corrected = measured Ca + 0.8 × (4.0 − albumin)` shipped end-to-end — the same-draw join (`db.get_joined_series`), the pure `derived.py` registry + compute, the `resolve_series` read seam, `/metrics` injection + write-block, the chart line, and 4 seeded thresholds (hypocalcemia <8.0; hypercalcemia 10/12/14). Raw calcium stays charted as measured; corrected calcium is its own derived series. This moved calcium out of #8 — it was a derived-metric problem, not a raw-calcium threshold problem.
> ▸ **Reusable asset built here: the same-draw join** (`db.get_joined_series` — inner-join on `observed_on`); every future cross-metric feature reuses it. Where a draw has Ca but no albumin → corrected Ca is **UNDEFINED there and the date is OMITTED** (gap-honesty, now a charter rule in `CLAUDE.md`).
> ▸ **DONE — BUN:Cr ratio (derived, REPLACING the stored metric).** `BUN/Creatinine Ratio` shipped as a derived metric (`derived.BUN_CREATININE_RATIO`): the metric resolves to the compute (BUN ÷ Creatinine over the same-draw join, calcium's exact pattern), **dimensionless** (`unit=""` — both inputs mg/dL, so the ratio has no unit; not the lab's `"Ratio"` label). A 0-denominator draw is OMITTED (undefined math → a gap, guarded in `compute_series`, never a crash). Bare line, no thresholds (Phase 1, like corrected calcium); interpretive BUN:Cr ranges stay deferred (surface-don't-diagnose). Rationale: the ratio is a pure function of two stored analytes, so computing it covers every draw that has both (the derived series has **10** points vs. the stored metric's 9 — the lab didn't print a ratio on one draw) and can't disagree with its own inputs; verified the compute reproduces the lab's stored ratio on all 9 shared dates before replacing.
> **Supersede mechanism — the stored metric was DELETED, not just shadowed** (revised from this bullet's earlier "nothing deleted" framing, per the user's "replace the stored one" decision). Keeping the stored rows alongside the derived registry entry would have (a) **double-listed** the name in `/metrics` (the route builds `present` from stored metrics then appends `derived.available` — no dedup guard) and (b) leaked the stale 9-point stored series into `/overview` + the timeline (which use raw series, not `resolve_series`). A backed-up migration (`health.db.bak-*`) deleted the 9 stored obs rows + the `metrics` row (no `metric_config`/`metric_settings` rows existed); the same pass also corrected the dimensionless-unit label `"Ratio"`→`""` on `A/G Ratio` and `Urine Specific Gravity`. Tests: `tests/test_derived_bun_cr.py`.
> ▸ **DONE — Tier A conversions (Bilirubin Indirect, Total Globulin, Non-HDL).** Three metrics a lab reports but always COMPUTES from other stored analytes, converted stored→derived (Bilirubin Indirect = Total − Direct; Total Globulin = Total Protein − Albumin; Non-HDL = Total Cholesterol − HDL, which keeps its ATP III 190 threshold). Faithfulness proven value-free (computed == every previously-stored reading, zero mismatch) before deleting the stored rows (`health.db.bak-tier-a-*`). Non-HDL + Bilirubin Indirect kept their config-backed `metrics` row (Calcium-Corrected shape); Total Globulin's bare row was dropped (BUN:Cr shape). Total Globulin GAINED 3 points (draws with protein+albumin but no separately-reported globulin). Two decisions surfaced by the user drove the final shape:
> > • **Rounding moved DISPLAY-side; floats PRESERVED.** `compute_series` no longer rounds (Tier A `precision=None`) — the raw float rides the API so no drift enters a chained derivation (a future A/G Ratio ÷ globulin). The client rounds via `format.js` noise-tolerant `decimalsOf` (`toPrecision(12)` collapses a binary-float tail); server flag MESSAGES denoise via `analysis._denoise` (round-to-10, leaving every stored metric's message byte-identical). BUN:Cr stays the one source-rounded exception (division → infinite decimals).
> > • **BAND-AS-DATA** (answering "what if my lab's reference range changes?"). The band CANNOT be faithfully computed from the inputs' bands — correlated inputs make interval arithmetic too wide / negative (Indirect = [0.2,1.3]−[0.0,0.4] = [−0.2,1.3] vs the lab's real 0.0–1.0). So a derived metric's reference band is genuine per-draw DATA: captured at import (range kept, value discarded) into the new `derived_reference_range` table (`schema.sql`; `db.get/set_derived_reference_range`) and joined into the computed series by `compute_series(spec, joined, ref_ranges)`. Self-updating — the next report's range overwrites it; a date with no captured band charts without one. This preserves Bilirubin Indirect's 3 `out_of_range` flags (its 0.0–1.0 band rides the computed series). The import path (`/observations/import`) now CAPTURES a derived row's band instead of rejecting it; a derived row with no band is refused (nothing to store — value is computed). Backfilled the current bands from the pre-conversion backup.
> ▸ **Also here: derived metrics reach the cross-metric roll-ups.** `/overview` and `/timeline` previously enumerated stored-only helpers, so a derived metric's flags never surfaced there. A single `api.resolve_derived_series` seam (injected into `timeline.build_timeline`, matching the `all_configs` DI style so `timeline.py` stays registry-free) gives derived metrics parity — their flags rank in the overview and their values appear as lab-panel line items + notable counts. Tests: `tests/test_derived_tier_a.py`.
> ▸ **DONE — AST/ALT Ratio + Calculated Osmolality (NEW computed metrics, not conversions).** Unlike everything above, these had no stored rows to supersede — they compute a standard value the lab doesn't print, appearing once their inputs exist (case-1/case-3 of the rule above). **AST/ALT Ratio** (De Ritis) = AST ÷ ALT (both U/L → dimensionless), a definitional identity like BUN:Cr; recovers the signal the ALT methodology note already points at; `precision=2` (our choice — no lab reports it to match); interpretive De Ritis cutoffs deferred (surface-don't-diagnose). **Calculated Osmolality** = 2·Na + glucose/18 + BUN/2.8 (Na mmol/L, glucose/BUN mg/dL — `requires_units` enforces), a CONVENTION disclosed in its caption (variants exist, e.g. +K); `precision=0` (whole mOsm/kg). Both chart bandless (no reported range). No migration (new metrics). Tests in `tests/test_derived_tier_a.py`.
> ▸ **DONE — A/G Ratio (a DIVISION that composes on a derived metric).** `A/G Ratio = Albumin ÷ Globulin` shipped as derived, but derived from the two STORED analytes directly — `Albumin ÷ (Total Protein − Albumin)` — because Globulin is itself derived and has no stored rows for `get_joined_series` to join. Computing globulin INLINE keeps the intermediate at full float precision (never a rounded globulin), which is the drift-free chaining that display-side rounding buys. Dimensionless (`unit=""`). As a DIVISION it's the source-round exception (like BUN:Cr): `precision=1` — the lab reports A/G to one decimal, verified faithful at 1 decimal on all 9 shared draws (gained 3 more: draws with protein+albumin but no printed ratio). 0-globulin draw → `ZeroDivisionError` → omitted (a gap), never a crash. The lab reported NO reference band for A/G, so it charts bandless (band-as-data has nothing to backfill; a future report's range would be captured). Bare metric (no config/seed_key) → row dropped like Total Globulin. Migration backed up (`health.db.bak-ag-*`).

**7. Per-metric detector config — NO editing UI; RCV becomes a seed-only curation arc** *(RECON DONE + reframed by user decision 2026-07-13; DROPPED the editing-UI premise)* — config lives in the `metric_config` table; rename-survival solved. **The original "editing UI" framing is retired.** Recon + discussion settled that per-metric detector config is *curated published constants*, not personal knobs, so it stays **seed-only** — same home as the threshold curation (#8), no user-facing editor.
> ▸ **User decisions (2026-07-13), locked:**
>   - **Threshold editing → DEFERRED INDEFINITELY.** Thresholds stay seed-only, curated in `metric_config.py` SEED. No add-your-own-lines, no in-place edit. (The recon's safety analysis — a user-typed `definition`/`source` could render AS a curated citation; editing a curated cutoff desyncs it from its reviewed prose — is *why* this is safe to defer, not a loss.)
>   - **No editing UI at all.** RCV coefficients are published reference constants (a metric's within-subject biological CV is universal, not per-lab), so the user would never hand-tune them; a UI is the wrong shape. Seed them like thresholds instead.
> ▸ **RECON — the current stack (verified in code):** per-metric config is the `(metric, key, value)` `metric_config` table; `value` is raw TEXT (JSON for structured keys). The `metric_config.py` registry recognizes **`thresholds`**, **`rcv_cv`** (`{"analytical": float, "intra": float}` — registered, enables `rcv_delta`, seeded by NOTHING today), and **`methodology_note`** (`display_only`, #9). `get_config` splats engine keys into `analyze_series`; `seed_defaults` is the blunt re-seed. **The edit-survival problem is MOOT for the seed-only path:** `seed_defaults` only writes the keys each SEED entry defines, so seeding `rcv_cv` is just another curated key — no provenance column, no schema change, no `delete_metric_config` needed (all of which the retired editing-UI plan required).
> ▸ **THE RCV CURATION ARC (the actual remaining work — parallels #8 threshold curation):**
>   - **Phase 0 — DONE (`this commit`): pin the detector before curating inputs against it.** `rcv_delta` was fully coded + wired into `analyze_series` but had ZERO tests and had NEVER fired (nothing seeds `rcv_cv`); seeding CVs would be the first thing to exercise it on real data. Per the project's discipline (curate against a PROVEN detector, never one being validated simultaneously — as thresholds were), `tests/test_rcv_delta.py` (10 tests) now pins the formula against hand arithmetic + an independent recompute, the two-sided firing threshold in both directions (just-under silent / just-over fires / exactly-on silent), and the `analyze_series` wiring (config → dated `delta` flag; no-config / one-point / censored-last → none). Two deliberate choices locked with code comments: **two-sided z=1.96** (both tails matter on a mixed panel; one-sided is just a z override) and the **large-swing caveat** (the `%` form is the textbook approximation, drifts from the log-transform exact RCV for big multiplies like Ferritin — documented boundary, revisit only on a real wrong-fire). Suite 129 → 139.
>   - **Phase 1 — DONE (2026-07-13/14): CV verification + seed + coverage badge.** 21 metrics seeded with web-verified within-subject CV_I, curated in reviewed batches (each presented + approved BEFORE seeding, same discipline as thresholds). **Sources:** the primary EuBIVAS papers — the summary report (Carobene, *Clin Chem Lab Med* 2021; chemistry/endocrine) and the EuBIVAS-protocol CBC study (Coşkun, 2018; hematology), both **BIVAC grade A** — read directly (the EFLM online database is a JS SPA that WebFetch can't scrape, so the underlying grade-A papers were used instead; each value cross-checked against the paper's own published RCV). CV_A = 0.5×CV_I (desirable-spec, uniform); stored as fractions in `rcv_cv`; injected into SEED via `_RCV_CVI_PERCENT` (one readable table, merges with existing threshold/note entries). **Seeded (21):** Hgb, Hct, RBC, MCHC, MCH, MCV, Platelet, WBC, Lymphocyte Abs, Monocytes Abs, Neutrophils Abs (heme) + Calcium, Albumin, Total Protein, Potassium, Creatinine, ALP, ALT, AST, TSH, Bilirubin Total (chem). **HELD — Sodium (CV_I 0.53%) / Chloride (0.98%):** the tight-RCV concern proved REAL for these — CV_I is below achievable analytical precision, so RCV would flag measurement noise not physiology (they're range-anchored anyway); the MCV/MCH/MCHC tight cases were KEPT because modern analyzers genuinely hit the sub-0.2% precision that makes their ~2% RCV real (verified: on live data MCV/MCH did fire, discriminating not over-firing). **DEFERRED — Ferritin / Urea(BUN) / CO2 / RDW-CV:** no BIVAC grade-A source (RDW-CV: the source reports the distinct RDW-SD); principle set — RCV seeds from grade-A sources only, don't fudge. Sub-<5-numeric metrics deferred (CV constant is stable whenever added). **Coverage badge:** `MetricCoverageOut.has_rcv` + a quiet violet `RCV` pill on the Settings → Metric coverage roster (backend route computes it; TSH shows source + badge, the coexistence case). Verified live: 21/140 badged, RCV fires on 4 real metrics (ALT/MCH/MCV/TSH). Tests: `test_rcv_seed.py` (8) pins the exact-21 set, held/deferred absence, the desirable-spec shape, end-to-end firing via `/flags`, and the coverage flag; two `test_methodology_note.py` assertions relaxed from `==​ {}` to "no display-only key leaks" (Creatinine/Calcium/LFTs now legitimately carry rcv_cv alongside their notes). Suite 139 → 147.
> ▸ **Out of scope (stays global, already has the tabbed Settings home):** the analysis.py tunables (`personal_baseline_z` z-watch/z-high, `linear_trend`/`mann_kendall` alphas, `rcv_delta` z) are GLOBAL, not per-metric — a separate, smaller settings.py extension if ever wanted, not part of #7.
> ▸ **Adjacent bug found during recon (NOT #7) — FIXED (`ce23611`).** `demo.py` had hand-built thresholds in the obsolete `[cutoff, source]` tuple shape while `clinical_threshold_crossing` now requires the `{cutoff, source, direction, boundary}` dict shape (the real app path converts via `metric_config._threshold_pairs`; only `demo.py`, which bypasses it, had rotted). Updated its hand-built thresholds to the dict shape; the smoke check runs clean again and trips all three detectors.

**8. Threshold-config curation (more guideline cutoffs)** — research + seed cutoffs for more metrics. **No remaining NAMED metric; open-ended for future cutoffs as they're verified** (each is SEED prose on the existing pipeline — see the seeded set in "Built so far").
> ▸ **Resolved (curation arc):**
> • **Glucose Serum/Plasma** — seed casual `≥200 up` (ADA, Standards of Care 2026; random/symptomatic criterion, fasting-independent). The existing fasting skip (100/126) **stands** — these are different lines, not a reversal.
> • **Ferritin Serum/Plasma** — seed `<30 down` (unified sex-independent iron-deficiency lower limit; Pasricha/Lancet 2021, lab adoption, ASH draft). Single low line; skip the overload bound (where the sex-split lived). Softer source tag — choose acronym deliberately.
> • **TSH** — seed three graded lines: `0.4 down` (established), `4.5 up` (**contested** — prose: "above typical range; significance debated, depends on free T4"), `10 up` (overt-hypothyroid, established). Rendering of established-vs-contested depends on #15. **(DONE: seeded; 4.5 now renders dashed + `status_note=contested` via #15.)**
> • **BUN (Blood Urea Nitrogen)** — **deferred, leaves #8.** No robust single-authority threshold exists; its ambiguity is intrinsic (a high BUN can be GI bleed + dehydration with fine kidneys — no value resolves on its own). Charted, never flagged. Gets a methodology note (#9), not a threshold. *(Signal now recovered as the derived BUN:Cr ratio, #6 — DONE.)*
> • **Calcium Serum/Plasma** — **leaves #8 → becomes #6** (corrected calcium derived metric).
> ▸ **Documented skip-decisions (carry-forward):** Glucose fasting 100/126 (fasting unconfirmed), Creatinine (no sex-aware cutoff mechanism), BUN (context-only, no single-authority threshold). **RESOLVED — C-Reactive Protein:** the standard assay stays note-only, but its "revisit with a true hs-CRP assay" condition was MET (2026-07-20) — the separate `C-Reactive Protein High Sensitivity` metric now carries the AHA/CDC `<1 / 1–3 / >3 mg/L` tertiles (Pearson 2003; `tests/test_hscrp_seed.py`). *Full rationale + the citation-status taxonomy: `CLAUDE.md` → "Threshold curation discipline" (the authoritative copy code comments reference).*

**9. Per-metric methodology note** *(FULLY CLOSED — infrastructure + Tiers 1–3 done, 20 notes shipped)* — curated per-metric prose for metrics whose interpretation depends on another.
> ▸ **DONE — the display-only lane.** `methodology_note` is a `display_only` key on `MetricConfigDef` (`metric_config.py`): seeded/stored through the normal path but EXCLUDED from `get_config`'s engine kwarg splat by `_cast_raw`, so it can never reach `analyze_series` (detect-side boundary holds). Read via `get_methodology_note`; surfaced additively on `ChartConfigOut.methodology_note` via `/chart-config`; rendered above the chart in `MetricsPage.jsx` reusing the `metrics__derived-note` style. Prose is descriptive / method-as-subject, non-diagnostic — same boundary as threshold definitions. A metric may carry a note WITH or WITHOUT thresholds (the coexistence case).
> ▸ **DONE — Tier 1 (`fbabdcc`), note-only metrics:** **BUN** → "context-only; interpret with creatinine / BUN:Cr ratio; not independently flagged" (makes BUN's #8 deferral graceful, not a silent omission); **Creatinine** → "read alongside eGFR; depends on sex and muscle mass, not renal function alone"; **Calcium Serum/Plasma** → "interpret with albumin; corrected calcium is derived (#6); ionized is the gold standard this approximates."
> ▸ **DONE — Tier 2 (`c344f89`), note ALONGSIDE thresholds:** **LDL Calculated** (Friedewald calculation, unreliable at high TG / very low LDL; direct LDL is the reference); **Testosterone Total by LC-MS/MS** (SHBG dependency; free T is the more direct measure — points at the threshold note for the morning-draw caveat rather than repeating it); **Glucose Serum/Plasma** (fasting-state dependency; the ≥200 line is random/symptomatic, 100/126 unseeded); **Estimated GFR** (itself a CKD-EPI estimate from creatinine/age/sex). (7 notes through Tiers 1–2.)
> ▸ **DONE — Tier 3 (`5c516e8`), the "context-only metric" category (13 notes):** **iron studies** (Iron Serum/Plasma, Total Iron Binding Capacity, Iron % Saturation, Transferrin, Transferrin Percent, Unsat. Iron Binding Capacity — read the panel together, not in isolation); the **LFT panel** (Alkaline Phosphatase Total, Alanine/Aspartate Aminotransferase, Bilirubin Total/Direct/Indirect); **CRP** (standard assay, not hs-CRP — no risk cutoffs seeded). All note-only. The 4 LFT notes for AST + the bilirubin fractions were **softened to drop pathophysiology/cause vocabulary** ("hemolytic", "post/pre-hepatic", "muscle injury") — naming what an abnormal value is caused by is diagnosis even stated generically; the notes describe how to read the panel, not what's happening in the body (surface-not-diagnose boundary). **20 methodology notes shipped total (3 + 4 + 13); #9 is closed.**

**10. Allergen bloodwork — find a data home** *(MECHANISM RESOLVED 2026-07-22 by metric groups, `35e4068` — see "Done this session"; curation of an actual allergen panel is open)* — per-allergen IgE panels; one-metric-per-allergen vs. grouped panel (dozens–hundreds of metrics stress the flat picker).
> ▸ **The open question was the PICKER, and it now has a general answer.** `metric_group` clusters arbitrarily many metrics under one `<optgroup>` heading, so the one-metric-per-allergen shape (the honest one — each allergen is genuinely its own analyte with its own band and its own series) no longer costs picker legibility. That was the only structural objection; nothing new needs building. What remains is DATA work when an allergen panel is actually entered: pick the group label, and decide whether the lab's per-allergen class scores (0–6) enter as numeric or qualitative.

**11. 24-hour urine metrics — a data home** *(Phase 1+2 DONE 2026-07-17 — backend verified; entry UX built + build-checked, needs an eyeball. Phase 3 display + PDF/threshold deferred.)* — rate-over-collection-period results.
> ▸ **The finding that shaped it:** most of a 24h result already fits the existing model — the meaningful value is a RATE and **the unit carries the period** (`mg/24h`), `observed_on` is the collection's **completion date**, and the per-24h reference band rides band-as-data. The only genuinely-homeless data is the collection's shared **volume/duration/start**. So this is NOT a new metric shape — it's a provenance record the analytes point at.
> ▸ **Design = a `collections` table + FK, mirroring `documents`** (the "source a reading came from"), NOT nullable columns on `observations` (which would duplicate volume/duration across every analyte row and invite drift). A timed collection stores volume/duration/dates ONCE; each analyte is a normal `observations` row linked by `collection_id` (nullable). Recon de-risked the migration: SQLite adds `collection_id INTEGER REFERENCES collections(id)` via a plain additive ALTER **and enforces the FK** — no table rebuild (we'd just pruned one). The metadata is CONTEXT: it lives in the `collections` table, not the series row, so it **structurally can't reach `analyze_series`** (which reads only value/observed_on/ref/result_type) — the rate value flags normally.
> ▸ **Decisions locked + shipped:** create-first (make the collection, then add analytes to it), refuse-delete-while-non-empty (`CollectionInUseError` → 409, like the rename merge-refusal), store duration (nullable). **Phase 1 (backend):** `collections` table + `observations.collection_id`; `db` CRUD (`add/get/list/update/delete_collection`, `list_collections` carries `n_readings`); `collection_id` threaded through `add_observation` + surfaced in `get_series`/`ObservationRow`; `POST/GET/PUT/DELETE /collections`; a bad `collection_id` on an observation → clear 404 (not the misleading duplicate). `tests/test_collections.py` (8). Sweep: only `/observations/*` changed (additive `collection_id: null` on every reading), no other endpoint, no adds/removes. **Phase 2 (entry UX):** `CollectionModal` (create a collection) + a "Timed collection" selector in the add form (none / existing / + New) that fixes the reading's date to the collection's completion date and rides `collection_id` on save.
> ▸ **DONE — Phase 3 display (2026-07-17):** (1) **picker grouping** — a metric with ≥1 collection-linked reading (`MetricInfo.in_collection`, an EXISTS in `list_metrics_with_units`) renders in a "Timed collections (24h)" `<optgroup>`, the same mechanism derived metrics use ("Computed metrics"). This is the clean answer to the user's name-prefix workaround: analytes cluster visually *without* a `24Hr Urine - ` prefix. (2) **Readings-table "24h" chip** — a row with a `collection_id` shows a quiet violet chip hovering to its collection's volume/duration/completion (`collectionById` map from `GET /collections`, threaded through `MetricsPage`). Sweep: only `/metrics` changed by CODE (the `in_collection` field); everything else in that capture was the user's own two collections entered live. Also this pass: **range display now spaces the hyphen** (`1000 – 2500`, not `1000-2500`) in the readings-table Normal column + the export preview (the chart tooltip already did) — dates stay `YYYY-MM-DD`, untouched.
> ▸ **DONE — Tier A follow-ups (2026-07-17):** (A1) **`started_on` input dropped** from `CollectionModal` — it's derivable (completion − duration); the nullable column stays for the rare irregular case. (A2) **Collections management UI** as a **tab on the Profile page** (the reusable `Tabs` + `?tab=` idiom from Settings; `CollectionsManager` lists/edits/deletes, delete gated to empty collections showing "locked"); `CollectionModal` gained edit mode. (A3) **Display aliases** set on the 8 entered 24h analytes (`Urine Copper (24h)` / `(per Cr)` / `(per vol)`, etc.) — the lab's "per Ration CRT" typo now DISPLAYS as "(per Cr)" while the canonical stays the lab's literal wording (import-match-safe); the Phase-3 optgroup handles grouping, so the `24Hr Urine -` prefix is no longer needed for it. (A4) **Timeline line for collections** — `build_collection_entries` (a `kind="collection"` entry at `completed_on`, linking to the Collections tab; violet chip, base prominence, floats de-`.0`'d), the frontend `KIND_META`/`KIND_ORDER` entry (chips auto-derive). Suite 227; sweep = only `/metrics` (aliases) + `/timeline` (collections) changed.
> ▸ **Still deferred:** PDF-import parsing of 24h panels; per-24h **thresholds** (#8).

**12. FHIR import path** (source/loinc columns already exist) — raw-doc extraction must run locally; imported rows need review-before-save.

**13. Package as a desktop app** — Tauri wrapper + PyInstaller-bundled backend. Depends on #14.

**14. Self-hosted server for multi-machine use** — backend on one always-on machine, frontend anywhere on LAN/VPN; one `health.db`, no cloud sync. Interlocks with #13.

**15. Threshold display semantics** *(DATA PLUMBING + CONFIDENCE/STYLE DONE; valence deferred)* — encode a threshold's *status*, not just its position. Two per-line display-only fields threaded seed → `get_thresholds_detailed` → `ThresholdOut` → `/chart-config` → `MetricChart` (commits `97e6dc0`/`e018523`/`ca60724`; sweep-verified — 11 `/chart-config` diffs, fields-only; the engine's `_threshold_pairs` ignores them, so the detect-side safety boundary held).
> • **DONE — `render_style`** (`solid`|`dashed`, default `solid`): drives the threshold `ReferenceLine` stroke — the roadmap's original **confidence → solid/dashed** channel.
> • **DONE — `status_note`** (closed set `contested` / `soft-source` / `caveated` / `substantively retired`, default null): an *explanatory* label in the legend/tooltip (NOT the stroke). Purpose-built because the a–e citation taxonomy couldn't express contested/soft/caveated — only `substantively retired` is reused verbatim (CLAUDE.md category d). **Resolves the one-vs-two-fields open decision → TWO fields**, but split *presentational* (`render_style`) vs *explanatory* (`status_note`) rather than the originally-imagined valence/confidence pair.
> • **Applied:** TSH 4.5 → dashed + contested; Vitamin D 30 → solid + substantively-retired; Ferritin 30 → solid + soft-source; Testosterone 300 → solid + caveated. (Vitamin D deliberately kept solid — "retired" ≠ a distinct dash glyph this pass.)
> • **DEFERRED — valence not built.** The other half — **valence (concerning vs protective → color)** and its motivating **protective HDL ≥60** line (which must NOT trip the downward-firing detector — an engine/seed concern) — is unshipped; no color channel exists yet. Revisit with the protective-line use-case.
> ▸ Styling lives on the rail + in-plot `ReferenceLine` (the rail merge from "Done this session"), not a new surface.

**16. Clinical-context interpretation tier** *(BUILT → REPURPOSED → dead code REMOVED 2026-07-15)* — a per-metric, on-demand, local-model reasoning tier (charter: `CLAUDE.md` "The interpretation tier"). Backend (`explain.py`, `/explain` route, gateway `explain_metric` allowlist) shipped in `688a2d5`; the frontend `InterpretationPanel` (violet-tinted callout, three states — reasoning / nothing-notable skip / unavailable) shipped in a following commit.
> ▸ **Finding, post-eyeball-test:** as an always-on INLINE block beneath the deterministic summary, the interpretation tier is LOSSY relative to the deterministic layer around it — a small local model (llama3.2) restating/reasoning over already-precise cited facts adds hedging and imprecision where the chart/legend/flags are already exact. The two-tier structural separation (grounded vs. reasoning, CLAUDE.md) held and did its job — nothing leaked as a false fact — but the *inline* placement undersells the deterministic picture it sits next to.
> ▸ **Decision: REPURPOSE, not retire.** The real value isn't a permanently-visible local-model paragraph — it's the ASSEMBLY (`explain.assemble_explain_context`): a deterministically-gathered, richly-structured, per-metric bundle (series, engine findings + stats, cited thresholds with `gap_to_cutoff`, personal baseline, methodology note, latest change). That bundle is the right shape to become the **Phase B export payload** — handed to a strong EXTERNAL model (which doesn't have the small-local-model precision problem) through the gateway's hosted path (#1/#2), under explicit per-action preview/confirmation, rather than silently rendered inline from a weak local one.
> ▸ **Kept as-is (backend):** `explain.py`'s assembler, the proximity-band skip logic, and the bundle shape — these become Phase B's payload-building block, effectively unchanged. **Retired as a default UX:** the always-on inline `InterpretationPanel` callout is NOT an endorsed shipped feature — it stays in the tree (committed, not reverted) but its fate is Phase B's export-preview surface, not a permanent inline chart-page element. **RESOLVED (Phase B (b) sub-unit 4, `0e29785`):** `ExportPanel` took over the interpretation slot in `MetricsPage.jsx`; `InterpretationPanel`'s code stays in the tree, intact and callable, but its UI trigger is gone — the dead-inline local tier is formally superseded as a UI surface, exactly as this item anticipated.
> ▸ **Scope discipline held:** single-metric only (Phase 1 as designed); local-only (no data left the machine); the model-never-sources-a-number invariant held throughout testing.
> ▸ **DONE — dead code REMOVED (2026-07-15).** After the export handoff superseded it as a UI surface AND made its runtime path unreachable (its engine resolved from the `in_program`-only summarizer enum, but `explain_metric` required `ollama`, so `/explain` always returned "unavailable"), the local tier was removed as a clean, zero-dead-code pass on the privacy chokepoint: `explain.explain_metric` + `_terse` + `ExplainResult` + `_NOTHING_NOTABLE`, the `/explain` route + `ExplainOut`, `InterpretationPanel.jsx` + `getExplain`, and — since nothing then reached it — the gateway's **entire `ollama` engine** (`_ollama_call`/`_ollama_prompt`/the registry entry/the `_local_call` branch). **Kept (all export-live):** `explain.assemble_explain_context` + `EXPLAIN_SYSTEM`/`FRAME` + `_proximity_scale`, and the gateway `explain_metric` *task* (the export path is now its only caller). `proximity_skip` retained as a tested pure utility (currently unused). Proven safe: full pytest (160) green, and the sweep byte-identical (717 matched / 0 differing) since `/explain` was excluded+never-enumerated and everything removed was unreachable. The interpretation-tier CHARTER stays — it now governs the export handoff (see the status note added to CLAUDE.md's "The interpretation tier"). Minor tail left: a few dead `.interp__*` CSS rules (entangled with the live `.interp__text`).

**17. Data-quality: a z-score reading stored as qualitative text** *(FIXED 2026-07-15)* — A z-score metric had one reading with `result_type='qualitative'`, `value_text='1.5'` — a plain number stored as categorical text, an import artifact (surfaced during the #4 qualitative-timeline recon: it was the one "qualitative" value that was actually numeric). **Fixed** by a backed-up one-row data correction (obs `id=283` → `result_type='numeric'`, `value=1.5`, `value_text=NULL`; unit stays `''`, no ref range — a dimensionless Z-score); it now charts as a numeric point instead of a "1.5" badge. Verified the other qualitative rows are legitimately categorical (HIV/Covid/cultures/urinalysis) and the `0-5`/`0-2` microscopy rows are the deliberately-kept range-as-text case — none changed.

**18. Sex-aware detection** *(Phase 1 seam DONE; Phase 2 DONE 2026-07-14 — three curated variants: Testosterone gating, white-cell RCV sex-keying, WHO hemoglobin anaemia thresholds; further curation OPEN)* — let the profile's biological `sex` select which curated detector config applies, so sex-specific thresholds/RCV can exist. Surfaced during the #7 RCV curation (white-cell CV_I differs by sex) and long-latent in the threshold work (the creatinine skip was justified by "the detector has no sex field to vary a cutoff on"). This is the deliberate arc that adds that field.
> ▸ **What it crosses (the reason it's a scoped arc, not a small change):** CLAUDE.md's Profile charter states profile data "feeds NO analysis, flag, or detection logic — it never enters the analysis engine" (the one carve-out, charting weight, is display-only and explicitly does NOT touch the detect side). This arc makes **`sex` (only)** the first profile field to enter detection — a deliberate, documented charter exception in the same spirit as "The interpretation tier" and "The export handoff," added to CLAUDE.md **at build time**, not now. DOB stays out; weight/height stay display-only. It is an INTERNAL analysis boundary, not a privacy-egress one — sex never leaves the machine.
> ▸ **Architecture — resolve at the config layer; the engine stays sex-blind (verified against the call sites).** Detection runs from four `api.py` sites (`/flags`, `_gather_explain_substrate` → /summary+/explain+/export, `/summary`, and the timeline/overview `current_flags`), all as `analyze_series(metric, series, personal_baseline_mode=mode, **metric_config.get_config(conn, metric))`. The clean seam is NOT to give `analyze_series` a `sex` param (that would break "the engine takes plain numbers") — it's to make **`get_config` / `get_thresholds_detailed` sex-aware**: they read `db.get_profile(conn)["sex"]` and, for a metric whose stored config carries sex-variants, return the matching numbers; the engine still just receives whichever `thresholds`/`rcv_cv` apply and never learns sex. The "profile→detection" crossing is thus confined to the config resolver. Storage is additive (the `metric_config` value is already free JSON): a threshold line gains an optional `sex` tag (`{cutoff, source, direction, boundary, definition, sex: "male"}` → shown/flagged only when profile sex matches; untagged lines apply to everyone), and `rcv_cv` can become sex-keyed (`{"male": {...}, "female": {...}, "default": {...}}`). **Fallback = today's behavior:** sex `null`/`"other"`, or config with no sex-variants, resolves exactly as now — so every current metric is byte-identical until a sex-variant is seeded.
> ▸ **Analysis-safety:** a sex-specific cutoff is still surface-don't-diagnose — "relative to [sex]'s reference framework," source + cutoff + framework vocabulary, curated with the same discipline as every threshold (#8). Sex-GATING a line (e.g. showing the testosterone 300 line only for males) is *more* honest than today's show-it-regardless-with-a-prose-caveat. No new diagnosis, no new number the engine sources.
> ▸ **PROPOSED PHASING:**
>   - **Phase 1 — the seam (backend, ZERO behavior change). DONE (2026-07-14).** Refinement from the scoped plan: the call sites did NOT need threading — `get_config`/`get_thresholds_detailed`/`all_configs` already take `conn`, so they read `metric_config._profile_sex(conn)` INTERNALLY and the four detection sites + `/chart-config` are untouched. Thresholds filter on an optional `sex` tag in `_cast_raw` (then STRIP it so the engine shape is byte-identical) and in `get_thresholds_detailed`; `rcv_cv` may be sex-keyed (`{"male","female","default"}`), resolved in `_cast_raw` with `default` fallback (no match + no default → kwarg omitted). Charter exception added to CLAUDE.md's Profile section (Exception 2). Pinned by `tests/test_sex_aware_config.py` (7 tests: sex-independent config identical across male/female/other/null; sex-tagged thresholds + display reader filter per sex; sex-keyed `rcv_cv` resolves with default fallback / omits when neither matches; flat `rcv_cv` passes through). Sweep byte-identical (717 matched, 0 differing). No curation yet.
>   - **Phase 2 — first curated instances. Testosterone DONE (2026-07-14):** the AUA 300 line in `Testosterone Total by LC-MS/MS`'s SEED now carries `sex: "male"` — shown/flagged only for a male profile, hidden for female/other/null (replacing the old shown-regardless-with-an-"in adult men"-prose-caveat). Pinned by `tests/test_sex_aware_config.py` (SEED-level + end-to-end per-sex resolution). Note: for a MALE profile this is output-invisible (the line still shows), so it's a no-op for a male profile and in the sweep — the behavior change manifests only for a non-male profile. Remaining candidates (RE-RANKED 2026-07-14 after a curation pass — the earlier "HDL 40/50" framing was WRONG):
>     - **HDL — INVESTIGATED & DECLINED, stays sex-independent.** The curated HDL entry deliberately uses one cutoff (40 mg/dL, both sexes) = ATP III's low-HDL *risk-factor* line. The `<40 men / <50 women` split is ATP III's **metabolic-syndrome** criterion — a ≥3-of-5 syndrome definition the app does NOT model — NOT the low-HDL classification. Seeding 40/50 would misattribute the syndrome number to the risk-factor line (a curation violation), so HDL is NOT a sex-variant. (This corrects this bullet's own earlier "40/50 low-HDL split" claim, which contradicted the SEED comment; the SEED was right.)
>     - **White-cell RCV (WBC / Neutrophils / Monocytes) — DONE (2026-07-14).** Sex-keyed `rcv_cv` seeded from Coşkun 2018 Table 2, read DIRECTLY from the PDF (the user downloaded it; primary web fetch stayed 405/403-blocked, so the Read/pypdf path unblocked it): male **7.96 / 11.07 / 11.60**, female **12.82 / 15.33 / 20.09** (CV_I %). **No `default`** — a null/'other' profile OMITS RCV for these three (defer-don't-fudge: the noise band genuinely can't be picked without sex). **FINDING:** the old flat values were the MALE column all along, mislabeled "sex-pooled"; monocytes corrected 11.08→11.07. Sweep byte-identical for a male profile (male band ≈ the old flat value); the female band is the new behavior. Lymphocytes stay flat (its CV_I doesn't differ by sex per the same table). Pinned by `tests/test_rcv_seed.py` (sex-keyed shape + verified values + per-sex resolution).
>     - **Hemoglobin anaemia thresholds (WHO) — DONE (2026-07-14).** Seeded two sex-tagged lines on `Hemoglobin` (was threshold-free): `<13.0 g/dL` male / `<12.0 g/dL` non-pregnant female (130/120 g/L), down-direction, exclusive boundary, `source: "WHO"` (new `SOURCES["WHO"]`, citation URL fetch-verified live). The 2024 WHO guideline REAFFIRMED both adult cutoffs (living/reaffirmed, category b). This is the first sex-variant where the CUTOFF VALUE differs by sex (male→13.0, female→12.0, null/'other'→neither), and the FIRST #18 change VISIBLE for a male profile: the 13.0 gridline draws on the Hgb chart (no flag when the readings sit above it). Hematocrit NOT seeded (WHO defines anaemia by Hgb; no single-authority Hct cutoff). Pinned by `tests/test_sex_aware_config.py`; sweep re-promoted (2 diffs: /chart-config/Hemoglobin + /metrics-coverage).
>     - **Ferritin** — the iron-OVERLOAD upper bound is where a sex split could live, but the current seed deliberately uses the unified-30 *low* line (ASH); not pursued now.
>     **NOTE — creatinine is a WEAKER instance than the skip implied:** even sex-aware, raw creatinine has no single-authority guideline *cutoff* (only lab reference ranges, already stored per-reading), and eGFR already covers the kidney signal sex-normalized — so creatinine likely stays note-only even after this arc. Don't treat the creatinine skip as the motivating payoff; testosterone (done) and WHO hemoglobin are the real ones.
> ▸ **Worth it? (honest framing under the don't-foreclose filter.)** This is genuinely MULTI-USER-shaped (every user has a sex) and survives unchanged into a multi-user product — exactly the kind of infrastructure the ROADMAP filter says to prefer. For the SINGLE user today the practical gain is modest (they know their own sex; the prose caveats partly cover it), so it's well worth SCOPING but not urgent to BUILD — a good pick-up when a sex-specific threshold is concretely wanted (most likely testosterone), not before.

---

## Dropped: the PDF importers *(2026-09-19, user decision)*

**Removed:** `pdf_import.py` (flat text-stream lab extraction + OCR), `lab_extract.py`
(geometry/bounding-box extraction from scanned tables), `import_cleanup.py` (the hosted
name/unit cleanup pass, roadmap #3), the routes `POST /import/pdf`, `POST
/observations/import`, `POST /import/cleanup/preview|confirm`, `GET
/documents/{id}/labs`, the gateway's `cleanup_import` allowlist entry, `PdfImport.jsx`,
`ImportCleanup.jsx`, their CSS, and four test files. ~1,400 lines net.

**Why:** the extractor missed roughly three times in four, and its purpose was always
bulk-loading the owner's own back-catalogue — a one-time job, now done. Keeping it meant
carrying a per-lab-layout parsing treadmill (a bespoke Italian parser already existed)
and a Tesseract system dependency in the install story of a project heading toward
public release.

**Kept deliberately:**
- `ocr_util.py` — the three Tesseract-locating helpers lifted out of `pdf_import`,
  because `ingest_documents.py` (the offline document-store builder) still needs them.
  It is a DEVELOPER tool; the running app imports none of it, so Tesseract is no longer
  part of the product's install story and `pypdf` moved out of core `requirements.txt`.
- The Documents page, `docstore.py`, `reports.py`, full-text search — all untouched.
  Reading scanned records is a different feature from importing readings out of them.
- `db.set_derived_reference_range` — see the known gap below.

**Archived, not lost:** `archive/pdf-extractors` (branch) and the
`archive-pdf-extractors-20260919` tag hold the full working code. The geometry approach
in `lab_extract.py` was the better of the two and is worth re-reading before anyone
attempts import again.

**Known gap this opened.** `POST /observations/import` was the ONLY production writer of
a DERIVED metric's reference band (`derived_reference_range`). Bands already captured
still ride their computed series and still flag normally — nothing regressed — but there
is now no UI path to record a NEW band when a lab changes its interval for a derived
metric (Bilirubin Indirect, Total Globulin, Non-HDL, A/G Ratio). `db.set_derived_reference_range`
is retained and tested, so the fix is a small entry-form addition whenever it's wanted.
Flagged rather than silently accepted, because band-as-data was a deliberate design and
this quietly removed half of it.

## Dropped: the document ingest tool and all OCR *(2026-09-19, user decision)*

**Removed:** `ingest_documents.py` (bundle splitting + OCR + `reocr`), `ocr_util.py`,
`requirements-ocr.txt`. With the PDF importers already gone, this was the last thing in
the project that ran Tesseract — **the codebase now has no OCR and no PDF parsing at
all**, and `requirements.txt` is numpy, scipy, fastapi, uvicorn, pydicom, Pillow.

**What is NOT affected:** `documents_store/` itself, `docstore.py`, the Documents page,
and full-text search. The store is already built — PDFs, text sidecars and manifest are
on disk — and serving it needs no OCR. Reading records is a different feature from
transcribing them.

**The consequence, stated plainly:** the document store is now **read-only**. There is
no supported way to add a new scanned bundle to it, or to re-transcribe what is there.
Doing either again means restoring the tool from `archive/document-ingest` (tag
`archive-document-ingest-20260919`) or writing a new one.

**Search was made language-agnostic in the same pass.** Accent folding was a hand-written
table of the characters one corpus happened to contain, which silently did nothing for
any language outside it. It now asks Unicode to remove diacritics from any letter, per
character so the length invariant that lets folded offsets index the original text still
holds, plus a short closed set for letters whose stroke is inside the glyph (ø, ł, đ, ħ,
ı, ſ). `snippets()` precomposes to NFC first, because a per-character fold is blind to a
diacritic stored as a separate combining mark — "e" + U+0301 would have survived folding
and missed. Verified across Italian, Czech, Polish, Turkish, Vietnamese (decomposed),
Spanish, French and Norwegian. One known, documented miss: German ß, because folding it
to "ss" is one character to two and would break the offset invariant.

## Done this session
- **Translation removed; search is OCR's only consumer (2026-08-01, later).** Four
  user-directed changes, plus a negative result worth more than the changes.
  • **Translation SCRAPPED ENTIRELY** — `translate.py`, `tests/test_translate.py`,
    `requirements-translate.txt`, both routes, the UI. It was a second error layer stacked
    on OCR ("a machine translation OF a scan read by OCR"), and its `available()` probe was
    also the ~10 s stall on the first Documents load after a restart. `argostranslate` and
    its torch dependency are now unreferenced — uninstalling them reclaims ~3 GB, left to
    the user since it is their environment.
  • **"Original PDF" link removed** — the PDF is embedded in the reader, so a button
    opening the same bytes in a tab was a second route to what you are already looking at.
  • **Search collapsed to a magnifier on the right**, expanding on click and hiding the
    type filter while open (relevance order replaces type order; both would fight over the
    list). Closing clears the query — a live filter behind a collapsed icon hides why the
    list is short. Placeholder is language-neutral: the corpus will be bilingual.
  • **"Make the OCR better for search" was measured and DECLINED.** `tessdata_best` across
    all 47 documents came out a WASH — 337 → 331 recoveries of known boilerplate, better on
    some terms and worse on others, for 2.4× the runtime. What survived instead is
    *tolerating* the errors at match time: search is now two-pass, exact first and a
    confusable-glyph fold (`1/i/|→l`, `0→o`, `5/$→s`, `8→b`) only if that finds nothing,
    flagged `approximate`. Fallback rather than default because folding buys ~1 extra
    document across real queries while `50`→`so` will match English prose once English
    records land.
  • **THE CAUTIONARY RESULT (read this before trusting a benchmark here).** A 5-page A/B
    said `tessdata_best` at scale 4.0 beat the baseline. Re-OCRing the whole corpus showed
    it was **8.9% WORSE** and had lost 6.8% of the text. Two mistakes at once: five pages
    was far too small a sample, and it moved TWO variables (model and scale) together —
    isolating them showed scale 4.0 was the culprit and the model was ~flat. The store was
    restored from backup. `ingest_documents.py` now exposes `HEALTH_TESSDATA` /
    `HEALTH_OCR_SCALE` so any future change is A/B'd against the FULL corpus.
  • `ingest_documents.py` promoted from a scratch script to a repo tool (`split` / `reocr`).
    Suite 440 → 421 (translation's 23 tests removed, 4 search tests added).
- **The scan is the document; OCR demoted to plumbing (2026-08-01).** Prompted by the user
  asking "should we just scrap OCR and display the PDF — what's the benefit of transcribing?"
  The answer was that the reader had it BACKWARDS: it rendered the OCR transcription as the
  default view with the PDF behind a button, i.e. it put the lossy derivative in front of the
  reader (on real scans a vertebral level like `L3` transcribes as `13`) with the authoritative copy one
  click away. Now the PDF is embedded inline as the only view of a document and the raw
  transcription is **never rendered as prose**. Text is retained for exactly the two jobs a
  PDF cannot do:
  • **Translation** — the one place text is still shown, because there is no translated PDF.
    It replaces the scan rather than sitting beside it, and for an OCR'd document is labelled
    as TWO lossy steps (a machine translation of an OCR read), which the old banner didn't say.
  • **Search** — `GET /documents/search?q=` across both stores, ~11 ms over the whole 420 KB
    corpus, no index. 47 documents over 221 pages are unnavigable without it. A snippet is
    styled as a quiet LOCATOR into the scan, never as the document's content.
  **This DROPPED the OCR-tuning project rather than building it** — once the scan is what you
  read, accuracy only has to be good enough to translate and search. Everything below was
  measured first and then deliberately not shipped, which is the point of recording it:
  • Preprocessing is ACTIVELY HARMFUL. Otsu binarization: confidence 82.9 → 78.4. Unsharp
    mask: lost 13% of the text. Tesseract's LSTM wants greyscale; the folk advice is wrong.
  • PSM tuning (4, 6): no gain. Resolution 2.5 → 4.0: +2 anchors, marginal.
  • `tessdata_best`: +13% anchor recovery (23 → 26) for 2.4× the time. Real but not worth a
    re-ingest once the PDF is the reading surface.
  • **EasyOCR is 22% WORSE** than the current setup (18 anchors vs 23) at 3× the cost — it is
    built for scene text, not document scans.
  • **Surya abandoned mid-install:** pulled `openai` + `transformers`, downgraded Pillow under
    the DICOM viewer, then demanded a separate `llama-server` native binary. Venv fully
    reverted afterwards and re-verified (Pillow back to the pinned 12.3.0, 434 tests green).
  • Structural finding worth keeping: OCR errors here are PAGE-DEPENDENT, not systematic — the
    same admission diagnosis is printed 9× and transcribed correctly at least once. Cross-page
    consensus voting would beat any single-pass engine on this corpus. Not built (unnecessary
    now), but it is the right idea if text ever becomes load-bearing again.
  `tests/test_docstore.py` 10 → 16; suite 434 → 440.
- **Italian hospital record: parsed, split, and surfaced (2026-08-01).** Two halves.
  • **Data entry (user-approved, review-before-save).** The 2025-06-20 trauma event's notes
    ended with "and additional injuries"; OCR of the Florence discharge summary + total-body
    CT gave the real list. THREE CORRECTIONS: the cervical fracture is **C4, not C5**; the rib
    fractures are **left**; the carotid dissection is the **left** ICA. SIX injuries were
    missing entirely (liver lacerations, pancreatic head hematoma, left kidney fracture,
    hemoperitoneum, bilateral pneumothorax, pulmonary contusions). 16 conditions added
    (5 monitoring, 11 resolved). The user's own account of the fall time (~23:45 on the 20th)
    was kept over the record's 02:34 intake timestamp, with both recorded.
    **Deliberately NOT attributed:** the US follow-up CT found wedge deformities at T6-T10,
    but calls every level "age-indeterminate" and the same scan notes exaggerated kyphosis on
    scoliosis documented since 2020 — so they are surfaced as a question, not assigned to the
    trauma. Facility and clinician names were kept OUT of the DB: event notes and conditions
    now ride in the full-picture export payload, so not storing an identifier beats relying
    on the redaction editor to catch it.
  • **`docstore.py` + `/documents` + a merged Documents page.** A hospital hands over ONE
    209-page scanned PDF per admission, which is unreadable as a single object. An offline
    ingest splits it on the per-document page counter each Italian form prints in its footer
    (`Pag. 3 di 61`) — a source property, not a content guess — into **47 documents, verified
    lossless (221 pages in, 221 out)**. Two non-obvious fixes, both found by checking output
    rather than trusting the first pass: type is classified from the **letterhead** (matching
    the whole body labelled the 61-page clinical record "pathology" for one stray
    "istologico"), and bare dates are filtered to a window derived from the bundle's own
    labelled dates (**the DOB is printed on every page**, and the naive rule dated 19 of 47
    documents to 1999). Same local-only, no-allowlist, never-exported posture as `reports.py`.
    `tests/test_docstore.py` (10) incl. a path-traversal guard; suite 424 → 434.
- **Full-picture export now sends the WHOLE record (2026-07-30).** The full-picture export
  sent only metrics; it now also sends the profile (biological **sex** + **age**),
  weight/height history, conditions, medications, timeline events, allowlisted imaging-study
  metadata, and radiology **report text**. New pure assembler `picture.py` (sibling to
  `explain.py` — no SQL/provider/network), merged into the multi-metric bundle as sibling
  top-level keys the `export_metrics` allowlist names **individually** (not one opaque
  `context` blob, which would make the filter vacuous). Charter section added: CLAUDE.md
  "The full-picture export".
  • **Two user decisions, asked before building** (both are charter changes, so neither was
    assumed): report PROSE is included but **editable in the preview**, and the profile
    contributes **sex + age but never the DOB**.
  • **DOB exclusion is STRUCTURAL, not a filter.** `picture.assemble_profile` consumes
    `date_of_birth` to compute `age_years` and emits no DOB, so no code path here can place
    one in a payload. Pinned end-to-end through the real preview route.
  • **Report prose has no structural footing and doesn't pretend to.** A report is one block
    of prose with no fields — an allowlist has nothing to select and regex can't catch an
    arbitrary Italian clinician's name. So the control is **human redaction at the
    chokepoint**: `GET /export/drafts` seeds editable drafts, and the edited string is what
    gets previewed, tokenized and sent. The server **never re-reads the file** when
    assembling — that would silently undo the redaction while every other check still
    passed, so a test pins it. Editing marks the preview stale and blocks Confirm until it's
    rebuilt (consent must attach to a current payload). Residual risk is honest and stated:
    this is only as good as the user's reading of their own report.
  • **The scrub now reaches prose — but ONLY prose** (`gateway._PROSE_FIELDS`: `text`,
    `notes`, `title`, `metric`). The depth limit is correctness, not laziness: blanket
    recursion would corrupt the data, because `observed_on` IS a "date" match and a value
    stringifying to five digits IS a "zip" match. Caught a `Dr. Rossi` in a condition NOTE as
    well as in report text. Known cost: a comparison exam date inside a report reads
    `[REDACTED:date]` — the pattern that catches a stray DOB can't tell them apart.
  • **Context is OFF by default** (`include_context`), so a panel or ad-hoc selection sends
    exactly what it sent before — data minimization, pinned by its own test.
  • **Follow-on the same day — the notes asymmetry closed.** Report prose was editable at
    the moment of consent; a `notes` field naming a doctor was only fixable by leaving the
    export flow to go edit the record. Same risk, and that friction is exactly what stops
    someone redacting — so `notes` (conditions/medications/events) and an event `title` now
    edit in the SAME box by the same mechanism (`RowTextIn` → `_apply_text_overrides`), and
    `/export/reports` became `/export/drafts` covering both (one route, so the two editors
    can't drift into two mechanisms). `_EDITABLE_TEXT` is an allowlist: a client naming an
    unlisted column is ignored, since the editor exists to remove text before a send, not
    to rewrite a record. Edits never write back to the DB. Found while testing: whitespace-
    only did NOT count as cleared on the DB path (the report path already stripped), so a
    box blanked with a space still sent — fixed in `picture._prose`.
  • `tests/test_full_picture_export.py` (21). Suite 402 → 424; sweep 938 records with 1
    data-only diff (/export/results gained the user's own confirmed send); frontend smoke
    9/9; eslint unchanged at 12 pre-existing problems.
- **DICOM imaging viewer — Core (2026-07-27).** Turns the `/imaging` ComingSoon placeholder
  into a working local DICOM viewer (`dicom_store.py` + `/imaging` routes + `ImagingPage.jsx`;
  architecture + privacy posture documented in CLAUDE.md's `dicom_store.py` bullet). **100%
  local by construction** — reads a gitignored `imaging_store/` folder, renders slices to PNG
  server-side, never touches the gateway/network (a medical image can't be de-identified — PII
  can be burned into pixels — so a hosted read stays charter-prohibited). Metadata is
  ALLOWLIST-surfaced (only StudyDate/desc + Modality/series-desc/body-part/dims); every PII tag
  is excluded by never being read, proven by `tests/test_dicom_imaging.py` (the sample files'
  real PatientName never appears in the output). Groups files into study→series→slices by DICOM
  UID (hospital-CD `IM000001` files with no extension just work), window/level presets
  (brain/soft-tissue/bone/lung) + HU rescale + MONOCHROME1 invert. Browser-verified end-to-end
  against pydicom sample data (CT slice renders, Bone window visibly re-renders). Deps pydicom +
  Pillow added to core requirements; degrades honestly if absent. Suite 324 → 333.
  • **DONE since (2026-07-27):** non-image (PR/KO) series filtered out + colour-slice rendering
    (both found against real CT studies in this library); a **non-scrolling app-pane layout** (the
    viewer is immovable by construction — the sidebar is the only scrolling pane, since
    `position: sticky` can never mean "cannot move"); **PACS-convention keyboard/wheel
    navigation** (researched against RadiAnt/Sectra/MicroDicom/Weasis/CaseStacks: wheel scrubs,
    arrows step, PgUp/PgDn ±10, Home/End, digits = window presets); **distance measurement** in
    real millimetres via `PixelSpacing`; and **timeline entries per study**
    (`build_imaging_entries` → `/imaging?study=<id>` deep link, one more SOURCES builder exactly
    as timeline.py's extensibility note designed).
  • **DONE (2026-07-27, second pass):** **ANGLE measurement** (3 clicks, vertex in the middle;
    verified against a deliberate right angle → exactly 90.0°), **window/level DRAG** (starts
    from the file's own `default_window`, now surfaced per series; horizontal = width, vertical
    = center, up = brighter; throttled since each step is a server re-render), and **smooth
    scrubbing** — canvas rendering (holds the last frame instead of flashing blank like an
    `<img>` src swap) over an in-memory decoded-frame cache that prefetches ±10/±4 and evicts
    farthest-first at 64. The cache MUST be in JS memory, not HTTP: the endpoint sends
    `Cache-Control: no-store` so rendered medical images never touch the disk cache. Verified by
    network trace — after 5 arrow-steps the fetches were for slices 11–15, i.e. 6–10 were
    already cached and the prefetch was running ahead of the cursor.
  • **DONE (2026-07-27, third pass — the remaining deferred items, per the standing rec):**
    **ROI statistics** (server-computed mean/SD/min/max in HU + area; the client's windowed
    PNG has lost the real values, so a client-side mean would be a fiction — pinned by a test
    that compares against the region read independently with pydicom; verified on a real
    vertebra: 256.1 ± 407.6 HU, range −473–2180, 654.8 mm²), **zoom/pan** (ctrl+wheel or +/−
    about the cursor, shift/middle-drag to pan, R to reset; the transform sits on the frame so
    annotations scale WITH the anatomy — verified), **cine playback** (space/Play, looping),
    and **graceful JPEG2000 handling** (`PixelDecodeError` → 415 with an actionable
    `pip install pylibjpeg pylibjpeg-openjpeg`, shown as a stage overlay instead of a blank
    frame). Also fixed a layout bug the ROI readout exposed: the viewer's flex column was
    shrinking the tool row and slider into each other, now `flex: none` on everything below
    the stage.
  • **DONE (2026-07-29) — PER-SUBFOLDER scan caching.** The persistent scan cache was keyed by
    ONE whole-store signature, so any change invalidated everything: importing a 6th disc would
    re-read the 13,000 files of the first five. That cost grew with every import — 20 s at one
    disc, 65 s at five — and was paid on the first Imaging load after each import. The cache is
    now partitioned by immediate subfolder (`"."` for loose root files), which matches how the
    store grows: each disc is its own folder and never changes again. Measured on the real
    13,066-file store: full rebuild 58 s, restart-from-cache **0.48 s**, and a newly added folder
    **1.3 s** reading exactly the new files (verified by counting `_read_header` calls). The
    correctness risk was fragmenting a study across partitions, so the cache stores each
    partition's UNFLATTENED instance list and `_finalize` merges by study/series id BEFORE
    ordering/flattening — a series present in two folders becomes one correctly-ordered series
    (pinned by a test). Equivalence proven, not assumed: the whole real store scanned per-partition
    is **byte-identical** to a single whole-store scan, file paths and frame indices included.
  • **DONE (2026-07-29) — FRONTEND SMOKE PROBE (`cd frontend && npm run smoke`).** Built after
    the collapsible-studies change shipped a blank-page crash: a `<details onToggle>` handler
    read `e.currentTarget.open` inside a state UPDATER, React nulls currentTarget once the
    handler returns, the updater ran later, and clicking a series unmounted the whole app.
    `vite build` and `eslint` both passed it — the project had NO harness that could see a
    frontend crash. The probe (`frontend/probe/`, jsdom, one new devDependency) mounts all 9
    pages under StrictMode, clicks the disclosure/tab/expand controls and each `<select>`, and
    fails on a throw, a blank, a stuck "Loading…", or an error branch. Confirmed it catches the
    real bug: reintroducing the one-line regression turned Imaging red with the exact stack and
    `root 0 chars`. Three findings from building it, each now pinned in a comment:
    **(1) StrictMode is load-bearing** — without it the probe PASSED the broken code (React's
    eager-state optimisation ran the updater while the event was still live), so a probe that
    doesn't mirror `main.jsx` certifies crashing builds. **(2) Assert on the routed page, not
    the root** — the app shell is ~700 chars and renders regardless, so the first version
    reported 9/9 PASS while every page was stuck on "Loading…". **(3) Re-query click targets**
    — a captured list goes stale on re-render, which silently limited it to one click per page.
    Safety: it drives the REAL backend for real response shapes (synthetic fixtures agree with
    the code by construction, which is how a shape bug hides) but is **GET-only, enforced in
    `probe/env.js`** — verified DELETE/POST → 405 with zero rows written, so no click can
    mutate the medical DB.
  • **DONE (2026-07-30) — OFFLINE TRANSLATION of documents into English** (`translate.py`,
    `GET /reports/{id}/translation`, the Documents "Translate to English" toggle). The reports
    are in Italian, so surfacing them only half-solved the problem.
    **This was the first feature that wanted to cross the export line, and it was put to the
    user as an explicit choice rather than assumed.** A report is prose carrying name/DOB/
    facility; the charter forbids those leaving the machine and the gateway is built so a raw
    document cannot be sent at all. Options offered: local offline MT; hosted (best quality,
    but PII leaves, needs a charter exception AND weakening the gateway's no-raw-text rule);
    hosted with the header stripped; or local-now-decide-later. **The user chose local now,
    hosted revisited later with evidence** — so the hosted question stays OPEN and unbuilt, to
    be reopened only if local quality proves inadequate on real reports.
    Implementation: argostranslate → CTranslate2, optional (`requirements-translate.txt`,
    ~2-3 GB because it pulls torch/spacy/stanza) with a one-time per-language model download
    via an explicit CLI (`python -m translate install it`). Two egress guarantees are PINNED BY
    TESTS rather than trusted: the module body may never mention argostranslate's remote
    backends (`LibreTranslateTranslation`/`RemoteTranslation`, `urlopen`, `requests.`), and the
    request path may never call the download APIs — those must stay inside the CLI, so viewing
    a page can't start a network fetch. Detection is script-range + function-word scoring
    (correct on it/en/de/fr/es/ru), presented as a hint the user can override; every failure is
    explained rather than silently returning the original, since a "translation" that changed
    nothing is indistinguishable from a broken one. Labelled `engine="local-model"` and
    rendered under an amber machine-translation banner ABOVE the text. Measured: 0.9-1.9 s per
    report, ~10 ms cached, good quality on medical Italian.
    Two measurement lessons worth keeping: the installed-pairs probe LOADS a model (2.4 s cold,
    0 ms after) so it is memoised process-wide and the translation cache is checked BEFORE it;
    and a "2.3 s cached request" that sent me hunting turned out to be my own harness resolving
    `localhost` — 127.0.0.1 gives 4.7 ms on an untouched `/metrics`. Measure against the
    loopback IP.
  • **DONE (2026-07-30) — the RADIOLOGY REPORTS are in the app** (`reports.py`, `/reports*`,
    `DocumentsPage.jsx`, replacing the Documents ComingSoon placeholder). The radiologist's
    written findings exist NOWHERE in the DICOM data — the only SR objects on these discs are
    radiation-dose reports — so this was the one part of the discs saying what the images MEAN,
    reachable previously only through a file browser. Now: a Documents page listing them
    newest-first with a reader, "Original PDF" in a new tab, "View images" back to the study,
    and a "Read the radiology report" link inside the imaging study picker (`report_ids` rides
    each `/imaging/studies` study). Three findings from building it:
    - **4 reports, not 9.** An earlier count in this session said 9; that was wrong. There are
      5 report folders, of which cd2 and cd3 are byte-identical — because they are two discs of
      ONE exam (the study that spans both scan partitions). They
      dedupe into a single entry carrying `n_discs: 2`.
    - **Linking must be by ACCESSION, not folder name.** The archive and the image store
      disagree on names (`cd1` vs `cd-import`), and one exam spans two discs — a folder join
      would be wrong on both counts. `AccessionNumber` matches exactly, read one header per
      study. That tag is outside `dicom_store`'s display allowlist ON PURPOSE, so the read
      lives in `reports.py` rather than widening the allowlist, and the value never leaves the
      function: callers get an opaque sha1[:12] id.
    - **This one is deliberately NOT allowlist-filtered**, which is a departure worth naming.
      An allowlist selects known-safe FIELDS; a report has no fields, just prose that opens
      with the patient's name/DOB/facility and whose clinical content is the entire point.
      Masking it would destroy what the user came to read, so the protection is the local-only
      boundary: no gateway, no network, no DB write, and never assembled into an export payload
      (that would have to be a new, deliberately-built path through the preview/consent chain).
      The accession and local file paths DO stay server-side, pinned by tests.
    13 tests; conftest gained an autouse fixture pointing `ARCHIVE_DIR` at an empty temp folder
    so no other test can read the real reports. Zero sweep diff (filesystem-backed, not swept —
    same reasoning as `/imaging/studies`, and a report body has no business in a baseline file).
    **Follow-up DONE (2026-07-30): reports ON the imaging timeline entry.** First built as a
    separate `kind="report"` entry sorting after its study; the user corrected the model —
    *"the report is **part** of the imaging"* — so it was folded INTO the imaging entry as
    `detail["reports"]` (opaque id + formats), rendered as a link inside it. That is the right
    read: a report is not a separate dated event, it's the written half of the same exam, and
    two rows made one thing look like two. A study whose disc carried no report gets an empty
    list (no client special case) — the case for the two 2025-09-03 studies, imported as loose
    folders rather than a CD. NO report prose enters the timeline (id + formats only), pinned
    by a test. Sweep: 1 endpoint (/timeline, 55 → 51); after normalising away the removed field
    and the new key, both sides compare equal element-for-element.
  • **DONE (2026-07-30) — TIMELINE ENTRIES ALL CARRY EQUAL WEIGHT.** The `prominence` field
    (`high`/`medium`/`base`) and its whole derivation — kind/subtype rank, notable-count and
    notes-length bumps — were REMOVED end-to-end: `TimelineEntry`, `TimelineEntryOut`, the
    tier CSS (dot size/ring, type weight/colour), and the per-entry class. Rationale, from the
    user: *"leave filtering for me to determine what's important to look at."* A presentational
    ranking derived from structural proxies was quietly arguing about what mattered; deciding
    that is the reader's job and the kind filters are the tool for it. One dot size, one type
    weight; the dot still carries KIND (colour) and nothing else.
    Also: the kind PALETTE was re-picked for chip legibility. The old set had three
    near-collisions (medication blue vs lab blue, collection violet beside both); the six kinds
    now sit far apart in hue AND differ in darkness, so they survive being shrunk to a 0.5 rem
    dot — green / blue / orange / magenta-purple / deep teal / crimson.
  • **Deferred, DELIBERATELY (unchanged recommendation):** **3D MPR** — the scanner already
    ships coronal/sagittal reconstructions on the CD, and it builds them from RAW projection
    data whereas we'd only have finished axial images, so ours would be strictly worse (blurred
    by ~1 mm slice spacing vs 0.35 mm in-plane). Revisit ONLY for an axial-only study.
    **Ingest-by-upload** — the local-folder scan stays the privacy-cleanest ingest.
    **JPEG2000 decoding itself** — the optional decoder is documented but not added as a
    dependency, since every study imported so far is Explicit VR Little Endian (uncompressed);
    the failure path is now honest, which is what mattered.
  • **Field note — burned-in PII is real, not theoretical.** The user's CD included a `RadScan`
    series that is a SCANNED REQUISITION FORM (facility name + patient/provider fields) rendered
    as DICOM pixels. The allowlist cannot reach it (it's pixels, not tags), which is exactly why
    the feature is local-only and why a hosted image read stays charter-prohibited. Practical
    consequence for future work: never screenshot a rendered slice into any external context.
- **Markdown rendering + send↔response join (2026-07-23).** Two follow-ons once the full
  export worked end-to-end:
  • **Markdown.** Model output is Markdown (it emits `**bold**` headers and bullet lists),
    which had been rendering as literal asterisks. `frontend/src/markdown.jsx` is a
    dependency-free renderer over the subset models actually emit (headings, bold, italic,
    inline code, bullet/ordered lists, paragraphs). **Hand-rolled deliberately:** it builds
    React elements only — no `dangerouslySetInnerHTML`, no HTML parsing — so markup in an
    external model's response structurally cannot become live DOM, and a medical app's
    dependency tree stays at its 4 runtime packages. `_italic_` is NOT supported on
    purpose: this app's own field names are snake_case (`ref_low`, `n_readings`) and appear
    verbatim in output, so underscore-italics would corrupt real content.
  • **Sends and responses now JOIN.** They were two unrelated records — a `gateway_audit.log`
    line and an `export_results` row with nothing linking them. `gateway._audit` now stamps
    each entry with a random `id` and returns it; `GatewayResult.audit_id` carries it back;
    `export_results.audit_id` (additive guarded ALTER) records it. Settings shows ONE list:
    each send with its response attached, payload behind a nested disclosure.
    `ExportResultsLog.jsx` was merged into `ExportAuditLog.jsx` and deleted — two unjoined
    lists of the same events made the pairing the reader's problem. A random id rather than
    a timestamp or payload hash: two entries can share a timestamp, and a hash collides
    across identical re-sends, which is exactly the case worth telling apart.
  • **Backfilled — on explicit user instruction, after being raised as their call.** The 3
    pre-existing saved results each matched an audit entry to the exact second, but those
    log lines predated `id`, so linking them meant REWRITING an append-only transparency
    record. That was surfaced as a decision rather than done silently (same principle as the
    historical fake test entries), and the user approved it. Method, worth reusing: dry run
    first proving every match is UNIQUE (no second anywhere in the 19 external entries holds
    >1 entry) and cross-checking the `model` field on each pair; backups of BOTH
    `gateway_audit.log` and `health.db`; then a rewrite that adds only the `id` key.
    Verified after: 117 lines before and after, exactly 3 differing, each gaining exactly one
    new key with nothing removed and no existing value altered (asserted programmatically,
    not eyeballed), and 0 unpaired results left. The orphan section in `ExportAuditLog`
    stays — it is the honest fallback if a result is ever saved without a resolvable send.
- **Export prompt + payload overhaul (2026-07-23).** Driven by a user observation that the
  external model "always comes back with two points" — which turned out to be OUR prompt,
  not the model's judgment. Four changes:
  • **The point cap is GONE.** Old rule 8 read "Raise AT MOST the two or three most
    data-supported points"; it now reports everything the data genuinely supports, grouped
    under shared threads, with length following the data ("do not ration" / "do not pad").
  • **`MAX_READINGS` (12) REMOVED — the full series is sent.** This CLOSES the deferred
    item flagged in #1's recon §5: the cap existed to bound what a small LOCAL model saw,
    and that rationale never carried over to a strong external model. Truncating history is
    actively wrong for a longitudinal tool where the TREND is the thing being exported. The
    parameter survives so a caller can still bound a payload deliberately. Scale check: the
    full picture is 612 readings across 176 metrics — modest, and 5 metrics were actually
    being truncated at 13 readings.
  • **Specialist persona + a RECENCY rule.** The prompt now reasons "with the depth of an
    experienced physician ... across cardiology, neurology, hematology, endocrinology,
    nephrology, hepatology, immunology" (user request), and new **rule 1** makes the CURRENT
    state the question: resolved history is raised only where it bears on the present, and a
    metric whose latest reading is itself old is called stale. Motivated by responses that
    kept re-narrating a 2025-06-21 trauma episode as though it were current. Rule 1 needs an
    anchor to be enforceable — the model can't tell last week from two years ago from reading
    dates alone — so `explain.system_instruction(as_of)` appends today's date. It rides the
    INSTRUCTION, not the payload: in the bundle it would repeat once per metric in the preview
    (176×) and would perturb the confirmation token at every midnight boundary.
  • **The instruction is now PREVIEWED** (`Preview.instruction` → `ExportPreviewOut` →
    collapsed block in `ExportPanel`). Charter updated — see CLAUDE.md's consent-mechanics
    subsection for the data-half-is-privacy / instruction-half-is-interpretability split, and
    why the instruction is deliberately NOT bound by the confirmation token.
  • **Held the line (deliberate, worth re-reading before any future prompt edit):** the
    persona asks the model to reason like a specialist, NOT to render a verdict — rule 5 now
    says so explicitly ("specialist depth means sharper, better-grounded possibilities; it
    does not mean a verdict"). Every protective rule is intact: no treatment/medication
    advice, possibilities-not-conclusions, hedged condition-naming only, "nothing stands out"
    still valid and valued. Pinned by `test_system_instruction_keeps_the_protective_rules`,
    which trips if a future edit drops any of them. Suite 310 → 316.
- **Metric groups + negative-data chart fix (`35e4068`, 2026-07-22).** A general `metric_group` registry label — a THIRD display-only label beside `name`/`alias`, touching no identity key and no reading — rendered as picker `<optgroup>`s. Precedence: derived (Computed) > explicit user group > collection (Timed collections) > ungrouped, so an explicit choice beats automatic collection grouping. `db.set_metric_group`, `PUT /metrics/{m}/group` (409 for derived — they already cluster under Computed), `MetricInfo.group`, `GroupModal.jsx`, `MetricPicker` rewritten; additive guarded ALTER mirrors `alias`. **Generalizes the two formerly-hardcoded optgroups, and is the answer to #10** (allergen panels no longer stress a flat picker). `tests/test_metric_group.py` (9); suite 298 → 307.
  • **Negative-data chart fix (same commit).** `MetricChart`'s sub-zero cosmetic floor, tick floor, and ceiling-band fade all assumed a below-zero domain was cosmetic padding (the bilirubin/LDL "bottoms at 0" case) and yanked the axis to ~0 — which CLIPPED a genuinely-negative series off the bottom. Surfaced by **Standard Base Excess** (~ −2..+2, routinely negative), the app's first metric whose data is legitimately negative. All three now gate on `dataGoesNegative = hardLo < 0`.
  • **DB curation (data, not code — `health.db` is gitignored):** the arterial blood-gas panel entered and grouped as "Arterial Blood Gas (EGA)" (22 metrics), canonical names normalized to the matrix-suffix convention with analyzer symbols as aliases, and `(serum/plasma)` restored to 13 aliases that had dropped the specimen matrix. **Convention established:** the specimen matrix appears in the name EVERYWHERE, even with no current overlap, so a future venous panel (EGV) is symmetric rather than retrofitted. **Temperature-corrected pH/pCO2/pO2 were checked and SKIPPED** — identical to the uncorrected values (the analyzer defaulted to 37 °C), so they carry no information; revisit only if a future draw reports them differing. **No ABG thresholds seeded** — blood gases are the context-only category (read as a set against the clinical situation and FiO2, never individually against a fixed line); the lab's per-draw bands ride band-as-data.
  • **FiO2 — INVESTIGATED & DECLINED as a metric; recorded as ONE Timeline event instead.** FO2(I) was 21% (room air) on the draw, and 21% is atmospheric composition — a fact about the air, not a measurement of the user, so a series of it would carry zero information. Two arguments were weighed and both collapsed: (1) *"an event can't reach the analysis"* — TRUE and worth knowing (`explain.py`'s export bundle reads `observations`/`flags`/`thresholds` only, never `events`, and `timeline.py` joins the two kinds by DATE alone, no FK), which WOULD favor a metric if FiO2 varied; (2) *"a metric makes P/F ratio (pO2 ÷ FiO2) derivable"* — void with a constant denominator, since that ratio is then just a rescale of pO2. With a single draw it's also inert by construction (every detector needs ≥4 points). Engine safety was confirmed incidentally: `personal_baseline_z` already falls back to mean-absolute-deviation and stays SILENT on a perfectly flat history (`analysis.py`), so a constant series is a no-op, not a divide-by-zero. **Revisit only if a future draw is on supplemental O2** — then FiO2 genuinely varies, the P/F argument revives, and it becomes a real metric.
- **Phase B / #1+#2 export arc (DONE, phases (a)–(d)).** Headline closures are on #1/#2 above; these are the carry-forward implementation details worth keeping out of git-log-only:
  • **(a) `f3dc917` + charter `8205d7d`:** the PII-clean claim is PINNED BY TEST, not asserted — allowlist keys == bundle keys (a future bundle field can't silently ride along unreviewed) and zero redactions/exclusions on a bundle from a REAL `analyze_series()` run; "The export handoff" charter subsection added (consent mechanics as written rules so a refactor can't quietly collapse the preview or make the enable-gate one-way).
  • **(b) gating `28b487e`:** `export_provider` = typed `SettingDef` enum (anthropic/openai, default anthropic — rides the existing Settings radio machinery); `export_hosted_enabled` = raw settings-table flag with a genuine two-way `GET/PUT /export/enabled` (revoke exactly as easy as grant). Structural proofs that `summarizer_engine` still rejects `hosted` and `explain_metric()` stays local-only (tested with a run-worthy series so the proximity-skip can't mask the engine check).
  • **(b) routes `91a7adb`:** `POST /export/{metric}/preview`/`/confirm` are STATELESS — both rebuild the bundle server-side from `assemble_explain_context` on every call (no payload cache; a data change between preview and confirm self-detects via the gateway's token mismatch → 409). `_gather_explain_substrate` extracted from `/explain` (behavior-preserving) so both paths share gathering. `LLMRequest` gained `provider`; `_hosted_call` returns `(text, served_model)` so `GatewayResult.model` + audit entries populate for external calls.
  • **(b) UI `0e29785`:** `ExportPanel.jsx` — full read-before-consent flow (quiet off-state → trigger → expanded-by-default faithful nested-payload preview → scroll-gated confirm → result). The scroll-gate deliberately does NOT use IntersectionObserver (verified live: callback delivery is silently withheld when `document.hidden`, since it rides the compositing pipeline) — manual `getBoundingClientRect()` on scroll/resize + one synchronous render-time check instead. Stale confirm (409) auto-refetches and names the likely cause via a client-side reading-count diff. The destination banner text is sourced from `settings.py`'s option descriptions — same string the Settings picker shows, so the two surfaces can't drift.
  • **(c) `66b6ae2` → see #2 for the provider wiring itself.** One found-and-fixed bug worth remembering: `claude-sonnet-5`'s adaptive thinking draws from the SAME `max_tokens` budget as the visible response, so heavy thinking could silently truncate output with `stop_reason "max_tokens"` and NO HTTP error — fixed by `_ANTHROPIC_MAX_TOKENS=4096` headroom PLUS a guard treating `stop_reason == "max_tokens"` as a clean `HostedCallError` (never a partial response passed off as complete). `EXPLAIN_SYSTEM`/`FRAME` made public (underscore dropped) — the export handoff uses the SAME system instruction + disclaimer frame as the local tier. 17 hermetic tests (`test_gateway_hosted.py`) mock the HTTP layer; the suite has NO live-API-key dependence.
  • **(d) `2836820`:** `ExportResultOut.disclaimer` is its OWN field, rendered from itself — never concatenated into `output` server-side, so the safety frame can't be silently dropped by a future refactor of a pre-merged string; `EXPLAIN_SYSTEM` rule 9 added as belt-and-suspenders (there was NO such rule before, contrary to assumption). Result renders as a standalone `.export__result` section reusing `InterpretationPanel`'s violet + lightbulb "model reasoning" language (`LightbulbIcon` lifted to `icons.jsx`), headed "Response from *engine* (*model*) — model reasoning, not cited data." Vacuous-pass test traps fixed (disclaimer tests assert non-empty AND equal-to-FRAME; `test_frame_constant_is_nonempty` pins the constant).
- **Threshold label rail (DONE).** Guideline threshold labels moved OUT of the plot into a right-margin rail (`<ThresholdRail>` in `MetricChart.jsx`), positioned off the plot's own y-scale via `useYAxisScale()`+`usePlotArea()`; threshold `ReferenceLine`s stay in-plot, personal-baseline label stays inline (violet dashed — Option A). This resolves the band/line/label muddle at the root (Ferritin's coincident-30 stack, TSH's three in-plot labels) by removing labels from the data space rather than restyling them. **Supersedes and retires two now-dead plans:** (a) the **fork-A label-coincidence-suppression plan** (drop/suppress an inline threshold label when it coincides with a band edge) — obsolete, the rail removes ALL threshold labels from the plot so there's no in-plot coincidence left to suppress; (b) the **darker-gray/thinner threshold-line tweak** (`#868e96 1.5` → `#495057 1`) — absorbed into this commit (its `#495057` lives on as the rail text color; the line finalized at `#495057/1`). #15 (threshold-status encoding) now **merges into the rail** (see #15) rather than being a separate item.

**20. Import the Italian admission labs** *(OPEN — queued 2026-08-20, needs a long session, probably several)* — the 2025-06-21 → 2025-07-29 hospitalisation left **nine lab reports in `documents_store` with no readings in the DB**: 2025-06-25, 06-29, 06-30, 07-09, 07-14, 07-16, 07-18, 07-22, 07-23. Only 2025-06-21 (73 readings) was ever imported, so a five-week admission charts as a single day — and the trends the treating team were actually watching (Hb, CRP, transaminases, albumin, all quoted in the daily notes) are absent from every chart.
> ▸ **Why it is not a quick job.** These are Italian-format reports, so they run through `pdf_import`'s `_italian_parse` (positional `NAME VALUE [*flag] UNIT LO-HI`, comma decimals, DD/MM dates whose year comes from the page header). Nine documents × a full inpatient panel is a lot of rows to READ before saving, and review-before-save is mandatory — the value of the import is entirely in the checking. Expect to split it across sessions, one document at a time.
> ▸ **Watch for:** metric-name de-dup against the existing registry (Italian names vs the US lab's wording — `resolve_ingest_id` matches canonical + alias, and `suggest_metrics` will offer near-misses; each needs a human call, and a wrong merge is worse than a duplicate); Italian units (mmol/L vs mg/dL) tripping the one-unit-per-metric invariant, which will surface as a 409 per row rather than a silent conversion; and **CRP is written `PCR`** in these notes (*proteina C reattiva*), which is a genuine collision with the molecular-test abbreviation.
> ▸ **Also in the record and NOT imported:** the daily notes carry spot values the reports may not (e.g. 2025-07-18 WBC 10 000, Hb 12, CRP 4). Prefer the lab report over a note transcription where both exist — the report is the primary source.

**19. Metric display aliases + ingest de-dup** *(DONE 2026-07-16 — backend verified; frontend built + type-checked by build, needs an eyeball)* — **`metric_id` IS the match key.** A metric carries two LABELS that both resolve to it, neither being the key: a verbose one (the lab's wording; also the URL segment, for stable readable routes) and an optional shorthand ALIAS (the display name). Naming is therefore pure presentation.
> ▸ **Why aliases and NOT renames** (the finding that drove it): the verbose names ARE the lab's wording, which is how a future PDF import arrives — an alias ADDS a label (both still resolve to the same id), whereas a rename REPLACES the lab-wording label, after which that import would no longer resolve and would mint a duplicate. And the verbosity is mostly *meaningful*: `Serum/Plasma` / `Whole Blood` is the SPECIMEN matrix (same analyte in urine / whole blood / glucometer = genuinely different ranges); `by LC-MS/MS` / `by Equilibrium Dialysis` distinguishes assays that can coexist (free testosterone has ≥3 methods); `Alkaline Phosphatase Total` distinguishes the sum from its isoenzymes. So: keep the key, alias the display. This also fixed the app's naming INCONSISTENCY (HDL/TSH abbreviated vs Blood Urea Nitrogen spelled out) as a display convention rather than a data migration.
> ▸ **Also a collision trap avoided:** the motivating example — `Vitamin E (Alpha-tocopherol)` → "Vitamin E" — is UNSAFE: `Vitamin E (Gamma-tocopherol)` also exists and they're different analytes (same for `Vitamin A (Retinol)` vs `(Retinyl Palmitate)`, and the vitamin-D fractions). Those parentheticals carry the distinction and are kept; normalization is deliberately conservative so they can never collapse.
> ▸ **Enforced de-dup** (`db.get_or_create_metric`): exact canonical → normalized (case/whitespace) canonical-or-alias (`resolve_ingest_id`) → only then mint. `BUN` / `blood urea nitrogen` attach to `Blood Urea Nitrogen`. Exact fast-path first ⇒ every existing exact caller byte-identical. **Fuzzy "did you mean"** (`db.suggest_metrics`, difflib) is ADVISORY only, surfaced at add/import, never auto-applied. `set_metric_alias` refuses a colliding alias (`AliasConflictError` → 409).
> ▸ **Shipped:** `metrics.alias` + partial-unique index (index created in `init_db`, not schema.sql — see the migration note in CLAUDE.md); `aliases.py` (27 curated defaults: common verbose lab wordings shortened — panel enzymes, a growth-factor pair, 13 Serum/Plasma drops, 5 Whole-Blood drops), seeded only where `alias IS NULL` so a user edit is never clobbered; `MetricInfo.alias`; `GET /metrics/resolve` (exact + suggestions); `PUT /metrics/{m}/display-name`. Frontend: picker/labels show the alias (value stays canonical), the old **Rename button became "Display name"** (`DisplayNameModal`; `RenameMetricModal` is now unwired — the canonical-rename route still exists for a genuinely-wrong canonical), and the add form shows a debounced "did you mean …?" nudge. Tests: `tests/test_metric_aliases.py` (13). Sweep: only `/metrics` changed (alias field) — per-metric endpoints stay keyed on the canonical name, so **no endpoint churn**.
> ▸ **DONE — import-review de-dup badges (2026-07-16).** Each draft row in `PdfImport` now shows what its metric name will actually DO on save, before you approve: `→ Existing Metric` (attaches — either label, normalized), `new — did you mean «X»?` (would create a new metric that looks like an existing one; click adopts the existing name), or `new metric` (genuinely new). The third state is the point: a lab reporting a known analyte under new wording used to mint a silent duplicate you'd only find later. **Resolution is BATCHED** — `POST /metrics/resolve-batch` (names → positional results, `max_length=500`) resolves the whole draft in ONE round trip instead of a request per row, and one debounced effect serves both the initial extraction and any later name edit. Both it and the single-name `GET /metrics/resolve` (kept for the add form's per-keystroke lookup, where batching buys nothing) call the SAME `api._resolve_one`, so the two surfaces can't drift — that shared-logic point is why a client-side JS re-implementation of the difflib scoring was rejected. Advisory only: the save path re-resolves server-side regardless, so a badge decides nothing. Tests: 2 more in `tests/test_metric_aliases.py` (batch is positional; batch == single per name; empty ok). Suite 211. Sweep byte-identical (the batch route is a POST, outside the GET sweep).
> ▸ **DONE — derived-metric display aliases (2026-07-17).** Derived (computed) metrics are now aliasable too, so they read as nicely as stored ones (e.g. the verbose "NLR (Neutrophil-Lymphocyte Ratio)" shows as **"NLR"**). A derived metric lives in the `derived.py` REGISTRY, not the `metrics` table, and must STAY out of the ingest/suggest machinery (you never import a computed value) — so a derived alias is **display-ONLY, not a match key**, and it can't ride the `metrics.alias` column. Two layers: a curated default (`DerivedMetric.display_name`, set for NLR) and a user override in a tiny `derived_alias` table (`db.get_derived_aliases`/`set_derived_alias`; keyed by the reserved canonical name; clearing falls back to the curated default, then the verbose name). `/metrics` resolves override → default → none; `PUT /metrics/{m}/display-name` now branches — a derived metric goes to `set_derived_alias` (with a UI-clarity collision check, `_derived_alias_conflict`, across stored names/aliases + other derived names/aliases → 409), a stored one keeps the old path. The **Display name** button now shows for derived metrics too; the modal copy adapts ("computed metric — clearing falls back to its default"). Tests: 4 more in `test_metric_aliases.py` incl. the key invariant that a derived alias is NOT an ingest key (adding under it mints a normal stored metric, never attaches to the derived one). Suite 217. Sweep: only `/metrics` changed (NLR's curated alias).

## NOT on the roadmap (tracked in the handoff layer, listed here so they aren't lost)
- **DONE — merged a duplicate WBC metric + corrected a charter claim it exposed.** A duplicate white-cell metric carrying a department header (n=1) was the SAME test as `White Blood Cell Count` (n=9) — confirmed by an identical reference band (3.9–10.7), unit, and the user's own report (a plain CBC white count under a benign-heme *department* header). The parser had glued the practice/department header onto the test name. Merged via a backed-up one-off (`health.db.bak-wbc-merge-*`): repointed the lone observation's `metric_id`, dropped the orphan registry row (`rename_metric` deliberately refuses a merge as irreversible data-mixing, so no reusable path — a manual repoint + FK check + commit). WBC 9→10, FK clean, 138 metrics. Re-duplication is now caught by the #19 import badge (fuzzy 0.71 > 0.6 → "did you mean White Blood Cell Count?"). Sweep 732→727, all WBC-attributable, baseline refreshed.
  - **The real find:** the metric NAME carried a physician-practice string, and the metric name is exactly what the **export handoff sends** (`explain.py`'s bundle → `"metric"`, allowlisted). The charter's "PII-clean **by construction**" claim for the export was **column-level** (it never reads the PII columns) but silently assumed the *contents* of the columns it DOES read are identifier-free — which a parser can violate. Nothing leaked (the faithful preview + consent is the actual control, and it would show the name before send; the regex scrub misses a department header entirely). **Corrected in CLAUDE.md** (both the "not every task is redaction-based" bullet and the export "Privacy footing — Model A" para): structural cleanliness is column-level, the **preview is the load-bearing control**, the scrub is belt-and-suspenders. **Pinned by `tests/test_export_metric_name.py`** so a future refactor can't drop the preview on the strength of the by-construction claim. *(Considered + declined: a parser denylist for header/practice wording — it's the "denylist inevitably misses" antipattern the privacy charter warns against, and the review step is the designed control.)*

- **DONE (`7ffa6eb`) — export handoff "temporal severance."** Was: once the export RESULT rendered, the exact cited facts that were sent (readings / engine findings / thresholds) were gone from view, so the model's reasoning couldn't be cross-checked against the specific facts it saw without re-triggering a preview. **Fixed** by keeping the sent bundle co-visible with the result — a collapsed `<details>` "Show the facts that were sent" in `ExportPanel`'s result state renders the SAME `BundleFacts`/`renderFacts` as the preview (single bundle or per-metric group for a multi export), so the two can't drift. Low-urgency item, now closed.
- **SHIPPED (`ade0d7b`) — static threshold-level detector + guideline mention folded into out-of-range.** Not a numbered roadmap item (emerged from a user question: a historical hemoglobin reading below the WHO line wasn't threshold-flagged). `clinical_threshold_crossing` fires only on a crossing in the latest two readings; `flag_threshold_level` adds the STANDING "your latest value is on the concerning side" flag (kind `threshold`, suppressed for any cutoff a crossing already reported), and `_annotate_guideline` folds a guideline mention INTO an `out_of_range` flag whose reading is also past a cited line (no separate flag → no added noise), in both `analyze_series` and the history path (`thresholds=` now threaded through `_history_flags`/`analyze_history`/`summarize_history`, passed from `/history` + `/overview`). Surface-don't-diagnose (source + cutoff only). Full detail in CLAUDE.md's detectors table + note; `tests/test_threshold_level.py`.
- **Decided/declined: no positive "charted as arrow" badge for censored rows.** The `ObservationTable` "· not charted" badge is `result_type === 'qualitative'` only — censored rows plot as arrows and carry NO badge (consistent with numeric rows, which carry no charting annotation). A positive "charted as arrow" indicator was considered and declined, to keep the badge meaning "not charted" only. *(Was the resolved "Done — not charted badge" bullet in the old `CLAUDE.md` roadmap; recorded here so the 16→15 reconciliation drops nothing.)*
- **RESOLVED (shipped `ec2bb53`) — top-of-chart dwarfing was SOFT-THRESHOLD-driven, not pad-driven (recon'd + fixed, Option B).** Separate two things the old note conflated:
  (1) The y-domain PAD is 15% of the *hard data range* and **symmetric** top/bottom (same `pad` on `hardLo−pad` / `hardHi+pad`; `hardYs` = values + censored bounds + ref edges, thresholds excluded). It is proportional and **not** the dwarfer. Its **bottom** side is additionally bounded by the cosmetic-margin change (floor in `[−(domainTop×0.05), 0]`, −200/−2 class impossible); the top has no analogous cap but doesn't need the same one.
  (2) The real **TOP dwarfing** is the SOFT branch: when the highest threshold sits far above the readings, `domainTop` is EXTENDED to `softMax + SOFT_MARGIN_FRACTION(4%)` so the gridline stays on-screen (`ifOverflow:'discard'` would else drop it), pushing the data into the lower portion. Measured (data % of plot height): **Glucose** readings 84–116 vs ADA 200 → **~32%**; **Triglycerides** reading 36 vs ATP III 500 → **~23%**; **Cholesterol** 196 vs 240 → **~4%** (worst; single reading + ceiling-open bottom); **TSH** band ≤~4.7 vs line 10 → **~41%**. Lesser, non-threshold variants: band-ref-edge (**Ferritin** readings 11–142 under a 464 ceiling → ~81%, band-driven) and single-reading **centering** (Non-HDL/HDL). **eGFR is a NON-case** — all readings censored `>90` → no numeric → not charted.
  **Shipped fix (`ec2bb53`):** a **symmetric pad cap was correctly ruled out** (it can't move Glucose's 200-driven top). The rework instead targets the SOFT branch: when a far threshold opens a gap of more than `CAP_RATIO`=0.85 hard-data-spans above `hardHi` (`R1 = (softMax−hardHi)/(hardHi−hardLo) > CAP_RATIO`), `domainTop` falls back to the data-driven `baseTop` and the off-domain threshold renders as an edge indicator on the rail — **final design shipped in `16a956d`**: an inline chevron-up glyph + muted `#868e96` label + faint dashed `#adb5bd` guide-tick at the plot's top-right corner (superseding the `ec2bb53` placeholder ↑ prefix). Capping also **re-admits the centering block** (gate now `(!topIsSoft || topCapped) && !bottomIsSoft`), reframing the freed data. Two carry-forward notes:
  • **The capped set is data-dependent per-render, not a fixed metric list.** Today Cholesterol, Glucose, Triglycerides, TSH trip `R1 > 0.85`, but membership can shift as readings change — the behavior is "whatever trips R1," not a hardcoded 4. **LDL is the closest non-capped case at R1=0.47** and would start capping if a future low reading narrowed its hard range.
  • **R1's denominator can collapse for narrow-hard-range / single-reading metrics** (Cholesterol's R1=10 came from a hard range of only 4), which over-flags for capping. Currently backstopped by centering re-absorbing the cap — confirmed: **Cholesterol renders identically pre/post-cap once centered** (top pulled back to ~242, its 240 landing in-domain again). Not yet a standalone fix; revisit only if a future metric has both a narrow hard range **and** no centering backstop available.
- **Gotcha (banked): TSH's −2 floor was never actually fixed before this.** It was *incidentally masked* when #8 seeded TSH-10, which flipped `topIsSoft` true and gated OFF the centering block (L358) that had been extending the floor downward. The `Math.max(0, …)` clamp is the real fix; that masking is no longer load-bearing.
- **Follow-up (rendering): rail-collision guard for 3+ simultaneously-capped thresholds — RESOLVED.** First triggered by **Calcium Corrected** (#6 Phase 2): its 10/12/14 hypercalcemia lines all capped and overprinted at the top-right corner. Fixed by splitting rail rendering into in-domain (own y-position) vs. capped (separated/stacked) groups — `MetricChart.jsx`. (Still open, deferred/not needed: letting the cap PRESERVE a just-above-data threshold rather than pushing it to the rail — a cap-logic change, not a rail one.)
- **DONE (2026-07-16) — scaffolding prune.** The metric_id registry migration (Phase 1 mint + Phase 2 metric_id-add/backfill + `_tighten_metric_id` + `_drop_observations_metric`, ~220 lines in `db.py`) is REMOVED; `schema.sql` now emits the FINAL shape directly (observations without `metric`, `metric_id NOT NULL REFERENCES metrics(id)` + `UNIQUE(metric_id, observed_on)`; metric_config/metric_settings carry the same FK; `metrics` moved above the tables that FK into it). The write path (`get_or_create_metric` in `add_observation`/`update_observation`/`set_metric_*`) already sets `metric_id` itself, so fresh rows never needed the backfill; reads already key on `metric_id`. **Support-scope decision made explicit:** a DB predating the registry migration is no longer upgraded on startup — none exists (real `health.db` + every `.bak-*` are already final shape). KEPT (out of scope, older + cheaper): the additive column ALTERs (`normal_text`, `resolved_on`, `ref_low/high_operator`) and the empty-legacy-`events` reshape, which still upgrade a DB predating those columns. **Proven:** a fresh `:memory:` build is byte-identical (columns/types/NOT NULL/PK/FK/indexes) to the real migrated DB; 189 tests pass; sweep 727/727 byte-identical (body-free sha256 diff). `demo.py` smoke check green.

## Proof tools / infra (standing)
- `sweep.py` — 717 deterministic GETs; canonical baseline `.sweep/sweep_baseline_6.json` (local/gitignored; refreshed in place through every data-changing arc — see `.sweep/README.txt` for the full log, latest = #1 static-threshold + the #17 fix); excludes `/summary`, `/changes`, `/settings`, `/export/audit` (`/explain` was dropped from the exclusions when the interpretation tier was removed, ROADMAP #16).
- `pytest` — ~171 tests. Frontend-only changes uncovered by either harness — eyeball those.
- No CI (run by hand; CI-ready). Benign `StarletteDeprecationWarning` silenceable once a pytest config file appears.
