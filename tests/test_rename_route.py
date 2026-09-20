"""
Route-level rename tests — the committed form of the scratch rename_route_test.py,
rebuilt on the conftest `client` fixture (synthetic standup, api.DB_PATH saved/
restored). Exercises PUT /metrics/{metric:path}/rename end-to-end.

Subject-construction path: each test requests both `client` and `temp_db` (the
client fixture depends on temp_db, so both resolve to the SAME synthetic DB). The
client's lifespan builds the schema on standup; the test then builds its subjects
through the public builders on that same path via db.connect(temp_db), so a route
request (its own get_conn connection) sees the committed rows. No real-data copy.

Part 1 asserts the success path + the six survival properties downstream of the
HTTP boundary. Part 2 asserts the four guard mappings (422/400/409/404), each on
its own function-scoped client (so cases can't bleed), including the 404
no-state-change check that caught the partial-state desync — it must pass at the
fixed code. All assertions metric-scoped.
"""

from __future__ import annotations

from urllib.parse import quote

import pytest

import db
import metric_config
from conftest import make_seeded_metric_with_obs, make_orphan_metric

_RENAME_SUFFIX = "__renamed"


def _build_seeded(temp_db):
    """Build a seeded-metric-with-obs in the synthetic DB; return (K, obs_count,
    seed_key)."""
    conn = db.connect(temp_db)
    try:
        K = make_seeded_metric_with_obs(conn)
        k_id = db.resolve_metric_id(conn, K)
        k_obs = conn.execute(
            "SELECT COUNT(*) FROM observations WHERE metric_id = ?", (k_id,)
        ).fetchone()[0]
        k_seed_key = conn.execute(
            "SELECT seed_key FROM metrics WHERE name = ?", (K,)
        ).fetchone()["seed_key"]
        return K, k_obs, k_seed_key
    finally:
        conn.close()


def _build_orphan(temp_db, name):
    conn = db.connect(temp_db)
    try:
        return make_orphan_metric(conn, name)
    finally:
        conn.close()


# ----------------------------------------------------------------------------- Part 1

@pytest.fixture
def routed_success(client, temp_db, schema_root):
    """Build K, rename it through the route, then simulate a db-layer restart.
    Yields the response + a post-restart connection + the facts the asserts need."""
    K, k_obs, k_seed_key = _build_seeded(temp_db)
    N = K + _RENAME_SUFFIX

    resp = client.put(f"/metrics/{quote(K, safe='/')}/rename", json={"new_name": N})

    conn = db.connect(temp_db)
    db.init_db(conn, schema_path=schema_root)
    db.link_seed_keys(conn, metric_config.SEED.keys())
    metric_config.seed_defaults(conn)
    try:
        yield {"resp": resp, "conn": conn, "K": K, "N": N,
               "k_obs": k_obs, "seed_key": k_seed_key}
    finally:
        conn.close()


def test_route_success_response(routed_success):
    resp = routed_success["resp"]
    assert resp.status_code == 200
    body = resp.json()
    assert all(k in body for k in ("old_name", "new_name", "observations_moved"))
    assert body["observations_moved"] == routed_success["k_obs"]


def test_route_survival_one_registry_row_named_N(routed_success):
    conn, N, seed_key = routed_success["conn"], routed_success["N"], routed_success["seed_key"]
    rows = conn.execute("SELECT name FROM metrics WHERE seed_key = ?", (seed_key,)).fetchall()
    assert len(rows) == 1
    assert rows[0]["name"] == N


def test_route_survival_resolve_by_seed_key(routed_success):
    conn, N, seed_key = routed_success["conn"], routed_success["N"], routed_success["seed_key"]
    assert db.resolve_by_seed_key(conn, seed_key) == N


def test_route_survival_config_under_N_none_under_K(routed_success):
    conn, K, N = routed_success["conn"], routed_success["K"], routed_success["N"]
    cfg_N = conn.execute("SELECT COUNT(*) FROM metric_config WHERE metric = ?", (N,)).fetchone()[0]
    cfg_K = conn.execute("SELECT COUNT(*) FROM metric_config WHERE metric = ?", (K,)).fetchone()[0]
    assert cfg_N >= 1
    assert cfg_K == 0


