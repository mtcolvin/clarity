"""
Methodology-note tests — #9 Tier 1 (display-only per-metric prose).

Covers the load-bearing pieces against a synthetic DB: the display-only registry
lane (a methodology_note seeds/stores through the normal path but is EXCLUDED from
the engine kwarg splat — the safety boundary), the dedicated reader
(metric_config.get_methodology_note), and the API surface (the note on
/chart-config, null when absent, and the engine still running clean for a
note-only metric).
"""

from __future__ import annotations

import db
import metric_config as mc

# The three Tier-1 note-only metrics (seeded with a methodology_note, no thresholds).
NOTE_METRICS = [
    "Blood Urea Nitrogen",
    "Creatinine Serum/Plasma",
    "Calcium Serum/Plasma",
]

# Tier-2 metrics carry a methodology_note ALONGSIDE thresholds — the coexistence
# case: the note must still be excluded from the engine splat while thresholds
# remain, and both must surface on /chart-config.
NOTE_WITH_THRESHOLDS_METRICS = [
    "LDL Calculated",
    "Testosterone Total by LC-MS/MS",
    "Glucose Serum/Plasma",
    "Estimated GFR",
]

# Tier-3 note-only metrics — the "context-only" clusters (iron studies, LFT panel,
# standard CRP). Names are the DB's stored names, not the common abbreviations.
TIER3_METRICS = [
    "Iron Serum/Plasma",
    "Total Iron Binding Capacity",
    "Iron % Saturation",
    "Transferrin",
    "Transferrin Percent",
    "Unsat. Iron Binding Capacity",
    "Alkaline Phosphatase Total",
    "Alanine Aminotransferase",
    "Aspartate Aminotransferase",
    "Bilirubin Total",
    "Bilirubin Direct",
    "Bilirubin Indirect",
    "C-Reactive Protein",
]


def _seed(conn):
    """Link seed keys + apply SEED to a fresh synthetic DB (what lifespan does)."""
    db.link_seed_keys(conn, mc.SEED.keys())
    mc.seed_defaults(conn)
    conn.commit()


def test_registry_lane_is_display_only():
    """methodology_note is registered but flagged display_only — the invariant that
    keeps it out of the engine splat."""
    d = mc.BY_KEY["methodology_note"]
    assert d.display_only is True
    # Every OTHER registered key is an engine kwarg (display_only False).
    assert all(not v.display_only for k, v in mc.BY_KEY.items() if k != "methodology_note")


def test_get_methodology_note_reads_each_seed(db_conn):
    _seed(db_conn)
    for m in NOTE_METRICS:
        note = mc.get_methodology_note(db_conn, m)
        assert note is not None and note.strip()
        # Matches the exact seeded prose (guards against silent drift).
        assert note == mc.SEED[m]["methodology_note"]


def test_get_methodology_note_none_when_absent(db_conn):
    """A metric with no note row returns None, not '' or a KeyError — including a
    threshold-bearing metric (Cholesterol) that simply carries no note."""
    _seed(db_conn)
    assert mc.get_methodology_note(db_conn, "Cholesterol") is None
    assert mc.get_methodology_note(db_conn, "Totally Unknown Metric") is None


def test_note_excluded_from_engine_config(db_conn):
    """SAFETY: methodology_note must NEVER appear in get_config / all_configs — those
    are splatted as **kwargs into analyze_series, so a display-only key there would
    crash the engine (and, worse, imply it's a detection input)."""
    _seed(db_conn)
    allc = mc.all_configs(db_conn)
    for m in NOTE_METRICS:
        cfg = mc.get_config(db_conn, m)
        assert "methodology_note" not in cfg
        assert "methodology_note" not in allc.get(m, {})
        # The engine config exposes ONLY non-display-only keys. A note-bearing
        # metric may legitimately also carry an engine key (e.g. rcv_cv from the
        # RCV curation arc — Creatinine/Calcium now do), but NEVER a display-only
        # one. This is the real safety property (was an over-strict `== {}` before
        # rcv_cv was seeded alongside the notes).
        assert all(not mc.BY_KEY[k].display_only for k in cfg)


def test_chart_config_surfaces_note(client):
    """/chart-config carries the note; thresholds stay empty for the note-only metrics."""
    for m in NOTE_METRICS:
        r = client.get(f"/chart-config/{m}")
        assert r.status_code == 200
        body = r.json()
        assert body["methodology_note"] == mc.SEED[m]["methodology_note"]
        assert body["thresholds"] == []


def test_chart_config_note_null_when_absent(client):
    """The field is present-but-null for a metric without a note (additive, safe)."""
    r = client.get("/chart-config/Cholesterol")
    assert r.status_code == 200
    assert r.json()["methodology_note"] is None


