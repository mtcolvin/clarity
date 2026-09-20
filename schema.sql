-- Personal health tracker — SQLite schema
--
-- Design note: labs and vitals share one shape, so they all live in ONE
-- `observations` table (metric, value, unit, date, + the reference range that
-- came with that specific result). This keeps every chart and every analysis
-- function running over a single uniform structure.

PRAGMA journal_mode = WAL;
PRAGMA foreign_keys = ON;

-- Original lab reports / scans, so an observation can point back to its source.
CREATE TABLE IF NOT EXISTS documents (
    id          INTEGER PRIMARY KEY,
    title       TEXT    NOT NULL,
    file_path   TEXT    NOT NULL,                       -- path to stored PDF/image
    document_on TEXT,                                   -- ISO date 'YYYY-MM-DD'
    created_at  TEXT    NOT NULL DEFAULT (datetime('now'))
);

-- Saved EXTERNAL-EXPORT RESULTS — the model's response to each confirmed export, kept
-- LOCALLY alongside the send audit so the Settings "External export" tab shows both what
-- left and what came back. Health-adjacent (a model's interpretation of the user's data),
-- so it lives in the local-only DB, never synced. `metrics` is a JSON array of the metric
-- names sent; `scope` is the human label (a metric name, "Full health picture", etc.).
-- Additive via IF NOT EXISTS.
CREATE TABLE IF NOT EXISTS export_results (
    id         INTEGER PRIMARY KEY,
    created_at TEXT NOT NULL DEFAULT (datetime('now')),
    scope      TEXT NOT NULL DEFAULT '',                -- human scope label
    metrics    TEXT NOT NULL DEFAULT '[]',              -- JSON array of metric names sent
    provider   TEXT,
    model      TEXT,
    output     TEXT NOT NULL,                           -- the model's response text
    audit_id   TEXT                                     -- gateway_audit.log entry this answers
);

