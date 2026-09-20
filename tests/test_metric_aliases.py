"""
Display aliases + ingest de-dup.

The MATCH KEY is the metric's id. Each metric carries TWO LABELS that both resolve to it:
a verbose one (the lab's wording) and an optional shorthand ALIAS (the display name).
Setting an alias ADDS a label, it never replaces the verbose one, so the metric keeps the
lab wording a future import resolves by. On ingest (import/add) an incoming name resolves
to an existing id via EITHER label, normalized (case/whitespace) — so a shorthand or a
case variant attaches instead of minting a duplicate. Fuzzy 'did you mean' suggestions
handle near-but-not-exact names (surfaced, never auto-applied).
"""

from __future__ import annotations

import db
import aliases
from conftest import make_orphan_metric


def _add(conn, metric, value, unit, date):
    db.add_observation(conn, metric=metric, value=value, unit=unit, observed_on=date)


# --- ingest de-dup (the enforced core) ----------------------------------------

def test_alias_name_attaches_not_duplicates(db_conn):
    _add(db_conn, "Blood Urea Nitrogen", 15, "mg/dL", "2020-01-01")
    db.set_metric_alias(db_conn, "Blood Urea Nitrogen", "BUN")
    # Adding under the ALIAS attaches to the same metric.
    _add(db_conn, "BUN", 16, "mg/dL", "2020-02-01")
    assert db_conn.execute("SELECT COUNT(*) FROM metrics").fetchone()[0] == 1
    assert len(db.get_series(db_conn, "Blood Urea Nitrogen")) == 2


def test_case_and_whitespace_variant_attaches(db_conn):
    _add(db_conn, "Sodium Serum/Plasma", 140, "mmol/L", "2020-01-01")
    _add(db_conn, "  sodium   serum/plasma ", 141, "mmol/L", "2020-02-01")  # normalized match
    assert db_conn.execute("SELECT COUNT(*) FROM metrics").fetchone()[0] == 1
    assert len(db.get_series(db_conn, "Sodium Serum/Plasma")) == 2


def test_genuinely_new_name_still_creates(db_conn):
    _add(db_conn, "Sodium Serum/Plasma", 140, "mmol/L", "2020-01-01")
    _add(db_conn, "Potassium Serum/Plasma", 4.0, "mmol/L", "2020-01-01")
    assert db_conn.execute("SELECT COUNT(*) FROM metrics").fetchone()[0] == 2


def test_exact_canonical_fast_path_unchanged(db_conn):
    # Two distinct canonical names must never collapse (normalization is conservative).
    _add(db_conn, "Vitamin E (Alpha-tocopherol)", 10, "mg/L", "2020-01-01")
    _add(db_conn, "Vitamin E (Gamma-tocopherol)", 2, "mg/L", "2020-01-01")
    assert db_conn.execute("SELECT COUNT(*) FROM metrics").fetchone()[0] == 2


# --- set_metric_alias ---------------------------------------------------------

def test_set_and_clear_alias(db_conn):
    make_orphan_metric(db_conn, "Aspartate Aminotransferase")
    assert db.set_metric_alias(db_conn, "Aspartate Aminotransferase", "AST") is True
    row = db_conn.execute("SELECT alias FROM metrics WHERE name=?",
                          ("Aspartate Aminotransferase",)).fetchone()
    assert row["alias"] == "AST"
    assert db.set_metric_alias(db_conn, "Aspartate Aminotransferase", "") is True
    row = db_conn.execute("SELECT alias FROM metrics WHERE name=?",
                          ("Aspartate Aminotransferase",)).fetchone()
    assert row["alias"] is None


