"""
The FULL-PICTURE export: the non-metric half of the payload (picture.py) and the route
that carries it (/export-multi with include_context).

What these pin, in priority order:

1. The DATE OF BIRTH cannot reach a payload. picture.assemble_profile consumes it to
   compute an age and never copies it — this asserts the absence end-to-end, through the
   real preview route, not just at the unit level. The charter names DOB explicitly, and
   this feature is the first thing that reads the profile table for egress at all.
2. Report text is the USER'S EDITED string, not the file on disk. The whole privacy
   footing for report prose is human redaction in the preview, so a refactor that
   "helpfully" re-reads the report would silently undo it — and a passing preview would
   look identical. Pinned by sending a redacted draft and asserting the original text is
   absent.
3. The gateway allowlist matches picture.py's top-level keys EXACTLY (the same guard
   test_export_gateway.py puts on explain.py), so a new context section can't ride out
   unreviewed, and can't be silently dropped either.
4. Context is OFF by default — a single-metric or panel export sends what it always sent.

Nothing here reaches a provider: confirmation=None returns a Preview and stops.
"""

from __future__ import annotations

import gateway
import picture


# --------------------------------------------------------------- picture.py, unit level

def test_age_is_computed_and_dob_is_never_copied():
    prof = picture.assemble_profile({"sex": "male", "date_of_birth": "1980-04-15"},
                                    [], [], "2026-07-30")
    assert prof["age_years"] == 46
    assert prof["sex"] == "male"
    # The absence is the point — assert on the whole serialized blob, not just key names,
    # so a future field that embeds the DOB inside a string is caught too.
    assert "date_of_birth" not in prof
    assert "1980-04-15" not in repr(prof)


def test_age_handles_a_birthday_that_has_not_happened_yet():
    # A whole-year age is off by one if the month/day comparison is skipped.
    assert picture.assemble_profile({"date_of_birth": "1980-12-31"}, [], [],
                                    "2026-07-30")["age_years"] == 45


def test_age_is_none_when_unknown_or_unparseable():
    for dob in (None, "", "not-a-date", "1980-13-45"):
        assert picture.assemble_profile({"date_of_birth": dob}, [], [],
                                        "2026-07-30")["age_years"] is None
    # No as_of anchor -> no age, rather than an age against an implicit "now".
    assert picture.assemble_profile({"date_of_birth": "1980-04-15"}, [], [],
                                    None)["age_years"] is None


def test_measurements_keep_their_units_as_entered():
    prof = picture.assemble_profile(
        None,
        [{"recorded_on": "2026-02-01", "value": 82.0, "unit": "kg"},
         {"recorded_on": "2026-01-01", "value": 180.0, "unit": "lb"}],
        [], "2026-07-30")
    # Oldest first, and no lb/kg conversion — the same honesty the observations table keeps.
    assert prof["weight"] == [{"recorded_on": "2026-01-01", "value": 180.0, "unit": "lb"},
                              {"recorded_on": "2026-02-01", "value": 82.0, "unit": "kg"}]


def test_an_emptied_report_is_dropped_entirely():
    """Clearing the box IS the decision to exclude that report — it must not go as an
    empty string with its study date still attached."""
    out = picture.assemble_reports([
        {"study_date": "2025-06-30", "text": "  \n "},
        {"study_date": "2025-01-02", "text": "Referto."},
    ])
    assert [r["study_date"] for r in out] == ["2025-01-02"]


def test_imaging_reads_only_allowlisted_display_tags():
    """picture.assemble_imaging consumes dicom_store.public_studies() output. Feed it a
    study carrying PII tags alongside the safe ones and prove they are not copied: the
    allowlist rule is 'excluded by never being read', so a passthrough would be the bug."""
    studies = [{
        "id": "1.2.3", "StudyDate": "2025-06-30", "StudyDescription": "CT ABDOMEN",
        "PatientName": "ROSSI^MARIO", "PatientID": "MRN0099",
        "ReferringPhysicianName": "DR^ROE", "InstitutionName": "Some Hospital",
        "series": [{"Modality": "CT", "BodyPartExamined": "ABDOMEN", "n_slices": 120}],
    }]
    out = picture.assemble_imaging(studies)
    blob = repr(out)
    for leak in ("ROSSI", "MRN0099", "ROE", "Some Hospital", "1.2.3"):
        assert leak not in blob
    assert out[0]["modalities"] == ["CT"] and out[0]["n_images"] == 120