-- Timed collections (e.g. a 24-hour urine). A spot draw is a POINT in time; a timed
-- collection spans a PERIOD and yields several analytes that all share ONE collection
-- (its total volume, duration, and dates). Modeled like `documents`: the provenance an
-- observation points back to (observations.collection_id -> collections.id), so the
-- volume/duration/start are stored ONCE here, not duplicated onto every analyte row. Each
-- analyte stays a normal observations row — its VALUE is the per-period RATE (the unit
-- carries the period, e.g. 'mg/24h'), and its `observed_on` is the collection's completion
-- date. This metadata is CONTEXT only: it never enters the analysis engine (analyze_series
-- reads only value/observed_on/ref/result_type off a series row). Additive via IF NOT EXISTS.
CREATE TABLE IF NOT EXISTS collections (
    id             INTEGER PRIMARY KEY,
    kind           TEXT NOT NULL DEFAULT '24h_urine',    -- timed-collection type; room to grow
    completed_on   TEXT NOT NULL,                        -- ISO date the collection ENDED (= analytes' observed_on)
    started_on     TEXT,                                 -- ISO date it began (nullable)
    duration_hours REAL,                                 -- e.g. 24.0 (nullable)
    volume_ml      REAL,                                 -- total collected volume (nullable)
    notes          TEXT,
    created_at     TEXT NOT NULL DEFAULT (datetime('now'))
);

-- Metric registry — the durable identity for a metric. A metric is NO LONGER an
-- implicit name; observations/metric_config/metric_settings key off this table's
-- stable `id`, so a rename is a pure display-name change (touch metrics.name only)
-- that can't desync a series or its config. `name` is the display name (UNIQUE —
-- keeps the UI unambiguous and ingestion-by-name resolvable). `seed_key` is the
-- IMMUTABLE link to a metric_config.py SEED entry (set once, never changed by a
-- rename), so a renamed metric keeps tracking its curated SEED config. NULL
-- seed_key = no SEED entry. Defined BEFORE the tables that FK into it.
CREATE TABLE IF NOT EXISTS metrics (
    id         INTEGER PRIMARY KEY,
    -- `id` IS THE MATCH KEY (the metric's identity). `name` and `alias` are two LABELS
    -- that both resolve TO it — neither is the key, and neither is privileged for
    -- matching: an incoming import/add name is matched against both (see
    -- db.resolve_ingest_id) and yields this id.
    name       TEXT NOT NULL UNIQUE,                     -- verbose label: the lab's own wording
    alias      TEXT,                                     -- shorthand label shown in the UI (NULL -> show name)
    metric_group TEXT,                                   -- optional user group label (NULL -> ungrouped); a picker optgroup
    seed_key   TEXT,                                     -- immutable SEED linkage; NULL = no SEED entry
    created_at TEXT NOT NULL DEFAULT (datetime('now'))
);
-- One metric per SEED entry: seed_key is unique among LINKED metrics. PARTIAL
-- (WHERE seed_key IS NOT NULL) so the many unlinked metrics (NULL seed_key) stay
-- deliberately unconstrained — SQLite would treat multiple NULLs as distinct
-- anyway, but the partial form makes the intent explicit and indexes only the
-- linked rows. Lets resolve_by_seed_key trust at-most-one match.
CREATE UNIQUE INDEX IF NOT EXISTS idx_metrics_seed_key
    ON metrics (seed_key) WHERE seed_key IS NOT NULL;
-- NOTE on the alias column above: its partial-unique index (idx_metrics_alias) is
-- created in db.init_db, NOT here — an existing DB predating the alias column reaches
-- this file's CREATE-TABLE-IF-NOT-EXISTS as a no-op, so the column doesn't exist yet
-- when executescript runs; indexing it here would fail. init_db adds the column (ALTER)
-- then creates the index, so both fresh and existing DBs converge. The alias is UNIQUE
-- among metrics that HAVE one (a display name resolves to at most one metric on ingest);
-- db.set_metric_alias additionally enforces alias-vs-other-canonical-name uniqueness,
-- which a single-column index can't.

-- The core time-series: every measurement, lab or vital. Most are numeric, but
-- results can also be qualitative (Positive/Negative/Detected) or censored
-- (<5, >100) — distinguished by `result_type`:
--   'numeric'     value set;  value_text NULL;     operator NULL
--   'qualitative' value NULL; value_text set;      operator NULL  (e.g. 'Positive')
--   'censored'    value set;  value_text NULL;     operator set   (e.g. '<' with value 5 => "<5")
-- Censored KEEPS the number (5) plus the operator so it's never confused with the
-- bare number 5 — the analysis engine excludes non-'numeric' rows from all math.
--
-- A metric's identity is its `metric_id` FK into the `metrics` registry (defined
-- above), NOT a name column here — so a rename touches only metrics.name and can't
-- desync a series. Column order below is the historical live order (metric_id was
-- the last column added), preserved verbatim so this DDL matches every existing DB.
CREATE TABLE IF NOT EXISTS observations (
    id          INTEGER PRIMARY KEY,
    value       REAL,                                    -- numeric/censored: the number; qualitative: NULL
    unit        TEXT    NOT NULL DEFAULT '',             -- 'mg/dL'; '' for unit-less qualitative results
    observed_on TEXT    NOT NULL,                        -- ISO date 'YYYY-MM-DD'
    ref_low     REAL,                                    -- reference range from THIS report
    ref_high    REAL,                                    -- (ranges vary by lab/age/sex — store per result)
    result_type TEXT    NOT NULL DEFAULT 'numeric',      -- 'numeric' | 'qualitative' | 'censored'
    value_text  TEXT,                                    -- qualitative result text (e.g. 'Positive')
    operator    TEXT,                                    -- censored comparator: '<' | '>' | '<=' | '>='
    loinc       TEXT,                                    -- optional, for FHIR/portal imports later
    source      TEXT    NOT NULL DEFAULT 'manual',       -- 'manual' | 'pdf' | 'fhir'
    document_id INTEGER REFERENCES documents(id),
    collection_id INTEGER REFERENCES collections(id),    -- the timed collection this analyte came from (nullable)
    created_at  TEXT    NOT NULL DEFAULT (datetime('now')),
    normal_text TEXT,                                    -- expected-normal for qualitative results
                                                         -- (numeric/censored use ref_low/ref_high)
    ref_low_operator  TEXT,                              -- makes the lower bound strict: '>' (else NULL/'>=' = inclusive)
    ref_high_operator TEXT,                              -- makes the upper bound strict: '<' (else NULL/'<=' = inclusive)
    metric_id   INTEGER NOT NULL REFERENCES metrics(id), -- metric identity (see metrics registry)
    -- One reading per metric per day. observed_on is date-only, so this also
    -- blocks the same result being entered twice. (A genuine same-day repeat,
    -- e.g. two BP readings, would need a timestamp instead — revisit then.)
    -- This UNIQUE constraint also creates the index that serves the
    -- WHERE metric_id = ? ORDER BY observed_on lookups in get_series().
    UNIQUE (metric_id, observed_on),
    -- Data-integrity invariants for the three result types (enforced in the DB,
    -- like the UNIQUE rule above).
    CHECK (result_type IN ('numeric', 'qualitative', 'censored')),
    CHECK (operator IS NULL OR operator IN ('<', '>', '<=', '>=')),
    -- Reference-bound operators: a bound's normal range can itself be censored
    -- (e.g. a normal of '<=10' or '>5'). NULL = inclusive, preserving prior rows.
    CHECK (ref_low_operator  IS NULL OR ref_low_operator  IN ('<', '>', '<=', '>=')),
    CHECK (ref_high_operator IS NULL OR ref_high_operator IN ('<', '>', '<=', '>=')),
    CHECK (
        (result_type = 'numeric'     AND value IS NOT NULL AND value_text IS NULL     AND operator IS NULL) OR
        (result_type = 'qualitative' AND value IS NULL     AND value_text IS NOT NULL AND operator IS NULL) OR
        (result_type = 'censored'    AND value IS NOT NULL AND value_text IS NULL     AND operator IS NOT NULL)
    )
);