def test_alias_conflict_with_existing_name_or_alias(db_conn):
    make_orphan_metric(db_conn, "Aspartate Aminotransferase")
    make_orphan_metric(db_conn, "Alanine Aminotransferase")
    db.set_metric_alias(db_conn, "Alanine Aminotransferase", "ALT")
    # Alias collides with another metric's ALIAS.
    try:
        db.set_metric_alias(db_conn, "Aspartate Aminotransferase", "alt")  # normalized
        assert False, "expected AliasConflictError"
    except db.AliasConflictError:
        pass
    # Alias collides with another metric's canonical NAME.
    try:
        db.set_metric_alias(db_conn, "Aspartate Aminotransferase", "Alanine Aminotransferase")
        assert False, "expected AliasConflictError"
    except db.AliasConflictError:
        pass


def test_set_alias_unknown_metric_returns_false(db_conn):
    assert db.set_metric_alias(db_conn, "No Such Metric", "X") is False


# --- suggestions --------------------------------------------------------------

def test_suggest_excludes_exact_and_ranks_similar(db_conn):
    make_orphan_metric(db_conn, "Insulin-like Growth Factor 1")
    db.set_metric_alias(db_conn, "Insulin-like Growth Factor 1", "IGF-1")
    # exact ingest match -> no suggestions (attaches directly)
    assert db.suggest_metrics(db_conn, "IGF-1") == []
    # a near name -> the metric is suggested
    names = [s["metric"] for s in db.suggest_metrics(db_conn, "Insulin Growth Factor 1")]
    assert "Insulin-like Growth Factor 1" in names


# --- seed idempotence / no-clobber -------------------------------------------

def test_seed_applies_defaults_but_never_clobbers_user_alias(db_conn):
    make_orphan_metric(db_conn, "Blood Urea Nitrogen")
    make_orphan_metric(db_conn, "Alanine Aminotransferase")
    db.set_metric_alias(db_conn, "Alanine Aminotransferase", "My ALT")  # user choice
    applied = aliases.seed_aliases(db_conn)
    assert applied >= 1
    a = {r[0]: r[1] for r in db_conn.execute("SELECT name, alias FROM metrics")}
    assert a["Blood Urea Nitrogen"] == "BUN"          # default applied (was null)
    assert a["Alanine Aminotransferase"] == "My ALT"  # user's choice preserved
    # second seed is a no-op (idempotent)
    assert aliases.seed_aliases(db_conn) == 0


def test_get_metric_alias_reads_the_current_label(db_conn):
    """The helper the seeder uses instead of its own SQL. None means 'no alias' — and also
    'no such metric', which is deliberate: both mean there's nothing to overwrite."""
    make_orphan_metric(db_conn, "Blood Urea Nitrogen")
    assert db.get_metric_alias(db_conn, "Blood Urea Nitrogen") is None
    db.set_metric_alias(db_conn, "Blood Urea Nitrogen", "BUN")
    assert db.get_metric_alias(db_conn, "Blood Urea Nitrogen") == "BUN"
    assert db.get_metric_alias(db_conn, "No Such Metric") is None


def test_seed_counts_only_metrics_it_actually_aliased(db_conn):
    """The curated map covers tests this user may never have had. Those are skipped, not
    counted and not an error — the count reflects real writes."""
    make_orphan_metric(db_conn, "Blood Urea Nitrogen")
    assert aliases.seed_aliases(db_conn) == 1        # 1 of ~25 curated entries exists here
    assert db.get_metric_alias(db_conn, "Blood Urea Nitrogen") == "BUN"


def test_only_db_module_runs_sql():
    """db.py is the persistence layer; nothing else reaches into SQLite. aliases.py was the
    last module doing its own SELECT, which is what this cleanup removed — a regression here
    means the boundary leaked again."""
    import pathlib
    root = pathlib.Path(db.__file__).parent
    offenders = []
    for path in root.glob("*.py"):
        if path.name == "db.py":
            continue
        source = path.read_text(encoding="utf-8")
        if ".execute(" in source or ".executescript(" in source:
            offenders.append(path.name)
    assert offenders == [], f"SQL outside db.py: {offenders}"


# --- routes -------------------------------------------------------------------

