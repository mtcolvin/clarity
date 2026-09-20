"""
personal_baseline_candidacy tests — the numeric_count field.

Pins the distinction the personal-baseline discoverability recon surfaced:
`n` (candidacy's existing field) counts only JUDGEABLE readings (those carrying
a ref_low/ref_high — needed for the out-of-range fraction the suggestion banner
gates on). `numeric_count` is a SEPARATE, lower bar: every numeric reading,
regardless of whether it has a range — the denominator the per-metric quiet
link's "is this computable at all" check needs, matching what
personal_baseline_z's history actually requires (no ref-bound requirement).

The bug-in-waiting this pins: a metric can have plenty of numeric readings but
few judgeable ones (or vice versa) — conflating the two would either hide a
working feature (numeric readings exist, few have ranges) or offer one that
can't compute anything yet.
"""

from __future__ import annotations

from urllib.parse import quote

import db
from analysis import personal_baseline_candidacy
from conftest import make_orphan_metric


def _add(conn, metric, value, date, ref_low=None, ref_high=None):
    db.add_observation(
        conn, metric=metric, value=value, unit="u", observed_on=date,
        ref_low=ref_low, ref_high=ref_high, seed_keys=(),
    )


# --------------------------------------------------------------- unit-level

def test_numeric_count_matches_all_numeric_readings(db_conn):
    """All numeric readings count, ranged or not."""
    for i, d in enumerate(["2024-01-01", "2024-02-01", "2024-03-01"]):
        _add(db_conn, "m", float(i), d)  # no ref bounds on any of them
    db_conn.commit()
    series = db.get_series(db_conn, "m")
    cand = personal_baseline_candidacy(series)
    assert cand["numeric_count"] == 3
    assert cand["n"] == 0  # none are judgeable — zero ref-bound readings


def test_numeric_count_diverges_from_n(db_conn):
    """The exact bug-in-waiting scenario: 6 numeric readings, only 2 judgeable.
    numeric_count must reflect all 6; n must stay 2 (unaffected, unchanged
    behavior). Conflating them would wrongly hide a computable-baseline metric
    behind the judgeable-only count."""
    dates = [f"2024-{m:02d}-01" for m in range(1, 7)]
    for i, d in enumerate(dates):
        # Only the first two carry a reference range.
        if i < 2:
            _add(db_conn, "m", float(i), d, ref_low=0, ref_high=100)
        else:
            _add(db_conn, "m", float(i), d)
    db_conn.commit()
    series = db.get_series(db_conn, "m")
    cand = personal_baseline_candidacy(series)
    assert cand["numeric_count"] == 6
    assert cand["n"] == 2


def test_numeric_count_zero_for_empty_series():
    cand = personal_baseline_candidacy([])
    assert cand["numeric_count"] == 0
    assert cand["n"] == 0
    assert cand["is_candidate"] is False


# --------------------------------------------------------------- route-level

def test_route_surfaces_numeric_count(client, temp_db):
    conn = db.connect(temp_db)
    try:
        make_orphan_metric(conn, "rt_candidacy")
        for i, d in enumerate(["2024-01-01", "2024-02-01", "2024-03-01", "2024-04-01"]):
            _add(conn, "rt_candidacy", float(i), d)  # no ref bounds -> n stays 0
        conn.commit()
    finally:
        conn.close()

    r = client.get(f"/metric-settings/{quote('rt_candidacy', safe='/')}")
    assert r.status_code == 200
    body = r.json()
    assert body["candidacy"]["numeric_count"] == 4
    assert body["candidacy"]["n"] == 0
    assert body["candidacy"]["is_candidate"] is False
