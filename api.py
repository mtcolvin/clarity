"""
api.py — thin FastAPI transport over db.py + analysis.analyze_series.

Deliberately contains NO analysis math and NO SQL. It only:
  - translates HTTP requests into db.py calls,
  - runs the pure analyze_series engine over a metric's series,
  - serializes Flag dataclasses to JSON.

This keeps the existing three-layer split intact:
  db.py        persistence
  analysis.py  pure detection
  api.py       transport  (this file)

Run:
    pip install fastapi "uvicorn[standard]"
    uvicorn api:app --reload      # interactive docs at /docs
"""

from __future__ import annotations

import json
import os
import re
import sqlite3
import sys
import urllib.request
from contextlib import asynccontextmanager
from dataclasses import asdict
from datetime import date

from fastapi import Depends, FastAPI, HTTPException, Request, Response
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel, Field, model_validator


# Strict YYYY-MM-DD (and a real calendar date) — used by the Profile validators so
# the Date Format charter holds server-side regardless of client.
def _valid_iso_date(s: str) -> bool:
    if not re.fullmatch(r"\d{4}-\d{2}-\d{2}", s):
        return False
    try:
        date.fromisoformat(s)
        return True
    except ValueError:
        return False

from env_local import load_env_local
from db import (
    connect,
    init_db,
    link_seed_keys,
    add_observation,
    update_observation,
    delete_observation,
    get_series,
    get_joined_series,
    get_derived_reference_ranges,
    list_metrics_with_units,
    list_observed_metrics,
    list_all_metric_config,
    get_metric_settings,
    set_metric_settings,
    list_conditions,
    add_condition,
    update_condition,
    delete_condition,
    list_immunizations,
    add_immunization,
    update_immunization,
    delete_immunization,
    list_medications,
    add_medication,
    update_medication,
    delete_medication,
    list_events,
    add_event,
    update_event,
    delete_event,
    get_profile,
    update_profile,
    add_profile_measurement,
    list_profile_history,
    get_latest_profile_measurement,
    delete_profile_measurement,
    update_profile_measurement,
    get_profile_measurement,
    rename_metric,
    set_metric_unit,
    set_metric_alias,
    set_metric_group,
    suggest_metrics,
    resolve_ingest,
    get_derived_aliases,
    set_derived_alias,
    list_registry_labels,
    normalize_label,
    add_collection,
    get_collection,
    list_collections,
    list_collection_readings,
    update_collection,
    delete_collection,
    metrics_in_collections_of,
    add_export_result,
    list_export_results,
    UnitMismatchError,
    MetricExistsError,
    AliasConflictError,
    CollectionInUseError,
    get_setting,
    set_setting,
)
import timeline as timeline_builder
from analysis import (
    analyze_series, summarize_history, latest_change, is_recent,
    personal_baseline_candidacy, personal_baseline_mean,
    current_flags, rank_flags_cross_metric, rank_groups_cross_metric,
)
from narrate import summarize_with_engine
import explain
import picture
from gateway import LLMRequest, complete, read_external_audit
import settings as settings_registry
import metric_config as metric_config_registry
import derived as derived_registry
import aliases as aliases_registry
import dicom_store
import synthetic
import reports as reports_store
import docstore

# Default is the real DB; HEALTH_DB overrides it BEFORE import/lifespan run. This
# override exists so a throwaway/verification backend can point somewhere else and
# be *physically unable* to touch health.db (a real medical file) — the gap that
# let a temp backend once write into it. sweep.py and tests/conftest.py rebind
# api.DB_PATH after import and are unaffected by this default.
DB_PATH = os.environ.get("HEALTH_DB", "health.db")

# Per-metric detector config (thresholds/RCV that analyze_series takes as kwargs)
# now lives in the `metric_config` SQLite table, read via the metric_config.py
# registry — NOT a hardcoded dict here. Call sites resolve it per metric with
# metric_config_registry.get_config(conn, metric); the seed below migrates the
# former hardcoded values in on first run. Editing UI is deferred (see Roadmap).


@asynccontextmanager
async def lifespan(app: FastAPI):
    # Load the gitignored .env.local (provider API key) into THIS process's
    # environment before serving — scoped here, never a global env var, so no
    # other process on the machine (e.g. Claude Code) can inherit the key.
    # gateway._anthropic_call reads it from os.environ at call time as before.
    load_env_local()
    # Ensure the schema exists before serving any request. init_db is idempotent.
    conn = connect(DB_PATH)
    try:
        init_db(conn)
        # Phase 1 (additive): link the metric registry's rows to their SEED entries
        # via the immutable seed_key. init_db already created + backfilled the
        # `metrics` table; this sets seed_key = name for SEED metrics. SEED keys come
        # from the registry (db.py stays registry-agnostic). Order vs seed_defaults is
        # immaterial this phase — nothing reads the registry yet.
        link_seed_keys(conn, metric_config_registry.SEED.keys())
        # Populate settings AND per-metric detector config defaults. metric_config
        # RE-SEEDS on every startup via UPSERT — SEED is the source of truth and the
        # table a runtime cache, so an existing row IS overwritten (edit SEED + restart
        # to change a cutoff). For settings the resolve() fallback makes this belt-and-
        # suspenders.
        settings_registry.seed_defaults(conn)
        metric_config_registry.seed_defaults(conn)
        # Curated DISPLAY aliases (friendly names). Sets an alias only where a metric
        # has none yet, so a user's own display-name edit persists across restarts
        # (unlike the blunt config re-seed above).
        aliases_registry.seed_aliases(conn)
    finally:
        conn.close()
    yield


app = FastAPI(title="Clarity", lifespan=lifespan)

# Browser calls from the Vite dev server are cross-origin. Scope to that origin
# explicitly rather than "*" — this is health data, so no wildcard even in dev.
# localhost and 127.0.0.1 are distinct origins to the browser, so list both.
# GET reads, POST adds, PUT edits, DELETE removes — still scoped to the Vite
# origin, no wildcard.
#
# HEALTH_DEV_ORIGINS ADDS origins for a second dev server on another port — used by
# verify/ui_shots.py, which runs its own Vite against a SYNTHETIC database so
# screenshots can never contain the real record. It only ever adds; the two real
# origins above are always present, and a wildcard is still impossible because each
# entry is compared literally by CORSMiddleware.
_EXTRA_ORIGINS = [o.strip() for o in os.environ.get("HEALTH_DEV_ORIGINS", "").split(",")
                  if o.strip()]

app.add_middleware(
    CORSMiddleware,
    allow_origins=["http://localhost:5173", "http://127.0.0.1:5173", *_EXTRA_ORIGINS],
    allow_methods=["GET", "POST", "PUT", "DELETE"],
    allow_headers=["*"],
)


def get_conn():
    """Per-request connection. Reuses db.connect so row_factory and the
    foreign_keys pragma stay consistent; check_same_thread=False because FastAPI
    may run the request on a different thread than the one that opened it."""
    conn = connect(DB_PATH, check_same_thread=False)
    try:
        yield conn
    finally:
        conn.close()


def resolve_series(conn, metric: str) -> list[dict]:
    """A metric's series for the read side — the single seam that makes a DERIVED
    metric ride every metric-keyed read endpoint. For a stored metric it's just
    get_series; for a derived one it joins the inputs (db.get_joined_series, the
    same-draw asset) and computes the series (derived.compute_series) — one point per
    date both inputs were drawn, others omitted. No math or detection here — the
    engine still runs over whatever series this returns."""
    spec = derived_registry.REGISTRY.get(metric)
    if spec is None:
        return get_series(conn, metric)
    joined = get_joined_series(conn, spec.inputs)
    ranges = get_derived_reference_ranges(conn, metric)
    return derived_registry.compute_series(spec, joined, ranges)


def resolve_derived_series(conn) -> dict[str, list[dict]]:
    """Every currently-computable derived metric -> its computed series, oldest first.
    The SINGLE source that gives derived metrics parity with stored ones in the
    cross-metric roll-ups (/overview and the Timeline). Availability follows the same
    rule as the /metrics picker (all inputs present), so a derived metric appears in
    the roll-ups exactly when it can be computed — and its rows are the same computed
    shape resolve_series returns (id=null, raw floats). Injected into build_timeline
    so timeline.py stays free of the derived registry (same DI style as all_configs)."""
    present = {row["metric"] for row in list_metrics_with_units(conn)}
    return {
        spec.name: derived_registry.compute_series(
            spec, get_joined_series(conn, spec.inputs),
            get_derived_reference_ranges(conn, spec.name))
        for spec in derived_registry.available(present)
    }


def _reject_derived_write(metric: str) -> None:
    """Guard for the write endpoints: a derived metric is COMPUTED, never stored, so
    it can't be added/edited/renamed onto. 409 (conflict with a reserved computed
    name). DELETE needs no guard — it's keyed by row id and a derived metric has none."""
    if derived_registry.is_derived(metric):
        raise HTTPException(
            status_code=409,
            detail=f"'{metric}' is a computed metric — it can't be added, edited, or "
                   f"renamed. It's derived from its inputs automatically.",
        )


# ----------------------------------------------------------------------------- schemas

class ObservationIn(BaseModel):
    metric: str
    value: float | None = None  # null for qualitative results
    unit: str = ""              # '' for unit-less qualitative results
    observed_on: str            # ISO date 'YYYY-MM-DD'
    ref_low: float | None = None
    ref_high: float | None = None
    result_type: str = "numeric"   # 'numeric' | 'qualitative' | 'censored'
    value_text: str | None = None  # qualitative result text
    operator: str | None = None    # censored comparator: '<' '>' '<=' '>='
    normal_text: str | None = None # expected-normal for qualitative results
    ref_low_operator: str | None = None   # strict lower bound '>' (else NULL/'>=' inclusive)
    ref_high_operator: str | None = None  # strict upper bound '<' (else NULL/'<=' inclusive)
    loinc: str | None = None
    source: str = "manual"
    document_id: int | None = None
    collection_id: int | None = None  # the timed collection this analyte belongs to


class ObservationOut(BaseModel):
    id: int


class ObservationRow(BaseModel):
    """One row of a metric's series, as get_series returns it (read side).
    `id` lets the frontend target a row for edit/delete. `value` is null for
    qualitative results; `value_text`/`operator` carry the non-numeric parts.
    `id` is null for a DERIVED (computed) metric's rows — they have no stored row,
    so the frontend keys them by observed_on and offers no edit/delete."""
    id: int | None = None
    observed_on: str
    value: float | None = None
    unit: str
    ref_low: float | None = None
    ref_high: float | None = None
    result_type: str = "numeric"
    value_text: str | None = None
    operator: str | None = None
    normal_text: str | None = None   # expected-normal for qualitative results
    ref_low_operator: str | None = None
    ref_high_operator: str | None = None
    collection_id: int | None = None  # the timed collection this analyte belongs to (null = spot)


class CollectionIn(BaseModel):
    """Create/update a timed collection (24h urine, etc.). `completed_on` (the end date, =
    the analytes' observed_on) is required and validated ISO; the rest is optional context.
    `kind` is a small open label (default '24h_urine')."""
    completed_on: str
    kind: str = "24h_urine"
    started_on: str | None = None
    duration_hours: float | None = None
    volume_ml: float | None = None
    notes: str | None = None

    @model_validator(mode="after")
    def _clean(self):
        for field in ("completed_on", "started_on"):
            v = getattr(self, field)
            if v is not None:
                v = v.strip()
                if v and not _valid_iso_date(v):
                    raise ValueError(f"{field} must be an ISO date (YYYY-MM-DD).")
                setattr(self, field, v or None)
        if not self.completed_on:
            raise ValueError("completed_on is required.")
        self.kind = (self.kind or "").strip() or "24h_urine"
        if self.duration_hours is not None and self.duration_hours <= 0:
            raise ValueError("duration_hours must be positive.")
        if self.volume_ml is not None and self.volume_ml < 0:
            raise ValueError("volume_ml can't be negative.")
        return self


class CollectionOut(BaseModel):
    """A timed collection as stored, plus `n_readings` (how many observations reference it)
    so the UI can show fullness and gate delete."""
    id: int
    kind: str
    completed_on: str
    started_on: str | None = None
    duration_hours: float | None = None
    volume_ml: float | None = None
    notes: str | None = None
    created_at: str | None = None
    n_readings: int = 0


class CollectionReadingOut(BaseModel):
    """One analyte inside a timed collection. Deliberately the SAME shape as a series row
    (ObservationRow) plus the metric's labels, so the client formats it with the reading
    formatter it already has rather than a second display path."""
    id: int
    metric: str
    alias: str | None = None
    observed_on: str
    value: float | None = None
    unit: str
    ref_low: float | None = None
    ref_high: float | None = None
    result_type: str = "numeric"
    value_text: str | None = None
    operator: str | None = None
    normal_text: str | None = None
    ref_low_operator: str | None = None
    ref_high_operator: str | None = None


class FlagOut(BaseModel):
    metric: str
    kind: str
    severity: str
    message: str
    detail: dict
    observed_on: str | None = None   # date of the reading this flag concerns (None = whole-series)


class AnomalyGroupOut(BaseModel):
    """One (kind, direction) of a metric's historical anomalies, condensed. The
    summary stats are deterministic counts/spans over the engine's flags; `detail`
    is the ranked, per-group-capped list of the individual readings."""
    metric: str
    kind: str
    direction: str
    severity: str
    count: int
    total: int
    value_min: float
    value_max: float
    unit: str
    date_first: str
    date_last: str
    condensed: bool
    summary: str
    detail: list[FlagOut]


class HistoryOut(BaseModel):
    """The per-metric historical-anomaly view: anomalies grouped + summarized by
    (kind, direction). Empty `groups` when nothing stands out."""
    metric: str
    groups: list[AnomalyGroupOut]


