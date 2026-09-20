"""
db.py — thin SQLite access layer for Clarity.

Deliberately minimal: connect, initialize from schema.sql, insert, and fetch a
metric's time-series. Nothing here knows about analysis — that lives in
analysis.py, so each layer stays independently testable.
"""

from __future__ import annotations

import difflib
import sqlite3
from pathlib import Path


class UnitMismatchError(Exception):
    """A write would log a metric in a unit that disagrees with its existing
    unit. Raised by the write functions so the same one-unit-per-metric rule
    holds for every caller (API, demo, future importers); api.py maps it to a
    409, mirroring how the UNIQUE(metric, observed_on) IntegrityError is mapped.
    """

    def __init__(self, metric: str, existing: str, attempted: str):
        self.metric = metric
        self.existing = existing
        self.attempted = attempted
        super().__init__(
            f"{metric} is recorded in {existing}; this reading uses {attempted}."
        )


class MetricExistsError(Exception):
    """A rename targets a name that's already an existing metric. Renaming onto a
    live metric would merge two distinct series (risking unit conflicts and
    UNIQUE(metric, observed_on) collisions), so it's refused rather than silently
    mixing data; api.py maps this to a 409. A deliberate merge would be a separate,
    explicitly-confirmed operation.
    """

    def __init__(self, metric: str):
        self.metric = metric
        super().__init__(f"A metric named {metric} already exists.")


class CollectionInUseError(Exception):
    """A delete targets a timed collection that still has observations pointing at it.
    Deleting it would orphan (or, with cascade, silently destroy) those readings, so it's
    refused — the caller must remove/reassign the readings first. api.py maps it to a 409,
    mirroring the rename merge-refusal. Deliberately explicit, per the 'refuse delete of a
    non-empty collection' decision."""

    def __init__(self, collection_id: int, n: int):
        self.collection_id = collection_id
        self.n = n
        super().__init__(
            f"Collection {collection_id} still has {n} reading(s); remove or reassign "
            f"them before deleting it."
        )


class AliasConflictError(Exception):
    """A display-name (alias) write would collide with a name already in use — another
    metric's canonical name OR another metric's alias (compared normalized). Refused so
    an alias always resolves to at most one metric on ingest; api.py maps it to a 409.
    """

    def __init__(self, alias: str, conflicts_with: str):
        self.alias = alias
        self.conflicts_with = conflicts_with
        super().__init__(
            f"The name {alias!r} is already used by {conflicts_with!r}."
        )


def connect(db_path: str = "health.db", check_same_thread: bool = True) -> sqlite3.Connection:
    """Open a connection. Use ':memory:' for tests, a file path to persist.

    check_same_thread=False lets a connection be handed between threads — the
    FastAPI per-request dependency needs this since the request and the worker
    that opened it may differ. Defaults to True (sqlite's safe default).
    """
    conn = sqlite3.connect(db_path, check_same_thread=check_same_thread)
    conn.row_factory = sqlite3.Row  # rows behave like dicts
    conn.execute("PRAGMA foreign_keys = ON")
    return conn


def init_db(conn: sqlite3.Connection, schema_path: str = "schema.sql") -> None:
    """Create tables from the schema file (idempotent — uses IF NOT EXISTS), then
    run the additive column migrations for DBs predating those columns."""
    schema = Path(schema_path).read_text()
    # Reshape an OLD events table (pre-Timeline shape: kind/name/occurred_on) to the
    # new event_date/event_type/title shape. That table was never wired up, so it is
    # expected to be empty — drop it here so schema.sql recreates it in the new shape.
    # GUARD: only drop when empty; if it somehow holds data, leave it and raise so the
    # data is surfaced, never silently destroyed.
    ecols = [r[1] for r in conn.execute("PRAGMA table_info(events)")]
    if ecols and "event_date" not in ecols:
        n = conn.execute("SELECT COUNT(*) FROM events").fetchone()[0]
        if n:
            raise RuntimeError(
                f"events table has the old shape but holds {n} row(s); refusing to "
                "drop it. Migrate or back up those rows, then retry."
            )
        print("[db] Migrating empty legacy 'events' table to the new Timeline shape.")
        conn.execute("DROP TABLE events")
    conn.executescript(schema)
    # Additive migration: normal_text (the expected-normal for qualitative results)
    # is a plain nullable column, so ALTER ADD COLUMN is safe — no rebuild.
    cols = [r[1] for r in conn.execute("PRAGMA table_info(observations)")]
    if cols and "normal_text" not in cols:
        conn.execute("ALTER TABLE observations ADD COLUMN normal_text TEXT")
    # Additive migration: conditions.resolved_on (set only when status='resolved').
    # Plain nullable column — safe additive ALTER, idempotent (skip if present).
    cols = [r[1] for r in conn.execute("PRAGMA table_info(conditions)")]
    if cols and "resolved_on" not in cols:
        conn.execute("ALTER TABLE conditions ADD COLUMN resolved_on TEXT")
    # Additive migration: censored REFERENCE bounds — ref_low_operator/ref_high_operator
    # make a bound strict (a normal range that is itself '<=10' or '>5'). Plain nullable
    # columns with a value CHECK; existing rows stay NULL = inclusive, so every prior
    # range comparison is unchanged. Guarded by presence, so idempotent. (SQLite permits
    # a CHECK on ADD COLUMN as long as it references only the new column.)
    cols = [r[1] for r in conn.execute("PRAGMA table_info(observations)")]
    if cols and "ref_low_operator" not in cols:
        conn.execute("ALTER TABLE observations ADD COLUMN ref_low_operator TEXT "
                     "CHECK (ref_low_operator IS NULL OR ref_low_operator IN ('<','>','<=','>='))")
    if cols and "ref_high_operator" not in cols:
        conn.execute("ALTER TABLE observations ADD COLUMN ref_high_operator TEXT "
                     "CHECK (ref_high_operator IS NULL OR ref_high_operator IN ('<','>','<=','>='))")
    # Additive migration: metrics.alias (the friendly DISPLAY name). Plain nullable
    # column; existing rows stay NULL (fall back to showing the canonical name). Its
    # partial-unique index is created by schema.sql (CREATE INDEX IF NOT EXISTS), so
    # only the column itself needs adding on an older DB. Guarded/idempotent.
    # Additive migration: observations.collection_id (the timed collection an analyte came
    # from). A nullable REFERENCES column adds cleanly via ALTER AND SQLite enforces the FK
    # (verified) — no table rebuild. `collections` is created by executescript above, so the
    # FK target exists. Guarded/idempotent.
    ocols = [r[1] for r in conn.execute("PRAGMA table_info(observations)")]
    if ocols and "collection_id" not in ocols:
        conn.execute("ALTER TABLE observations ADD COLUMN collection_id "
                     "INTEGER REFERENCES collections(id)")
    # Additive migration: immunizations.amount (the VOLUME given, e.g. '0.5 mL'), which is
    # a different fact from dose_label (WHICH dose in a series). Plain nullable column;
    # existing rows stay NULL. Guarded/idempotent.
    icols = [r[1] for r in conn.execute("PRAGMA table_info(immunizations)")]
    if icols and "amount" not in icols:
        conn.execute("ALTER TABLE immunizations ADD COLUMN amount TEXT")
    mcols = [r[1] for r in conn.execute("PRAGMA table_info(metrics)")]
    if mcols and "alias" not in mcols:
        conn.execute("ALTER TABLE metrics ADD COLUMN alias TEXT")
    # Additive migration: metrics.metric_group (optional user group label, a picker
    # optgroup — e.g. an arterial blood-gas panel). Plain nullable column; existing rows
    # stay NULL (ungrouped). No index/uniqueness — many metrics share a group label, and
    # at this scale a scan is free. Guarded/idempotent.
    if mcols and "metric_group" not in mcols:
        conn.execute("ALTER TABLE metrics ADD COLUMN metric_group TEXT")
    # Additive migration: export_results.audit_id — the gateway_audit.log entry a saved
    # response answers, so "what left the machine" and "what came back" join instead of
    # sitting in two unrelated records. Nullable by necessity: rows saved before the id
    # existed have no send to point at (see the backfill note in ROADMAP).
    ecols = [r[1] for r in conn.execute("PRAGMA table_info(export_results)")]
    if ecols and "audit_id" not in ecols:
        conn.execute("ALTER TABLE export_results ADD COLUMN audit_id TEXT")
    # Create the alias index HERE (not in schema.sql): on an existing DB the column is
    # added just above (after schema.sql's CREATE-TABLE no-op), so the index can only be
    # made once the column is guaranteed to exist. IF NOT EXISTS covers the fresh DB too
    # (where schema.sql's CREATE TABLE already added the column but not the index).
    if mcols:
        conn.execute("CREATE UNIQUE INDEX IF NOT EXISTS idx_metrics_alias "
                     "ON metrics (alias) WHERE alias IS NOT NULL")
    conn.commit()
    # The metric_id registry is now the FINAL shape produced directly by schema.sql
    # (observations/metric_config/metric_settings carry a NOT NULL metric_id FK into
    # `metrics`, and observations has no `metric` column). The multi-phase migration
    # that once transformed the old name-keyed shape into this one — registry mint,
    # metric_id add + backfill, and the NOT-NULL/UNIQUE table rebuilds — was retired
    # once every live DB reached the final shape (all its guards had gone permanently
    # inert). The write path (get_or_create_metric in add_observation / set_metric_*)
    # sets metric_id itself, so fresh rows need no backfill. Support scope: a DB that
    # predates the registry migration is no longer upgraded here — none exists.