-- Ongoing conditions (things with a status, not a value).
CREATE TABLE IF NOT EXISTS conditions (
    id          INTEGER PRIMARY KEY,
    name        TEXT NOT NULL,
    icd10       TEXT,
    onset_on    TEXT,
    status      TEXT NOT NULL DEFAULT 'active',          -- active | resolved | monitoring
    resolved_on TEXT,                                    -- ISO date; set only when status='resolved'
    notes       TEXT,
    created_at  TEXT NOT NULL DEFAULT (datetime('now'))
);

-- Current/past medications. "active" is DERIVED, not stored: a row with
-- end_date IS NULL is active (no redundant status column to drift out of sync).
-- dose/frequency are free text on purpose (e.g. '20 mg', 'once daily') — no
-- structured drug coding yet. Additive and standalone: shares nothing with
-- observations or the analysis engine.
CREATE TABLE IF NOT EXISTS medications (
    id         INTEGER PRIMARY KEY,
    name       TEXT NOT NULL,
    dose       TEXT,                                    -- free text, e.g. '20 mg'
    frequency  TEXT,                                    -- free text, e.g. 'once daily'
    start_date TEXT,                                    -- ISO 'YYYY-MM-DD'
    end_date   TEXT,                                    -- ISO; NULL => active
    notes      TEXT,
    created_at TEXT NOT NULL DEFAULT (datetime('now'))
);

-- Point-in-time events for the Timeline (things with a date and notes, not a
-- value): visits, symptoms, life events, procedures, other. event_type is one of
-- a fixed set (enforced in the API). Additive and standalone — shares nothing
-- with observations or the analysis engine.
CREATE TABLE IF NOT EXISTS events (
    id          INTEGER PRIMARY KEY,
    event_date  TEXT NOT NULL,                           -- ISO 'YYYY-MM-DD'
    event_type  TEXT NOT NULL,                           -- visit | symptom | life_event | procedure | other
    title       TEXT NOT NULL,
    notes       TEXT,
    created_at  TEXT NOT NULL DEFAULT (datetime('now'))
);