class MetricInfo(BaseModel):
    """A metric and its current unit. The MATCH KEY is the metric's id; `metric` (the
    lab's verbose wording) and `alias` (the shorthand) are two LABELS that both resolve to
    it. `metric` is the label used in per-metric URLs (stable + human-readable); `alias`
    (null -> show `metric`) is what the UI displays and never appears in a route path.
    `derived` marks a COMPUTED metric (e.g. 'Calcium Corrected') — read-only, not
    user-writable, no lab reference range."""
    metric: str
    alias: str | None = None
    unit: str | None = None  # NULL for a metric with only qualitative readings (unitless);
    #                          the form then doesn't lock a unit, so a first numeric can set it
    in_collection: bool = False  # ≥1 reading belongs to a timed collection (picker grouping)
    group: str | None = None     # optional user group label (picker optgroup); null -> ungrouped
    derived: bool = False
    derived_description: str | None = None  # "computed from ..." caption; null for stored metrics
    derived_advisory: str | None = None     # warning-level notice for a derived metric that is a
    #                                          documented exception to the "clinically standard" bar
    #                                          (e.g. NLR — a research marker, no reference range);
    #                                          null for every standard metric. Rendered prominently.
    latest_on: str | None = None            # that metric's most recent reading date. The list stays
    #                                          ordered by NAME; this is a fact about each metric, so
    #                                          the UI can default to the most recently measured one
    #                                          instead of whatever sorts first alphabetically.


class MetricRenameIn(BaseModel):
    """Request body for renaming a metric. new_name is trimmed; the empty case is
    rejected here so the route only ever sees a usable name."""
    new_name: str

    @model_validator(mode="after")
    def _clean(self):
        self.new_name = self.new_name.strip()
        if not self.new_name:
            raise ValueError("new_name is required.")
        return self


class MetricRenameOut(BaseModel):
    """Result of a rename: the old/new names and how many readings moved."""
    old_name: str
    new_name: str
    observations_moved: int


class DisplayNameIn(BaseModel):
    """Request body for setting a metric's display name (alias). `alias` is trimmed;
    empty/None CLEARS it (the UI then falls back to the verbose label). Unlike a rename,
    this ADDS a label rather than replacing one — both labels keep resolving to the same
    metric_id (the match key), so it can't cost the metric its lab-wording label."""
    alias: str | None = None

    @model_validator(mode="after")
    def _clean(self):
        if self.alias is not None:
            self.alias = self.alias.strip() or None
        return self


class MetricRef(BaseModel):
    """A metric's canonical name + display alias — the minimal identity pair, used where
    a full MetricInfo (with unit) isn't needed (e.g. an ingest-resolution match)."""
    metric: str
    alias: str | None = None


class MetricSuggestion(BaseModel):
    """A 'did you mean' candidate: an existing metric similar to a queried name, with the
    similarity score (0–1). Surfaced at import/add so a same-analyte-different-wording
    case can attach to the existing metric instead of duplicating. Advisory, not applied."""
    metric: str
    alias: str | None = None
    score: float


class MetricResolveOut(BaseModel):
    """Resolution of an incoming (import/add) name against the registry. `exact` is the
    metric the name attaches to right now (either label, normalized), or null if it's
    genuinely new; `suggestions` are fuzzy near-matches to offer when there's no exact
    hit — the 'already exists under another name?' nudge."""
    query: str
    exact: MetricRef | None = None
    suggestions: list[MetricSuggestion] = []


class MetricResolveBatchIn(BaseModel):
    """Request body for resolving a whole import draft in one round trip: the incoming
    names, in row order. Capped so a pathological payload can't turn one request into an
    unbounded fuzzy-scan (each name scans the registry)."""
    names: list[str] = Field(default_factory=list, max_length=500)


class MetricResolveBatchOut(BaseModel):
    """Batch resolution results, POSITIONAL: results[i] is the resolution of names[i]."""
    results: list[MetricResolveOut] = []


class ThresholdOut(BaseModel):
    """One guideline cutoff for the chart gridline + the Reference-thresholds
    section. `definition` describes the source's own framework boundary (never a
    condition); `source_full_name`/`source_guideline`/`url` are joined from the
    SOURCES registry (url is the org's official guideline page). `render_style`
    ('solid'|'dashed') tells the chart how to stroke the line; `status_note` is an
    optional closed line-confidence label (contested/soft-source/caveated/
    substantively retired) shown in the legend. Both are DISPLAY-only — the engine
    never reads them. Descriptive only."""
    cutoff: float
    source: str
    source_full_name: str
    source_guideline: str | None = None
    definition: str = ""
    url: str | None = None
    render_style: str = "solid"
    status_note: str | None = None


class ChartConfigOut(BaseModel):
    """Per-metric reference lines for the chart. `thresholds` are the metric's
    guideline cutoffs (each with its source citation + definition);
    `personal_baseline_mean` is the engine's robust CENTER (median) of the metric's
    numeric values — legacy field name; it carries the MEDIAN (robust to outliers,
    matching the detector), present ONLY when personal-baseline mode is on (null
    otherwise). `methodology_note`
    is optional display-only prose (#9) for a metric whose interpretation depends on
    another (e.g. BUN → read with creatinine); null when the metric has none.
    Descriptive values only — the chart draws gridlines labelled by source/cutoff, a
    neutral 'Personal baseline', and the note as plain text; no clinical interpretation."""
    metric: str
    thresholds: list[ThresholdOut] = []
    personal_baseline_mean: float | None = None
    methodology_note: str | None = None


class MetricCoverageOut(BaseModel):
    """One row of the metrics-coverage roster: an observed metric tagged with
    whether it carries Kind-1 guideline thresholds (and if so the bare source
    acronyms behind them, deduped) and whether it has an RCV (Reference Change
    Value) coefficient seeded — the two kinds of per-metric detector config a
    metric can carry. Names + tags + acronyms only — no cutoffs, rule text, CV
    values, or source full names (that detail lives on the metric page). The
    closed shape is itself the guard against leaking more."""
    metric: str
    has_thresholds: bool
    sources: list[str] = []
    has_rcv: bool = False


class ChangeOut(BaseModel):
    """One metric's movement since its immediately previous reading. Descriptive
    only — restates the engine's deterministic Change (no interpretation)."""
    metric: str
    status: str                     # 'rose'|'fell'|'unchanged'|'changed'|'no_previous'
    category: str                   # 'moved'|'stable'|'no_previous'
    text: str
    previous: float | None = None
    current: float | None = None
    previous_display: str | None = None
    current_display: str | None = None
    delta: float | None = None
    pct: float | None = None
    flag_transition: str | None = None
    observed_on: str | None = None


class ChangesOut(BaseModel):
    """The cross-metric 'since your last reading' digest. Surfaces ONLY metrics
    that both MOVED and whose latest reading is RECENT (within recent_days).
    Stable and single-reading metrics are still computed by the engine but
    intentionally not surfaced here. total_metrics lets the UI distinguish 'no
    data yet' (0) from 'no recent movement' (>0 but empty moved list)."""
    moved: list[ChangeOut]
    recent_days: int
    total_metrics: int


class OverviewFlagOut(BaseModel):
    """One current-state flag in the cross-metric overview (Section 1). Restates
    the engine's Flag verbatim — message is the detector's own, never reworded."""
    metric: str
    kind: str
    severity: str
    message: str
    observed_on: str | None = None


class OverviewGroupOut(BaseModel):
    """One historical-anomaly group in the cross-metric overview (Section 2).
    Restates an AnomalyGroup's deterministic summary verbatim."""
    metric: str
    kind: str
    direction: str
    severity: str
    count: int
    total: int
    summary: str


class OverviewOut(BaseModel):
    """The cross-metric overview: two ranked lists across ALL metrics. `current`
    (Section 1) is each metric's latest-reading state; `history` (Section 2) is the
    aggregated historical-anomaly groups. Both ranked severity>magnitude>recency;
    the UI shows the top few and expands the rest. Pure deterministic transform of
    flags/groups the engine already produced — no new math, no rewording."""
    current: list[OverviewFlagOut]
    history: list[OverviewGroupOut]
    total_metrics: int


class SummaryOut(BaseModel):
    """Plain-language narration of a metric's flags. `engine` is always
    `in_program` (the on-device deterministic template) now that the local-Ollama
    option is removed. `model`/`fallback_reason` are retained (always null) so the
    shape is stable — they distinguished an Ollama run and its fallback, both gone."""
    summary: str
    engine: str
    model: str | None = None
    fallback_reason: str | None = None


# Conditions & medications: standalone records (status/dates, not values). No
# analysis, no observations — additive tables surfaced for review and tracking.
_CONDITION_STATUSES = ("active", "resolved", "monitoring")


class ConditionIn(BaseModel):
    name: str
    icd10: str | None = None        # free text; the UI offers an ICD-10 lookup helper
    onset_on: str | None = None     # ISO 'YYYY-MM-DD'
    status: str = "active"          # active | resolved | monitoring
    resolved_on: str | None = None  # ISO; required iff status='resolved'
    notes: str | None = None

    @model_validator(mode="after")
    def _check_resolution(self):
        """Normalize the resolved_on invariant in ONE place (covers both POST and
        PUT): only a resolved condition may carry a resolution date. resolved_on is
        OPTIONAL even when resolved (a resolved condition with no date reads as
        'date unknown' — we don't invent one). For any other status a stray
        resolved_on is cleared, so an active/monitoring condition can never hold a
        stale resolution date."""
        if self.status not in _CONDITION_STATUSES:
            raise ValueError(
                f"status must be one of {_CONDITION_STATUSES}, got {self.status!r}."
            )
        if self.status != "resolved":
            self.resolved_on = None
        elif self.resolved_on is not None and not self.resolved_on.strip():
            self.resolved_on = None  # blank string -> unknown (stored null)
        return self


class ConditionOut(BaseModel):
    id: int
    name: str
    icd10: str | None = None
    onset_on: str | None = None
    status: str
    resolved_on: str | None = None
    notes: str | None = None
    created_at: str


class ImmunizationIn(BaseModel):
    """One vaccination record. Only the vaccine NAME is required.

    `administered_on` is optional and stays null when unknown — a childhood shot recalled
    from a paper card is a real record with no date, and inventing one would put a
    fabricated point in the record. A blank string is normalized to null so an emptied
    date field doesn't store "".

    `dose_label` and `amount` are two DIFFERENT facts: dose_label says WHICH dose in a
    series ("Dose 1", "Booster", "2023-24 season"), amount says HOW MUCH went in
    ("0.5 mL"). Both free text — dose_label because encoding a schedule would mean knowing
    each vaccine's schedule and judging whether a record is complete (a clinical judgment
    this app doesn't make), amount because it carries its own unit, exactly as an
    observation does."""
    vaccine: str
    administered_on: str | None = None    # ISO 'YYYY-MM-DD'; null = date unknown
    dose_label: str | None = None         # WHICH dose
    amount: str | None = None             # HOW MUCH, with its unit
    site: str | None = None
    lot: str | None = None
    notes: str | None = None

    @model_validator(mode="after")
    def _check(self):
        if not self.vaccine.strip():
            raise ValueError("vaccine is required.")
        if self.administered_on is not None:
            if not self.administered_on.strip():
                self.administered_on = None
            elif not _valid_iso_date(self.administered_on):
                raise ValueError("administered_on must be 'YYYY-MM-DD'.")
        return self


class ImmunizationOut(BaseModel):
    id: int
    vaccine: str
    administered_on: str | None = None
    dose_label: str | None = None
    amount: str | None = None
    site: str | None = None
    lot: str | None = None
    notes: str | None = None
    created_at: str


class MedicationIn(BaseModel):
    name: str
    dose: str | None = None         # free text, e.g. '20 mg'
    frequency: str | None = None    # free text, e.g. 'once daily'
    start_date: str | None = None   # ISO 'YYYY-MM-DD'
    end_date: str | None = None     # ISO; null => active
    notes: str | None = None


class MedicationOut(BaseModel):
    id: int
    name: str
    dose: str | None = None
    frequency: str | None = None
    start_date: str | None = None
    end_date: str | None = None
    notes: str | None = None
    active: bool                    # DERIVED: end_date is null
    created_at: str


class CreatedOut(BaseModel):
    """A newly created record's id (conditions / medications / events add)."""
    id: int


# Events: point-in-time Timeline records. event_type is one of a fixed set,
# enforced here (like the condition-status validator).
_EVENT_TYPES = ("visit", "symptom", "life_event", "procedure", "other")


class EventIn(BaseModel):
    event_date: str                 # ISO 'YYYY-MM-DD'
    event_type: str                 # visit | symptom | life_event | procedure | other
    title: str
    notes: str | None = None

    @model_validator(mode="after")
    def _check_type(self):
        if self.event_type not in _EVENT_TYPES:
            raise ValueError(f"event_type must be one of {_EVENT_TYPES}, got {self.event_type!r}.")
        return self


class EventOut(BaseModel):
    id: int
    event_date: str
    event_type: str
    title: str
    notes: str | None = None
    created_at: str


# Profile: permanent demographics + time-varying physical measurements. Local-only;
# feeds NO analysis/flag/chart logic (foundation data for future derived calcs).
_SEX_VALUES = ("male", "female", "other")
_MEASUREMENT_FIELDS = ("weight", "height")


class MeasurementOut(BaseModel):
    id: int
    field: str                      # 'weight' | 'height'
    value: float
    unit: str
    recorded_on: str                # ISO 'YYYY-MM-DD'


class ProfileOut(BaseModel):
    """The singleton profile plus the CURRENT (latest) weight and height. Any of
    these is null when not yet entered — the empty state the UI renders cleanly."""
    sex: str | None = None
    date_of_birth: str | None = None
    weight: MeasurementOut | None = None
    height: MeasurementOut | None = None


class ProfileIn(BaseModel):
    """Update the singleton's sex / DOB. Both optional/nullable; constraints are
    enforced HERE so they hold regardless of client (sex enum, DOB strict ISO)."""
    sex: str | None = None
    date_of_birth: str | None = None

    @model_validator(mode="after")
    def _check(self):
        if self.sex is not None and self.sex not in _SEX_VALUES:
            raise ValueError(f"sex must be one of {_SEX_VALUES} or null, got {self.sex!r}.")
        if self.date_of_birth is not None and not _valid_iso_date(self.date_of_birth):
            raise ValueError("date_of_birth must be 'YYYY-MM-DD'.")
        return self


class MeasurementIn(BaseModel):
    """Add a weight/height measurement (append-only). field enum + strict ISO date
    + non-empty unit, all enforced server-side."""
    field: str
    value: float
    unit: str
    recorded_on: str                # ISO 'YYYY-MM-DD'

    @model_validator(mode="after")
    def _check(self):
        if self.field not in _MEASUREMENT_FIELDS:
            raise ValueError(f"field must be one of {_MEASUREMENT_FIELDS}, got {self.field!r}.")
        if not self.unit.strip():
            raise ValueError("unit is required.")
        if not _valid_iso_date(self.recorded_on):
            raise ValueError("recorded_on must be 'YYYY-MM-DD'.")
        return self


