"""
Timed collections (24-hour urine, etc.) — Phase 1 backend.

A collection is the provenance a set of analytes share (modeled like `documents`): its
volume/duration/dates live ONCE in the `collections` table, and each analyte is a normal
`observations` row linked by `collection_id`. The analyte VALUE is the per-period rate
(unit carries the period, e.g. mg/24h) and its observed_on is the collection's completion
date. The collection metadata is CONTEXT — it must never reach the analysis engine.

Pins the decisions locked for this build: create-first, refuse-delete-when-non-empty,
store duration.
"""

from __future__ import annotations

import analysis
import db


# ---- db layer ----------------------------------------------------------------

def test_create_then_add_analytes_and_read_back(db_conn):
    cid = db.add_collection(db_conn, completed_on="2026-05-02", started_on="2026-05-01",
                            duration_hours=24.0, volume_ml=1850.0, notes="first")
    db.add_observation(db_conn, "Protein 24-Hour Urine", 180.0, "mg/24h", "2026-05-02",
                       ref_low=0, ref_high=150, collection_id=cid)
    db.add_observation(db_conn, "Sodium 24-Hour Urine", 150.0, "mmol/24h", "2026-05-02",
                       collection_id=cid)
    # analytes carry the link
    assert db.get_series(db_conn, "Protein 24-Hour Urine")[0]["collection_id"] == cid
    # the collection stores context ONCE + counts its readings
    col = db.get_collection(db_conn, cid)
    assert col["volume_ml"] == 1850.0 and col["duration_hours"] == 24.0
    listed = [c for c in db.list_collections(db_conn) if c["id"] == cid][0]
    assert listed["n_readings"] == 2


def test_refuse_delete_while_non_empty_then_allow_when_empty(db_conn):
    cid = db.add_collection(db_conn, completed_on="2026-05-02")
    db.add_observation(db_conn, "Protein 24-Hour Urine", 180.0, "mg/24h", "2026-05-02",
                       collection_id=cid)
    try:
        db.delete_collection(db_conn, cid)
        assert False, "expected CollectionInUseError"
    except db.CollectionInUseError as e:
        assert e.n == 1
    # remove the reading, then delete succeeds
    obs_id = db.get_series(db_conn, "Protein 24-Hour Urine")[0]["id"]
    db.delete_observation(db_conn, obs_id)
    assert db.delete_collection(db_conn, cid) is True
    assert db.get_collection(db_conn, cid) is None


def test_fk_is_enforced_bad_collection_id_rejected(db_conn):
    import sqlite3
    try:
        db.add_observation(db_conn, "Protein 24-Hour Urine", 180.0, "mg/24h",
                           "2026-05-02", collection_id=999)
        assert False, "expected an FK IntegrityError"
    except sqlite3.IntegrityError:
        pass


def test_collection_metadata_never_enters_analysis(db_conn):
    """The analyte is a normal rate series; its collection's volume/duration are NOT part
    of the series rows analyze_series sees, so they can't influence detection. The value
    still flags normally (180 > ref_high 150)."""
    cid = db.add_collection(db_conn, completed_on="2026-05-02", volume_ml=1850.0)
    db.add_observation(db_conn, "Protein 24-Hour Urine", 180.0, "mg/24h", "2026-05-02",
                       ref_low=0, ref_high=150, collection_id=cid)
    series = db.get_series(db_conn, "Protein 24-Hour Urine")
    # collection_id rides the row but volume/duration/started_on do NOT
    assert "volume_ml" not in series[0] and "duration_hours" not in series[0]
    flags = analysis.analyze_series("Protein 24-Hour Urine", series)
    assert any(f.kind == "out_of_range" for f in flags)


# ---- routes ------------------------------------------------------------------

