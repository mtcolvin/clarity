"""
Coverage for GET /changes (the cross-metric "since your last reading" digest) and
its enumerator db.list_metrics_with_units.

WHY THIS EXISTS — /changes is verified by NEITHER existing harness: the sweep
excludes it as clock-relative (its `moved` membership filters on is_recent vs
date.today()), and there was no pytest test. It consumes list_metrics_with_units,
which an upcoming "A-prep" migrates from `SELECT o.metric ... GROUP BY o.metric`
to deriving the name via JOIN metrics m ON m.id = o.metric_id. These tests pin the
two real A-prep risks: the SET of observation-backed metrics, and the
has-observations semantics (a config-only / zero-observation metric must NOT leak
into the digest).

CLOCK DISCIPLINE — /changes is genuinely clock-relative, so we neutralize that by
constructing observed_on dates at GENEROUS offsets from date.today(): a "recent"
reading at today-3d (well inside the 30-day changes_recent_days default) and a
"stale" reading at today-400d (far outside). The margins mean the test can't
flicker based on which calendar day it runs.

Built on the conftest `client`+`temp_db` (route test) and `db_conn` (db-layer
test) fixtures; subjects are built through public funcs exactly like the
rename-route tests. A second recent-moved metric is included so the alphabetical
enumerator ordering is genuinely assertable (which makes total_metrics == 5).
"""

from __future__ import annotations

import json
from datetime import date, timedelta

import db
import metric_config
from conftest import make_orphan_metric

# Offsets chosen with wide margin vs the changes_recent_days default (30).
_RECENT = 3      # today-3d  -> recent (surfaces)
_STALE = 400     # today-400d -> stale (dropped)
_UNIT = "x"

# Metric names sorted so the alphabetical enumerator order is known:
#   alpha < bravo < single < stable < stale  (the two MOVED+RECENT are alpha,bravo)
_ALPHA = "chg_moved_alpha"      # recent + moved (100 -> 150)
_BRAVO = "chg_moved_bravo"      # recent + moved (200 -> 250)  [2nd moved: ordering]
_SINGLE = "chg_single"          # one reading only -> no_previous
_STABLE = "chg_stable"          # recent but unchanged (100 -> 100)
_STALE_M = "chg_stale_moved"    # moved but stale (latest at today-400d)
_CONFIG_ONLY = "chg_config_only"  # registry+config, ZERO observations -> must NOT appear

# The five observation-backed metrics (config_only is deliberately excluded).
_OBS_BACKED = {_ALPHA, _BRAVO, _SINGLE, _STABLE, _STALE_M}


def _iso(days_ago: int) -> str:
    return (date.today() - timedelta(days=days_ago)).isoformat()


def _add(conn, metric, value, days_ago):
    db.add_observation(conn, metric=metric, value=float(value), unit=_UNIT,
                       observed_on=_iso(days_ago), seed_keys=metric_config.SEED.keys())


def _build_set(conn) -> None:
    """Build the controlled metric set on `conn` (caller commits). Two-reading
    metrics get an earlier reading well before their latest so latest_change has a
    previous to compare against."""
    # moved + recent (two metrics, for ordering)
    _add(conn, _ALPHA, 100, _RECENT + 7); _add(conn, _ALPHA, 150, _RECENT)
    _add(conn, _BRAVO, 200, _RECENT + 7); _add(conn, _BRAVO, 250, _RECENT)
    # single reading only
    _add(conn, _SINGLE, 100, _RECENT)
    # recent but unchanged
    _add(conn, _STABLE, 100, _RECENT + 7); _add(conn, _STABLE, 100, _RECENT)
    # moved but stale (latest far outside the recency window)
    _add(conn, _STALE_M, 100, _STALE + 7); _add(conn, _STALE_M, 150, _STALE)
    # config-only metric: registry row + a config row, but NO observations
    make_orphan_metric(conn, _CONFIG_ONLY)
    db.set_metric_config(conn, _CONFIG_ONLY, "thresholds", json.dumps([[5.7, "ADA"]]),
                         seed_keys=metric_config.SEED.keys())
    conn.commit()


# ------------------------------------------------------------------ Test 1: route

def test_changes_route(client, temp_db):
    conn = db.connect(temp_db)
    try:
        _build_set(conn)
    finally:
        conn.close()

    resp = client.get("/changes")
    assert resp.status_code == 200
    body = resp.json()

    # total_metrics counts observation-backed metrics only -> 5 (config_only excluded).
    # If this were 6, config_only leaked in (the has-observations regression).
    assert body["total_metrics"] == len(_OBS_BACKED) == 5

    moved_names = [c["metric"] for c in body["moved"]]
    # Only the recent+moved metrics surface; stale/stable/single/config_only do not.
    assert _ALPHA in moved_names
    assert _BRAVO in moved_names
    assert _STALE_M not in moved_names
    assert _STABLE not in moved_names
    assert _SINGLE not in moved_names
    assert _CONFIG_ONLY not in moved_names
    assert set(moved_names) == {_ALPHA, _BRAVO}

    # Ordering follows the alphabetical enumerator order (alpha before bravo).
    assert moved_names == [_ALPHA, _BRAVO]

    # Per-field content of the alpha change (synthetic test constants 100 -> 150).
    alpha = next(c for c in body["moved"] if c["metric"] == _ALPHA)
    assert alpha["category"] == "moved"
    assert alpha["status"] == "rose"           # 100 -> 150 is an increase
    assert alpha["observed_on"] == _iso(_RECENT)
    assert alpha["previous"] == 100
    assert alpha["current"] == 150
    assert alpha["delta"] == 50                # current - previous


# ------------------------------------------------------------------ Test 2: db layer

def test_list_metrics_with_units_excludes_config_only(db_conn):
    """The crispest A-prep guard, independent of /changes plumbing: the enumerator
    returns exactly the observation-backed metrics and never a config-only one."""
    _build_set(db_conn)

    names = {row["metric"] for row in db.list_metrics_with_units(db_conn)}
    assert names == _OBS_BACKED
    assert _CONFIG_ONLY not in names