class MeasurementUpdateIn(BaseModel):
    """Correct an existing weight/height measurement. `field` is deliberately absent —
    weight and height are different quantities, so a row never moves between them (see
    db.update_profile_measurement)."""
    value: float
    unit: str
    recorded_on: str                # ISO 'YYYY-MM-DD'

    @model_validator(mode="after")
    def _check(self):
        if not self.unit.strip():
            raise ValueError("unit is required.")
        if not _valid_iso_date(self.recorded_on):
            raise ValueError("recorded_on must be 'YYYY-MM-DD'.")
        return self


class TimelineEntryOut(BaseModel):
    """One dated Timeline entry, merged from a source. Serialized from
    timeline.TimelineEntry; the client filters by `kind` and flips order locally."""
    date: str
    kind: str                       # 'condition' | 'medication' | 'event' | 'lab'
    title: str
    subtype: str | None = None
    detail: dict = {}
    link: str | None = None
    ref_id: int | None = None


class SettingOut(BaseModel):
    """One adjustable setting, fully described for the panel. `value` is the
    effective value (stored override, else the code-constant default). The
    `minimum`/`maximum` fields are the seam for future bounded settings — null
    for the current display-volume ones. `options` is non-null only for a
    categorical (enum) setting, carrying its closed choice list for the picker;
    a numeric setting leaves it null. Serialized from settings.view().

    NOTE: this response intentionally carries NO credential or endpoint field —
    the engine SELECTION lives here, but provider keys/endpoints stay in env and
    are never serialized."""
    key: str
    value: int | float | str        # int settings stay int (render cleanly, no '30.0'); enum is a str
    default: int | float | str
    type: str                       # 'int' | 'float' | 'enum'
    label: str
    description: str
    minimum: float | None = None
    maximum: float | None = None
    step: float | None = None
    unit: str | None = None
    group: str | None = None        # panel section heading
    options: list[dict] | None = None  # enum only: [{value, label, description}]


class SettingsUpdateIn(BaseModel):
    """A batch of {key: value} edits from the panel's Save. Validated against the
    registry in settings.apply_updates (unknown key / wrong type / out-of-allowlist
    enum -> 400). Values are numeric for numeric settings and a string for an
    enum; the registry enforces the closed allowlist server-side."""
    values: dict[str, float | str]


class CandidacyOut(BaseModel):
    """Purely statistical assessment of whether a metric should be OFFERED
    personal-baseline tracking — counts and a fraction, no interpretation.
    `numeric_count` is a SEPARATE, lower bar than `n`: total numeric readings
    (no ref-bound requirement), the denominator the per-metric quiet link's
    "is this computable at all" check uses — distinct from `n` (judgeable-only,
    for the suggestion-banner fraction). See personal_baseline_candidacy."""
    n: int                          # judgeable numeric readings (carry a lab range)
    out_of_range: int
    fraction: float
    is_candidate: bool
    numeric_count: int              # ALL numeric readings, no ref-bound requirement


class MetricSettingsOut(BaseModel):
    """A metric's personal-baseline state plus its (live) candidacy. `note` is the
    user's own annotation. suggestion_dismissed is a DISTINCT state from 'not a
    candidate' — it records 'don't suggest again' so the banner shows only when
    candidate AND mode off AND not dismissed."""
    metric: str
    personal_baseline_mode: bool
    note: str
    suggestion_dismissed: bool
    candidacy: CandidacyOut


class MetricSettingsIn(BaseModel):
    """Update a metric's personal-baseline settings. All fields optional — only
    those provided change; the rest keep their stored value."""
    personal_baseline_mode: bool | None = None
    note: str | None = None
    suggestion_dismissed: bool | None = None


# The raw settings-table key for the one-time global personal-baseline explainer.
# Deliberately NOT a settings.py SettingDef — that registry models tunable knobs
# (numeric/enum), not a one-shot "has the user seen this" boolean. Stored via
# db.get_setting/set_setting directly, same physical table, but a raw key never
# surfaced in GET /settings (settings.views() only iterates its own registry).
BASELINE_EXPLAINER_SEEN_KEY = "baseline_explainer_seen"


class BaselineExplainerOut(BaseModel):
    """Whether the user has dismissed the one-time global personal-baseline
    explainer. Absent key (nothing ever persisted) reads as seen: False."""
    seen: bool


# The raw settings-table key for the export handoff's capability gate (CLAUDE.md
# "The export handoff" — Consent mechanics). Like BASELINE_EXPLAINER_SEEN_KEY,
# deliberately NOT a settings.py SettingDef — a capability flag, not a tunable
# knob, so it never surfaces in GET /settings. UNLIKE that one-way "seen" flag,
# this is a genuine ON/OFF toggle (PUT, not a one-way POST /dismiss): the
# charter requires revoking the capability to be exactly as easy as granting it.
EXPORT_HOSTED_ENABLED_KEY = "export_hosted_enabled"


class ExportEnabledOut(BaseModel):
    """Whether the export handoff's capability gate is on. Absent key (nothing
    ever persisted) reads as enabled: False. This gate alone sends nothing —
    it only allows a preview to be assembled; every send still needs its own
    per-action confirmation (see /export/{metric}/preview and /confirm)."""
    enabled: bool


class ExportEnabledIn(BaseModel):
    enabled: bool


# ----------------------------------------------------------------------------- routes

@app.post("/observations", response_model=ObservationOut)
def create_observation(obs: ObservationIn, conn=Depends(get_conn)) -> ObservationOut:
    """Insert one measurement; returns its new row id.

    A reading is unique per (metric, observed_on); a repeat returns 409 Conflict
    rather than surfacing the raw UNIQUE-constraint IntegrityError as a 500."""
    _reject_derived_write(obs.metric)
    # A bad collection_id would otherwise surface as the misleading duplicate 409 (via the
    # FK IntegrityError); check it explicitly for a clear 404.
    if obs.collection_id is not None and get_collection(conn, obs.collection_id) is None:
        raise HTTPException(status_code=404,
                            detail=f"No collection with id {obs.collection_id}.")
    try:
        new_id = add_observation(conn, **obs.model_dump(),
                                 seed_keys=metric_config_registry.SEED.keys())
    except sqlite3.IntegrityError:
        raise HTTPException(
            status_code=409,
            detail=f"An observation for '{obs.metric}' on {obs.observed_on} already exists.",
        )
    except UnitMismatchError as e:
        raise HTTPException(
            status_code=409,
            detail=f"{e} Use {e.existing}, or edit the existing readings first.",
        )
    return ObservationOut(id=new_id)


@app.put("/observations/{obs_id}", response_model=ObservationOut)
def edit_observation(obs_id: int, obs: ObservationIn, conn=Depends(get_conn)) -> ObservationOut:
    """Update an observation by id. Changing the date onto one that already
    exists for the metric hits UNIQUE(metric, observed_on) and returns the same
    409 as the add path; an unknown id returns 404."""
    _reject_derived_write(obs.metric)
    try:
        found = update_observation(
            conn, obs_id, obs.metric, obs.value, obs.unit, obs.observed_on,
            obs.ref_low, obs.ref_high, obs.operator,
            obs.ref_low_operator, obs.ref_high_operator,
            seed_keys=metric_config_registry.SEED.keys(),
        )
    except sqlite3.IntegrityError:
        raise HTTPException(
            status_code=409,
            detail=f"An observation for '{obs.metric}' on {obs.observed_on} already exists.",
        )
    except UnitMismatchError as e:
        raise HTTPException(
            status_code=409,
            detail=f"{e} Use {e.existing}, or edit the existing readings first.",
        )
    if not found:
        raise HTTPException(status_code=404, detail=f"No observation with id {obs_id}.")
    return ObservationOut(id=obs_id)


@app.delete("/observations/{obs_id}", status_code=204)
def remove_observation(obs_id: int, conn=Depends(get_conn)) -> None:
    """Delete an observation by id. Unknown id returns 404."""
    if not delete_observation(conn, obs_id):
        raise HTTPException(status_code=404, detail=f"No observation with id {obs_id}.")


@app.get("/flags/{metric:path}", response_model=list[FlagOut])
def get_flags(metric: str, conn=Depends(get_conn)) -> list[FlagOut]:
    """Run the detection engine over a metric's full series. Empty list if the
    metric has no observations or nothing stands out."""
    series = resolve_series(conn, metric)
    mode = get_metric_settings(conn, metric)["personal_baseline_mode"]
    flags = analyze_series(metric, series, personal_baseline_mode=mode,
                           **metric_config_registry.get_config(conn, metric))
    return [FlagOut(**asdict(f)) for f in flags]


@app.get("/history/{metric:path}", response_model=HistoryOut)
def get_history(metric: str, conn=Depends(get_conn)) -> HistoryOut:
    """Every reading that stood out across this metric's whole history — outside
    its own reference range, or unusual against the personal baseline at that
    point — grouped by (kind, direction) and condensed into a summary line when a
    group has many readings (so a noisy metric leads with a digest, not a wall).
    Summary counts come from the FULL flag set; each group's `detail` is the
    ranked, capped-at-10 list of its members. No SQL or math here."""
    series = resolve_series(conn, metric)
    mode = get_metric_settings(conn, metric)["personal_baseline_mode"]
    groups = summarize_history(
        metric, series,
        condense_threshold=settings_registry.resolve(conn, "anomaly_condense_threshold"),
        max_detail=settings_registry.resolve(conn, "anomaly_detail_cap"),
        personal_baseline_mode=mode,
        thresholds=metric_config_registry.get_config(conn, metric).get("thresholds"),
    )
    return HistoryOut(metric=metric, groups=[AnomalyGroupOut(**asdict(g)) for g in groups])


def _gather_explain_substrate(conn, metric: str) -> dict:
    """The deterministic substrate explain.assemble_explain_context needs for
    ONE metric — the same calls /summary and /chart-config make. Used by the
    export handoff's /export/{metric} preview/confirm routes (CLAUDE.md "The
    export handoff") to build the outbound bundle. No math/SQL beyond the fetches."""
    series = resolve_series(conn, metric)
    mode = get_metric_settings(conn, metric)["personal_baseline_mode"]
    flags = analyze_series(metric, series, personal_baseline_mode=mode,
                           **metric_config_registry.get_config(conn, metric))
    thresholds = metric_config_registry.get_thresholds_detailed(conn, metric)
    unit = next((r.get("unit") for r in reversed(series) if r.get("unit")), "")
    pb_mean = personal_baseline_mean(series)
    note = metric_config_registry.get_methodology_note(conn, metric)
    change = latest_change(metric, series)
    return {"series": series, "mode": mode, "flags": flags, "thresholds": thresholds,
            "unit": unit, "pb_mean": pb_mean, "note": note, "change": change}


def _assemble_export_bundle(conn, metric: str) -> dict:
    """Assembles the per-metric bundle the export handoff sends (CLAUDE.md 'The
    export handoff'). Always freshly assembled from the CURRENT DB state — never
    cached — so preview and
    confirm each reflect what's true right now; the gateway's token
    byte-compare (not a server-side cache) is what catches a change between
    the two calls."""
    s = _gather_explain_substrate(conn, metric)
    return explain.assemble_explain_context(
        metric, s["unit"], s["series"], s["flags"], s["thresholds"],
        s["pb_mean"], s["note"], s["change"], s["mode"],
    )


@app.get("/summary/{metric:path}", response_model=SummaryOut)
def get_summary(metric: str, conn=Depends(get_conn)) -> SummaryOut:
    """Narrate the SAME flags `/flags/{metric}` returns. All detection and math
    stay in analyze_series; this only turns the finished Flag list into prose via
    the swappable narrate layer (default deterministic template; no SQL or math
    here)."""
    series = resolve_series(conn, metric)
    mode = get_metric_settings(conn, metric)["personal_baseline_mode"]
    flags = analyze_series(metric, series, personal_baseline_mode=mode,
                           **metric_config_registry.get_config(conn, metric))
    # Engine selection is the persisted setting (env only seeds its initial value);
    # the gateway still owns redaction/preview/confirmation per engine downstream.
    engine_choice = settings_registry.resolve(conn, settings_registry.SUMMARIZER_ENGINE_KEY)
    result = summarize_with_engine(flags, engine_choice)
    return SummaryOut(summary=result.text, engine=result.engine,
                      model=result.model, fallback_reason=result.fallback_reason)


@app.get("/observations/{metric:path}", response_model=list[ObservationRow])
def get_observations(metric: str, conn=Depends(get_conn)) -> list[ObservationRow]:
    """Raw series for a metric, oldest first — passthrough of get_series, no
    analysis. Empty list if the metric has no observations. For a DERIVED metric
    this returns the computed series (id=null rows; gaps as value=null)."""
    return [ObservationRow(**row) for row in resolve_series(conn, metric)]


@app.get("/metrics", response_model=list[MetricInfo])
def get_metrics(conn=Depends(get_conn)) -> list[MetricInfo]:
    """Each stored metric with its current unit (most recent reading's unit), so
    the entry form can auto-fill/lock the unit for an already-known metric. DERIVED
    metrics (computed, e.g. 'Calcium Corrected') are appended here — and ONLY here,
    not in the shared list_metrics_with_units — so they surface in the picker without
    leaking into /overview or the timeline, which don't run resolve_series. A derived
    metric appears only once all its inputs have readings, then the merged list is
    re-sorted case-insensitively to match the stored-metric ordering."""
    def _to_info(row: dict) -> MetricInfo:
        row = dict(row)
        row["group"] = row.pop("metric_group", None)  # DB column -> model field name
        return MetricInfo(**row)
    infos = [_to_info(row) for row in list_metrics_with_units(conn)]
    present = {i.metric for i in infos}
    # A derived metric's display alias: the user's override (db.derived_alias) wins, else
    # the spec's curated default (e.g. NLR), else none (show the verbose name).
    overrides = get_derived_aliases(conn)
    infos += [
        MetricInfo(metric=d.name, alias=overrides.get(d.name) or d.display_name,
                   unit=d.unit, derived=True, derived_description=d.description,
                   derived_advisory=d.advisory)
        for d in derived_registry.available(present)
    ]
    infos.sort(key=lambda i: i.metric.lower())
    return infos