def test_metrics_route_returns_alias(client, temp_db):
    conn = db.connect(temp_db)
    _add(conn, "Blood Urea Nitrogen", 15, "mg/dL", "2020-01-01")
    db.set_metric_alias(conn, "Blood Urea Nitrogen", "BUN")
    conn.commit(); conn.close()
    rows = client.get("/metrics").json()
    bun = [r for r in rows if r["metric"] == "Blood Urea Nitrogen"][0]
    assert bun["alias"] == "BUN"


def test_resolve_route_exact_and_suggestions(client, temp_db):
    conn = db.connect(temp_db)
    _add(conn, "Insulin-like Growth Factor 1", 150, "ng/mL", "2020-01-01")
    db.set_metric_alias(conn, "Insulin-like Growth Factor 1", "IGF-1")
    conn.commit(); conn.close()
    # exact via alias
    r = client.get("/metrics/resolve", params={"name": "IGF-1"}).json()
    assert r["exact"] and r["exact"]["metric"] == "Insulin-like Growth Factor 1"
    assert r["suggestions"] == []
    # fuzzy near-match
    r2 = client.get("/metrics/resolve", params={"name": "Insulin Growth Factor 1"}).json()
    assert r2["exact"] is None
    assert any(s["metric"] == "Insulin-like Growth Factor 1" for s in r2["suggestions"])


def test_resolve_batch_route_is_positional_and_matches_single(client, temp_db):
    """The import review resolves a whole draft in one trip. Results are POSITIONAL, and
    each must equal what the single-name GET returns (both go through _resolve_one, so the
    two surfaces can't drift)."""
    conn = db.connect(temp_db)
    _add(conn, "Insulin-like Growth Factor 1", 150, "ng/mL", "2020-01-01")
    db.set_metric_alias(conn, "Insulin-like Growth Factor 1", "IGF-1")
    conn.commit(); conn.close()

    names = ["IGF-1", "Insulin Growth Factor 1", "Zzz Totally New Analyte"]
    res = client.post("/metrics/resolve-batch", json={"names": names}).json()["results"]
    assert [r["query"] for r in res] == names          # positional, in row order
    assert res[0]["exact"]["metric"] == "Insulin-like Growth Factor 1"  # alias -> attaches
    assert res[1]["exact"] is None and res[1]["suggestions"]           # fuzzy -> nudge
    assert res[2]["exact"] is None and res[2]["suggestions"] == []     # genuinely new

    # Batch == single, per name (one source of truth).
    for n, batched in zip(names, res):
        single = client.get("/metrics/resolve", params={"name": n}).json()
        assert single == batched


def test_resolve_batch_empty_is_ok(client, temp_db):
    assert client.post("/metrics/resolve-batch", json={"names": []}).json()["results"] == []


# --- derived-metric display aliases (display-only, not an ingest key) ----------

NLR = "NLR (Neutrophil-Lymphocyte Ratio)"


def _seed_nlr(conn):
    _add(conn, "Neutrophils Absolute", 3.0, "10*9/L", "2020-01-01")
    _add(conn, "Lymphocyte Absolute", 2.0, "10*9/L", "2020-01-01")


def test_metrics_route_shows_derived_curated_default(client, temp_db):
    conn = db.connect(temp_db); _seed_nlr(conn); conn.commit(); conn.close()
    rows = client.get("/metrics").json()
    nlr = [r for r in rows if r["metric"] == NLR][0]
    assert nlr["derived"] is True
    assert nlr["alias"] == "NLR"  # the spec's curated default, no override set


def test_display_name_route_overrides_and_clears_a_derived_alias(client, temp_db):
    conn = db.connect(temp_db); _seed_nlr(conn); conn.commit(); conn.close()
    # override the curated default
    r = client.put(f"/metrics/{NLR}/display-name", json={"alias": "My NLR"})
    assert r.status_code == 200
    rows = client.get("/metrics").json()
    assert [x for x in rows if x["metric"] == NLR][0]["alias"] == "My NLR"
    # clear -> falls back to the curated default, not the verbose name
    r2 = client.put(f"/metrics/{NLR}/display-name", json={"alias": ""})
    assert r2.status_code == 200
    rows2 = client.get("/metrics").json()
    assert [x for x in rows2 if x["metric"] == NLR][0]["alias"] == "NLR"