-- Immunizations: the vaccination record. A dated fact with no value and no status
-- — closest in shape to `events`, and like conditions/medications it is standalone
-- (shares nothing with observations or the analysis engine; nothing here is ever
-- detected on).
--
-- `dose_label` and `amount` are two DIFFERENT facts and a record can carry either, both
-- or neither: dose_label says WHICH dose in a series ("Dose 1", "Booster"), amount says
-- HOW MUCH went in ("0.5 mL"). Collapsing them into one "dose" column would make a list
-- of "Dose 1" and "0.5 mL" unsortable and unreadable — they answer different questions.
-- `amount` is free text WITH its unit, like an observation's unit: 0.5 mL and 0.25 mL are
-- both real vaccine volumes and the record prints the unit, so storing a bare number
-- would be throwing away what the record says.
--
-- `administered_on` is NULLABLE on purpose: a childhood shot recalled from a paper
-- card is a real record with no date, and inventing one would put a fabricated point
-- on the Timeline. A dose LABEL rather than a dose number, and free text at that: the
-- app tracks what a record says, and encoding a schedule ("dose 2 of 3") would mean
-- knowing each vaccine's schedule and deciding whether a record is complete — which is
-- a clinical judgment, not a storage concern.
CREATE TABLE IF NOT EXISTS immunizations (
    id              INTEGER PRIMARY KEY,
    vaccine         TEXT NOT NULL,                       -- e.g. 'Influenza (quadrivalent)'
    administered_on TEXT,                                -- ISO 'YYYY-MM-DD'; NULL = date unknown
    dose_label      TEXT,                                -- WHICH dose: 'Dose 1', 'Booster', '2023-24 season'
    amount          TEXT,                                -- HOW MUCH: '0.5 mL' (a volume, free text with its unit)
    site            TEXT,                                -- 'left deltoid'
    lot             TEXT,                                -- manufacturer lot, as printed on the record
    notes           TEXT,
    created_at      TEXT NOT NULL DEFAULT (datetime('now'))
);

-- Newest-first listing puts a dated record above an undated one; the index serves it.
CREATE INDEX IF NOT EXISTS idx_immunizations_date
    ON immunizations (administered_on DESC);

-- User-adjustable settings (key/value). Pure storage — the MEANING of each key
-- (default, type, label, bounds) lives in the settings.py registry, not here, so
-- db.py stays ignorant of analysis. value is TEXT and cast on read, so the same
-- table holds ints today and floats (future bounded knobs) without a schema change.
-- A key absent from this table falls back to its code-constant default, so the
-- app works even when the table is empty.
CREATE TABLE IF NOT EXISTS settings (
    key        TEXT PRIMARY KEY,
    value      TEXT NOT NULL,
    updated_at TEXT NOT NULL DEFAULT (datetime('now'))
);

-- Per-metric settings, keyed by metric name. personal_baseline_mode opts a
-- chronically-out-of-lab-range metric into being tracked against the user's own
-- baseline instead (recontextualizing the lab-range exceedance while the
-- personal-baseline detector keeps alarming on real deviation). `note` is the
-- USER's own annotation (e.g. "Gilbert's — expected"), never the tool's
-- inference. suggestion_dismissed records "don't suggest this again" so a
-- declined (or manually turned-off) metric isn't re-nagged — a distinct state
-- from "not yet a candidate". Additive: a metric with no row falls back to all
-- defaults (mode off, no note, not dismissed).
CREATE TABLE IF NOT EXISTS metric_settings (
    metric                 TEXT PRIMARY KEY,             -- display name (kept for rename-carry; identity is metric_id)
    personal_baseline_mode INTEGER NOT NULL DEFAULT 0,   -- 0/1
    note                   TEXT    NOT NULL DEFAULT '',
    suggestion_dismissed   INTEGER NOT NULL DEFAULT 0,   -- 0/1
    updated_at             TEXT    NOT NULL DEFAULT (datetime('now')),
    metric_id              INTEGER NOT NULL REFERENCES metrics(id)
);

-- Per-metric DETECTOR config (the opt-in thresholds / RCV that analyze_series
-- takes as kwargs), keyed by (metric, key) — a generic key/value table like
-- `settings`, but per metric. `value` is raw TEXT (JSON for structured keys like
-- a thresholds list); the metric_config.py registry casts it on read, so db.py
-- stays ignorant of what a key means (same separation as settings). A metric with
-- no rows yields an empty config, handled exactly like the former "not in the
-- hardcoded METRIC_CONFIG" fallback (no thresholds, default RCV).
--
-- `metric` is a PLAIN TEXT key, deliberately NOT a foreign key into observations:
-- so a metric rename carries its config forward with a simple
-- `UPDATE metric_config SET metric=? WHERE metric=?` inside the rename
-- transaction (no FK constraint to fight). Additive via IF NOT EXISTS.
CREATE TABLE IF NOT EXISTS metric_config (
    metric     TEXT NOT NULL,                            -- display name (kept for rename-carry; identity is metric_id)
    key        TEXT NOT NULL,
    value      TEXT NOT NULL,
    updated_at TEXT NOT NULL DEFAULT (datetime('now')),
    metric_id  INTEGER NOT NULL REFERENCES metrics(id),
    PRIMARY KEY (metric, key)
);