def _resolve_one(conn, name: str) -> MetricResolveOut:
    """Resolve ONE incoming name to {exact | suggestions}. Shared by the single-name GET
    (the add form's per-keystroke lookup) and the batch POST (the import review's whole
    draft at once), so both surfaces score identically — one source of truth."""
    exact = resolve_ingest(conn, name)
    suggestions = [] if exact else suggest_metrics(conn, name)
    return MetricResolveOut(
        query=name,
        exact=MetricRef(**exact) if exact else None,
        suggestions=[MetricSuggestion(**s) for s in suggestions],
    )


@app.get("/metrics/resolve", response_model=MetricResolveOut)
def get_metric_resolve(name: str, conn=Depends(get_conn)) -> MetricResolveOut:
    """Resolve an incoming metric name (import/add de-dup). Returns the EXACT metric it
    attaches to (either label, normalized) if any, else fuzzy 'did you mean' suggestions —
    so the same analyte under different wording can be mapped to the existing metric
    instead of creating a duplicate. Read-only; the caller decides. Single-name form, for
    the add form's debounced per-keystroke lookup (batching buys nothing there)."""
    return _resolve_one(conn, name)


@app.post("/metrics/resolve-batch", response_model=MetricResolveBatchOut)
def post_metrics_resolve_batch(body: MetricResolveBatchIn,
                               conn=Depends(get_conn)) -> MetricResolveBatchOut:
    """Resolve MANY incoming names in one round trip — the import review's whole draft
    (a PDF is typically 10–40 rows), rather than one request per row. Same per-name logic
    as the GET (both call _resolve_one), so the two surfaces can't drift. Results are
    positional: results[i] corresponds to names[i]. Read-only — resolving decides nothing;
    the save path re-resolves server-side anyway."""
    return MetricResolveBatchOut(results=[_resolve_one(conn, n) for n in body.names])


def _derived_alias_conflict(conn, metric: str, alias: str) -> str | None:
    """The display label a proposed DERIVED alias would collide with (normalized), or None.
    Derived aliases are display-only (not ingest match keys), so this is a UI-clarity check,
    not a data-integrity one: it just keeps the picker unambiguous. Checks stored metrics
    (name + alias) and every OTHER derived metric (name + its effective alias)."""
    target = normalize_label(alias)
    for r in list_registry_labels(conn):
        if normalize_label(r["name"]) == target:
            return r["name"]
        if r["alias"] and normalize_label(r["alias"]) == target:
            return r["alias"]
    overrides = get_derived_aliases(conn)
    for d in derived_registry.REGISTRY.values():
        if d.name == metric:
            continue
        if normalize_label(d.name) == target:
            return d.name
        eff = overrides.get(d.name) or d.display_name
        if eff and normalize_label(eff) == target:
            return eff
    return None


@app.put("/metrics/{metric:path}/display-name", response_model=MetricRef)
def put_metric_display_name(metric: str, body: DisplayNameIn,
                            conn=Depends(get_conn)) -> MetricRef:
    """Set (or clear) a metric's DISPLAY name (alias) — a pure presentation change. For a
    STORED metric it ADDS a second label rather than replacing the verbose one; both keep
    resolving to the same metric_id (the match key), so the metric never loses its
    lab-wording label. For a DERIVED (computed) metric it overrides the display label only
    (stored in db.derived_alias; clearing falls back to the spec's curated default). A
    colliding label (one another metric already shows/resolves by) → 409; an unknown metric
    → 404."""
    if derived_registry.is_derived(metric):
        if body.alias is not None:
            conflict = _derived_alias_conflict(conn, metric, body.alias)
            if conflict is not None:
                raise HTTPException(
                    status_code=409,
                    detail=f"The name {body.alias!r} is already used by {conflict!r}.")
        set_derived_alias(conn, metric, body.alias)
        return MetricRef(metric=metric, alias=body.alias)
    try:
        ok = set_metric_alias(conn, metric, body.alias)
    except AliasConflictError as e:
        raise HTTPException(status_code=409, detail=str(e))
    if not ok:
        raise HTTPException(status_code=404, detail=f"No metric named {metric}.")
    return MetricRef(metric=metric, alias=body.alias)


@app.put("/metrics/{metric:path}/rename", response_model=MetricRenameOut)
def put_rename_metric(metric: str, body: MetricRenameIn,
                      conn=Depends(get_conn)) -> MetricRenameOut:
    """Rename a metric (relabel only — purely local, no analysis touched). The
    db layer carries readings + per-metric settings across atomically. Maps its
    guards to HTTP: renaming onto an existing metric → 409 (refused merge), an
    unknown source metric (no readings moved) → 404. A no-op same-name rename is
    rejected up front. `{metric:path}` so names containing '/' (e.g. 'A/G Ratio')
    resolve."""
    new = body.new_name  # already trimmed/validated non-empty
    if new == metric:
        raise HTTPException(status_code=400,
                            detail="The new name is the same as the current name.")
    # A derived name is reserved/computed: can't rename FROM it (it has no rows) or
    # ONTO it (that would shadow the virtual metric with a stored one).
    _reject_derived_write(metric)
    _reject_derived_write(new)
    try:
        moved = rename_metric(conn, metric, new)
    except MetricExistsError as e:
        raise HTTPException(status_code=409, detail=str(e))
    if moved == 0:
        raise HTTPException(status_code=404, detail=f"No metric named {metric}.")
    return MetricRenameOut(old_name=metric, new_name=new, observations_moved=moved)


class MetricUnitIn(BaseModel):
    """New unit LABEL for a metric — a relabel across all its non-qualitative readings.
    Values are NOT converted (stored as entered). Trimmed; may be '' (dimensionless)."""
    unit: str

    @model_validator(mode="after")
    def _clean(self):
        self.unit = self.unit.strip()
        return self


class MetricUnitOut(BaseModel):
    metric: str
    unit: str
    readings_relabeled: int


@app.put("/metrics/{metric:path}/unit", response_model=MetricUnitOut)
def put_metric_unit(metric: str, body: MetricUnitIn,
                    conn=Depends(get_conn)) -> MetricUnitOut:
    """RELABEL a metric's unit across all its numeric/censored readings — a pure LABEL
    change, NOT a value conversion (values are stored as entered and left untouched; use
    this for casing fixes like 'mg/dl'->'mg/dL' or equivalent units like 'EU/dL'->'mg/dL',
    not for a real conversion, which needs the values edited too). Qualitative readings
    are unitless and untouched. A DERIVED metric's unit is fixed by its computation → 409.
    An unknown metric, or one with no non-qualitative readings to relabel → 404.
    `{metric:path}` so names containing '/' resolve."""
    _reject_derived_write(metric)
    n = set_metric_unit(conn, metric, body.unit)
    if n == 0:
        raise HTTPException(status_code=404,
                            detail=f"No numeric readings to relabel for {metric}.")
    return MetricUnitOut(metric=metric, unit=body.unit, readings_relabeled=n)


class MetricGroupIn(BaseModel):
    """Group LABEL for a metric — a purely presentational picker cluster (an <optgroup>).
    Trimmed; '' or null CLEARS the group (metric returns to the ungrouped top level)."""
    group: str | None = None

    @model_validator(mode="after")
    def _clean(self):
        self.group = (self.group or "").strip() or None
        return self


class MetricGroupOut(BaseModel):
    metric: str
    group: str | None = None


@app.put("/metrics/{metric:path}/group", response_model=MetricGroupOut)
def put_metric_group(metric: str, body: MetricGroupIn,
                     conn=Depends(get_conn)) -> MetricGroupOut:
    """Set (or clear) a metric's GROUP label — a display-only picker cluster, like the
    alias. Touches no identity/match key and no reading. A DERIVED metric already has its
    own 'Computed metrics' group → 409. An unknown metric → 404. `{metric:path}` so names
    containing '/' resolve."""
    _reject_derived_write(metric)
    ok = set_metric_group(conn, metric, body.group)
    if not ok:
        raise HTTPException(status_code=404, detail=f"No metric named {metric}.")
    return MetricGroupOut(metric=metric, group=body.group)


@app.get("/chart-config/{metric:path}", response_model=ChartConfigOut)
def get_chart_config(metric: str, conn=Depends(get_conn)) -> ChartConfigOut:
    """Reference-line config the chart draws as gridlines: the metric's threshold
    cutoffs (from metric_config, always — each joined with its source's full name /
    guideline / official URL for the Reference-thresholds section) and — only when
    personal-baseline mode is on — the engine's mean of its numeric values. No
    detection here; the mean is computed by analysis.personal_baseline_mean so the
    engine owns the number."""
    detailed = metric_config_registry.get_thresholds_detailed(conn, metric)
    thresholds = []
    for t in detailed:
        src = metric_config_registry.SOURCES.get(t["source"], {})
        thresholds.append(ThresholdOut(
            cutoff=t["cutoff"], source=t["source"],
            source_full_name=src.get("full_name", t["source"]),
            source_guideline=src.get("guideline"),
            definition=t["definition"], url=src.get("url"),
            render_style=t["render_style"], status_note=t["status_note"],
        ))
    mode = get_metric_settings(conn, metric)["personal_baseline_mode"]
    pb_mean = personal_baseline_mean(resolve_series(conn, metric)) if mode else None
    note = metric_config_registry.get_methodology_note(conn, metric)
    return ChartConfigOut(metric=metric, thresholds=thresholds,
                          personal_baseline_mean=pb_mean, methodology_note=note)


@app.get("/metrics-coverage", response_model=list[MetricCoverageOut])
def get_metrics_coverage(conn=Depends(get_conn)) -> list[MetricCoverageOut]:
    """Read-only coverage roster: every observed metric tagged with whether it has
    Kind-1 guideline thresholds, and (when it does) the deduped source acronyms
    behind them. Pure assembly of existing reads — no new query. The observed list
    is already alphabetical; a configured metric with no observations (the legacy
    dummy) is absent from it and so never appears. Acronyms only — no cutoffs, rule
    text, or source full names; the per-threshold detail lives on the metric page."""
    configured = list_all_metric_config(conn)  # {metric: {key: value}}
    out = []
    for metric in list_observed_metrics(conn):
        cfg = configured.get(metric, {})
        has_thresholds = "thresholds" in cfg
        has_rcv = "rcv_cv" in cfg
        sources = []
        if has_thresholds:
            # Bare source labels, deduped, first-seen order preserved.
            detailed = metric_config_registry.get_thresholds_detailed(conn, metric)
            sources = list(dict.fromkeys(t["source"] for t in detailed))
        out.append(MetricCoverageOut(metric=metric, has_thresholds=has_thresholds,
                                     sources=sources, has_rcv=has_rcv))
    return out


@app.get("/changes", response_model=ChangesOut)
def get_changes(conn=Depends(get_conn)) -> ChangesOut:
    """Cross-metric 'since your last reading' digest. For each metric the engine
    (latest_change) computes its movement deterministically; this route only
    SURFACES the ones that both moved and are recent (is_recent vs the
    changes_recent_days setting) — stale months-old changes, unchanged metrics,
    and single-reading metrics are dropped from the digest so it doesn't
    re-report movement the user has already seen. No math here; the engine
    computes every Change and the recency test."""
    recent_days = settings_registry.resolve(conn, "changes_recent_days")
    metrics = list_metrics_with_units(conn)
    moved_recent: list[ChangeOut] = []
    for info in metrics:
        change = latest_change(info["metric"], get_series(conn, info["metric"]))
        if change.category == "moved" and is_recent(change.observed_on, within_days=recent_days):
            moved_recent.append(ChangeOut(**asdict(change)))
    return ChangesOut(moved=moved_recent, recent_days=recent_days,
                      total_metrics=len(metrics))


# How many ranked items each overview section returns. The UI shows the top 5 and
# expands the rest, so this only bounds the payload for a pathological metric count
# (single local user — generous). Not a detection knob.
OVERVIEW_MAX = 100


@app.get("/overview", response_model=OverviewOut)
def get_overview(conn=Depends(get_conn)) -> OverviewOut:
    """Cross-metric overview in ONE server-side pass over all metrics (like
    /changes): per metric one get_series + one mode resolve, then the pure engine
    computes its current-state flags (current_flags) and historical-anomaly groups
    (summarize_history). The two lists are concatenated across metrics and ranked
    by the engine's existing keys (rank_flags_cross_metric / rank_groups_cross_metric):
    severity > deviation magnitude > recency. No SQL math and no rewording here —
    every line is a Flag.message or AnomalyGroup.summary the engine produced.

    Personal-baseline mode is resolved per metric (same as /flags, /history), so a
    pb-mode metric contributes neutral 'within your established range' readings as
    INFO (they sort last) and reserves watch/high for genuine pattern breaks."""
    metrics = list_metrics_with_units(conn)
    # Resolve the display-volume settings once, not per metric.
    condense = settings_registry.resolve(conn, "anomaly_condense_threshold")
    detail_cap = settings_registry.resolve(conn, "anomaly_detail_cap")

    current: list = []
    groups: list = []
    # Stored metrics (get_series) then derived metrics (computed on read) — the same
    # engine over both, so a derived metric's flags (e.g. Non-HDL's ATP III threshold)
    # rank alongside stored ones. resolve_derived_series is the parity seam.
    stored = [(info["metric"], get_series(conn, info["metric"])) for info in metrics]
    derived = list(resolve_derived_series(conn).items())
    for m, series in stored + derived:
        mode = get_metric_settings(conn, m)["personal_baseline_mode"]
        cfg = metric_config_registry.get_config(conn, m)
        current.extend(current_flags(m, series, personal_baseline_mode=mode, **cfg))
        groups.extend(summarize_history(
            m, series, condense_threshold=condense, max_detail=detail_cap,
            personal_baseline_mode=mode, thresholds=cfg.get("thresholds"),
        ))

    current = rank_flags_cross_metric(current)[:OVERVIEW_MAX]
    groups = rank_groups_cross_metric(groups)[:OVERVIEW_MAX]
    return OverviewOut(
        current=[OverviewFlagOut(metric=f.metric, kind=f.kind, severity=f.severity,
                                 message=f.message, observed_on=f.observed_on)
                 for f in current],
        history=[OverviewGroupOut(metric=g.metric, kind=g.kind, direction=g.direction,
                                  severity=g.severity, count=g.count, total=g.total,
                                  summary=g.summary)
                 for g in groups],
        total_metrics=len(metrics) + len(derived),
    )


@app.get("/conditions", response_model=list[ConditionOut])
def get_conditions(conn=Depends(get_conn)) -> list[ConditionOut]:
    """List all conditions (status, not value). No analysis — a plain record read."""
    return [ConditionOut(**row) for row in list_conditions(conn)]