# ----------------------------------------------------------------- the gateway boundary

def test_allowlist_matches_the_context_keys_exactly():
    """The same guard test_export_gateway.py puts on explain.py. A new section added to
    assemble_context must be added to the allowlist deliberately (this fails loudly
    otherwise), and the allowlist can't silently start dropping one either."""
    context = picture.assemble_context(
        profile_row=None, weight_rows=[], height_rows=[], conditions=[], medications=[],
        events=[], imaging_studies=[], approved_reports=[], as_of="2026-07-30")
    allow = gateway._ALLOWLISTS["export_metrics"]
    # `metrics` and `scope` are the pre-existing metric half; the rest is picture.py's.
    assert set(context) | {"metrics", "scope"} == allow


def test_scrub_reaches_report_prose_but_leaves_readings_alone():
    """The scrub is belt-and-suspenders behind the user's edit, but it has to actually
    RUN on the prose — and it must not run on the structured bundle, where an ISO date is
    a reading date and a five-digit value looks like a zip code."""
    payload = [{
        "reports": [{"study_date": "2025-06-30",
                     "text": "Referto. Confronto 12/03/2025. Dr. Rossi ha firmato."}],
        "metrics": [{"metric": "Sodium",
                     "readings": [{"observed_on": "2026-01-02", "value": 10025.0}]}],
    }]
    scrubbed, redactions = gateway._scrub(payload,
                                          gateway._PROSE_FIELDS["export_metrics"])
    text = scrubbed[0]["reports"][0]["text"]
    assert "Rossi" not in text and "12/03/2025" not in text
    assert {r["type"] for r in redactions} == {"date", "physician"}
    # The structured half is untouched: the reading date survives, and a value that
    # matches the zip pattern as a string is a number here and never scrubbed.
    reading = scrubbed[0]["metrics"][0]["readings"][0]
    assert reading == {"observed_on": "2026-01-02", "value": 10025.0}
    # The report's own study_date is structured metadata, not prose — it stays readable.
    assert scrubbed[0]["reports"][0]["study_date"] == "2025-06-30"


def test_a_task_declaring_no_prose_fields_is_unchanged():
    """Regression guard for the recursion: every other task must scrub exactly as before
    (top-level strings only, nested values untouched)."""
    payload = [{"metric": "Sodium", "readings": [{"observed_on": "2026-01-02"}]}]
    scrubbed, redactions = gateway._scrub(payload)
    assert scrubbed == payload and redactions == []


# ------------------------------------------------------------------------- the API route

def _enable_export(client):
    client.put("/export/enabled", json={"enabled": True})


def _seed_record(client):
    """A minimal but REAL record: one metric with two readings, plus one of each context
    row, so the assembled payload is production-shaped rather than a stub."""
    for date, value in (("2026-01-02", 140.0), ("2026-03-02", 149.0)):
        client.post("/observations", json={
            "metric": "Sodium Serum/Plasma", "value": value, "unit": "mmol/L",
            "observed_on": date, "ref_low": 135.0, "ref_high": 145.0})
    client.put("/profile", json={"sex": "male", "date_of_birth": "1980-04-15"})
    client.post("/profile/measurements", json={
        "field": "weight", "value": 180.0, "unit": "lb", "recorded_on": "2026-01-02"})
    client.post("/conditions", json={"name": "Gilbert syndrome", "onset_on": "2019-03-01"})
    client.post("/medications", json={"name": "Lisinopril", "dose": "10 mg",
                                      "start_date": "2024-02-01"})
    client.post("/events", json={"event_date": "2025-06-30", "event_type": "procedure",
                                 "title": "CT abdomen"})


def test_full_picture_preview_carries_the_whole_record_and_no_dob(client):
    _enable_export(client)
    _seed_record(client)
    r = client.post("/export-multi/preview", json={
        "metrics": ["Sodium Serum/Plasma"], "scope_label": "Full health picture",
        "include_context": True})
    assert r.status_code == 200
    payload = r.json()["payload"][0]

    assert payload["profile"]["sex"] == "male"
    assert payload["profile"]["age_years"] is not None
    assert payload["profile"]["weight"][0]["unit"] == "lb"
    assert [c["name"] for c in payload["conditions"]] == ["Gilbert syndrome"]
    assert [m["name"] for m in payload["medications"]] == ["Lisinopril"]
    assert [e["title"] for e in payload["events"]] == ["CT abdomen"]
    # The metric half is still there and still complete.
    assert len(payload["metrics"][0]["readings"]) == 2

    # The load-bearing assertion: the DOB is nowhere in what would be sent.
    assert "1980-04-15" not in r.text
    assert "date_of_birth" not in r.text


