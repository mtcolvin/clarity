"""
Immunizations — the vaccination record.

A dated fact with no value and no status, closest in shape to `events`, and like
conditions/medications entirely standalone: nothing here is ever analysed.

Two decisions are pinned because both are easy to "fix" into something worse:

  * `administered_on` is NULLABLE and undated records sort LAST. A childhood shot
    recalled from a paper card is a real record with no date; inventing one would
    put a fabricated point in the record, and SQLite's NULL-first default would
    otherwise float exactly those records to the top of the list.
  * `dose_label` is FREE TEXT, not a dose number. Encoding a schedule would mean
    knowing each vaccine's schedule and judging whether a record is complete —
    a clinical judgment this app doesn't make.
"""

from __future__ import annotations

import db


# ---- db layer ------------------------------------------------------------------

def test_add_and_list(db_conn):
    db.add_immunization(db_conn, "Influenza (quadrivalent)", administered_on="2025-11-08",
                        dose_label="2025-26 season", amount="0.5 mL", site="left deltoid",
                        lot="AB1234", notes="pharmacy")
    rows = db.list_immunizations(db_conn)
    assert len(rows) == 1
    r = rows[0]
    assert r["vaccine"] == "Influenza (quadrivalent)"
    assert r["administered_on"] == "2025-11-08"
    assert (r["dose_label"], r["site"], r["lot"]) == ("2025-26 season", "left deltoid", "AB1234")


def test_dose_label_and_amount_are_separate_facts(db_conn):
    """WHICH dose vs HOW MUCH. A single "dose" column would have to hold both "Booster"
    and "0.5 mL", which answers two different questions in one unsortable column."""
    iid = db.add_immunization(db_conn, "Meningococcal ACWY", administered_on="2025-09-29",
                              dose_label="Booster", amount="0.5 mL")
    r = db.list_immunizations(db_conn)[0]
    assert r["dose_label"] == "Booster" and r["amount"] == "0.5 mL"
    # each survives an edit of the other
    db.update_immunization(db_conn, iid, vaccine="Meningococcal ACWY",
                           administered_on="2025-09-29", dose_label="Booster",
                           amount="0.25 mL")
    assert db.list_immunizations(db_conn)[0]["dose_label"] == "Booster"


def test_amount_keeps_its_unit(db_conn):
    """Stored as the record prints it. 0.5 mL and 0.25 mL are both real vaccine volumes,
    so a bare number would throw away half of what the record says."""
    db.add_immunization(db_conn, "Hepatitis A (pediatric)", amount="0.5 mL")
    assert db.list_immunizations(db_conn)[0]["amount"] == "0.5 mL"


def test_only_the_vaccine_name_is_required(db_conn):
    """The paper-card case: a name and nothing else."""
    db.add_immunization(db_conn, "MMR")
    row = db.list_immunizations(db_conn)[0]
    assert row["vaccine"] == "MMR"
    assert row["administered_on"] is None
    assert row["dose_label"] is None and row["site"] is None and row["lot"] is None


def test_undated_records_sort_last(db_conn):
    """NOT SQLite's default: NULLs sort FIRST there, which would put every recalled
    childhood shot above this year's flu shot."""
    db.add_immunization(db_conn, "Childhood polio")                       # undated
    db.add_immunization(db_conn, "Influenza", administered_on="2024-10-01")
    db.add_immunization(db_conn, "Tdap", administered_on="2025-06-11")
    assert [r["vaccine"] for r in db.list_immunizations(db_conn)] == [
        "Tdap", "Influenza", "Childhood polio",
    ]


def test_update_replaces_every_field(db_conn):
    iid = db.add_immunization(db_conn, "Influenza", administered_on="2025-11-08",
                              site="left deltoid")
    assert db.update_immunization(db_conn, iid, vaccine="Influenza (high-dose)",
                                  administered_on="2025-10-03", site="right deltoid",
                                  dose_label="Booster") is True
    row = db.list_immunizations(db_conn)[0]
    assert row["vaccine"] == "Influenza (high-dose)"
    assert row["administered_on"] == "2025-10-03"
    assert row["site"] == "right deltoid" and row["dose_label"] == "Booster"


def test_update_and_delete_report_a_miss(db_conn):
    assert db.update_immunization(db_conn, 9999, vaccine="x") is False
    assert db.delete_immunization(db_conn, 9999) is False


