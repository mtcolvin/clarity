"""
Editing a profile measurement (weight/height), and reading a collection's analytes.

Two small read/write additions the Profile and Collections UIs needed, pinned here
because each carries a decision that is easy to undo by accident:

  * A measurement's `field` is NOT editable. Weight and height are different
    quantities; letting a row move between them would silently change what two
    charts show, so a mistyped field means delete + re-add (the same rule a
    reading's result_type follows).
  * A collection's analyte list is a READ. Nothing here writes to observations,
    and the collection's own metadata is not folded into the rows — it is stored
    once on the collection, and duplicating it per analyte is exactly what the
    collections table exists to avoid.
"""

from __future__ import annotations

import db


# ---- db layer: measurement edit ------------------------------------------------

def test_update_measurement_changes_value_unit_and_date(db_conn):
    mid = db.add_profile_measurement(db_conn, "weight", 140.3, "lb", "2026-07-27")
    assert db.update_profile_measurement(db_conn, mid, 141.0, "lb", "2026-07-28") is True
    row = db.get_profile_measurement(db_conn, mid)
    assert (row["value"], row["unit"], row["recorded_on"]) == (141.0, "lb", "2026-07-28")
    # the field is untouched — there is no code path that moves a row between
    # weight and height (see db.update_profile_measurement's docstring).
    assert row["field"] == "weight"


def test_update_unknown_measurement_reports_no_match(db_conn):
    assert db.update_profile_measurement(db_conn, 9999, 1.0, "lb", "2026-07-27") is False


def test_edit_does_not_add_a_row(db_conn):
    """An edit CORRECTS history; it does not append to it. The table is append-only
    for new measurements, which is a different thing from being immutable."""
    db.add_profile_measurement(db_conn, "weight", 140.3, "lb", "2026-07-27")
    mid = db.add_profile_measurement(db_conn, "weight", 138.1, "lb", "2026-07-20")
    db.update_profile_measurement(db_conn, mid, 138.5, "lb", "2026-07-20")
    hist = db.list_profile_history(db_conn, "weight")
    assert len(hist) == 2
    assert [h["value"] for h in hist] == [140.3, 138.5]


# ---- routes: measurement edit --------------------------------------------------

def test_put_measurement_route(client):
    mid = client.post("/profile/measurements", json={
        "field": "weight", "value": 140.3, "unit": "lb", "recorded_on": "2026-07-27",
    }).json()["id"]

    r = client.put(f"/profile/measurements/{mid}",
                   json={"value": 141.2, "unit": "lb", "recorded_on": "2026-07-26"})
    assert r.status_code == 200
    assert r.json()["value"] == 141.2 and r.json()["recorded_on"] == "2026-07-26"
    # and it is reflected in the CURRENT value the profile serves
    assert client.get("/profile").json()["weight"]["value"] == 141.2


def test_put_measurement_validates_date_and_unit(client):
    mid = client.post("/profile/measurements", json={
        "field": "weight", "value": 140.3, "unit": "lb", "recorded_on": "2026-07-27",
    }).json()["id"]

    assert client.put(f"/profile/measurements/{mid}",
                      json={"value": 1.0, "unit": "lb", "recorded_on": "07/27/2026"}
                      ).status_code == 422
    assert client.put(f"/profile/measurements/{mid}",
                      json={"value": 1.0, "unit": "  ", "recorded_on": "2026-07-27"}
                      ).status_code == 422


def test_put_unknown_measurement_404(client):
    assert client.put("/profile/measurements/9999",
                      json={"value": 1.0, "unit": "lb", "recorded_on": "2026-07-27"}
                      ).status_code == 404


# ---- collection analytes -------------------------------------------------------

def test_collection_readings_list_their_analytes(db_conn):
    cid = db.add_collection(db_conn, completed_on="2026-05-02", volume_ml=1850.0)
    db.add_observation(db_conn, "Sodium 24-Hour Urine", 150.0, "mmol/24h", "2026-05-02",
                       collection_id=cid)
    db.add_observation(db_conn, "Protein 24-Hour Urine", 180.0, "mg/24h", "2026-05-02",
                       ref_low=0, ref_high=150, collection_id=cid)
    # a reading NOT in the collection must not appear
    db.add_observation(db_conn, "Hemoglobin", 15.1, "g/dL", "2026-05-02")

    rows = db.list_collection_readings(db_conn, cid)
    assert [r["metric"] for r in rows] == ["Protein 24-Hour Urine", "Sodium 24-Hour Urine"]
    protein = rows[0]
    # the SAME row shape a series row has, so the client formats it with the
    # formatter it already uses for a reading
    assert protein["value"] == 180.0 and protein["unit"] == "mg/24h"
    assert protein["ref_low"] == 0 and protein["ref_high"] == 150
    assert protein["result_type"] == "numeric"
    # the collection's own metadata is NOT duplicated onto each analyte
    assert "volume_ml" not in protein


def test_collection_readings_route(client):
    cid = client.post("/collections", json={
        "kind": "24h_urine", "completed_on": "2026-05-02", "volume_ml": 1850.0,
    }).json()["id"]
    client.post("/observations", json={
        "metric": "Protein 24-Hour Urine", "value": 180.0, "unit": "mg/24h",
        "observed_on": "2026-05-02", "collection_id": cid,
    })

    rows = client.get(f"/collections/{cid}/readings").json()
    assert [r["metric"] for r in rows] == ["Protein 24-Hour Urine"]
    assert rows[0]["value"] == 180.0

    # an EMPTY collection is [] — distinct from an unknown id, which is 404
    empty = client.post("/collections", json={
        "kind": "24h_urine", "completed_on": "2026-06-02",
    }).json()["id"]
    assert client.get(f"/collections/{empty}/readings").json() == []
    assert client.get("/collections/9999/readings").status_code == 404