-- Reference bands for DERIVED metrics (band-as-data). A derived metric's VALUE is
-- computed on read (never stored — no fabrication), but its reference band is NOT
-- derivable from the inputs' bands: the inputs are correlated (direct bilirubin is
-- part of total; albumin is part of total protein), so interval arithmetic over their
-- ranges is systematically too wide and can go negative. The band is genuine, lab-
-- specific, time-varying DATA the report carries — so it travels WITH the draw exactly
-- like a stored metric's range: captured per date at import (the value discarded, the
-- range kept) and joined into the computed series on read. When the lab changes its
-- interval, the next import updates the band automatically; a date with no captured
-- band simply charts without one. Keyed by (metric, date), metric as PLAIN TEXT (like
-- metric_config/metric_settings — derived names are reserved, never renamed). Additive.
CREATE TABLE IF NOT EXISTS derived_reference_range (
    metric      TEXT NOT NULL,                            -- derived metric display name
    observed_on TEXT NOT NULL,                            -- ISO 'YYYY-MM-DD' (the draw date)
    ref_low     REAL,                                     -- band low  (nullable = one-sided)
    ref_high    REAL,                                     -- band high (nullable = one-sided)
    unit        TEXT NOT NULL DEFAULT '',                 -- must match the derived metric's unit to apply
    updated_at  TEXT NOT NULL DEFAULT (datetime('now')),
    PRIMARY KEY (metric, observed_on)
);

-- User DISPLAY-name overrides for DERIVED (computed) metrics. A derived metric lives in
-- the derived.py REGISTRY, not the `metrics` table (it has no observations of its own and
-- must NOT enter the ingest/suggest machinery — you never import a computed value), so its
-- display alias can't ride the metrics.alias column. This tiny key/value store holds a
-- user's override, keyed by the derived metric's canonical name (reserved, never renamed).
-- Absent row ⇒ fall back to the spec's curated display_name, else the verbose name. A
-- derived alias is display-ONLY (not a match key). Additive via IF NOT EXISTS.
CREATE TABLE IF NOT EXISTS derived_alias (
    metric     TEXT PRIMARY KEY,                         -- derived metric canonical name
    alias      TEXT NOT NULL,                            -- user's chosen display label
    updated_at TEXT NOT NULL DEFAULT (datetime('now'))
);

-- Personal profile — permanent/low-change demographics, a SINGLETON row. The
-- CHECK(id = 1) enforces exactly one row at the DB level, so update_profile can
-- UPSERT on id=1 (race-free, no check-then-insert). `sex` is biological sex for
-- medical-reference context only; nullable, constrained to a small set. Profile
-- data is local-only and feeds NO analysis/flag/chart logic — it's stored and
-- shown in the Profile section only (future builds will use it for derived
-- calculations like BMI / CKD-EPI). Additive via IF NOT EXISTS.
CREATE TABLE IF NOT EXISTS profile (
    id            INTEGER PRIMARY KEY CHECK (id = 1),     -- singleton: exactly one row
    sex           TEXT CHECK (sex IS NULL OR sex IN ('male', 'female', 'other')),
    date_of_birth TEXT,                                   -- ISO 'YYYY-MM-DD'
    created_at    TEXT NOT NULL DEFAULT (datetime('now')),
    updated_at    TEXT NOT NULL DEFAULT (datetime('now'))
);

-- Time-varying physical measurements (weight, height). APPEND-ONLY: each update
-- is a new row; the "current value" is the latest row per field (max recorded_on).
-- `unit` is required and stored AS ENTERED (lb vs kg, in vs cm) — no auto-
-- conversion, the same honesty as observations. Additive via IF NOT EXISTS.
CREATE TABLE IF NOT EXISTS profile_history (
    id          INTEGER PRIMARY KEY,
    field       TEXT NOT NULL CHECK (field IN ('weight', 'height')),
    value       REAL NOT NULL,
    unit        TEXT NOT NULL,                            -- 'lb'/'kg', 'in'/'cm'
    recorded_on TEXT NOT NULL,                            -- ISO 'YYYY-MM-DD'
    created_at  TEXT NOT NULL DEFAULT (datetime('now'))
);
-- Serves the latest-value-per-field lookup (field =, ORDER BY recorded_on DESC).
CREATE INDEX IF NOT EXISTS idx_profile_history_field_date
    ON profile_history (field, recorded_on DESC);