@app.post("/conditions", response_model=CreatedOut, status_code=201)
def create_condition(body: ConditionIn, conn=Depends(get_conn)) -> CreatedOut:
    """Add a condition. ICD-10 is free text; the resolved_on invariant is enforced
    on the ConditionIn model (set iff status='resolved')."""
    new_id = add_condition(conn, body.name, icd10=body.icd10, onset_on=body.onset_on,
                           status=body.status, resolved_on=body.resolved_on, notes=body.notes)
    return CreatedOut(id=new_id)


@app.put("/conditions/{condition_id}", response_model=ConditionOut)
def edit_condition(condition_id: int, body: ConditionIn, conn=Depends(get_conn)) -> ConditionOut:
    """Full-replace edit of a condition (same fields as POST, same resolved_on
    invariant). Unknown id returns 404. Returns the updated record."""
    found = update_condition(conn, condition_id, name=body.name, icd10=body.icd10,
                             onset_on=body.onset_on, status=body.status,
                             resolved_on=body.resolved_on, notes=body.notes)
    if not found:
        raise HTTPException(status_code=404, detail=f"No condition with id {condition_id}.")
    row = next(c for c in list_conditions(conn) if c["id"] == condition_id)
    return ConditionOut(**row)


@app.delete("/conditions/{condition_id}", status_code=204)
def remove_condition(condition_id: int, conn=Depends(get_conn)) -> None:
    """Delete a condition by id. Unknown id returns 404."""
    if not delete_condition(conn, condition_id):
        raise HTTPException(status_code=404, detail=f"No condition with id {condition_id}.")


@app.get("/immunizations", response_model=list[ImmunizationOut])
def get_immunizations(conn=Depends(get_conn)) -> list[ImmunizationOut]:
    """List all immunizations, newest first with undated records last. A plain record
    read — an immunization has a date and a name, never a value, and no analysis runs
    over it."""
    return [ImmunizationOut(**row) for row in list_immunizations(conn)]


@app.post("/immunizations", response_model=CreatedOut, status_code=201)
def create_immunization(body: ImmunizationIn, conn=Depends(get_conn)) -> CreatedOut:
    """Add an immunization. Only the vaccine name is required; see ImmunizationIn."""
    new_id = add_immunization(conn, body.vaccine, administered_on=body.administered_on,
                              dose_label=body.dose_label, amount=body.amount,
                              site=body.site, lot=body.lot, notes=body.notes)
    return CreatedOut(id=new_id)


@app.put("/immunizations/{immunization_id}", response_model=ImmunizationOut)
def edit_immunization(immunization_id: int, body: ImmunizationIn,
                      conn=Depends(get_conn)) -> ImmunizationOut:
    """Full-replace edit (same fields as POST). Unknown id returns 404."""
    found = update_immunization(conn, immunization_id, vaccine=body.vaccine,
                                administered_on=body.administered_on,
                                dose_label=body.dose_label, amount=body.amount,
                                site=body.site, lot=body.lot, notes=body.notes)
    if not found:
        raise HTTPException(status_code=404,
                            detail=f"No immunization with id {immunization_id}.")
    row = next(i for i in list_immunizations(conn) if i["id"] == immunization_id)
    return ImmunizationOut(**row)


@app.delete("/immunizations/{immunization_id}", status_code=204)
def remove_immunization(immunization_id: int, conn=Depends(get_conn)) -> None:
    """Delete an immunization by id. Unknown id returns 404."""
    if not delete_immunization(conn, immunization_id):
        raise HTTPException(status_code=404,
                            detail=f"No immunization with id {immunization_id}.")


@app.get("/medications", response_model=list[MedicationOut])
def get_medications(conn=Depends(get_conn)) -> list[MedicationOut]:
    """List all medications. `active` is derived (end_date is null), not stored."""
    return [MedicationOut(**row) for row in list_medications(conn)]


@app.post("/medications", response_model=CreatedOut, status_code=201)
def create_medication(body: MedicationIn, conn=Depends(get_conn)) -> CreatedOut:
    """Add a medication. dose/frequency are free text; a null end_date means active."""
    new_id = add_medication(conn, body.name, dose=body.dose, frequency=body.frequency,
                            start_date=body.start_date, end_date=body.end_date,
                            notes=body.notes)
    return CreatedOut(id=new_id)


@app.put("/medications/{medication_id}", response_model=MedicationOut)
def edit_medication(medication_id: int, body: MedicationIn, conn=Depends(get_conn)) -> MedicationOut:
    """Full-replace edit of a medication (same fields as POST). Editing end_date
    drives the derived `active` badge — no separate status flag. Unknown id → 404."""
    found = update_medication(conn, medication_id, name=body.name, dose=body.dose,
                              frequency=body.frequency, start_date=body.start_date,
                              end_date=body.end_date, notes=body.notes)
    if not found:
        raise HTTPException(status_code=404, detail=f"No medication with id {medication_id}.")
    row = next(m for m in list_medications(conn) if m["id"] == medication_id)
    return MedicationOut(**row)


@app.delete("/medications/{medication_id}", status_code=204)
def remove_medication(medication_id: int, conn=Depends(get_conn)) -> None:
    """Delete a medication by id. Unknown id returns 404."""
    if not delete_medication(conn, medication_id):
        raise HTTPException(status_code=404, detail=f"No medication with id {medication_id}.")


@app.get("/events", response_model=list[EventOut])
def get_events(conn=Depends(get_conn)) -> list[EventOut]:
    """List all events (point-in-time Timeline records). No analysis."""
    return [EventOut(**row) for row in list_events(conn)]


@app.post("/events", response_model=CreatedOut, status_code=201)
def create_event(body: EventIn, conn=Depends(get_conn)) -> CreatedOut:
    """Add an event. event_type is validated against the fixed set on EventIn."""
    new_id = add_event(conn, body.event_date, body.event_type, body.title, notes=body.notes)
    return CreatedOut(id=new_id)


@app.put("/events/{event_id}", response_model=EventOut)
def edit_event(event_id: int, body: EventIn, conn=Depends(get_conn)) -> EventOut:
    """Full-replace edit of an event (same fields as POST). Unknown id → 404."""
    found = update_event(conn, event_id, event_date=body.event_date,
                         event_type=body.event_type, title=body.title, notes=body.notes)
    if not found:
        raise HTTPException(status_code=404, detail=f"No event with id {event_id}.")
    row = next(e for e in list_events(conn) if e["id"] == event_id)
    return EventOut(**row)


@app.delete("/events/{event_id}", status_code=204)
def remove_event(event_id: int, conn=Depends(get_conn)) -> None:
    """Delete an event by id. Unknown id returns 404."""
    if not delete_event(conn, event_id):
        raise HTTPException(status_code=404, detail=f"No event with id {event_id}.")


# --------------------------------------------------------------------- timed collections

@app.get("/collections", response_model=list[CollectionOut])
def get_collections(conn=Depends(get_conn)) -> list[CollectionOut]:
    """List timed collections (24h urine, etc.), newest-completed first, each with its
    `n_readings` count. No analysis — a collection is provenance/context only."""
    return [CollectionOut(**row) for row in list_collections(conn)]


@app.post("/collections", response_model=CollectionOut, status_code=201)
def create_collection(body: CollectionIn, conn=Depends(get_conn)) -> CollectionOut:
    """Create a timed collection (create-first flow: make the collection, then add its
    analytes referencing it). Returns the new record incl. n_readings (0 at creation)."""
    new_id = add_collection(
        conn, completed_on=body.completed_on, kind=body.kind, started_on=body.started_on,
        duration_hours=body.duration_hours, volume_ml=body.volume_ml, notes=body.notes,
    )
    return CollectionOut(**get_collection(conn, new_id), n_readings=0)


@app.put("/collections/{collection_id}", response_model=CollectionOut)
def edit_collection(collection_id: int, body: CollectionIn,
                    conn=Depends(get_conn)) -> CollectionOut:
    """Full-replace edit of a collection's context fields (same shape as POST). Its
    analytes are untouched — this only changes the shared collection metadata. 404 if
    unknown."""
    found = update_collection(
        conn, collection_id, completed_on=body.completed_on, kind=body.kind,
        started_on=body.started_on, duration_hours=body.duration_hours,
        volume_ml=body.volume_ml, notes=body.notes,
    )
    if not found:
        raise HTTPException(status_code=404, detail=f"No collection with id {collection_id}.")
    return CollectionOut(**next(c for c in list_collections(conn) if c["id"] == collection_id))


@app.get("/collections/{collection_id}/readings", response_model=list[CollectionReadingOut])
def read_collection_readings(collection_id: int,
                             conn=Depends(get_conn)) -> list[CollectionReadingOut]:
    """The analytes belonging to one collection, alphabetical by display label. Unknown id
    → 404 (distinct from a real collection that simply has no analytes yet, which is [])."""
    if get_collection(conn, collection_id) is None:
        raise HTTPException(status_code=404, detail=f"No collection with id {collection_id}.")
    return [CollectionReadingOut(**row) for row in list_collection_readings(conn, collection_id)]


@app.delete("/collections/{collection_id}", status_code=204)
def remove_collection(collection_id: int, conn=Depends(get_conn)) -> None:
    """Delete a collection. Refuses (409) while it still has readings — remove/reassign
    them first (the 'refuse delete of a non-empty collection' decision). Unknown id → 404."""
    try:
        deleted = delete_collection(conn, collection_id)
    except CollectionInUseError as e:
        raise HTTPException(status_code=409, detail=str(e))
    if not deleted:
        raise HTTPException(status_code=404, detail=f"No collection with id {collection_id}.")


# ----------------------------------------------------------------------------- profile

def _profile_out(conn) -> ProfileOut:
    """Assemble the singleton + current weight + current height. Used by GET and
    PUT so both return the same shape. Missing pieces are null (the empty state)."""
    prof = get_profile(conn) or {}
    def latest(field):
        row = get_latest_profile_measurement(conn, field)
        return MeasurementOut(**row) if row else None
    return ProfileOut(sex=prof.get("sex"), date_of_birth=prof.get("date_of_birth"),
                      weight=latest("weight"), height=latest("height"))


@app.get("/profile", response_model=ProfileOut)
def read_profile(conn=Depends(get_conn)) -> ProfileOut:
    """The profile: sex, DOB, and the CURRENT weight/height. All null when nothing
    has been entered yet (a fresh install) — the UI renders that empty state."""
    return _profile_out(conn)


@app.put("/profile", response_model=ProfileOut)
def edit_profile(body: ProfileIn, conn=Depends(get_conn)) -> ProfileOut:
    """Update the singleton's sex / DOB (UPSERT on id=1). Returns the refreshed
    profile (including current weight/height, unchanged here)."""
    update_profile(conn, body.sex, body.date_of_birth)
    return _profile_out(conn)


@app.post("/profile/measurements", response_model=CreatedOut, status_code=201)
def create_profile_measurement(body: MeasurementIn, conn=Depends(get_conn)) -> CreatedOut:
    """Append a weight/height measurement (append-only; the latest is the current
    value). Returns the new row id."""
    new_id = add_profile_measurement(conn, body.field, body.value, body.unit, body.recorded_on)
    return CreatedOut(id=new_id)


@app.get("/profile/history/{field}", response_model=list[MeasurementOut])
def read_profile_history(field: str, conn=Depends(get_conn)) -> list[MeasurementOut]:
    """All measurements for a field, newest first. Unknown field → 404."""
    if field not in _MEASUREMENT_FIELDS:
        raise HTTPException(status_code=404, detail=f"Unknown profile field '{field}'.")
    return [MeasurementOut(**row) for row in list_profile_history(conn, field)]


@app.put("/profile/measurements/{measurement_id}", response_model=MeasurementOut)
def edit_profile_measurement(measurement_id: int, body: MeasurementUpdateIn,
                             conn=Depends(get_conn)) -> MeasurementOut:
    """Correct a measurement in place (value/unit/date). Unknown id → 404. `field` can't
    change — see MeasurementUpdateIn."""
    if not update_profile_measurement(conn, measurement_id, body.value, body.unit,
                                      body.recorded_on):
        raise HTTPException(status_code=404, detail=f"No measurement with id {measurement_id}.")
    row = get_profile_measurement(conn, measurement_id)
    return MeasurementOut(**row)


@app.delete("/profile/measurements/{measurement_id}", status_code=204)
def remove_profile_measurement(measurement_id: int, conn=Depends(get_conn)) -> None:
    """Delete a measurement by id. Unknown id returns 404."""
    if not delete_profile_measurement(conn, measurement_id):
        raise HTTPException(status_code=404, detail=f"No measurement with id {measurement_id}.")


@app.get("/timeline", response_model=list[TimelineEntryOut])
def get_timeline(conn=Depends(get_conn)) -> list[TimelineEntryOut]:
    """The merged, newest-first Timeline across all sources (conditions, medications,
    events, lab observations). Read-only aggregation in timeline.build_timeline; the
    lab 'notable' count reuses the engine (mode-resolved per metric, so a chronic
    pb-mode exceedance doesn't inflate it). No SQL/math here. The client filters by
    kind and flips to oldest-first in memory."""
    entries = timeline_builder.build_timeline(
        conn, metric_config_registry.all_configs(conn),
        derived_series=resolve_derived_series(conn))
    return [TimelineEntryOut(**asdict(e)) for e in entries]


@app.get("/settings", response_model=list[SettingOut])
def get_settings(conn=Depends(get_conn)) -> list[SettingOut]:
    """The adjustable settings with their effective values and everything the
    panel needs to render them (label, description, type, bounds). Values are
    resolved from the settings table with the code constant as fallback. (No enum
    option needs a live availability probe now — the local-Ollama summarizer
    option, the only one that did, was removed; every remaining option is always
    usable, so the UI's `available === false` handling is simply never triggered.)"""
    return [SettingOut(**v) for v in settings_registry.views(conn)]


@app.put("/settings", response_model=list[SettingOut])
def put_settings(body: SettingsUpdateIn, conn=Depends(get_conn)) -> list[SettingOut]:
    """Persist a batch of setting edits and return the refreshed list. Validation
    (known key + correct type) happens in the registry; a bad field is rejected
    before anything is written, so the save can't half-apply. These settings are
    display-volume and suggestion-trigger thresholds only — no detection logic or
    stored health data is touched."""
    try:
        updated = settings_registry.apply_updates(conn, body.values)
    except settings_registry.SettingError as e:
        raise HTTPException(status_code=400, detail=str(e))
    return [SettingOut(**v) for v in updated]