def test_context_is_off_by_default(client):
    """A panel or ad-hoc selection must send exactly what it sent before this feature —
    data minimization, not a new default."""
    _enable_export(client)
    _seed_record(client)
    r = client.post("/export-multi/preview", json={"metrics": ["Sodium Serum/Plasma"]})
    assert r.status_code == 200
    payload = r.json()["payload"][0]
    assert set(payload) == {"metrics", "scope"}


def _make_archive(tmp_path, monkeypatch, text: str) -> None:
    """A one-report archive in the real on-disc layout: <root>/<disc>/other_content/
    <accession>/report.txt (an imaging CD carries its report beside its images)."""
    import reports as reports_store
    folder = tmp_path / "archive" / "cd1" / "other_content" / "ACC123"
    folder.mkdir(parents=True)
    (folder / "report.txt").write_text(text, encoding="utf-8")
    monkeypatch.setattr(reports_store, "ARCHIVE_DIR", str(tmp_path / "archive"))


def test_report_text_sent_is_the_edited_draft_not_the_file(client, tmp_path, monkeypatch):
    """The privacy footing for report prose is that the user edits it before it leaves.
    A refactor that re-read the report from disk would erase that edit while every other
    assertion in this file still passed — so pin it directly."""
    _make_archive(tmp_path, monkeypatch, "Paziente ROSSI MARIO. Referto: nulla di rilevante.")

    _enable_export(client)
    _seed_record(client)
    drafts = client.get("/export/drafts").json()
    assert drafts["reports_available"] and drafts["reports"], "fixture archive should yield a draft"
    report_id = drafts["reports"][0]["id"]
    assert "ROSSI" in drafts["reports"][0]["text"], "the draft starts as the real text"

    r = client.post("/export-multi/preview", json={
        "metrics": ["Sodium Serum/Plasma"], "include_context": True,
        "reports": [{"id": report_id, "text": "Referto: nulla di rilevante."}]})
    assert r.status_code == 200
    payload = r.json()["payload"][0]
    assert len(payload["reports"]) == 1
    assert payload["reports"][0]["text"] == "Referto: nulla di rilevante."
    assert "ROSSI" not in r.text


def test_report_text_cannot_ride_an_export_that_has_no_context(client):
    """Report prose is only ever sent through the path that previews it. Passing reports
    without include_context must drop them, not smuggle them into a panel export."""
    _enable_export(client)
    _seed_record(client)
    r = client.post("/export-multi/preview", json={
        "metrics": ["Sodium Serum/Plasma"],
        "reports": [{"id": "whatever", "text": "Dr. Roe wrote this."}]})
    assert r.status_code == 200
    assert "Roe" not in r.text


def test_editing_a_report_changes_the_confirmation_token(client, tmp_path, monkeypatch):
    """The token binds the DATA. If it didn't move with the report text, a preview of one
    redaction could be used to confirm a send of another."""
    _make_archive(tmp_path, monkeypatch, "Referto originale.")

    _enable_export(client)
    _seed_record(client)
    rid = client.get("/export/drafts").json()["reports"][0]["id"]
    body = {"metrics": ["Sodium Serum/Plasma"], "include_context": True}

    first = client.post("/export-multi/preview",
                        json={**body, "reports": [{"id": rid, "text": "Referto originale."}]})
    second = client.post("/export-multi/preview",
                         json={**body, "reports": [{"id": rid, "text": "Referto redatto."}]})
    assert (first.json()["confirmation_token"]
            != second.json()["confirmation_token"])


def test_export_reports_route_is_gated(client):
    """With hosted export off there is nothing to prepare a draft for — and the route
    reads clinical prose, so it shouldn't answer when the capability is disabled."""
    assert client.get("/export/drafts").status_code == 403


# ------------------------------------------- editable free text on the DB rows (notes)
# Same footing as the report text above: prose the allowlist can't filter and the scrub
# can't guarantee, made redactable at the moment of consent. These pin that the edit
# actually reaches the payload, that it does NOT reach the database, and that it can't
# ride an export which never previewed it.

def _seed_notes(client):
    client.post("/conditions", json={"name": "Gilbert syndrome", "onset_on": "2019-03-01",
                                     "notes": "benign, per Dr. Rossi"})
    client.post("/events", json={"event_date": "2025-06-30", "event_type": "procedure",
                                 "title": "CT with Dr. Roe", "notes": ""})