def get_metric_unit(
    conn: sqlite3.Connection, metric: str, exclude_id: int | None = None
) -> str | None:
    """The metric's canonical unit = the unit of its most recent NON-QUALITATIVE
    reading, or None if it has none yet (a brand-new metric, OR one that so far has
    only qualitative readings — the next numeric/censored write establishes the unit).

    QUALITATIVE readings are EXCLUDED here: a qualitative result ('Negative',
    'Yellow') is inherently unitless, so its blank unit is the ABSENCE of a unit,
    not a dimensionless unit choice (unlike a numeric ratio, whose '' IS a real
    unit). Letting a qualitative reading define the canonical unit would wrongly
    lock the metric to '' and reject a legitimate numeric mg/dL reading — the
    urine-glucose case (dipstick 'Negative' on one report, a quantitative mg/dL on
    another; same test, one metric). Numeric/censored unit consistency is untouched:
    two numeric readings with different units still conflict.

    `exclude_id` skips one row when deciding the canonical unit — used by the
    edit path so a reading is checked against the other readings, not itself
    (otherwise editing the newest reading would compare it to itself and never
    enforce). The most recent (non-qualitative) reading is unambiguous:
    UNIQUE(metric, observed_on) rules out date ties.
    """
    mid = resolve_metric_id(conn, metric)
    if mid is None:
        return None
    if exclude_id is None:
        row = conn.execute(
            "SELECT unit FROM observations WHERE metric_id = ?"
            " AND IFNULL(result_type,'numeric') <> 'qualitative'"
            " ORDER BY observed_on DESC LIMIT 1",
            (mid,),
        ).fetchone()
    else:
        row = conn.execute(
            "SELECT unit FROM observations WHERE metric_id = ? AND id <> ?"
            " AND IFNULL(result_type,'numeric') <> 'qualitative'"
            " ORDER BY observed_on DESC LIMIT 1",
            (mid, exclude_id),
        ).fetchone()
    return row["unit"] if row else None


# --- Metric registry resolution (name <-> stable id) --------------------------
# The metrics registry (Phase 1) gives each metric a durable id. These two helpers
# are the single chokepoint where a name becomes an id. resolve_metric_id is
# lookup-only (the id-keyed reads in sub-phase 3b); get_or_create_metric mints on
# the write path. Both are registry-agnostic — the caller passes SEED keys (db.py
# never imports the metric_config registry), exactly like link_seed_keys.

def resolve_metric_id(conn: sqlite3.Connection, name: str) -> int | None:
    """The registry id for `name` (EXACT canonical-name match), or None. Lookup-ONLY —
    never mints, so a read path can't conjure a ghost metric from an unknown URL name
    (it resolves to None -> an id-keyed query matches nothing -> the same empty result
    names give today). This is the INTERNAL identity lookup (callers pass the canonical
    name); ingest-time smart matching (normalized, alias-aware) is resolve_ingest_id."""
    row = conn.execute("SELECT id FROM metrics WHERE name = ?", (name,)).fetchone()
    return row["id"] if row else None


def _normalize(s: str) -> str:
    """Fold a metric name for ingest MATCHING only (never for storage/display):
    case-fold + collapse internal whitespace + strip. So 'IGF-1', 'igf-1', and
    ' IGF-1 ' resolve to the same metric, and 'Sodium  Serum/Plasma' matches
    'Sodium Serum/Plasma'. Deliberately conservative — it does NOT strip punctuation
    or reorder words, so distinct analytes never collapse together."""
    return " ".join((s or "").split()).casefold()


def resolve_ingest_id(conn: sqlite3.Connection, name: str) -> int | None:
    """The MATCH KEY (metric_id) an INCOMING (import/add) name should attach to — or None
    if the name is genuinely new. metric_id is the identity; `name` (the lab's verbose
    wording) and `alias` (the shorthand) are two EQUAL-STATUS LABELS that both resolve to
    it, so this matches against BOTH, normalized. That's the de-dup: importing/typing
    'IGF-1' (shorthand), 'Insulin-like Growth Factor 1' (verbose), or a case/whitespace
    variant of either all land on the same id instead of minting a duplicate. Distinct
    from resolve_metric_id (exact verbose-label lookup, used for internal identity). Small
    table -> a Python-side normalized scan is fine and lets us collapse internal
    whitespace, which lower(trim(...)) in SQL can't."""
    target = _normalize(name)
    if not target:
        return None
    for r in conn.execute("SELECT id, name, alias FROM metrics"):
        if _normalize(r["name"]) == target:
            return r["id"]
        if r["alias"] and _normalize(r["alias"]) == target:
            return r["id"]
    return None


def resolve_ingest(conn: sqlite3.Connection, name: str) -> dict | None:
    """The metric an incoming name attaches to, as {"metric": canonical, "alias": alias},
    or None if it's genuinely new. Thin wrapper over resolve_ingest_id so the API layer
    gets the canonical name + display alias without running SQL itself."""
    mid = resolve_ingest_id(conn, name)
    if mid is None:
        return None
    r = conn.execute("SELECT name, alias FROM metrics WHERE id = ?", (mid,)).fetchone()
    return {"metric": r["name"], "alias": r["alias"]} if r else None


def resolve_by_seed_key(conn: sqlite3.Connection, seed_key: str) -> str | None:
    """The CURRENT display name of the metric linked to `seed_key`, or None if no
    metric carries it. Lets SEED config re-seed under the metric's live name after a
    rename (seed_key is immutable, name is not). LIMIT 1 is defensive: seed_key is
    de-facto unique (link_seed_keys writes each once) but not constraint-unique."""
    row = conn.execute(
        "SELECT name FROM metrics WHERE seed_key = ? LIMIT 1", (seed_key,)
    ).fetchone()
    return row["name"] if row else None


def get_or_create_metric(conn: sqlite3.Connection, name: str, seed_keys=()) -> int:
    """Return the registry id for `name`, minting a registry row if it's new. On a
    mint, seed_key is set to the name iff it's in `seed_keys` (the immutable SEED
    linkage), else NULL. Composes on resolve_metric_id (lookup-first), so it never
    duplicates a row; a concurrent mint that wins the UNIQUE(name) race is absorbed
    by re-resolving on the IntegrityError. Does NOT commit — the caller's
    transaction (e.g. add_observation's try/rollback) commits the mint atomically
    with the row it's for, so a failed insert never leaves a stray metric."""
    existing = resolve_metric_id(conn, name)
    if existing is not None:
        return existing
    # Enforced de-dup: before minting, resolve the incoming name to a match key (id) via
    # EITHER label — the verbose lab wording or the shorthand alias — normalized. So both
    # names tie back to the same id instead of creating a duplicate. The exact-label fast
    # path above is checked first, so every existing exact caller (SEED names, internal
    # identity) is byte-identical; this only catches what would otherwise have minted a
    # near-duplicate.
    ingest = resolve_ingest_id(conn, name)
    if ingest is not None:
        return ingest
    seed_key = name if name in seed_keys else None
    try:
        cur = conn.execute(
            "INSERT INTO metrics (name, seed_key) VALUES (?, ?)", (name, seed_key)
        )
        return cur.lastrowid
    except sqlite3.IntegrityError:
        rid = resolve_metric_id(conn, name)
        if rid is None:
            raise
        return rid


