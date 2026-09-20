"""
Coverage for the duplicate-date 409 protection on observation writes — the guard
that Phase 6 (A)'s constraint swap must preserve.

WHY THIS EXISTS (gap-(A)) — a reading is unique per (metric, observed_on). Today
that rests on observations' UNIQUE(metric, observed_on): a duplicate write raises
sqlite3.IntegrityError, which both write routes catch and map to 409 (not a raw
500). Phase 6 (A) drops the observations.metric column and MUST replace that
constraint with UNIQUE(metric_id, observed_on). These tests are the swap guard:
GREEN at HEAD (current UNIQUE), and they must STAY green after (A) (replacement
UNIQUE) — a duplicate (metric, observed_on) is, post-(A), a duplicate
(metric_id, observed_on), so it still raises and still returns 409. They go RED
if (A) drops the UNIQUE without replacing it (the duplicate would insert silently
-> 200).

Built on the conftest `client` fixture only: ObservationIn requires just
metric + observed_on, and the first POST mints the metric via add_observation ->
get_or_create_metric, so no pre-built subject is needed.

Route shapes (api.py): POST /observations (create_observation) returns {id};
PUT /observations/{obs_id} (edit_observation) takes a full ObservationIn body.
Both map sqlite3.IntegrityError -> 409.
"""

from __future__ import annotations

_METRIC = "dup_test"
_UNIT = "x"


def test_post_duplicate_date_returns_409(client):
    body = {"metric": _METRIC, "value": 100, "unit": _UNIT, "observed_on": "2024-01-15"}

    first = client.post("/observations", json=body)
    assert first.status_code == 200          # mints the metric + inserts the row

    dup = client.post("/observations", json=body)  # identical (metric, observed_on)
    # Clean 409 (IntegrityError caught and mapped), never a raw 500.
    assert dup.status_code == 409
    assert dup.status_code != 500


def test_put_onto_existing_date_returns_409(client):
    # Two readings for one metric on DIFFERENT dates (both succeed).
    r1 = client.post("/observations",
                     json={"metric": _METRIC, "value": 100, "unit": _UNIT,
                           "observed_on": "2024-02-01"})
    r2 = client.post("/observations",
                     json={"metric": _METRIC, "value": 110, "unit": _UNIT,
                           "observed_on": "2024-02-02"})
    assert r1.status_code == 200
    assert r2.status_code == 200
    id1 = r1.json()["id"]

    # Move row 1's date ONTO row 2's date -> hits the same UNIQUE -> 409.
    put = client.put(f"/observations/{id1}",
                     json={"metric": _METRIC, "value": 100, "unit": _UNIT,
                           "observed_on": "2024-02-02"})
    assert put.status_code == 409
    assert put.status_code != 500