def test_delete(db_conn):
    iid = db.add_immunization(db_conn, "Tdap")
    assert db.delete_immunization(db_conn, iid) is True
    assert db.list_immunizations(db_conn) == []


# ---- routes --------------------------------------------------------------------

def test_crud_routes(client):
    created = client.post("/immunizations", json={
        "vaccine": "Influenza (quadrivalent)", "administered_on": "2025-11-08",
        "dose_label": "2025-26 season", "site": "left deltoid",
    })
    assert created.status_code == 201
    iid = created.json()["id"]

    listed = client.get("/immunizations").json()
    assert [r["vaccine"] for r in listed] == ["Influenza (quadrivalent)"]

    edited = client.put(f"/immunizations/{iid}", json={
        "vaccine": "Influenza (high-dose)", "administered_on": "2025-11-08",
        "amount": "0.5 mL",
    })
    assert edited.status_code == 200
    assert edited.json()["vaccine"] == "Influenza (high-dose)"
    assert edited.json()["amount"] == "0.5 mL"
    # a field omitted on a full-replace edit is cleared, not kept
    assert edited.json()["site"] is None

    assert client.delete(f"/immunizations/{iid}").status_code == 204
    assert client.get("/immunizations").json() == []


def test_route_validation(client):
    # a name is required
    assert client.post("/immunizations", json={"vaccine": "   "}).status_code == 422
    # a date, if given, must be ISO
    assert client.post("/immunizations", json={
        "vaccine": "Tdap", "administered_on": "10/02/2025"}).status_code == 422
    # a BLANK date is not an error — it's "unknown", stored null
    r = client.post("/immunizations", json={"vaccine": "Tdap", "administered_on": ""})
    assert r.status_code == 201
    assert client.get("/immunizations").json()[0]["administered_on"] is None


def test_unknown_id_404s(client):
    assert client.put("/immunizations/9999", json={"vaccine": "x"}).status_code == 404
    assert client.delete("/immunizations/9999").status_code == 404


def test_immunizations_reach_no_analysis_surface(client):
    """Standalone by construction: adding one creates no metric and no flag. It DOES
    add a Timeline entry (it is a dated fact), but nothing analytical — pins that this
    record never became a detector input by accident."""
    before_metrics = client.get("/metrics").json()
    client.post("/immunizations", json={"vaccine": "Tdap", "administered_on": "2025-06-11"})
    assert client.get("/metrics").json() == before_metrics
    assert client.get("/flags/Tdap").json() == []


# ---- timeline ------------------------------------------------------------------

def test_dated_immunization_appears_on_the_timeline(client):
    client.post("/immunizations", json={
        "vaccine": "Influenza (quadrivalent)", "administered_on": "2025-11-08",
        "dose_label": "2025-26 season", "site": "left deltoid",
    })
    entries = [e for e in client.get("/timeline").json() if e["kind"] == "immunization"]
    assert len(entries) == 1
    e = entries[0]
    assert e["date"] == "2025-11-08"
    assert e["title"] == "Influenza (quadrivalent)"
    assert e["detail"]["dose_label"] == "2025-26 season"
    # it links to the tab that owns the record, rather than being editable in place
    assert e["link"] == "/profile?tab=immunizations"


def test_undated_immunization_is_omitted_from_the_timeline(client):
    """The Timeline places things in TIME. A record whose date is unknown has no place
    on it, and inventing one (created_at, today, a guessed year) would put a fabricated
    point on the line — the same rule a condition with no onset date follows. The record
    is still fully readable on the Profile tab."""
    client.post("/immunizations", json={"vaccine": "MMR"})
    assert [e for e in client.get("/timeline").json() if e["kind"] == "immunization"] == []
    assert len(client.get("/immunizations").json()) == 1


def test_lot_number_stays_off_the_timeline_entry(client):
    """A lot number identifies a manufactured batch, not the person — but it is also
    pure noise on a timeline, so the entry carries what a reader needs (vaccine, dose,
    site, notes) and the full record stays on its own tab."""
    client.post("/immunizations", json={
        "vaccine": "Tdap", "administered_on": "2025-06-11", "lot": "AB1234",
    })
    e = [x for x in client.get("/timeline").json() if x["kind"] == "immunization"][0]
    assert "AB1234" not in str(e["title"])