def test_route_survival_observations_under_N(routed_success):
    conn, N = routed_success["conn"], routed_success["N"]
    n_id = db.resolve_metric_id(conn, N)
    assert conn.execute(
        "SELECT COUNT(*) FROM observations WHERE metric_id = ?", (n_id,)
    ).fetchone()[0] >= 1


def test_route_survival_resolve_metric_id_N(routed_success):
    conn, N = routed_success["conn"], routed_success["N"]
    assert db.resolve_metric_id(conn, N) is not None


def test_route_survival_zero_rows_named_K(routed_success):
    conn, K = routed_success["conn"], routed_success["K"]
    assert conn.execute("SELECT COUNT(*) FROM metrics WHERE name = ?", (K,)).fetchone()[0] == 0


# ----------------------------------------------------------------------------- Part 2: guards

def test_guard_422_blank_name(client, temp_db):
    """Whitespace new_name -> stripped empty -> Pydantic validator -> 422."""
    K, _, _ = _build_seeded(temp_db)
    resp = client.put(f"/metrics/{quote(K, safe='/')}/rename", json={"new_name": "   "})
    assert resp.status_code == 422


def test_guard_400_noop(client, temp_db):
    """new == source -> handler pre-check -> 400, with no state change to K."""
    K, _, k_seed_key = _build_seeded(temp_db)
    resp = client.put(f"/metrics/{quote(K, safe='/')}/rename", json={"new_name": K})
    assert resp.status_code == 400
    conn = db.connect(temp_db)
    try:
        named_K = conn.execute("SELECT COUNT(*) FROM metrics WHERE name = ?", (K,)).fetchone()[0]
        sk = conn.execute("SELECT seed_key FROM metrics WHERE name = ?", (K,)).fetchone()
        cfg_K = conn.execute("SELECT COUNT(*) FROM metric_config WHERE metric = ?", (K,)).fetchone()[0]
    finally:
        conn.close()
    assert named_K == 1
    assert sk is not None and sk["seed_key"] == k_seed_key
    assert cfg_K >= 1


def test_guard_409_orphan_collision(client, temp_db):
    """Rename K -> M where M is a registry-present, zero-observation orphan: only the
    registry-aware guard catches it -> 409, with no partial state to K."""
    K, k_obs, _ = _build_seeded(temp_db)
    M = _build_orphan(temp_db, "test_orphan_409")
    assert M != K
    resp = client.put(f"/metrics/{quote(K, safe='/')}/rename", json={"new_name": M})
    assert resp.status_code == 409
    conn = db.connect(temp_db)
    try:
        named_K = conn.execute("SELECT COUNT(*) FROM metrics WHERE name = ?", (K,)).fetchone()[0]
        k_id = db.resolve_metric_id(conn, K)
        obs_K = conn.execute("SELECT COUNT(*) FROM observations WHERE metric_id = ?", (k_id,)).fetchone()[0]
    finally:
        conn.close()
    assert named_K == 1          # K's registry row untouched
    assert obs_K == k_obs        # K's observations untouched (guard raised pre-transaction)


def test_guard_404_zero_obs_source(client, temp_db):
    """Rename a zero-observation source -> moved == 0 -> 404, and the registry row is
    NOT renamed (the partial-state assertion that caught the 3c->3d bug)."""
    Z = _build_orphan(temp_db, "test_zero_obs_404")
    fresh = Z + "_404_target"
    resp = client.put(f"/metrics/{quote(Z, safe='/')}/rename", json={"new_name": fresh})
    assert resp.status_code == 404
    conn = db.connect(temp_db)
    try:
        z_unchanged = conn.execute(
            "SELECT COUNT(*) FROM metrics WHERE name = ?", (Z,)
        ).fetchone()[0] == 1
        fresh_in_registry = conn.execute(
            "SELECT COUNT(*) FROM metrics WHERE name = ?", (fresh,)
        ).fetchone()[0] >= 1
    finally:
        conn.close()
    assert z_unchanged           # Z's registry row still named Z
    assert fresh_in_registry is False   # the rejected name was never written