def add_observation(
    conn: sqlite3.Connection,
    metric: str,
    value: float | None,
    unit: str,
    observed_on: str,           # ISO date 'YYYY-MM-DD'
    ref_low: float | None = None,
    ref_high: float | None = None,
    result_type: str = "numeric",   # 'numeric' | 'qualitative' | 'censored'
    value_text: str | None = None,  # qualitative result text
    operator: str | None = None,    # censored comparator: '<' '>' '<=' '>='
    normal_text: str | None = None, # expected-normal text for qualitative results
    ref_low_operator: str | None = None,   # strict lower bound: '>' (else NULL/'>=' inclusive)
    ref_high_operator: str | None = None,  # strict upper bound: '<' (else NULL/'<=' inclusive)
    loinc: str | None = None,
    source: str = "manual",
    document_id: int | None = None,
    collection_id: int | None = None,   # the timed collection this analyte came from
    seed_keys=(),                   # SEED key names, passed in (registry-agnostic)
) -> int:
    """Insert one measurement. Returns the new row id.

    Handles numeric, qualitative (value None, value_text set), and censored
    (value + operator) results; the DB CHECK constraints enforce the per-type
    shape. Enforces one unit per metric: if the metric already has readings, the
    unit must match its existing one (raises UnitMismatchError otherwise). A
    QUALITATIVE reading being added is EXEMPT — it's inherently unitless, so it
    neither has to match the metric's numeric unit nor blocks a later numeric one
    (see get_metric_unit). This is what lets a metric hold both a dipstick
    'Negative' and a quantitative mg/dL reading of the same test.

    ref_low_operator/ref_high_operator make a reference BOUND strict (a normal range
    that is itself censored, e.g. '<=10'); NULL means inclusive, the common case.
    """
    existing = get_metric_unit(conn, metric)
    if result_type != "qualitative" and existing is not None and existing != unit:
        raise UnitMismatchError(metric, existing, unit)
    # Mint/resolve the registry id and INSERT in ONE transaction: if the INSERT
    # fails (duplicate-date IntegrityError, etc.) the rollback also undoes a fresh
    # mint, so a failed write never leaves a stray registry row — even mid-import-
    # loop (each call is atomic). Same try/rollback pattern as rename_metric.
    # metric_id is WRITTEN here but still UNREAD until sub-phase 3b (transparent).
    try:
        metric_id = get_or_create_metric(conn, metric, seed_keys)
        cur = conn.execute(
            """INSERT INTO observations
                   (metric_id, value, unit, observed_on, ref_low, ref_high,
                    result_type, value_text, operator, normal_text,
                    ref_low_operator, ref_high_operator, loinc, source, document_id,
                    collection_id)
               VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
            (metric_id, value, unit, observed_on, ref_low, ref_high,
             result_type, value_text, operator, normal_text,
             ref_low_operator, ref_high_operator, loinc, source, document_id,
             collection_id),
        )
        conn.commit()
        return cur.lastrowid
    except Exception:
        conn.rollback()
        raise


def get_series(conn: sqlite3.Connection, metric: str) -> list[dict]:
    """Return all observations for a metric, oldest first, as a list of dicts.

    Includes `id` so callers can target a row for update/delete. analyze_series
    reads its fields by name and ignores the extra key, so the analysis layer is
    unaffected."""
    mid = resolve_metric_id(conn, metric)
    if mid is None:
        return []
    rows = conn.execute(
        """SELECT id, observed_on, value, unit, ref_low, ref_high,
                  result_type, value_text, operator, normal_text,
                  ref_low_operator, ref_high_operator, collection_id
           FROM observations
           WHERE metric_id = ?
           ORDER BY observed_on""",
        (mid,),
    ).fetchall()
    return [dict(r) for r in rows]


def update_observation(
    conn: sqlite3.Connection,
    obs_id: int,
    metric: str,
    value: float,
    unit: str,
    observed_on: str,
    ref_low: float | None = None,
    ref_high: float | None = None,
    operator: str | None = None,
    ref_low_operator: str | None = None,
    ref_high_operator: str | None = None,
    seed_keys=(),                   # SEED key names, passed in (registry-agnostic)
) -> bool:
    """Update one observation by id. Only the user-managed columns are touched;
    loinc/source/document_id provenance is left as-is. Returns True if a row
    matched. May raise sqlite3.IntegrityError on the UNIQUE(metric, observed_on)
    constraint — callers translate that to a 409. Also enforces one unit per
    metric (UnitMismatchError), checked against the metric's *other* readings so
    a sole reading can still have its unit corrected.

    `operator` is written too, so a censored reading's comparator ('<'/'>'/...)
    actually persists on edit (it was silently dropped before). A numeric edit
    passes operator=None, restoring NULL — consistent with the CHECK constraint
    (numeric ⇒ operator NULL, censored ⇒ operator NOT NULL). result_type is
    type-locked on edit, so it never changes here. ref_low_operator/
    ref_high_operator persist a censored reference bound on edit (NULL = inclusive)."""
    existing = get_metric_unit(conn, metric, exclude_id=obs_id)
    if existing is not None and existing != unit:
        raise UnitMismatchError(metric, existing, unit)
    # Resolve metric_id and UPDATE atomically (try/rollback), so a failed edit
    # (e.g. duplicate-date IntegrityError) leaves no stray mint. metric_id is set
    # defensively: the UI locks the metric on edit, but the API contract allows a
    # name change, so resolving keeps metric_id correct if one ever happens. Still
    # UNREAD until 3b (transparent).
    try:
        metric_id = get_or_create_metric(conn, metric, seed_keys)
        cur = conn.execute(
            """UPDATE observations
                  SET metric_id = ?, value = ?, unit = ?, observed_on = ?,
                      ref_low = ?, ref_high = ?, operator = ?,
                      ref_low_operator = ?, ref_high_operator = ?
                WHERE id = ?""",
            (metric_id, value, unit, observed_on, ref_low, ref_high, operator,
             ref_low_operator, ref_high_operator, obs_id),
        )
        conn.commit()
        return cur.rowcount > 0
    except Exception:
        conn.rollback()
        raise


def delete_observation(conn: sqlite3.Connection, obs_id: int) -> bool:
    """Delete one observation by id. Returns True if a row was removed."""
    cur = conn.execute("DELETE FROM observations WHERE id = ?", (obs_id,))
    conn.commit()
    return cur.rowcount > 0


def list_metrics(conn: sqlite3.Connection) -> list[str]:
    """Distinct metric names currently stored."""
    rows = conn.execute(
        "SELECT DISTINCT m.name AS metric FROM observations o "
        "JOIN metrics m ON m.id = o.metric_id ORDER BY m.name COLLATE NOCASE"
    ).fetchall()
    return [r["metric"] for r in rows]


def get_joined_series(
    conn: sqlite3.Connection, metrics: list[str], join: str = "same_date"
) -> list[dict]:
    """Same-draw join across several metrics — the reusable primitive every
    cross-metric feature (derived metrics, future correlation) builds on.

    Returns one entry per date where EVERY listed metric has a reading (an INNER
    join on observed_on): ``[{"observed_on": date, "inputs": {metric: row, ...}}]``,
    oldest first. A date missing any input is excluded by construction — that's the
    same-draw gap, no special-casing downstream. UNIQUE(metric, observed_on)
    guarantees at most one row per (metric, date), so indexing by date is safe.

    v1 key is an EXACT observed_on match: labs from one draw share a date. If a
    same-date-different-draw collision ever appears, ``document_id`` is the stronger
    key to switch to — not built now (no such case in the data)."""
    if join != "same_date":
        raise ValueError(f"unknown join mode: {join!r}")
    per_metric = {m: {r["observed_on"]: r for r in get_series(conn, m)} for m in metrics}
    if not per_metric:
        return []
    common = set.intersection(*(set(by_date) for by_date in per_metric.values()))
    return [
        {"observed_on": d, "inputs": {m: per_metric[m][d] for m in metrics}}
        for d in sorted(common)
    ]


def get_derived_reference_ranges(conn: sqlite3.Connection, metric: str) -> dict[str, dict]:
    """Captured reference bands for a DERIVED metric, keyed by date (band-as-data).

    Returns {observed_on: {"ref_low", "ref_high", "unit"}} — the lab-stated reference
    band for the computed metric on each draw where one was captured at import. The
    derived compute path (derived.compute_series) joins these onto the computed rows,
    so a derived metric's band travels with the draw exactly like a stored metric's
    range. A metric with no captured bands returns {} (the series then charts with no
    band, which is honest — no band was reported)."""
    rows = conn.execute(
        "SELECT observed_on, ref_low, ref_high, unit FROM derived_reference_range "
        "WHERE metric = ?",
        (metric,),
    ).fetchall()
    return {r["observed_on"]: {"ref_low": r["ref_low"], "ref_high": r["ref_high"],
                               "unit": r["unit"]} for r in rows}


def set_derived_reference_range(
    conn: sqlite3.Connection, metric: str, observed_on: str,
    ref_low: float | None, ref_high: float | None, unit: str = "",
) -> None:
    """Capture (UPSERT) the reference band a lab reported for a DERIVED metric on one
    date. Stores ONLY the range — never the value (the value is computed on read, so
    storing it would fabricate a duplicate). Re-importing a date with a new band from
    the lab overwrites it, which is the self-update mechanism: the band always reflects
    the most recent report. Does not commit (the caller batches)."""
    conn.execute(
        "INSERT INTO derived_reference_range (metric, observed_on, ref_low, ref_high, unit) "
        "VALUES (?, ?, ?, ?, ?) "
        "ON CONFLICT(metric, observed_on) DO UPDATE SET "
        "ref_low = excluded.ref_low, ref_high = excluded.ref_high, "
        "unit = excluded.unit, updated_at = datetime('now')",
        (metric, observed_on, ref_low, ref_high, unit),
    )


def get_metric_alias(conn: sqlite3.Connection, name: str) -> str | None:
    """A metric's current DISPLAY alias, or None when it has none.

    None ALSO means "no such metric" — the two cases are deliberately not distinguished,
    because every caller so far treats them the same (nothing to overwrite either way). A
    caller that must tell them apart should ask `resolve_metric_id` first.

    Exists so the alias SEEDER doesn't have to reach into the metrics table itself: it was
    the only module outside db.py running its own SQL, which is the boundary this layer is
    for."""
    row = conn.execute("SELECT alias FROM metrics WHERE name = ?", (name,)).fetchone()
    return row["alias"] if row else None


def set_metric_alias(conn: sqlite3.Connection, name: str, alias: str | None) -> bool:
    """Set (or clear) a metric's friendly DISPLAY name. `name` is the canonical name;
    `alias` is the shown label, or None/'' to clear it (falls back to the canonical
    name). Returns True if the metric existed and was updated, False if unknown.

    The verbose `name` label is NEVER touched here — this is a pure display change. Both
    labels keep resolving to the same metric_id (the match key), so setting a shorthand
    can't cost the metric its lab-wording label and fragment a future import.
    Refuses (AliasConflictError) an alias that, NORMALIZED, collides with another
    metric's canonical name or another metric's alias — so a display name still resolves
    to at most one metric on ingest. Clearing (None/'') is always allowed. Commits."""
    mid = resolve_metric_id(conn, name)
    if mid is None:
        return False
    cleaned = (alias or "").strip()
    if not cleaned:
        conn.execute("UPDATE metrics SET alias = NULL WHERE id = ?", (mid,))
        conn.commit()
        return True
    target = _normalize(cleaned)
    # Allow setting the alias equal to the metric's OWN canonical name (a no-op-ish
    # relabel); only OTHER metrics' names/aliases are conflicts.
    for r in conn.execute("SELECT id, name, alias FROM metrics WHERE id <> ?", (mid,)):
        if _normalize(r["name"]) == target:
            raise AliasConflictError(cleaned, r["name"])
        if r["alias"] and _normalize(r["alias"]) == target:
            raise AliasConflictError(cleaned, r["alias"])
    conn.execute("UPDATE metrics SET alias = ? WHERE id = ?", (cleaned, mid))
    conn.commit()
    return True


def suggest_metrics(
    conn: sqlite3.Connection, name: str, limit: int = 5, min_score: float = 0.6
) -> list[dict]:
    """Fuzzy 'did you mean' candidates for an INCOMING name — existing metrics whose
    canonical name OR alias is SIMILAR (but not an exact ingest match) to `name`. Powers
    the import/add de-dup nudge: it flags 'this looks like an existing metric' so the
    same analyte under different wording isn't silently duplicated. Suggestions only —
    never auto-applied; the user chooses. Scored by difflib SequenceMatcher over
    normalized strings (a metric's score is the better of its name/alias match). Returns
    [{"metric", "alias", "score"}] over min_score, best first, capped at `limit`. An
    EXACT ingest match is excluded (that path attaches directly, no nudge needed)."""
    target = _normalize(name)
    if not target:
        return []
    exact = resolve_ingest_id(conn, name)
    out = []
    for r in conn.execute("SELECT id, name, alias FROM metrics"):
        if r["id"] == exact:
            continue
        score = difflib.SequenceMatcher(None, target, _normalize(r["name"])).ratio()
        if r["alias"]:
            score = max(score, difflib.SequenceMatcher(
                None, target, _normalize(r["alias"])).ratio())
        if score >= min_score:
            out.append({"metric": r["name"], "alias": r["alias"], "score": round(score, 3)})
    out.sort(key=lambda d: d["score"], reverse=True)
    return out[:limit]


def list_registry_labels(conn: sqlite3.Connection) -> list[dict]:
    """Every stored metric's (name, alias) pair — the display-label space of stored
    metrics. Used by the API to collision-check a proposed DERIVED alias against stored
    metrics without the API running SQL itself."""
    return [dict(r) for r in conn.execute("SELECT name, alias FROM metrics")]


def normalize_label(s: str) -> str:
    """Public alias of _normalize for callers (e.g. the API's cross-label collision check)
    that must fold a display label the SAME way ingest matching does."""
    return _normalize(s)


def get_derived_aliases(conn: sqlite3.Connection) -> dict[str, str]:
    """User DISPLAY-name overrides for derived metrics, {canonical_name: alias}. Only rows
    the user actually set; a derived metric with no override isn't present (the caller
    falls back to the spec's curated display_name, then the verbose name). Registry-agnostic
    — db.py doesn't know which names are derived; the API layer validates that."""
    rows = conn.execute("SELECT metric, alias FROM derived_alias").fetchall()
    return {r["metric"]: r["alias"] for r in rows}


def set_derived_alias(conn: sqlite3.Connection, metric: str, alias: str | None) -> None:
    """Set (or clear) a user's display-name override for a DERIVED metric. `alias` None/''
    clears it (row deleted ⇒ falls back to the spec's curated default, then the verbose
    name). A derived alias is display-ONLY — it's never an ingest match key — so there's no
    de-dup role here; the API layer does the cross-label collision check before calling.
    Commits."""
    cleaned = (alias or "").strip()
    if not cleaned:
        conn.execute("DELETE FROM derived_alias WHERE metric = ?", (metric,))
    else:
        conn.execute(
            "INSERT INTO derived_alias (metric, alias) VALUES (?, ?) "
            "ON CONFLICT(metric) DO UPDATE SET alias = excluded.alias, "
            "updated_at = datetime('now')",
            (metric, cleaned),
        )
    conn.commit()


# --- Timed collections (24-hour urine, etc.) ----------------------------------
# A collection is the provenance a set of analytes share (like `documents`). Volume/
# duration/dates are stored ONCE here; each analyte is a normal observations row keyed by
# collection_id. Pure persistence — knows nothing about analysis (the metadata is context,
# never a detector input).

_COLLECTION_COLS = ("id", "kind", "completed_on", "started_on", "duration_hours",
                    "volume_ml", "notes", "created_at")


def add_collection(
    conn: sqlite3.Connection, completed_on: str, kind: str = "24h_urine",
    started_on: str | None = None, duration_hours: float | None = None,
    volume_ml: float | None = None, notes: str | None = None,
) -> int:
    """Create a timed-collection record and return its id. `completed_on` (the collection's
    end date) is required — it's the date the analytes' `observed_on` should use. Everything
    else is optional context. Commits."""
    cur = conn.execute(
        "INSERT INTO collections (kind, completed_on, started_on, duration_hours, "
        "volume_ml, notes) VALUES (?, ?, ?, ?, ?, ?)",
        (kind, completed_on, started_on, duration_hours, volume_ml, notes),
    )
    conn.commit()
    return cur.lastrowid


def get_collection(conn: sqlite3.Connection, collection_id: int) -> dict | None:
    """One collection by id, or None."""
    row = conn.execute(
        f"SELECT {', '.join(_COLLECTION_COLS)} FROM collections WHERE id = ?",
        (collection_id,),
    ).fetchone()
    return dict(row) if row else None


def list_collections(conn: sqlite3.Connection) -> list[dict]:
    """All collections, most-recently-completed first. Each carries an `n_readings` count
    (how many observations reference it) so the UI can show fullness and gate delete."""
    rows = conn.execute(
        f"""SELECT {', '.join('c.' + c for c in _COLLECTION_COLS)},
                   (SELECT COUNT(*) FROM observations o WHERE o.collection_id = c.id)
                       AS n_readings
              FROM collections c
             ORDER BY c.completed_on DESC, c.id DESC"""
    ).fetchall()
    return [dict(r) for r in rows]


def list_collection_readings(conn: sqlite3.Connection, collection_id: int) -> list[dict]:
    """The analytes belonging to one collection, alphabetical by metric.

    Read-only, and deliberately the SAME row shape a series row has (value/unit/
    result_type/value_text/operator/ref bounds) so the client can format a collection's
    analyte with the formatter it already uses for a reading — no second display path.
    The collection's own metadata is NOT joined in: volume/duration/dates are stored once
    on the collection and the caller already has them."""
    rows = conn.execute(
        """SELECT o.id, m.name AS metric, m.alias,
                  o.value, o.unit, o.observed_on, o.result_type, o.value_text,
                  o.operator, o.ref_low, o.ref_high, o.normal_text,
                  o.ref_low_operator, o.ref_high_operator
             FROM observations o
             JOIN metrics m ON m.id = o.metric_id
            WHERE o.collection_id = ?
            ORDER BY COALESCE(m.alias, m.name) COLLATE NOCASE""",
        (collection_id,),
    ).fetchall()
    return [dict(r) for r in rows]


def update_collection(conn: sqlite3.Connection, collection_id: int, **fields) -> bool:
    """Update a collection's editable fields (kind/completed_on/started_on/duration_hours/
    volume_ml/notes). Returns True if a row matched. Unknown keys are ignored. Commits."""
    editable = ("kind", "completed_on", "started_on", "duration_hours", "volume_ml", "notes")
    sets = {k: v for k, v in fields.items() if k in editable}
    if not sets:
        return get_collection(conn, collection_id) is not None
    cols = ", ".join(f"{k} = ?" for k in sets)
    cur = conn.execute(
        f"UPDATE collections SET {cols} WHERE id = ?",
        (*sets.values(), collection_id),
    )
    conn.commit()
    return cur.rowcount > 0


def delete_collection(conn: sqlite3.Connection, collection_id: int) -> bool:
    """Delete a collection. REFUSES (CollectionInUseError) if any observation still points
    at it — the caller must remove/reassign those readings first (the 'refuse delete of a
    non-empty collection' decision). Returns True if a row was deleted, False if unknown."""
    n = conn.execute(
        "SELECT COUNT(*) FROM observations WHERE collection_id = ?", (collection_id,)
    ).fetchone()[0]
    if n:
        raise CollectionInUseError(collection_id, n)
    cur = conn.execute("DELETE FROM collections WHERE id = ?", (collection_id,))
    conn.commit()
    return cur.rowcount > 0


def rename_metric(conn: sqlite3.Connection, old: str, new: str) -> int:
    """Relabel a metric across every table that stores its name, atomically.

    Updates all `observations` rows and carries the metric's `metric_settings`
    row (personal-baseline mode/note) and its `metric_config` rows (detector
    thresholds/RCV) along, so the rename is invisible to the rest of the app.
    Returns the number of observation rows moved; 0 means `old` had no readings
    (caller maps that to a 404).

    Refuses to rename onto an existing metric (raises MetricExistsError) — that
    would merge two distinct series, which the charter treats as irreversible
    data-mixing. The one-unit-per-metric invariant is therefore preserved: a
    rename only ever moves a whole series to a fresh name, never blends units.

    All writes share one transaction so a failure can't leave the name half-
    changed. `metric_settings`/`metric_config` use OR REPLACE to absorb any stale
    orphan rows under `new` (settings/config without observations); the renamed
    metric's own rows win.
    """
    if new in list_metrics(conn):
        raise MetricExistsError(new)
    # Registry-aware collision check: the observations-based guard above misses an
    # ORPHAN registry row already named `new` (a metrics row with no observations).
    # Renaming onto it in-place would hit metrics.name UNIQUE, so refuse first.
    # old_id is captured here (before any rename) and reused for the registry UPDATE.
    old_id = resolve_metric_id(conn, old)
    new_id = resolve_metric_id(conn, new)
    if new_id is not None and new_id != old_id:
        raise MetricExistsError(new)
    try:
        # observations no longer carries a `metric` column ((A)) — they're keyed by
        # the immutable metric_id, which a rename does NOT change. So a rename moves
        # zero observation rows; `moved` is the metric's observation COUNT (by id),
        # preserving the moved > 0 gate and the moved == 0 -> 404 path exactly. The
        # actual relabel is the registry UPDATE below.
        moved = conn.execute(
            "SELECT COUNT(*) FROM observations WHERE metric_id = ?", (old_id,)
        ).fetchone()[0]
        if moved > 0:
            conn.execute(
                "UPDATE OR REPLACE metric_settings SET metric = ? WHERE metric = ?",
                (new, old),
            )
            # Carry the metric's detector config (thresholds/RCV) forward too, so a
            # rename never silently drops it. Same transaction as the rows above.
            conn.execute(
                "UPDATE OR REPLACE metric_config SET metric = ? WHERE metric = ?",
                (new, old),
            )
            # Rename the registry row IN PLACE (same id, seed_key preserved), so a
            # seeded metric keeps tracking its SEED config under the new name and no
            # orphan row is left behind. Gated on moved > 0 alongside the carries
            # above: a zero-observation source changes NOTHING (clean 404 at the
            # route), never a partial registry rename. Guarded for a never-registered
            # name (old_id None) as defensive belt-and-suspenders.
            if old_id is not None:
                conn.execute("UPDATE metrics SET name = ? WHERE id = ?", (new, old_id))
        conn.commit()
    except Exception:
        conn.rollback()
        raise
    return moved


def set_metric_unit(conn: sqlite3.Connection, metric: str, unit: str) -> int:
    """RELABEL a metric's unit across all its numeric/censored readings — a pure
    LABEL change, NOT a value conversion. Values are stored as entered; changing the
    unit string never touches them. This is for fixing casing ('mg/dl' -> 'mg/dL') or
    unifying equivalent units ('EU/dL' -> 'mg/dL', which for urobilinogen are 1:1); a
    genuine unit CONVERSION (e.g. mg/dL -> mg/L) means editing the values too, which
    this does NOT do.

    QUALITATIVE readings are left untouched — they're inherently unitless (unit '';
    see get_metric_unit), so a unit relabel doesn't apply to them. Returns the number
    of rows relabeled; 0 means the metric has no non-qualitative readings to relabel
    (caller maps that to a 404). Commits.
    """
    mid = resolve_metric_id(conn, metric)
    if mid is None:
        return 0
    cur = conn.execute(
        "UPDATE observations SET unit = ? WHERE metric_id = ?"
        " AND IFNULL(result_type,'numeric') <> 'qualitative'",
        (unit, mid),
    )
    conn.commit()
    return cur.rowcount


# --- Settings (key/value) -----------------------------------------------------
# Pure persistence: get/set/list raw string values. This layer knows nothing
# about what a key means — defaults, types, labels and bounds live in the
# settings.py registry, keeping db.py ignorant of analysis (same separation as
# the rest of this module).

def get_setting(conn: sqlite3.Connection, key: str) -> str | None:
    """The stored raw value for `key`, or None if it isn't set (caller falls back
    to the code-constant default)."""
    row = conn.execute("SELECT value FROM settings WHERE key = ?", (key,)).fetchone()
    return row["value"] if row else None


def set_setting(conn: sqlite3.Connection, key: str, value: str) -> None:
    """Upsert one setting's raw string value, stamping updated_at."""
    conn.execute(
        """INSERT INTO settings (key, value) VALUES (?, ?)
           ON CONFLICT(key) DO UPDATE SET value = excluded.value,
                                          updated_at = datetime('now')""",
        (key, value),
    )
    conn.commit()


def get_all_settings(conn: sqlite3.Connection) -> dict[str, str]:
    """Every stored setting as a {key: raw_value} map."""
    rows = conn.execute("SELECT key, value FROM settings").fetchall()
    return {r["key"]: r["value"] for r in rows}


# --- Per-metric detector config (metric_config) -------------------------------
# Pure persistence of the (metric, key) -> raw TEXT value rows. The MEANING of a
# key (its type/cast, its default) lives in the metric_config.py registry, not
# here — db.py stays ignorant of analysis, exactly like the key/value settings
# above. A metric with no rows simply has no config.

def get_metric_config(conn: sqlite3.Connection, metric: str) -> dict[str, str]:
    """Raw {key: value} detector-config rows for one metric. Empty if none."""
    mid = resolve_metric_id(conn, metric)
    if mid is None:
        return {}
    rows = conn.execute(
        "SELECT key, value FROM metric_config WHERE metric_id = ?", (mid,)
    ).fetchall()
    return {r["key"]: r["value"] for r in rows}


def list_all_metric_config(conn: sqlite3.Connection) -> dict[str, dict[str, str]]:
    """All config rows grouped as {metric: {key: value}}. Lets a caller resolve
    every metric's config in one pass (the timeline build does this)."""
    out: dict[str, dict[str, str]] = {}
    for r in conn.execute("SELECT metric, key, value FROM metric_config").fetchall():
        out.setdefault(r["metric"], {})[r["key"]] = r["value"]
    return out


def link_seed_keys(conn: sqlite3.Connection, seed_keys) -> None:
    """Phase 1 (additive): set metrics.seed_key = name for every registry row whose
    name matches a SEED entry, so a later phase can re-apply SEED config by this
    IMMUTABLE key (a rename won't change seed_key, only the display name). Pure SQL
    and registry-agnostic — the caller passes the SEED key names (db.py stays ignorant
    of the metric_config registry). UPDATE-only (the backfill in init_db creates the
    rows); a metric not in SEED keeps seed_key NULL. Idempotent: re-running sets the
    same value. Writes only the new `metrics` table — no existing read/write affected."""
    keys = list(seed_keys)
    if not keys:
        return
    placeholders = ",".join("?" for _ in keys)
    conn.execute(
        f"UPDATE metrics SET seed_key = name WHERE name IN ({placeholders})", keys
    )
    conn.commit()


def set_metric_config(
    conn: sqlite3.Connection, metric: str, key: str, value: str, seed_keys=()
) -> None:
    """Upsert one (metric, key) config value, stamping updated_at. Seeding calls
    this for every SEED entry on every startup, so an existing row IS overwritten
    (SEED is the source of truth, this table a runtime cache); ready for a future
    edit UI. Mints/resolves the registry id and writes metric_id in the SAME
    transaction (mirroring add_observation) so the metric_id-keyed read sees the
    write immediately, and DO UPDATE re-stamps metric_id to self-heal a row left
    NULL by an earlier write. seed_keys (the SEED names) sets a minted metric's
    seed_key — passed by the caller, since db.py can't import metric_config."""
    try:
        metric_id = get_or_create_metric(conn, metric, seed_keys)
        conn.execute(
            """INSERT INTO metric_config (metric, key, value, metric_id)
                   VALUES (?, ?, ?, ?)
               ON CONFLICT(metric, key) DO UPDATE SET
                   value      = excluded.value,
                   metric_id  = excluded.metric_id,
                   updated_at = datetime('now')""",
            (metric, key, value, metric_id),
        )
        conn.commit()
    except Exception:
        conn.rollback()
        raise


# --- Per-metric settings ------------------------------------------------------
# Pure persistence, like the key/value settings above. The MEANING (what
# personal-baseline mode does, when to suggest it) lives in analysis.py/api.py;
# this layer just stores and returns the row. A metric with no row falls back to
# the defaults below (mode off, empty note, not dismissed).

_METRIC_SETTINGS_DEFAULT = {
    "personal_baseline_mode": False,
    "note": "",
    "suggestion_dismissed": False,
}


def get_metric_settings(conn: sqlite3.Connection, metric: str) -> dict:
    """This metric's settings, or the defaults if it has no row yet. Booleans are
    returned as Python bools (stored as 0/1)."""
    mid = resolve_metric_id(conn, metric)
    if mid is None:
        return dict(_METRIC_SETTINGS_DEFAULT)
    row = conn.execute(
        """SELECT personal_baseline_mode, note, suggestion_dismissed
             FROM metric_settings WHERE metric_id = ?""",
        (mid,),
    ).fetchone()
    if row is None:
        return dict(_METRIC_SETTINGS_DEFAULT)
    return {
        "personal_baseline_mode": bool(row["personal_baseline_mode"]),
        "note": row["note"],
        "suggestion_dismissed": bool(row["suggestion_dismissed"]),
    }


def set_metric_settings(
    conn: sqlite3.Connection,
    metric: str,
    *,
    personal_baseline_mode: bool,
    note: str,
    suggestion_dismissed: bool,
    seed_keys=(),
) -> None:
    """Upsert this metric's full settings row, stamping updated_at. Callers read
    the current row, apply their change, and write it back (the API does this).
    Mints/resolves the registry id and writes metric_id in the SAME transaction
    (mirroring add_observation) so the metric_id-keyed read sees the write
    immediately, and DO UPDATE re-stamps metric_id to self-heal a row left NULL by
    an earlier write. seed_keys (the SEED names) sets a minted metric's seed_key —
    passed by the caller, since db.py can't import metric_config."""
    try:
        metric_id = get_or_create_metric(conn, metric, seed_keys)
        conn.execute(
            """INSERT INTO metric_settings
                   (metric, metric_id, personal_baseline_mode, note, suggestion_dismissed)
               VALUES (?, ?, ?, ?, ?)
               ON CONFLICT(metric) DO UPDATE SET
                   metric_id              = excluded.metric_id,
                   personal_baseline_mode = excluded.personal_baseline_mode,
                   note                   = excluded.note,
                   suggestion_dismissed   = excluded.suggestion_dismissed,
                   updated_at             = datetime('now')""",
            (metric, metric_id, int(personal_baseline_mode), note,
             int(suggestion_dismissed)),
        )
        conn.commit()
    except Exception:
        conn.rollback()
        raise


def list_metrics_with_units(conn: sqlite3.Connection) -> list[dict]:
    """Each metric paired with its canonical unit and display alias (NULL when unset).
    Lets the entry form auto-fill/lock the unit for an already-known metric and the UI
    show the friendly name. The unit is the most recent NON-QUALITATIVE reading's unit
    (NULL when the metric has only qualitative readings so far) — matching
    get_metric_unit, so the form doesn't lock a qualitative-only metric to '' and can
    still accept a first numeric mg/dL reading (the urine-glucose case). A metric is
    listed when it has ANY reading (qualitative or not).

    `latest_on` is that metric's most recent reading date. The rows stay ordered by NAME
    (the picker is alphabetical), so this is a fact ABOUT each metric rather than an
    ordering — it exists so a caller can pick a meaningful default without fetching every
    series to find out which was measured last."""
    rows = conn.execute(
        """SELECT m.name AS metric, m.alias AS alias, m.metric_group AS metric_group,
                  (SELECT o2.unit FROM observations o2
                    WHERE o2.metric_id = m.id
                      AND IFNULL(o2.result_type,'numeric') <> 'qualitative'
                    ORDER BY o2.observed_on DESC LIMIT 1) AS unit,
                  EXISTS(SELECT 1 FROM observations ox
                          WHERE ox.metric_id = m.id
                            AND ox.collection_id IS NOT NULL) AS in_collection,
                  (SELECT MAX(o3.observed_on) FROM observations o3
                    WHERE o3.metric_id = m.id) AS latest_on
             FROM metrics m
            WHERE EXISTS(SELECT 1 FROM observations o WHERE o.metric_id = m.id)
            ORDER BY m.name COLLATE NOCASE"""
    ).fetchall()
    return [dict(r) for r in rows]


def set_metric_group(conn: sqlite3.Connection, name: str, group: str | None) -> bool:
    """Set (or clear) a metric's GROUP label — a purely presentational cluster the picker
    renders as an <optgroup> (e.g. an arterial blood-gas panel). `name` is the canonical
    name; `group` is the label, or None/'' to clear it (metric returns to the ungrouped
    top level). Returns True if the metric existed and was updated, False if unknown. Like
    the alias, this is display-only — it touches no identity/match key and no reading."""
    mid = resolve_metric_id(conn, name)
    if mid is None:
        return False
    cleaned = (group or "").strip() or None
    conn.execute("UPDATE metrics SET metric_group = ? WHERE id = ?", (cleaned, mid))
    conn.commit()
    return True


def add_export_result(conn: sqlite3.Connection, scope: str, metrics: list[str],
                      output: str, provider: str | None = None,
                      model: str | None = None, audit_id: str | None = None) -> int:
    """Save one confirmed export's model response locally (Settings → External export shows
    it attached to its send). `metrics` is stored as a JSON array. `audit_id` is the
    gateway audit entry this answers — the join between what LEFT and what came BACK.
    Commits."""
    import json
    cur = conn.execute(
        "INSERT INTO export_results (scope, metrics, provider, model, output, audit_id) "
        "VALUES (?, ?, ?, ?, ?, ?)",
        (scope, json.dumps(metrics), provider, model, output, audit_id),
    )
    conn.commit()
    return cur.lastrowid


def list_export_results(conn: sqlite3.Connection) -> list[dict]:
    """Saved export results, newest first; `metrics` decoded back to a list."""
    import json
    rows = conn.execute(
        "SELECT id, created_at, scope, metrics, provider, model, output, audit_id "
        "FROM export_results ORDER BY created_at DESC, id DESC"
    ).fetchall()
    return [{**dict(r), "metrics": json.loads(r["metrics"])} for r in rows]


def metrics_in_collections_of(conn: sqlite3.Connection, metric: str) -> list[str]:
    """The 'panel' for a collection-linked metric: every metric name that shares a timed
    collection with `metric` (INCLUDING it), sorted. EMPTY if the metric doesn't exist OR
    has no collection-linked readings (nothing shares a collection with it) — so the UI
    shows an 'export this panel' action only when the panel actually has members. Powers
    'export this panel'."""
    mid = resolve_metric_id(conn, metric)
    if mid is None:
        return []
    rows = conn.execute(
        """SELECT DISTINCT m.name FROM observations o JOIN metrics m ON m.id = o.metric_id
            WHERE o.collection_id IN (
                SELECT DISTINCT collection_id FROM observations
                 WHERE metric_id = ? AND collection_id IS NOT NULL)
            ORDER BY m.name COLLATE NOCASE""",
        (mid,),
    ).fetchall()
    return [r["name"] for r in rows]


def list_observed_metrics(conn: sqlite3.Connection) -> list[str]:
    """Metric names that have at least one observation of ANY result_type
    (numeric, censored, or qualitative), sorted: a metric appears here iff the user
    has recorded any reading for it. Used by the metrics-coverage roster to list
    every tracked metric regardless of whether its readings are numeric."""
    rows = conn.execute(
        "SELECT DISTINCT m.name AS metric FROM observations o "
        "JOIN metrics m ON m.id = o.metric_id ORDER BY m.name COLLATE NOCASE"
    ).fetchall()
    return [r["metric"] for r in rows]


# ----------------------------------------------------------------------------- conditions

def list_conditions(conn: sqlite3.Connection) -> list[dict]:
    """All conditions, most recently added first. Pure storage read — knows nothing
    about analysis; conditions have a status, not a value."""
    rows = conn.execute(
        """SELECT id, name, icd10, onset_on, status, resolved_on, notes, created_at
             FROM conditions ORDER BY id DESC"""
    ).fetchall()
    return [dict(r) for r in rows]


def add_condition(
    conn: sqlite3.Connection,
    name: str,
    *,
    icd10: str | None = None,
    onset_on: str | None = None,    # ISO date 'YYYY-MM-DD'
    status: str = "active",         # active | resolved | monitoring
    resolved_on: str | None = None, # ISO date; only meaningful when status='resolved'
    notes: str | None = None,
) -> int:
    """Insert one condition. icd10 is free text. resolved_on is the resolution
    date (the API enforces it's set iff status='resolved'). Returns the new id."""
    cur = conn.execute(
        """INSERT INTO conditions (name, icd10, onset_on, status, resolved_on, notes)
           VALUES (?, ?, ?, ?, ?, ?)""",
        (name, icd10, onset_on, status, resolved_on, notes),
    )
    conn.commit()
    return cur.lastrowid


def update_condition(
    conn: sqlite3.Connection,
    condition_id: int,
    *,
    name: str,
    icd10: str | None = None,
    onset_on: str | None = None,
    status: str = "active",
    resolved_on: str | None = None,
    notes: str | None = None,
) -> bool:
    """Full-replace update of one condition (all fields supplied by the edit form).
    Returns True if a row was updated, False if the id didn't exist (→ 404)."""
    cur = conn.execute(
        """UPDATE conditions
              SET name = ?, icd10 = ?, onset_on = ?, status = ?,
                  resolved_on = ?, notes = ?
            WHERE id = ?""",
        (name, icd10, onset_on, status, resolved_on, notes, condition_id),
    )
    conn.commit()
    return cur.rowcount > 0


def delete_condition(conn: sqlite3.Connection, condition_id: int) -> bool:
    """Delete a condition by id. Returns True if a row was removed, False if the
    id didn't exist (so the API can map a miss to 404)."""
    cur = conn.execute("DELETE FROM conditions WHERE id = ?", (condition_id,))
    conn.commit()
    return cur.rowcount > 0


# --------------------------------------------------------------------------- immunizations

def list_immunizations(conn: sqlite3.Connection) -> list[dict]:
    """All immunizations, newest first, with UNDATED records last.

    The ordering matters: an undated childhood record sorts to the bottom rather than the
    top, where SQLite's NULL-first default would otherwise put it. Pure storage read — an
    immunization has a date and a name, never a value, and nothing here is analysed."""
    rows = conn.execute(
        """SELECT id, vaccine, administered_on, dose_label, amount, site, lot, notes,
                  created_at
             FROM immunizations
            ORDER BY administered_on IS NULL, administered_on DESC, id DESC"""
    ).fetchall()
    return [dict(r) for r in rows]


def add_immunization(
    conn: sqlite3.Connection,
    vaccine: str,
    *,
    administered_on: str | None = None,   # ISO 'YYYY-MM-DD'; None = date unknown
    dose_label: str | None = None,        # WHICH dose: 'Dose 1', 'Booster'
    amount: str | None = None,            # HOW MUCH: '0.5 mL' — a volume, with its unit
    site: str | None = None,
    lot: str | None = None,
    notes: str | None = None,
) -> int:
    """Insert one immunization and return its id. Every field but the vaccine name is
    optional — a record recalled from a paper card may carry nothing else. Commits."""
    cur = conn.execute(
        """INSERT INTO immunizations (vaccine, administered_on, dose_label, amount,
                                     site, lot, notes)
           VALUES (?, ?, ?, ?, ?, ?, ?)""",
        (vaccine, administered_on, dose_label, amount, site, lot, notes),
    )
    conn.commit()
    return cur.lastrowid


def update_immunization(
    conn: sqlite3.Connection,
    immunization_id: int,
    *,
    vaccine: str,
    administered_on: str | None = None,
    dose_label: str | None = None,
    amount: str | None = None,
    site: str | None = None,
    lot: str | None = None,
    notes: str | None = None,
) -> bool:
    """Full-replace update (all fields come from the edit form, like conditions).
    Returns True if a row matched, False if the id didn't exist (-> 404). Commits."""
    cur = conn.execute(
        """UPDATE immunizations
              SET vaccine = ?, administered_on = ?, dose_label = ?, amount = ?,
                  site = ?, lot = ?, notes = ?
            WHERE id = ?""",
        (vaccine, administered_on, dose_label, amount, site, lot, notes, immunization_id),
    )
    conn.commit()
    return cur.rowcount > 0


def delete_immunization(conn: sqlite3.Connection, immunization_id: int) -> bool:
    """Delete one immunization by id. Returns True if a row was removed. Commits."""
    cur = conn.execute("DELETE FROM immunizations WHERE id = ?", (immunization_id,))
    conn.commit()
    return cur.rowcount > 0


# ----------------------------------------------------------------------------- medications

def list_medications(conn: sqlite3.Connection) -> list[dict]:
    """All medications, most recently added first. `active` is DERIVED here
    (end_date IS NULL) rather than stored, so it can never drift from end_date."""
    rows = conn.execute(
        """SELECT id, name, dose, frequency, start_date, end_date, notes, created_at
             FROM medications ORDER BY id DESC"""
    ).fetchall()
    out = []
    for r in rows:
        d = dict(r)
        d["active"] = d["end_date"] is None
        out.append(d)
    return out


def add_medication(
    conn: sqlite3.Connection,
    name: str,
    *,
    dose: str | None = None,
    frequency: str | None = None,
    start_date: str | None = None,   # ISO date 'YYYY-MM-DD'
    end_date: str | None = None,     # ISO; None => active
    notes: str | None = None,
) -> int:
    """Insert one medication. dose/frequency are free text. Returns the new id."""
    cur = conn.execute(
        """INSERT INTO medications (name, dose, frequency, start_date, end_date, notes)
           VALUES (?, ?, ?, ?, ?, ?)""",
        (name, dose, frequency, start_date, end_date, notes),
    )
    conn.commit()
    return cur.lastrowid


def update_medication(
    conn: sqlite3.Connection,
    medication_id: int,
    *,
    name: str,
    dose: str | None = None,
    frequency: str | None = None,
    start_date: str | None = None,
    end_date: str | None = None,
    notes: str | None = None,
) -> bool:
    """Full-replace update of one medication. A null end_date keeps it active.
    Returns True if a row was updated, False if the id didn't exist (→ 404)."""
    cur = conn.execute(
        """UPDATE medications
              SET name = ?, dose = ?, frequency = ?, start_date = ?,
                  end_date = ?, notes = ?
            WHERE id = ?""",
        (name, dose, frequency, start_date, end_date, notes, medication_id),
    )
    conn.commit()
    return cur.rowcount > 0


def delete_medication(conn: sqlite3.Connection, medication_id: int) -> bool:
    """Delete a medication by id. Returns True if a row was removed, False if the
    id didn't exist (so the API can map a miss to 404)."""
    cur = conn.execute("DELETE FROM medications WHERE id = ?", (medication_id,))
    conn.commit()
    return cur.rowcount > 0


# ----------------------------------------------------------------------------- events

def list_events(conn: sqlite3.Connection) -> list[dict]:
    """All events, most recent first. Point-in-time records (date + notes, not a
    value) shown on the Timeline. Pure storage read — no analysis."""
    rows = conn.execute(
        """SELECT id, event_date, event_type, title, notes, created_at
             FROM events ORDER BY event_date DESC, id DESC"""
    ).fetchall()
    return [dict(r) for r in rows]


def add_event(
    conn: sqlite3.Connection,
    event_date: str,            # ISO 'YYYY-MM-DD'
    event_type: str,            # visit | symptom | life_event | procedure | other
    title: str,
    *,
    notes: str | None = None,
) -> int:
    """Insert one event (the API validates event_type). Returns the new id."""
    cur = conn.execute(
        """INSERT INTO events (event_date, event_type, title, notes)
           VALUES (?, ?, ?, ?)""",
        (event_date, event_type, title, notes),
    )
    conn.commit()
    return cur.lastrowid


def update_event(
    conn: sqlite3.Connection,
    event_id: int,
    *,
    event_date: str,
    event_type: str,
    title: str,
    notes: str | None = None,
) -> bool:
    """Full-replace update of one event. Returns True if a row was updated, False
    if the id didn't exist (→ 404)."""
    cur = conn.execute(
        """UPDATE events
              SET event_date = ?, event_type = ?, title = ?, notes = ?
            WHERE id = ?""",
        (event_date, event_type, title, notes, event_id),
    )
    conn.commit()
    return cur.rowcount > 0


def delete_event(conn: sqlite3.Connection, event_id: int) -> bool:
    """Delete an event by id. Returns True if a row was removed, False if the id
    didn't exist (so the API can map a miss to 404)."""
    cur = conn.execute("DELETE FROM events WHERE id = ?", (event_id,))
    conn.commit()
    return cur.rowcount > 0


# ----------------------------------------------------------------------------- all observations

def list_observations(conn: sqlite3.Connection) -> list[dict]:
    """Every observation across ALL metrics, newest first — for the Timeline's
    date-grouped lab view (which spans metrics, unlike get_series). Pure read; the
    notable-count math is the engine's, computed per metric by the caller."""
    rows = conn.execute(
        """SELECT o.id, m.name AS metric, o.observed_on, o.value, o.unit,
                  o.result_type, o.value_text, o.operator
             FROM observations o
             JOIN metrics m ON m.id = o.metric_id
            ORDER BY o.observed_on DESC, m.name ASC"""
    ).fetchall()
    return [dict(r) for r in rows]


# ----------------------------------------------------------------------------- profile

def get_profile(conn: sqlite3.Connection) -> dict | None:
    """The singleton profile row (sex, date_of_birth), or None if never set.
    The caller treats None as 'all fields unset'."""
    row = conn.execute(
        "SELECT sex, date_of_birth FROM profile WHERE id = 1"
    ).fetchone()
    return dict(row) if row else None


def update_profile(conn: sqlite3.Connection, sex: str | None,
                   date_of_birth: str | None) -> None:
    """UPSERT the singleton profile (id is always 1 — CHECK(id=1) enforces the
    singleton, so this is race-free with no check-then-insert). Stamps updated_at."""
    conn.execute(
        """INSERT INTO profile (id, sex, date_of_birth) VALUES (1, ?, ?)
           ON CONFLICT(id) DO UPDATE SET sex = excluded.sex,
                                         date_of_birth = excluded.date_of_birth,
                                         updated_at = datetime('now')""",
        (sex, date_of_birth),
    )
    conn.commit()


def add_profile_measurement(conn: sqlite3.Connection, field: str, value: float,
                            unit: str, recorded_on: str) -> int:
    """Append one physical measurement (weight/height). Append-only: an update is a
    new row, and the latest by recorded_on is the current value. Returns the new id.
    The DB CHECK constrains `field`; unit is stored as entered (no conversion)."""
    cur = conn.execute(
        """INSERT INTO profile_history (field, value, unit, recorded_on)
           VALUES (?, ?, ?, ?)""",
        (field, value, unit, recorded_on),
    )
    conn.commit()
    return cur.lastrowid


def list_profile_history(conn: sqlite3.Connection, field: str) -> list[dict]:
    """All measurements for one field, newest first (recorded_on, then created_at
    as a same-day tiebreak)."""
    rows = conn.execute(
        """SELECT id, field, value, unit, recorded_on
             FROM profile_history
            WHERE field = ?
            ORDER BY recorded_on DESC, created_at DESC""",
        (field,),
    ).fetchall()
    return [dict(r) for r in rows]


def get_latest_profile_measurement(conn: sqlite3.Connection, field: str) -> dict | None:
    """The current value of a field = its most recent row (served by the
    (field, recorded_on DESC) index), or None if none recorded yet."""
    row = conn.execute(
        """SELECT id, field, value, unit, recorded_on
             FROM profile_history
            WHERE field = ?
            ORDER BY recorded_on DESC, created_at DESC
            LIMIT 1""",
        (field,),
    ).fetchone()
    return dict(row) if row else None


def get_profile_measurement(conn: sqlite3.Connection, measurement_id: int) -> dict | None:
    """One measurement by id, or None. Lets a caller read back what it just wrote."""
    row = conn.execute(
        "SELECT id, field, value, unit, recorded_on FROM profile_history WHERE id = ?",
        (measurement_id,),
    ).fetchone()
    return dict(row) if row else None


def update_profile_measurement(conn: sqlite3.Connection, measurement_id: int,
                               value: float, unit: str, recorded_on: str) -> bool:
    """Correct one measurement in place. Returns True if a row matched.

    `field` is NOT editable: weight and height are different quantities, and moving a row
    between them would silently change what two charts show. Fixing a mistyped field means
    delete + re-add, the same rule a reading's result_type follows. Commits."""
    cur = conn.execute(
        """UPDATE profile_history
              SET value = ?, unit = ?, recorded_on = ?
            WHERE id = ?""",
        (value, unit, recorded_on, measurement_id),
    )
    conn.commit()
    return cur.rowcount > 0


def delete_profile_measurement(conn: sqlite3.Connection, measurement_id: int) -> bool:
    """Delete one measurement by id. Returns True if a row was removed."""
    cur = conn.execute("DELETE FROM profile_history WHERE id = ?", (measurement_id,))
    conn.commit()
    return cur.rowcount > 0