def _metric_settings_out(conn, metric: str) -> MetricSettingsOut:
    """Assemble a metric's stored personal-baseline state plus its LIVE candidacy
    (computed with the current suggestion thresholds, resolved from settings)."""
    ms = get_metric_settings(conn, metric)
    cand = personal_baseline_candidacy(
        get_series(conn, metric),
        min_fraction=settings_registry.resolve(conn, "personal_baseline_suggest_min_fraction"),
        min_readings=settings_registry.resolve(conn, "personal_baseline_suggest_min_readings"),
    )
    return MetricSettingsOut(metric=metric, candidacy=CandidacyOut(**cand), **ms)


@app.get("/metric-settings/{metric:path}", response_model=MetricSettingsOut)
def get_metric_settings_route(metric: str, conn=Depends(get_conn)) -> MetricSettingsOut:
    """A metric's personal-baseline state + live candidacy. The frontend uses this
    to decide whether to show the suggestion banner (candidate AND mode off AND
    not dismissed) or the active-mode indicator. Candidacy is purely statistical."""
    return _metric_settings_out(conn, metric)


@app.put("/metric-settings/{metric:path}", response_model=MetricSettingsOut)
def put_metric_settings_route(metric: str, body: MetricSettingsIn,
                              conn=Depends(get_conn)) -> MetricSettingsOut:
    """Update a metric's personal-baseline settings (partial: only provided fields
    change). Turning the mode OFF also dismisses the suggestion, so a deliberate
    toggle-off isn't immediately re-suggested — unless the caller explicitly sets
    suggestion_dismissed in the same request. Recontextualization is display-only;
    no stored health data (observations) is touched."""
    current = get_metric_settings(conn, metric)
    mode = current["personal_baseline_mode"] if body.personal_baseline_mode is None \
        else body.personal_baseline_mode
    note = current["note"] if body.note is None else body.note
    dismissed = current["suggestion_dismissed"] if body.suggestion_dismissed is None \
        else body.suggestion_dismissed
    # A manual switch to mode OFF also marks the suggestion dismissed (don't
    # re-nag a deliberate choice), unless the request set dismissed itself.
    if body.personal_baseline_mode is False and body.suggestion_dismissed is None:
        dismissed = True
    set_metric_settings(conn, metric, personal_baseline_mode=mode, note=note,
                        suggestion_dismissed=dismissed,
                        seed_keys=metric_config_registry.SEED.keys())
    return _metric_settings_out(conn, metric)


@app.get("/baseline-explainer", response_model=BaselineExplainerOut)
def get_baseline_explainer(conn=Depends(get_conn)) -> BaselineExplainerOut:
    """Has the user dismissed the one-time global personal-baseline explainer?
    Global state, not per-metric — a fresh install (nothing persisted) reads
    seen: False."""
    return BaselineExplainerOut(seen=get_setting(conn, BASELINE_EXPLAINER_SEEN_KEY) == "1")


@app.post("/baseline-explainer/dismiss", response_model=BaselineExplainerOut)
def dismiss_baseline_explainer(conn=Depends(get_conn)) -> BaselineExplainerOut:
    """Marks the explainer seen. Idempotent — dismissing an already-seen flag is
    a harmless repeat write, still returns seen: True."""
    set_setting(conn, BASELINE_EXPLAINER_SEEN_KEY, "1")
    return BaselineExplainerOut(seen=True)


@app.get("/export/enabled", response_model=ExportEnabledOut)
def get_export_enabled(conn=Depends(get_conn)) -> ExportEnabledOut:
    """Is the export handoff's capability gate on? Global, not per-metric — a
    fresh install (nothing persisted) reads enabled: False."""
    return ExportEnabledOut(enabled=get_setting(conn, EXPORT_HOSTED_ENABLED_KEY) == "1")


@app.put("/export/enabled", response_model=ExportEnabledOut)
def put_export_enabled(body: ExportEnabledIn, conn=Depends(get_conn)) -> ExportEnabledOut:
    """Turns the export handoff's capability gate on or off. A real toggle, not
    a one-way dismiss — CLAUDE.md's consent-mechanics principle requires
    revoking to be exactly as easy as granting."""
    set_setting(conn, EXPORT_HOSTED_ENABLED_KEY, "1" if body.enabled else "0")
    return ExportEnabledOut(enabled=body.enabled)


def _require_export_enabled(conn) -> None:
    """The capability gate (CLAUDE.md 'The export handoff' — Consent mechanics):
    a preview can't even be ASSEMBLED while this is off. Checked before any
    bundle assembly, so a disabled export never touches health data at all."""
    if get_setting(conn, EXPORT_HOSTED_ENABLED_KEY) != "1":
        raise HTTPException(status_code=403,
                            detail="External export is disabled. Enable it in Settings first.")


def _today() -> str:
    """Today, ISO — the anchor the export instruction needs to judge recency (see
    explain.system_instruction). Ambient context, not user data. It rides the
    INSTRUCTION rather than the payload, so it never perturbs the confirmation token:
    a preview held across midnight still confirms cleanly."""
    return date.today().isoformat()


class ExportPreviewOut(BaseModel):
    """The gateway's hosted preview, verbatim — the faithful, COMPLETE payload
    a confirm screen must render before consent (CLAUDE.md 'The export
    handoff' — Consent mechanics). `payload` is the full nested bundle,
    allowlisted + scrubbed, never summarized and never hashed. Nothing has
    been sent yet. `instruction` is the system prompt that will accompany the
    payload — PII-free and not part of the confirmation token (which binds the
    DATA), but surfaced because it shapes the entire response: reviewing the
    data alone leaves the user unable to see why an answer looks as it does."""
    task: str
    provider: str
    payload: list[dict]
    excluded_fields: list[str]
    redactions: list[dict]
    provider_settings: dict
    confirmation_token: str
    instruction: str = ""


class ExportConfirmIn(BaseModel):
    confirmation_token: str


class ExportResultOut(BaseModel):
    """The external model's response. `output` is the model's RAW text —
    NEVER includes the disclaimer (kept separate on purpose, see below).
    `engine`/`model` label which engine actually produced it, per the
    charter's always-label-the-engine rule. `disclaimer` is the SAME fixed
    frame the local interpretation tier appends (explain.FRAME) — returned as
    its OWN field, not concatenated into `output`, so the render can guarantee
    it appears every time as a structurally distinct element instead of
    trusting a pre-merged string a future refactor could quietly drop.
    `saved` reports whether the local archive write succeeded — see
    `_save_export_result`; False means the response is in THIS response only."""
    output: str
    disclaimer: str
    engine: str
    model: str | None = None
    saved: bool = True


def _save_export_result(conn, *, scope: str, metrics: list[str], output: str,
                        provider: str | None, model: str | None,
                        audit_id: str | None = None) -> bool:
    """Archive one confirmed export's response locally — NEVER at the cost of the
    response itself.

    Ordering is what makes this necessary: by the time this runs the send has already
    happened. The bytes left the machine, the user consented to that, and the provider
    billed for it. If the local archive write then fails, letting the exception escape
    would turn a recoverable bookkeeping failure into an unrecoverable one — FastAPI
    would return a 500 and DISCARD the very text the user paid to obtain, with no way
    to get it back short of consenting to send their health data again.

    So every DB error is caught and reported as `saved=False` rather than raised. The
    UI surfaces that so the user can copy the text before navigating away. The archive
    is a convenience; the response is the thing of value."""
    try:
        add_export_result(conn, scope=scope, metrics=metrics, output=output,
                          provider=provider, model=model, audit_id=audit_id)
        return True
    except Exception as e:  # deliberate catch-all — see docstring; never re-raised
        # Local-only diagnostic. The response text is NOT logged: it's the model's
        # reasoning over the user's health data, and it's already returned to the
        # caller and (when the write works) stored in the local DB.
        print(f"[export] local archive write failed, response returned unsaved: {e!r}",
              file=sys.stderr)
        return False


@app.post("/export/{metric:path}/preview", response_model=ExportPreviewOut)
def export_preview(metric: str, conn=Depends(get_conn)) -> ExportPreviewOut:
    """Step 1 of the export handoff: assemble the metric's bundle FRESH from
    the current DB state and preview what would be sent — nothing sends here.
    Refuses (403) if the capability gate is off, before any bundle is built."""
    _require_export_enabled(conn)
    bundle = _assemble_export_bundle(conn, metric)
    provider = settings_registry.resolve(conn, "export_provider")
    result = complete(LLMRequest(task="explain_metric", engine="hosted",
                                 fields=[bundle], instruction=explain.system_instruction(_today()),
                                 provider=provider))
    p = result.preview
    return ExportPreviewOut(task=p.task, provider=p.provider, payload=p.payload,
                            excluded_fields=p.excluded_fields, redactions=p.redactions,
                            provider_settings=p.provider_settings,
                            confirmation_token=p.confirmation_token,
                            instruction=p.instruction)


@app.post("/export/{metric:path}/confirm", response_model=ExportResultOut)
def export_confirm(metric: str, body: ExportConfirmIn,
                   conn=Depends(get_conn)) -> ExportResultOut:
    """Step 2: re-assemble the bundle FRESH (stateless — no server-side payload
    cache; the route, not a cache, rebuilds `fields` from `metric` on both
    calls) and confirm. The gateway byte-compares the freshly-rebuilt
    payload's token against `confirmation_token`; if the data changed since
    preview (e.g. a new reading was added), the tokens won't match and the
    gateway self-refuses — surfaced here as 409 ("refused" — re-preview will
    fix it), distinct from a "provider_error" (502 — the send was attempted
    and the provider itself failed; re-previewing won't help). Same system
    instruction as the local interpretation tier (CLAUDE.md "The export
    handoff" — Rule F: the same hard rules, not looser ones, for a stronger
    model), and the same code-appended, non-model-generated disclaimer frame."""
    _require_export_enabled(conn)
    bundle = _assemble_export_bundle(conn, metric)
    provider = settings_registry.resolve(conn, "export_provider")
    result = complete(LLMRequest(task="explain_metric", engine="hosted",
                                 fields=[bundle], instruction=explain.system_instruction(_today()),
                                 provider=provider),
                      confirmation=body.confirmation_token)
    if result.status == "refused":
        raise HTTPException(
            status_code=409,
            detail=result.reason or
                   "The data has changed since you previewed this — please preview again.")
    if result.status == "provider_error":
        raise HTTPException(status_code=502, detail=result.reason or
                            "The external provider call failed.")
    output = result.output.strip()
    saved = _save_export_result(conn, scope=metric, metrics=[metric], output=output,
                                provider=provider, model=result.model,
                                audit_id=result.audit_id)
    return ExportResultOut(output=output, disclaimer=explain.FRAME,
                           engine=result.engine, model=result.model, saved=saved)


# --------------------------------------------------------------- multi-metric export
# CLAUDE.md "Hypothesis floating & multi-metric scope": export a SET of metrics (a panel,
# a user-selected set, or the full picture) as one bundle {metrics:[...], scope}, so the
# external model can float hedged possibilities across them. Same gated / previewed /
# confirmed chain as the single-metric export — just a list of the same per-metric bundles.

def _approved_reports(reports_in: list["ReportTextIn"]) -> list[dict]:
    """Pair each user-approved report TEXT with its study's date/description.

    The client sends {id, text}: the id is the opaque handle it already holds, the text
    is what the user left in the editor after redacting. The id is resolved HERE and
    dropped — it is derived from the accession number, which the charter names as an
    identifier, and it tells a model nothing. The TEXT is taken exactly as submitted and
    never re-read from disk: re-reading would silently undo the user's edits, which are
    the whole control this path rests on. An unknown id contributes no metadata rather
    than raising — the text is still the user's to send."""
    if not reports_in:
        return []
    meta = {}
    if reports_store.available():
        meta = {r["id"]: r for r in reports_store.list_reports()}
    out = []
    for r in reports_in:
        m = meta.get(r.id, {})
        out.append({"study_date": m.get("study_date"),
                    "study_description": m.get("study_description"),
                    "text": r.text})
    return out


# The free-text fields a full-picture export can carry from the DB — user-authored prose
# where an identifier can sit anywhere, exactly like a radiology report, just shorter. They
# get the SAME in-preview editing the report text gets: a `notes` reading "benign, per Dr.
# Rossi" is the same class of problem as a report naming its radiologist, and having the
# report editable while the note was only editable by leaving the flow and going to edit the
# record was an inconsistency, not a decision. `title` is included because an event titled
# after the person who was there is the obvious failure mode; the row's other columns (a
# condition name, a drug name, a dose) are vocabulary, not prose, and stay non-editable.
_EDITABLE_TEXT: dict[str, tuple[str, ...]] = {
    "condition": ("notes",),
    "medication": ("notes",),
    "event": ("title", "notes"),
}


def _apply_text_overrides(rows: list[dict], kind: str,
                          overrides: dict[tuple[str, int, str], str]) -> list[dict]:
    """Replace the editable free-text fields of `rows` with what the user approved.

    Applied HERE rather than inside picture.py so that module stays a dumb shaper: it
    receives rows and emits a payload, and never has to know an override mechanism exists.
    Rows are copied, never mutated — these dicts came from db and must not be edited in
    place. A field with no override keeps its stored value; an override to an empty string
    is honoured as written (blanking a note IS a redaction), which is why this checks key
    presence rather than truthiness."""
    if not overrides:
        return rows
    out = []
    for row in rows:
        row = dict(row)
        for field in _EDITABLE_TEXT.get(kind, ()):
            key = (kind, row.get("id"), field)
            if key in overrides:
                row[field] = overrides[key]
        out.append(row)
    return out


def _assemble_export_context(conn, reports_in: list["ReportTextIn"],
                             texts_in: list["RowTextIn"] | None = None) -> dict:
    """Gather the non-metric substrate and hand it to picture.py (which does the shaping;
    this only fetches). Imaging is read from the local DICOM store's ALREADY-allowlisted
    scan, so no PII tag is read here either. User edits to the DB rows' free text are
    applied on the way through — see _apply_text_overrides."""
    studies = dicom_store.public_studies() if dicom_store.available() else []
    ov = {(t.kind, t.id, t.field): t.text for t in (texts_in or [])
          if t.field in _EDITABLE_TEXT.get(t.kind, ())}
    return picture.assemble_context(
        profile_row=get_profile(conn),
        weight_rows=list_profile_history(conn, "weight"),
        height_rows=list_profile_history(conn, "height"),
        conditions=_apply_text_overrides(list_conditions(conn), "condition", ov),
        medications=_apply_text_overrides(list_medications(conn), "medication", ov),
        events=_apply_text_overrides(list_events(conn), "event", ov),
        imaging_studies=studies,
        approved_reports=_approved_reports(reports_in),
        as_of=_today(),
    )