def test_drafts_list_the_free_text_worth_redacting(client):
    _enable_export(client)
    _seed_record(client)
    _seed_notes(client)
    texts = client.get("/export/drafts").json()["texts"]
    # Keyed by (kind, field, text) — _seed_record also adds an event, so there is more
    # than one row per (kind, field) and a two-part key would silently keep only the last.
    cond = [t for t in texts if t["kind"] == "condition" and t["field"] == "notes"]
    assert [t["text"] for t in cond] == ["benign, per Dr. Rossi"]
    assert cond[0]["label"] == "Gilbert syndrome"
    assert "CT with Dr. Roe" in [t["text"] for t in texts if t["field"] == "title"]
    # An EMPTY field is skipped: there is nothing to redact in a blank note, and listing
    # every empty box would bury the ones that matter. Both seeded events have no notes.
    assert not [t for t in texts if t["kind"] == "event" and t["field"] == "notes"]
    # A drug name / dose / condition name is vocabulary, not prose — not offered.
    assert all(t["field"] in ("notes", "title") for t in texts)


def test_an_edited_note_reaches_the_payload_and_not_the_database(client):
    _enable_export(client)
    _seed_record(client)
    _seed_notes(client)
    cid = client.get("/conditions").json()[0]["id"]
    r = client.post("/export-multi/preview", json={
        "metrics": ["Sodium Serum/Plasma"], "include_context": True,
        "texts": [{"kind": "condition", "id": cid, "field": "notes", "text": "benign"}]})
    assert r.status_code == 200
    assert r.json()["payload"][0]["conditions"][0]["notes"] == "benign"
    assert "Rossi" not in r.text
    # Redacting for a send must not quietly rewrite the user's own record.
    assert client.get("/conditions").json()[0]["notes"] == "benign, per Dr. Rossi"


def test_blanking_a_note_removes_it_from_the_payload(client):
    _enable_export(client)
    _seed_record(client)
    _seed_notes(client)
    cid = client.get("/conditions").json()[0]["id"]
    r = client.post("/export-multi/preview", json={
        "metrics": ["Sodium Serum/Plasma"], "include_context": True,
        "texts": [{"kind": "condition", "id": cid, "field": "notes", "text": "   "}]})
    assert r.json()["payload"][0]["conditions"][0]["notes"] is None
    assert "Rossi" not in r.text


def test_an_override_outside_the_editable_allowlist_is_ignored(client):
    """_EDITABLE_TEXT is the allowlist. A client naming a column that isn't offered for
    editing must not be able to rewrite it — the editor exists to REMOVE text before a
    send, not to become a back door for changing what the record says."""
    _enable_export(client)
    _seed_record(client)
    _seed_notes(client)
    cid = client.get("/conditions").json()[0]["id"]
    r = client.post("/export-multi/preview", json={
        "metrics": ["Sodium Serum/Plasma"], "include_context": True,
        "texts": [{"kind": "condition", "id": cid, "field": "name", "text": "Something else"}]})
    assert r.json()["payload"][0]["conditions"][0]["name"] == "Gilbert syndrome"


def test_note_edits_cannot_ride_an_export_without_context(client):
    _enable_export(client)
    _seed_record(client)
    _seed_notes(client)
    cid = client.get("/conditions").json()[0]["id"]
    r = client.post("/export-multi/preview", json={
        "metrics": ["Sodium Serum/Plasma"],
        "texts": [{"kind": "condition", "id": cid, "field": "notes", "text": "smuggled"}]})
    assert r.status_code == 200
    assert "smuggled" not in r.text


def test_editing_a_note_changes_the_confirmation_token(client):
    """Same reason as the report case: the token binds the DATA, so a preview of one
    redaction must not confirm a send of another."""
    _enable_export(client)
    _seed_record(client)
    _seed_notes(client)
    cid = client.get("/conditions").json()[0]["id"]
    body = {"metrics": ["Sodium Serum/Plasma"], "include_context": True}
    a = client.post("/export-multi/preview", json={**body, "texts": [
        {"kind": "condition", "id": cid, "field": "notes", "text": "one"}]})
    b = client.post("/export-multi/preview", json={**body, "texts": [
        {"kind": "condition", "id": cid, "field": "notes", "text": "two"}]})
    assert a.json()["confirmation_token"] != b.json()["confirmation_token"]
