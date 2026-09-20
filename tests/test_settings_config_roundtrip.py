"""
Round-trip tests for per-metric SETTINGS and CONFIG — they assert the CORRECT
behavior (write-then-read returns what was written), so they FAIL at HEAD
(3b82369) and are the RED half of a fix-it-next TDD step.

The bug they pin: the read paths (`get_metric_settings` / `get_metric_config`)
were switched to key on `metric_id` (Phase 3), but the write paths
(`set_metric_settings` / `set_metric_config`) still INSERT only the `metric`
name column — leaving the new row's `metric_id` NULL. `init_db`'s backfill only
fills that NULL on the NEXT startup, so within a single session a write-then-read
keyed by `metric_id` misses and falls back to the defaults/empty config. The
self-heal property (the written row's `metric_id` ends up non-NULL) therefore
also fails at HEAD.

Built on the conftest fixtures (db_conn / client + temp_db) and builders
(make_orphan_metric). Same synthetic-DB discipline as the rename tests: a route
test builds its subject through db.connect(temp_db) (committed) so the route's
own get_conn connection sees it.
"""

from __future__ import annotations

import json
from urllib.parse import quote

import db
import metric_config
from conftest import make_orphan_metric


# ----------------------------------------------------------------- 1. settings db round-trip

def test_settings_db_roundtrip(db_conn):
    """set_metric_settings then get_metric_settings must return the written values.
    At HEAD: returns defaults (False/""/False) — the written row's metric_id is
    NULL, so the metric_id-keyed read misses it."""
    make_orphan_metric(db_conn, "rt_settings")
    db.set_metric_settings(
        db_conn, "rt_settings",
        personal_baseline_mode=True, note="hello", suggestion_dismissed=True,
    )
    result = db.get_metric_settings(db_conn, "rt_settings")
    assert result["personal_baseline_mode"] is True
    assert result["note"] == "hello"
    assert result["suggestion_dismissed"] is True


# ----------------------------------------------------------------- 2. settings route round-trip

def test_settings_route_roundtrip(client, temp_db):
    """PUT /metric-settings then GET must reflect the written values. At HEAD: the
    PUT's own read-back (_metric_settings_out -> get_metric_settings) returns
    defaults, so the response body doesn't reflect the write."""
    # Build the subject metric on the same synthetic DB the client uses.
    conn = db.connect(temp_db)
    try:
        make_orphan_metric(conn, "rt_settings")
    finally:
        conn.close()

    put = client.put(
        f"/metric-settings/{quote('rt_settings', safe='/')}",
        json={"personal_baseline_mode": True, "note": "hello",
              "suggestion_dismissed": True},
    )
    assert put.status_code == 200
    pbody = put.json()
    assert pbody["personal_baseline_mode"] is True
    assert pbody["note"] == "hello"
    assert pbody["suggestion_dismissed"] is True

    get = client.get(f"/metric-settings/{quote('rt_settings', safe='/')}")
    assert get.status_code == 200
    gbody = get.json()
    assert gbody["personal_baseline_mode"] is True
    assert gbody["note"] == "hello"
    assert gbody["suggestion_dismissed"] is True


# ----------------------------------------------------------------- 3. settings UPSERT + self-heal

def test_settings_upsert_idempotent(db_conn):
    """Two writes for the same metric must UPDATE one row (not duplicate), the read
    must reflect the SECOND write, and the row's metric_id must end up non-NULL
    (the self-heal property). At HEAD: count-stays-1 passes (the UPSERT conflict
    target works), but the metric_id-NOT-NULL assertion fails (writes leave it
    NULL) and the read reflects defaults rather than the second write."""
    make_orphan_metric(db_conn, "rt_upsert")
    db.set_metric_settings(
        db_conn, "rt_upsert",
        personal_baseline_mode=True, note="", suggestion_dismissed=False,
    )
    db.set_metric_settings(
        db_conn, "rt_upsert",
        personal_baseline_mode=False, note="", suggestion_dismissed=False,
    )

    count = db_conn.execute(
        "SELECT COUNT(*) FROM metric_settings WHERE metric = ?", ("rt_upsert",)
    ).fetchone()[0]
    assert count == 1

    result = db.get_metric_settings(db_conn, "rt_upsert")
    assert result["personal_baseline_mode"] is False

    mid = db_conn.execute(
        "SELECT metric_id FROM metric_settings WHERE metric = ?", ("rt_upsert",)
    ).fetchone()[0]
    assert mid is not None


# ----------------------------------------------------------------- 4. config db round-trip

def test_config_db_roundtrip(db_conn):
    """set_metric_config then get_metric_config must surface the written key/value.
    At HEAD: get_metric_config is metric_id-keyed and the written row's metric_id
    is NULL, so it returns {} (empty)."""
    make_orphan_metric(db_conn, "rt_config")
    value = json.dumps([[5.7, "ADA"]])  # a valid `thresholds` raw value
    db.set_metric_config(db_conn, "rt_config", "thresholds", value)

    result = db.get_metric_config(db_conn, "rt_config")
    assert "thresholds" in result
    assert result["thresholds"] == value