def _assemble_export_multi(conn, metrics: list[str], scope_label: str, *,
                           include_context: bool = False,
                           reports_in: list["ReportTextIn"] | None = None,
                           texts_in: list["RowTextIn"] | None = None) -> dict:
    """The multi-metric bundle: each metric's own (single-metric) export bundle, wrapped
    in a list, plus a scope label. Rebuilt fresh on every call (stateless — the token
    byte-compare catches any change between preview and confirm). Derived metrics are
    export-able too (their bundles assemble the same way).

    With `include_context` the FULL-PICTURE half is merged in as sibling top-level keys
    (profile / conditions / medications / events / imaging / reports — each named in the
    gateway allowlist). It stays OFF by default so a single panel or ad-hoc selection
    sends exactly what it sent before: a lab panel doesn't need the medication list, and
    the charter's data-minimization rule says don't send what the task doesn't need."""
    bundle = {
        "metrics": [_assemble_export_bundle(conn, m) for m in metrics],
        "scope": scope_label,
    }
    if include_context:
        bundle.update(_assemble_export_context(conn, reports_in or [], texts_in or []))
    return bundle


class ReportTextIn(BaseModel):
    """One radiology report the user chose to include, with the text they approved.

    The text is EDITABLE on the client by design (CLAUDE.md "The export handoff"): a
    report is prose with no fields, so neither the allowlist nor the regex scrub can
    guarantee it holds no clinician name — human review at the chokepoint is the control,
    and editing is what makes that review able to act. Whatever arrives here is what gets
    previewed, tokenized, and sent; an empty string drops the report entirely."""
    id: str
    text: str = Field(default="", max_length=100_000)


class RowTextIn(BaseModel):
    """One edited free-text field on a DB row (a condition/medication/event note, or an
    event title). Same rationale as ReportTextIn, applied to the shorter prose the user
    wrote themselves: an identifier can hide in a note as easily as in a report, so it is
    redactable at the same moment, in the same place, rather than only by leaving the
    export flow to go edit the record. An unknown kind/field is ignored, not an error —
    the allowlist is `_EDITABLE_TEXT`, checked at apply time."""
    kind: str
    id: int
    field: str
    text: str = Field(default="", max_length=20_000)


class MultiExportIn(BaseModel):
    """Which metrics to export together. `scope_label` is a human label for the set
    (e.g. 'Full health picture', 'Copper panel') shown in the preview/audit; empty is
    fine. The list is de-duped + capped so a pathological request can't assemble an
    unbounded payload (the full picture is legitimately large but finite).

    `include_context` adds the non-metric half (profile / conditions / medications /
    events / imaging / reports); `reports` carries the user-approved report text, and
    `texts` the user-approved edits to the DB rows' own free-text fields."""
    metrics: list[str] = Field(default_factory=list, max_length=500)
    scope_label: str = ""
    include_context: bool = False
    reports: list[ReportTextIn] = Field(default_factory=list, max_length=200)
    texts: list[RowTextIn] = Field(default_factory=list, max_length=2000)

    @model_validator(mode="after")
    def _clean(self):
        # De-dupe preserving order; drop blanks.
        seen, out = set(), []
        for m in self.metrics:
            m = (m or "").strip()
            if m and m not in seen:
                seen.add(m)
                out.append(m)
        self.metrics = out
        self.scope_label = (self.scope_label or "").strip()
        if not self.metrics:
            raise ValueError("At least one metric is required.")
        # Edited text can only ride along with the context half — otherwise a caller
        # could slip prose into an ordinary panel export that never previews it.
        if not self.include_context:
            self.reports = []
            self.texts = []
        return self


class MultiExportConfirmIn(MultiExportIn):
    """Confirm a previewed multi-metric send: the SAME metric set + scope (so the route
    rebuilds the identical bundle) plus the preview's confirmation token."""
    confirmation_token: str


class PanelOut(BaseModel):
    """The 'panel' of a collection-linked metric: every metric sharing a timed collection
    with it (including itself). Empty/singleton when the metric isn't collection-linked."""
    metric: str
    panel: list[str] = []


@app.get("/metrics/{metric:path}/panel", response_model=PanelOut)
def get_metric_panel(metric: str, conn=Depends(get_conn)) -> PanelOut:
    """The metrics that share a timed collection with `metric` — the set 'export this
    panel' would send. Read-only."""
    return PanelOut(metric=metric, panel=metrics_in_collections_of(conn, metric))


class ExportReportDraftOut(BaseModel):
    """One radiology report offered for inclusion in a full-picture export, with its
    extracted text as the STARTING POINT for the user's edit. `id` is the same opaque
    handle /reports uses; it is a client-side handle only and never enters a payload."""
    id: str
    study_date: str | None = None
    study_description: str | None = None
    text: str = ""


class ExportTextDraftOut(BaseModel):
    """One editable free-text field on a DB row. `label` says WHICH row it belongs to (the
    condition/medication name, an event's date) so the editor is intelligible without
    re-fetching those lists; it is display-only and is not sent back."""
    kind: str
    id: int
    field: str
    label: str
    text: str = ""


class ExportDraftsOut(BaseModel):
    """Everything in a full-picture export the user can edit before it is sent.

    ONE route for both kinds of prose on purpose. They are the same risk — free text where
    an identifier can hide — and splitting them into two endpoints would invite the two
    editors to drift into two mechanisms, which is precisely the inconsistency this
    replaced. `reports_available` is about the imaging archive only; the note drafts come
    from the DB and are always available."""
    reports_available: bool
    reports: list[ExportReportDraftOut] = []
    texts: list[ExportTextDraftOut] = []


def _text_drafts(conn) -> list[ExportTextDraftOut]:
    """The editable free-text fields across conditions/medications/events, skipping rows
    whose field is empty — there is nothing to redact in a blank note, and listing 17 empty
    boxes would bury the two that matter."""
    out: list[ExportTextDraftOut] = []
    sources = (
        ("condition", list_conditions(conn), lambda r: r.get("name") or "Condition"),
        ("medication", list_medications(conn), lambda r: r.get("name") or "Medication"),
        ("event", list_events(conn),
         lambda r: f"{r.get('event_date') or ''} {r.get('event_type') or 'event'}".strip()),
    )
    for kind, rows, label_of in sources:
        for row in rows:
            for field in _EDITABLE_TEXT[kind]:
                text = row.get(field) or ""
                if text.strip():
                    out.append(ExportTextDraftOut(kind=kind, id=row["id"], field=field,
                                                  label=label_of(row), text=text))
    return out


@app.get("/export/drafts", response_model=ExportDraftsOut)
def get_export_drafts(conn=Depends(get_conn)) -> ExportDraftsOut:
    """The prose a full-picture export can carry, as EDITABLE drafts — radiology report
    text plus the free-text fields on conditions/medications/events.

    This reads clinical prose, which /reports/{id} and /conditions already do — nothing new
    leaves the machine here and nothing is sent by calling it. It exists because the preview
    can only show what has already been approved, so the editing step needs its own source.
    Gated by the export capability toggle: with hosted export off there is nothing to
    prepare a draft for."""
    _require_export_enabled(conn)
    drafts = []
    if reports_store.available():
        for meta in reports_store.list_reports():
            full = reports_store.get_report(meta["id"]) or {}
            drafts.append(ExportReportDraftOut(
                id=meta["id"], study_date=meta.get("study_date"),
                study_description=meta.get("study_description"),
                text=full.get("text") or ""))
    return ExportDraftsOut(reports_available=reports_store.available(),
                           reports=drafts, texts=_text_drafts(conn))


@app.post("/export-multi/preview", response_model=ExportPreviewOut)
def export_multi_preview(body: MultiExportIn, conn=Depends(get_conn)) -> ExportPreviewOut:
    """Step 1 of a MULTI-metric export: assemble the set's bundle fresh and preview what
    would be sent — nothing sends here. Gated (403 if the capability is off)."""
    _require_export_enabled(conn)
    # A bad/derived-only/unknown metric name would assemble an empty per-metric bundle;
    # reject an unknown one up front for a clear error.
    known = set(list_observed_metrics(conn)) | {d.name for d in derived_registry.REGISTRY.values()}
    missing = [m for m in body.metrics if m not in known]
    if missing:
        raise HTTPException(status_code=404, detail=f"Unknown metric(s): {', '.join(missing)}.")
    bundle = _assemble_export_multi(conn, body.metrics, body.scope_label,
                                    include_context=body.include_context,
                                    reports_in=body.reports, texts_in=body.texts)
    provider = settings_registry.resolve(conn, "export_provider")
    result = complete(LLMRequest(task="export_metrics", engine="hosted", fields=[bundle],
                                 instruction=explain.system_instruction(_today()), provider=provider))
    p = result.preview
    return ExportPreviewOut(task=p.task, provider=p.provider, payload=p.payload,
                            excluded_fields=p.excluded_fields, redactions=p.redactions,
                            provider_settings=p.provider_settings,
                            confirmation_token=p.confirmation_token,
                            instruction=p.instruction)


@app.post("/export-multi/confirm", response_model=ExportResultOut)
def export_multi_confirm(body: MultiExportConfirmIn,
                         conn=Depends(get_conn)) -> ExportResultOut:
    """Step 2: re-assemble the set fresh (stateless) and confirm. Same token byte-compare
    as the single-metric confirm — a change since preview → 409; a provider failure → 502."""
    _require_export_enabled(conn)
    bundle = _assemble_export_multi(conn, body.metrics, body.scope_label,
                                    include_context=body.include_context,
                                    reports_in=body.reports, texts_in=body.texts)
    provider = settings_registry.resolve(conn, "export_provider")
    result = complete(LLMRequest(task="export_metrics", engine="hosted", fields=[bundle],
                                 instruction=explain.system_instruction(_today()), provider=provider),
                      confirmation=body.confirmation_token)
    if result.status == "refused":
        raise HTTPException(status_code=409, detail=result.reason or
                            "The data has changed since you previewed this — preview again.")
    if result.status == "provider_error":
        raise HTTPException(status_code=502, detail=result.reason or
                            "The external provider call failed.")
    output = result.output.strip()
    saved = _save_export_result(conn, scope=body.scope_label or "Selected metrics",
                                metrics=body.metrics, output=output, provider=provider,
                                model=result.model, audit_id=result.audit_id)
    return ExportResultOut(output=output, disclaimer=explain.FRAME,
                           engine=result.engine, model=result.model, saved=saved)


class ExportResultRecordOut(BaseModel):
    """One saved export result — the model's response to a confirmed send, kept locally so
    the Settings 'External export' tab can show it attached to its send. `audit_id` is
    that join — the gateway audit entry this answers. Null on rows saved before the id
    existed, which therefore show unattached."""
    id: int
    created_at: str
    scope: str
    metrics: list[str] = []
    provider: str | None = None
    model: str | None = None
    output: str
    audit_id: str | None = None


class ExportResultsOut(BaseModel):
    results: list[ExportResultRecordOut] = []


@app.get("/export/results", response_model=ExportResultsOut)
def get_export_results(conn=Depends(get_conn)) -> ExportResultsOut:
    """Saved external-export RESULTS (the model responses), newest first — shown in the
    Settings 'External export' tab beside the send audit. Not gated by the export toggle:
    what already came back stays reviewable after the capability is turned off (same
    reasoning as /export/audit)."""
    return ExportResultsOut(results=[ExportResultRecordOut(**r) for r in list_export_results(conn)])


class ExportAuditEntryOut(BaseModel):
    """One external audit-log entry, verbatim — the durable local record of
    exactly what left (or tried to leave) the machine. `payload` is the full
    sent bundle, never summarized; `error` present means the send was
    ATTEMPTED but no response was served (audited honestly by the gateway).
    `provider_settings` are the settings enforced at send time. `id` keys this entry
    so a saved response can point back at it; absent on pre-id entries."""
    ts: str
    id: str | None = None
    task: str
    engine: str
    provider: str | None = None
    model: str | None = None
    payload: list[dict] = []
    provider_settings: dict = {}
    redactions: list[dict] = []
    error: str | None = None


class ExportAuditOut(BaseModel):
    entries: list[ExportAuditEntryOut]


@app.get("/export/audit", response_model=ExportAuditOut)
def get_export_audit() -> ExportAuditOut:
    """Recent external sends, newest first — the read-only, after-the-fact
    half of the charter's transparency rule (the before-send half is the
    preview). Reads the local gateway audit log only: no DB, no egress, no
    model. Deliberately NOT gated by export_hosted_enabled — the record of
    what already left the machine must stay reviewable after the capability
    is turned back off (revocability doesn't erase history)."""
    # Extra log keys (e.g. `destination`) are ignored by Pydantic's default
    # extra='ignore'; absent keys fall back to the model's defaults.
    return ExportAuditOut(entries=[ExportAuditEntryOut(**e)
                                   for e in read_external_audit()])


# ------------------------------------------------------------------- imaging (DICOM viewer)
# CLAUDE.md privacy prime directive: DICOM headers carry PatientName/DOB/MRN/physician/
# facility PII, and images can't be reliably de-identified (PII can be burned into pixels),
# so this feature is 100% LOCAL — it reads a local imaging folder, surfaces ONLY allowlisted
# metadata (dicom_store._SAFE_* tags), renders pixels to PNG on the server, and NEVER touches
# the gateway or the network. There is no external path here by construction.

class ImagingSeriesOut(BaseModel):
    """One series' allowlisted metadata + opaque id + slice count. No PII, no file paths.
    `pixel_spacing` = [row_mm, col_mm] physical calibration for distance measurement;
    null when the modality doesn't provide it (measurements then read in px, uncalibrated)."""
    id: str
    n_slices: int
    Modality: str | None = None
    SeriesDescription: str | None = None
    BodyPartExamined: str | None = None
    SeriesNumber: int | None = None
    Rows: int | None = None
    Columns: int | None = None
    pixel_spacing: list[float] | None = None
    default_window: dict | None = None   # {wc, ww} the file's own display calibration
    # What this series' values ARE ("HU" for CT, else RescaleType, else "raw"). The client
    # offers the HU window presets only when this is "HU" — they're meaningless otherwise.
    value_units: str | None = None


