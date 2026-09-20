"""
db-layer rename-survival tests — the committed form of the scratch
rename_survival_test.py, rebuilt on the conftest synthetic fixtures.

Asserts the CORRECT post-fix state (the six survival properties hold) after a
seeded metric is renamed and a restart is simulated. A committed test asserts
correct behavior; it does not depend on broken code, so the one-time 4/6->6/6
contrast from the scratch probe is intentionally not reproduced here.

All assertions are metric-scoped (WHERE name / seed_key / metric = ...), never
table totals — a from-scratch standup seeds every SEED config row.
"""

from __future__ import annotations

import pytest

import db
import metric_config
from conftest import make_seeded_metric_with_obs

_RENAME_SUFFIX = "__renamed"


@pytest.fixture
def renamed_state(db_conn, schema_root):
    """Build a seeded metric (K) with an observation, rename it to N, then simulate
    a restart (init_db -> link_seed_keys -> seed_defaults) on the same connection.
    Returns the facts the survival assertions need."""
    K = make_seeded_metric_with_obs(db_conn)
    # Resolve K's seed_key from the DB rather than assuming it equals K, so the test
    # stays correct if the builder's seeding changes.
    k_seed_key = db_conn.execute(
        "SELECT seed_key FROM metrics WHERE name = ?", (K,)
    ).fetchone()["seed_key"]
    N = K + _RENAME_SUFFIX

    db.rename_metric(db_conn, K, N)

    db.init_db(db_conn, schema_path=schema_root)
    db.link_seed_keys(db_conn, metric_config.SEED.keys())
    metric_config.seed_defaults(db_conn)

    return {"conn": db_conn, "K": K, "N": N, "seed_key": k_seed_key}


def test_one_registry_row_seedkey_named_N(renamed_state):
    """Exactly one registry row carries K's seed_key, and it is named N (the rename
    happened in place — no orphan row left under the old name)."""
    conn, N, seed_key = renamed_state["conn"], renamed_state["N"], renamed_state["seed_key"]
    rows = conn.execute(
        "SELECT name FROM metrics WHERE seed_key = ?", (seed_key,)
    ).fetchall()
    assert len(rows) == 1
    assert rows[0]["name"] == N


def test_resolve_by_seed_key_returns_N(renamed_state):
    conn, N, seed_key = renamed_state["conn"], renamed_state["N"], renamed_state["seed_key"]
    assert db.resolve_by_seed_key(conn, seed_key) == N


def test_config_under_N_none_under_K(renamed_state):
    conn, K, N = renamed_state["conn"], renamed_state["K"], renamed_state["N"]
    cfg_N = conn.execute(
        "SELECT COUNT(*) FROM metric_config WHERE metric = ?", (N,)
    ).fetchone()[0]
    cfg_K = conn.execute(
        "SELECT COUNT(*) FROM metric_config WHERE metric = ?", (K,)
    ).fetchone()[0]
    assert cfg_N >= 1
    assert cfg_K == 0


def test_observations_under_N(renamed_state):
    conn, N = renamed_state["conn"], renamed_state["N"]
    mid = db.resolve_metric_id(conn, N)
    obs_N = conn.execute(
        "SELECT COUNT(*) FROM observations WHERE metric_id = ?", (mid,)
    ).fetchone()[0]
    assert obs_N >= 1


def test_resolve_metric_id_N_valid(renamed_state):
    conn, N = renamed_state["conn"], renamed_state["N"]
    assert db.resolve_metric_id(conn, N) is not None


def test_zero_registry_rows_named_K(renamed_state):
    conn, K = renamed_state["conn"], renamed_state["K"]
    rows_named_K = conn.execute(
        "SELECT COUNT(*) FROM metrics WHERE name = ?", (K,)
    ).fetchone()[0]
    assert rows_named_K == 0