def test_engine_runs_clean_for_note_only_metric(client):
    """A note-only metric's /flags endpoint runs the engine without an unexpected
    kwarg — the display-only lane doesn't leak into analyze_series."""
    r = client.get("/flags/Blood Urea Nitrogen")
    assert r.status_code == 200


# --- Tier 2: note COEXISTS with thresholds -------------------------------------

def test_tier2_note_reads_and_matches_seed(db_conn):
    _seed(db_conn)
    for m in NOTE_WITH_THRESHOLDS_METRICS:
        note = mc.get_methodology_note(db_conn, m)
        assert note is not None and note.strip()
        assert note == mc.SEED[m]["methodology_note"]


def test_tier2_note_excluded_but_thresholds_kept(db_conn):
    """SAFETY (coexistence): a metric with BOTH a note and thresholds must expose
    thresholds to the engine but NOT the note — get_config carries thresholds only."""
    _seed(db_conn)
    # Testosterone's AUA 300 line is male-gated (#18 Phase 2), so resolve under a
    # male profile to keep it in this coexistence coverage (the other three metrics
    # are sex-independent and resolve identically regardless).
    db.update_profile(db_conn, sex="male", date_of_birth=None)
    allc = mc.all_configs(db_conn)
    for m in NOTE_WITH_THRESHOLDS_METRICS:
        cfg = mc.get_config(db_conn, m)
        assert "methodology_note" not in cfg
        assert "methodology_note" not in allc.get(m, {})
        # Thresholds survive alongside the excluded note.
        assert cfg.get("thresholds"), f"{m} lost its thresholds"


def test_tier2_chart_config_shows_both(client, temp_db):
    """/chart-config surfaces the note AND keeps the (non-empty) thresholds — a pure
    additive field, nothing else moves."""
    # Testosterone's AUA 300 line is male-gated (#18 Phase 2); set a male profile so it
    # resolves (the other three metrics are sex-independent). Same DB the client reads.
    conn = db.connect(temp_db)
    db.update_profile(conn, sex="male", date_of_birth=None)
    conn.close()
    for m in NOTE_WITH_THRESHOLDS_METRICS:
        body = client.get(f"/chart-config/{m}").json()
        assert body["methodology_note"] == mc.SEED[m]["methodology_note"]
        assert len(body["thresholds"]) >= 1


# --- Tier 3: note-only context-only clusters -----------------------------------

def test_tier3_notes_read_and_engine_excluded(db_conn):
    """Each Tier-3 metric reads its note, carries no threshold config, and never
    leaks the note into the engine splat. Four of them (ALP/ALT/AST/Bilirubin
    Total) also carry rcv_cv from the RCV curation arc — a legit engine key — so
    the check is 'no display-only key leaks + no thresholds', not '== {}'."""
    _seed(db_conn)
    allc = mc.all_configs(db_conn)
    for m in TIER3_METRICS:
        note = mc.get_methodology_note(db_conn, m)
        assert note == mc.SEED[m]["methodology_note"]
        cfg = mc.get_config(db_conn, m)
        assert "methodology_note" not in cfg
        assert "thresholds" not in cfg
        assert all(not mc.BY_KEY[k].display_only for k in cfg)
        assert "methodology_note" not in allc.get(m, {})


def test_tier3_chart_config_surfaces_note(client):
    """Spot the note on /chart-config for the stored-name cases most likely to be
    mistyped (abbreviation vs stored name)."""
    for m in ["Unsat. Iron Binding Capacity", "Alanine Aminotransferase",
              "Aspartate Aminotransferase", "Alkaline Phosphatase Total"]:
        body = client.get(f"/chart-config/{m}").json()
        assert body["methodology_note"] == mc.SEED[m]["methodology_note"]
        assert body["thresholds"] == []


def test_all_notes_seeded_and_count(db_conn):
    """Every SEED entry carrying a methodology_note is applied to the DB (the DB's
    note-count equals SEED's), and the current total is the expected 21 (3 Tier 1 +
    4 Tier 2 + 13 Tier 3 + hs-CRP's #8 note). The introspective equality tracks future
    additions; the literal pin catches an accidental drop in THIS batch."""
    _seed(db_conn)
    seed_with_note = {m for m, cfg in mc.SEED.items() if "methodology_note" in cfg}
    raw = db.list_all_metric_config(db_conn)
    db_with_note = {m for m, kv in raw.items() if "methodology_note" in kv}
    assert db_with_note == seed_with_note
    assert len(seed_with_note) == 21