class ImagingStudyOut(BaseModel):
    id: str
    StudyDate: str | None = None
    StudyDescription: str | None = None
    series: list[ImagingSeriesOut] = []
    # Opaque ids of the radiology reports that belong to this study, so the viewer can offer
    # "read the report" beside the images it interprets. Empty when the disc carried none.
    report_ids: list[str] = []


class ImagingIndexOut(BaseModel):
    """Whether the viewer is usable, the window/level presets, and the studies found. A
    single call the page can bootstrap from."""
    available: bool
    reason: str | None = None
    presets: dict = {}
    # The units the presets are expressed in, so the client can decide per series whether
    # they apply rather than hardcoding "CT" on the frontend.
    presets_units: str = ""
    studies: list[ImagingStudyOut] = []


@app.get("/imaging/studies", response_model=ImagingIndexOut)
def get_imaging_studies() -> ImagingIndexOut:
    """List locally-stored DICOM studies (allowlisted metadata only). If pydicom/Pillow
    aren't installed, reports available=false with a reason rather than erroring — the
    same honest-degradation pattern as PDF OCR extras."""
    if not dicom_store.available():
        return ImagingIndexOut(
            available=False,
            reason="Imaging support needs the pydicom and Pillow packages installed.",
            presets=dicom_store.WINDOW_PRESETS,
            presets_units=dicom_store.WINDOW_PRESETS_UNITS)
    by_study = reports_store.reports_by_study() if reports_store.available() else {}
    return ImagingIndexOut(
        available=True,
        presets=dicom_store.WINDOW_PRESETS,
        presets_units=dicom_store.WINDOW_PRESETS_UNITS,
        studies=[ImagingStudyOut(**st, report_ids=by_study.get(st["id"], []))
                 for st in dicom_store.public_studies()])


@app.get("/imaging/series/{series_id}/slice/{index}")
def get_imaging_slice(series_id: str, index: int,
                      wc: float | None = None, ww: float | None = None) -> Response:
    """Render one slice to PNG, applying window/level (wc=center, ww=width; the file's own
    default window if omitted). Local render only — nothing leaves the machine. 404 if the
    series id / slice index is unknown; 415 if the pixels need a decoder that isn't
    installed (compressed transfer syntax), which is reported rather than 500-ing."""
    if not dicom_store.available():
        raise HTTPException(status_code=503, detail="Imaging support is not installed.")
    try:
        png = dicom_store.render_slice(series_id, index, wc=wc, ww=ww)
    except dicom_store.PixelDecodeError as e:
        raise HTTPException(status_code=415, detail=str(e)) from e
    if png is None:
        raise HTTPException(status_code=404, detail="No such series or slice index.")
    # no-store: a rendered medical image is not something to leave in an HTTP cache.
    return Response(content=png, media_type="image/png",
                    headers={"Cache-Control": "no-store"})


class DemoOut(BaseModel):
    """Whether the database this backend is OPEN ON is a seeded demo store."""
    demo: bool


@app.get("/demo", response_model=DemoOut)
def get_demo(conn: sqlite3.Connection = Depends(get_conn)) -> DemoOut:
    """Is this a demo store? Read from a marker INSIDE the database, not from an env var.

    The direction of failure is what decides this. A flag set by the launcher could say
    "demo" while the process was actually open on the real record — and that is the
    dangerous lie, because it invites you to put the screen in front of someone. A marker
    written by the seeder travels with the data it describes: it cannot appear in the real
    database unless somebody seeded over it."""
    return DemoOut(demo=synthetic.is_synthetic(conn))


@app.get("/imaging/series/{series_id}/frame/{index}")
def get_imaging_frame(series_id: str, index: int) -> Response:
    """One slice's pixel VALUES (plus rescale, VOI function and out-of-field mask), so the
    browser can window it itself. See dicom_store.frame_payload for the wire format.

    This is what makes window/level instant: a frame cached here is window-INDEPENDENT, so
    dragging re-renders from memory instead of refetching a differently-windowed picture.
    404 when the series/index is unknown OR when the slice is colour or an unsupported pixel
    width — the client falls back to the PNG route for those, which is the honest answer
    since window/level is a grayscale concept. 415 if the pixels need a decoder."""
    if not dicom_store.available():
        raise HTTPException(status_code=503, detail="Imaging support is not installed.")
    try:
        payload = dicom_store.frame_payload(series_id, index)
    except dicom_store.PixelDecodeError as e:
        raise HTTPException(status_code=415, detail=str(e)) from e
    if payload is None:
        raise HTTPException(status_code=404, detail="No frame data for that slice.")
    # no-store for the same reason the PNG route uses it: pixel values ARE the medical
    # image, and they are not something to leave in an HTTP cache on disk.
    return Response(content=payload, media_type="application/octet-stream",
                    headers={"Cache-Control": "no-store"})


class ImagingRoiOut(BaseModel):
    """Descriptive pixel statistics for a rectangular region of one slice, in the modality's
    real units (Hounsfield for CT). MEASUREMENT, not interpretation — the same footing as the
    distance/angle tools: it reports what the pixels are, never what they mean."""
    mean: float
    sd: float
    min: float
    max: float
    n_pixels: int
    # Padding pixels dropped from the stats (outside the scanned field of view). Surfaced so
    # a partly-out-of-field region reads as measured-on-fewer-pixels, not silently smaller.
    n_excluded: int = 0
    area_mm2: float | None = None
    units: str


@app.get("/imaging/series/{series_id}/slice/{index}/roi", response_model=ImagingRoiOut)
def get_imaging_roi(series_id: str, index: int,
                    x: int, y: int, w: int, h: int) -> ImagingRoiOut:
    """Pixel statistics for the rectangle (x, y, w, h) in IMAGE-pixel coordinates. Computed
    locally from the file's own pixel data + rescale; nothing leaves the machine. 404 for an
    unknown series/slice, 400 for an empty region or a colour image (statistics are
    meaningless on RGB), 415 for undecodable pixels."""
    if not dicom_store.available():
        raise HTTPException(status_code=503, detail="Imaging support is not installed.")
    try:
        stats = dicom_store.roi_stats(series_id, index, x, y, w, h)
    except dicom_store.PixelDecodeError as e:
        raise HTTPException(status_code=415, detail=str(e)) from e
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e)) from e
    if stats is None:
        raise HTTPException(status_code=404, detail="No such series or slice index.")
    return ImagingRoiOut(**stats)


# ------------------------------------------------------------- radiology reports (documents)
# The written report that came on an imaging disc — the one document that says what the
# images MEAN, and which exists nowhere in the DICOM data. 100% LOCAL, like imaging: read
# from a local folder, served over loopback, never assembled into an export payload and never
# written to the database. A report opens with the patient's name/DOB/facility, so it is
# deliberately NOT allowlist-filtered (an allowlist selects safe FIELDS; a report is one block
# of prose whose content is the point) — the local-only boundary is the protection. See
# reports.py's header. The accession number that links a report to its study is treated as an
# identifier: used internally as a join key, never returned.

class ReportOut(BaseModel):
    """A report's metadata. `id` is opaque (derived from the accession, which is never
    exposed); `study_id` ties it to the imaging study it belongs to."""
    id: str
    study_id: str | None = None
    study_date: str | None = None
    study_description: str | None = None
    formats: list[str] = []
    # How many discs carried this same report — one exam can be delivered across two.
    n_discs: int = 1


class ReportDetailOut(ReportOut):
    text: str = ""
    source: str | None = None      # 'text' (a .txt on the disc) | 'html' (extracted)


class ReportIndexOut(BaseModel):
    available: bool
    reason: str | None = None
    reports: list[ReportOut] = []


@app.get("/reports", response_model=ReportIndexOut)
def get_reports() -> ReportIndexOut:
    """List the radiology reports found in the local archive. Metadata only — no report text
    is read to build this, so the list never pulls clinical prose it doesn't need."""
    if not reports_store.available():
        return ReportIndexOut(
            available=False,
            reason=("No imaging archive folder found. Reports are copied there by "
                    "import_imaging_cd.py when a disc is imported."))
    return ReportIndexOut(available=True,
                          reports=[ReportOut(**r) for r in reports_store.list_reports()])


@app.get("/reports/{report_id}", response_model=ReportDetailOut)
def get_report_detail(report_id: str) -> ReportDetailOut:
    """One report's extracted text. Read on demand, local only."""
    record = reports_store.get_report(report_id)
    if record is None:
        raise HTTPException(status_code=404, detail="No such report.")
    return ReportDetailOut(**record)


# ------------------------------------------------------------------ clinical documents
# docstore.py's half of the Documents page: the split-up hospital record (discharge
# summary, ER record, operative/pathology reports, lab printouts) as opposed to the
# radiology reports that ride on an imaging disc. Same posture as /reports — read from a
# local folder, served over loopback, never assembled into an export payload, never
# written to the DB — and deliberately NOT allowlist-filtered for the same reason: a
# discharge summary is prose with no fields to select, so the local-only boundary is the
# protection. Not swept, matching /reports: filesystem-backed, and the detail route's body
# is clinical prose that has no business in a baseline file.

class DocumentOut(BaseModel):
    """One imported clinical document. `id` is opaque (derived from the source bundle and
    its page range); `source`/`source_pages` are provenance, so a reader can find the
    original pages in the physical record. No local path is ever returned."""
    id: str
    date: str | None = None
    title: str
    title_original: str | None = None
    n_pages: int = 0
    source: str | None = None
    source_pages: list[int] | None = None


class DocumentDetailOut(DocumentOut):
    text: str = ""
    formats: list[str] = []


class DocumentIndexOut(BaseModel):
    available: bool
    reason: str | None = None
    documents: list[DocumentOut] = []


@app.get("/documents", response_model=DocumentIndexOut)
def get_documents() -> DocumentIndexOut:
    """List the imported clinical documents. Metadata only — no document text is read to
    build this, so the list never pulls clinical prose it doesn't need."""
    if not docstore.available():
        return DocumentIndexOut(
            available=False,
            reason=("No imported documents found. Hospital record PDFs are split into "
                    "their constituent documents by the offline ingest."))
    return DocumentIndexOut(available=True,
                            documents=[DocumentOut(**d) for d in docstore.list_documents()])


class DocumentSearchHit(BaseModel):
    """One document or report matching a search. `snippets` are short context windows —
    for a `document` they come from OCR text and can contain recognition errors, which is
    why the client marks them as such and links to the PDF rather than treating them as
    the document's content."""
    kind: str                        # 'document' | 'report'
    id: str
    date: str | None = None
    title: str
    n_matches: int
    snippets: list[str] = []
    # True when the exact pass found nothing and OCR-confusable glyphs were folded to get
    # a result. Surfaced so the UI can say the match is approximate rather than silently
    # presenting a fuzzy hit as an exact one.
    approximate: bool = False


class DocumentSearchOut(BaseModel):
    query: str
    results: list[DocumentSearchHit] = []


@app.get("/documents/search", response_model=DocumentSearchOut)
def search_documents(q: str = "") -> DocumentSearchOut:
    """Full-text search across BOTH local document sources — the split hospital record and
    the imaging-disc radiology reports.

    Declared BEFORE /documents/{doc_id} on purpose: FastAPI matches routes in definition
    order, so the literal path has to win or 'search' would be read as a document id.

    Local only: this reads text already on this machine and sends nothing anywhere. A
    query shorter than the minimum returns no results rather than matching everything."""
    hits: list[DocumentSearchHit] = []
    if docstore.available():
        hits += [DocumentSearchHit(kind="document", id=d["id"], date=d["date"],
                                   title=d["title"], n_matches=d["n_matches"],
                                   snippets=d["snippets"],
                                   approximate=d.get("approximate", False))
                 for d in docstore.search(q)]
    if reports_store.available() and len(q.strip()) >= docstore.MIN_QUERY:
        for meta in reports_store.list_reports():
            full = reports_store.get_report(meta["id"]) or {}
            n, snips = docstore.snippets(full.get("text") or "", q)
            if n:
                hits.append(DocumentSearchHit(
                    kind="report", id=meta["id"], date=meta.get("study_date"),
                    title=meta.get("study_description") or "Radiology report",
                    n_matches=n, snippets=snips))
    hits.sort(key=lambda h: (-h.n_matches, h.date or ""))
    return DocumentSearchOut(query=q, results=hits)


@app.get("/documents/{doc_id}", response_model=DocumentDetailOut)
def get_document_detail(doc_id: str) -> DocumentDetailOut:
    """One document's extracted text. Read on demand, local only."""
    record = docstore.get_document(doc_id)
    if record is None:
        raise HTTPException(status_code=404, detail="No such document.")
    return DocumentDetailOut(**record)


@app.get("/documents/{doc_id}/pdf")
def get_document_pdf(doc_id: str) -> Response:
    """The document's original PDF pages. `no-store` for the same reason the report PDF and
    the slice renderer use it: a medical document must not linger in the browser's cache."""
    path = docstore.pdf_path(doc_id)
    if not path:
        raise HTTPException(status_code=404, detail="No PDF for this document.")
    try:
        with open(path, "rb") as fh:
            data = fh.read()
    except OSError as e:
        raise HTTPException(status_code=404, detail="The document file could not be read.") from e
    return Response(content=data, media_type="application/pdf",
                    headers={"Cache-Control": "no-store",
                             "Content-Disposition": 'inline; filename="document.pdf"'})


@app.get("/reports/{report_id}/pdf")
def get_report_pdf(report_id: str) -> Response:
    """The report's original PDF bytes. `no-store` for the same reason the slice renderer
    uses it: a medical document must not linger in the browser's disk cache. `inline` so the
    browser's viewer opens it rather than downloading a file with a meaningless name."""
    path = reports_store.pdf_path(report_id)
    if not path:
        raise HTTPException(status_code=404, detail="No PDF for this report.")
    try:
        with open(path, "rb") as fh:
            data = fh.read()
    except OSError as e:
        raise HTTPException(status_code=404, detail="The report file could not be read.") from e
    return Response(content=data, media_type="application/pdf",
                    headers={"Cache-Control": "no-store",
                             "Content-Disposition": 'inline; filename="report.pdf"'})
