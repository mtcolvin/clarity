"""
Smoke tests — prove the test infrastructure (fixtures + synthetic-DB builders)
works before any rename-specific test is added. No rename behavior asserted here.

All assertions are metric-SCOPED (WHERE name = ... / seed_key = ...), never table
totals: a from-scratch standup seeds all SEED config rows, so totals mislead.
"""

from __future__ import annotations

import db
from conftest import make_seeded_metric_with_obs, make_orphan_metric


def test_db_conn_yields_complete_empty_schema(db_conn):
    """init_db on an empty DB gives the current schema with zero rows."""
    tables = {
        r[0] for r in db_conn.execute(
            "SELECT name FROM sqlite_master WHERE type='table'"
        )
    }
    assert "metrics" in tables
    assert db_conn.execute("SELECT COUNT(*) FROM metrics").fetchone()[0] == 0
    # observations carries the Phase-2 metric_id column => current schema, not legacy.
    obs_cols = {r[1] for r in db_conn.execute("PRAGMA table_info(observations)")}
    assert "metric_id" in obs_cols


def test_make_seeded_metric_mints_registry_with_seed_key(db_conn):
    """A seeded-metric-with-obs fixture mints exactly one registry row carrying a
    non-null seed_key and at least one metric_config row (all metric-scoped)."""
    name = make_seeded_metric_with_obs(db_conn)

    rows = db_conn.execute(
        "SELECT seed_key FROM metrics WHERE name = ?", (name,)
    ).fetchall()
    assert len(rows) == 1
    assert rows[0]["seed_key"] is not None

    cfg_count = db_conn.execute(
        "SELECT COUNT(*) FROM metric_config WHERE metric = ?", (name,)
    ).fetchone()[0]
    assert cfg_count >= 1


def test_make_orphan_metric_registry_present_zero_obs(db_conn):
    """An orphan fixture creates a registry-present metric with zero observations."""
    name = make_orphan_metric(db_conn, "test_orphan_xyz")

    assert db.resolve_metric_id(db_conn, name) is not None
    mid = db.resolve_metric_id(db_conn, name)
    obs = db_conn.execute(
        "SELECT COUNT(*) FROM observations WHERE metric_id = ?", (mid,)
    ).fetchone()[0]
    assert obs == 0