def test_collection_routes_create_list_edit(client, temp_db):
    created = client.post("/collections", json={
        "completed_on": "2026-05-02", "started_on": "2026-05-01",
        "duration_hours": 24.0, "volume_ml": 1850.0, "notes": "first",
    })
    assert created.status_code == 201
    cid = created.json()["id"]
    assert created.json()["n_readings"] == 0

    # add an analyte referencing it
    obs = client.post("/observations", json={
        "metric": "Protein 24-Hour Urine", "value": 180.0, "unit": "mg/24h",
        "observed_on": "2026-05-02", "ref_low": 0, "ref_high": 150,
        "collection_id": cid,
    })
    assert obs.status_code == 200

    # list shows n_readings; the analyte's series carries collection_id
    listed = [c for c in client.get("/collections").json() if c["id"] == cid][0]
    assert listed["n_readings"] == 1
    row = client.get("/observations/Protein 24-Hour Urine").json()[0]
    assert row["collection_id"] == cid

    # edit the shared context
    edited = client.put(f"/collections/{cid}", json={"completed_on": "2026-05-02",
                                                     "volume_ml": 1900.0})
    assert edited.status_code == 200 and edited.json()["volume_ml"] == 1900.0


def test_route_refuse_delete_409_then_204(client, temp_db):
    cid = client.post("/collections", json={"completed_on": "2026-05-02"}).json()["id"]
    client.post("/observations", json={
        "metric": "Protein 24-Hour Urine", "value": 180.0, "unit": "mg/24h",
        "observed_on": "2026-05-02", "collection_id": cid})
    assert client.delete(f"/collections/{cid}").status_code == 409  # non-empty
    # empty collection deletes cleanly
    empty = client.post("/collections", json={"completed_on": "2026-06-01"}).json()["id"]
    assert client.delete(f"/collections/{empty}").status_code == 204


def test_metrics_route_marks_collection_membership(client, temp_db):
    """/metrics.in_collection drives the picker's 'Timed collections' optgroup: true for a
    metric with a collection-linked reading, false for a plain one."""
    cid = client.post("/collections", json={"completed_on": "2026-05-02"}).json()["id"]
    client.post("/observations", json={
        "metric": "Protein 24-Hour Urine", "value": 180.0, "unit": "mg/24h",
        "observed_on": "2026-05-02", "collection_id": cid})
    client.post("/observations", json={
        "metric": "Sodium Serum/Plasma", "value": 140.0, "unit": "mmol/L",
        "observed_on": "2026-05-02"})  # spot reading, no collection
    rows = {r["metric"]: r["in_collection"] for r in client.get("/metrics").json()}
    assert rows["Protein 24-Hour Urine"] is True
    assert rows["Sodium Serum/Plasma"] is False


def test_bad_collection_id_on_observation_is_404(client, temp_db):
    r = client.post("/observations", json={
        "metric": "Protein 24-Hour Urine", "value": 180.0, "unit": "mg/24h",
        "observed_on": "2026-05-02", "collection_id": 999})
    assert r.status_code == 404


def test_collection_appears_on_timeline(client, temp_db):
    cid = client.post("/collections", json={
        "completed_on": "2026-05-02", "volume_ml": 1750.0, "duration_hours": 24.0}).json()["id"]
    client.post("/observations", json={
        "metric": "Protein 24-Hour Urine", "value": 180.0, "unit": "mg/24h",
        "observed_on": "2026-05-02", "collection_id": cid})
    tl = client.get("/timeline").json()
    coll = [e for e in tl if e["kind"] == "collection"]
    assert len(coll) == 1
    assert coll[0]["date"] == "2026-05-02"
    assert "24-hour urine collection" in coll[0]["title"]
    assert "1750 mL" in coll[0]["title"]  # float .0 stripped
    assert coll[0]["link"] == "/profile?tab=collections"


def test_completed_on_required_and_validated(client, temp_db):
    assert client.post("/collections", json={"completed_on": "not-a-date"}).status_code == 422
    assert client.post("/collections", json={"kind": "24h_urine"}).status_code == 422