def test_derived_alias_collision_with_stored_is_409(client, temp_db):
    conn = db.connect(temp_db)
    _seed_nlr(conn)
    _add(conn, "Blood Urea Nitrogen", 15, "mg/dL", "2020-01-01")
    db.set_metric_alias(conn, "Blood Urea Nitrogen", "BUN")
    conn.commit(); conn.close()
    # a derived alias colliding with a stored metric's alias (normalized) is refused
    assert client.put(f"/metrics/{NLR}/display-name", json={"alias": "bun"}).status_code == 409
    # colliding with a stored metric's canonical name too
    assert client.put(f"/metrics/{NLR}/display-name",
                      json={"alias": "Blood Urea Nitrogen"}).status_code == 409


def test_derived_alias_is_not_an_ingest_key(db_conn):
    """A derived alias is display-ONLY: adding an observation under it must NOT attach to
    the derived metric (which can't hold observations) — it creates a normal stored metric,
    exactly as a brand-new name would. Proves derived aliases stay out of ingest matching."""
    _seed_nlr(db_conn)
    db.set_derived_alias(db_conn, NLR, "My NLR")
    db_conn.commit()
    before = db_conn.execute("SELECT COUNT(*) FROM metrics").fetchone()[0]
    db.add_observation(db_conn, metric="My NLR", value=2.5, unit="", observed_on="2021-01-01")
    after = db_conn.execute("SELECT COUNT(*) FROM metrics").fetchone()[0]
    assert after == before + 1  # a new stored metric, NOT an attach to the derived NLR


def test_display_name_route_set_conflict_and_404(client, temp_db):
    conn = db.connect(temp_db)
    _add(conn, "Blood Urea Nitrogen", 15, "mg/dL", "2020-01-01")
    _add(conn, "Alanine Aminotransferase", 20, "U/L", "2020-01-01")
    db.set_metric_alias(conn, "Alanine Aminotransferase", "ALT")
    conn.commit(); conn.close()
    # set OK
    ok = client.put("/metrics/Blood Urea Nitrogen/display-name", json={"alias": "BUN"})
    assert ok.status_code == 200 and ok.json()["alias"] == "BUN"
    # conflict with existing alias -> 409
    conflict = client.put("/metrics/Blood Urea Nitrogen/display-name", json={"alias": "ALT"})
    assert conflict.status_code == 409
    # unknown metric -> 404
    missing = client.put("/metrics/No Such Metric/display-name", json={"alias": "X"})
    assert missing.status_code == 404


def test_ingest_dedups_via_alias(client, temp_db):
    """Ingest de-dup lives in db.get_or_create_metric, not in any one caller: a reading
    added under a metric's ALIAS attaches to the existing metric instead of minting a
    duplicate. Pinned through db + the API read path (the PDF-import route that used to
    exercise this is gone; the rule it relied on is not)."""
    conn = db.connect(temp_db)
    _add(conn, "Blood Urea Nitrogen", 15, "mg/dL", "2020-01-01")
    db.set_metric_alias(conn, "Blood Urea Nitrogen", "BUN")
    # Add under the ALIAS -> resolves to the existing metric, no duplicate minted.
    db.add_observation(conn, metric="BUN", value=16.0, unit="mg/dL",
                       observed_on="2020-02-01", result_type="numeric")
    conn.commit(); conn.close()

    rows = client.get("/metrics").json()
    assert len([r for r in rows if r["metric"] in ("BUN", "Blood Urea Nitrogen")]) == 1
    assert len(client.get("/observations/Blood Urea Nitrogen").json()) == 2
