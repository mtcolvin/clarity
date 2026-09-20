"""
Demo mode — the invented record, and the marker that says a store is one.

The load-bearing property is the DIRECTION the marker can fail in. A demo flag that came
from the launcher could claim "demo" while the process was open on the real database, which
is the failure that matters: it invites you to put a real medical history on a screen for
someone else. So the marker lives in the database and travels with the data, and these tests
pin both halves — a seeded store says yes, an ordinary one says no.
"""

from __future__ import annotations

import json
import os

import pytest
from fastapi.testclient import TestClient

import db
import synthetic


def test_marker_absent_on_an_ordinary_database(tmp_path):
    conn = db.connect(str(tmp_path / "plain.db"))
    db.init_db(conn)
    assert synthetic.is_synthetic(conn) is False


def test_seeded_store_is_marked_and_populated(tmp_path):
    conn = db.connect(str(tmp_path / "demo.db"))
    synthetic.seed_db(conn)
    assert synthetic.is_synthetic(conn) is True
    # A demo with nothing in it demonstrates nothing.
    assert len(db.list_metrics_with_units(conn)) > 10
    assert db.list_conditions(conn)
    assert db.list_immunizations(conn)
    assert db.get_profile(conn)["sex"] == "female"


def test_the_demo_person_is_a_different_person(tmp_path):
    """The invented record must be UNLIKE the real one, not merely stored apart from it —
    a demo that mirrors the real history discloses it while everyone in the room believes
    it is fiction (see synthetic.py's header).

    What that rule needs is a human check, and it got one. What CODE can pin is narrower and
    still worth pinning: the record is internally coherent as one person's history, so the
    conditions, the medications and the shaped series cannot drift apart into a set of
    details assembled to look plausible one at a time — which is how the first version came
    to resemble its owner.
    """
    conn = db.connect(str(tmp_path / "demo.db"))
    synthetic.seed_db(conn)

    conditions = {c["name"]: c for c in db.list_conditions(conn)}
    meds = {m["name"]: m for m in db.list_medications(conn)}
    assert conditions and meds

    # A resolved condition and the course of treatment that resolved it end together.
    resolved = [c for c in conditions.values() if c["status"] == "resolved"]
    assert resolved, "a record of only current problems reads as a problem list, not a history"
    finished = [m for m in meds.values() if m["end_date"]]
    assert finished, "a resolved condition with no finished treatment is half a story"
    assert {c["resolved_on"] for c in resolved} == {m["end_date"] for m in finished}

    # And the series the documents quote actually move, rather than being noise.
    for metric in ("TSH", "Ferritin", "Hemoglobin"):
        values = [r["value"] for r in db.get_series(conn, metric)]
        assert max(values) / min(values) > 1.2, f"{metric} tells no story"


def test_seed_is_deterministic(tmp_path):
    """The same demo every time: a screenshot taken today should match last week's."""
    values = []
    for name in ("a.db", "b.db"):
        conn = db.connect(str(tmp_path / name))
        synthetic.seed_db(conn)
        values.append([r["value"] for r in db.get_series(conn, "Hemoglobin")])
    assert values[0] == values[1]


def test_demo_route_reports_the_open_database(tmp_path, monkeypatch):
    """/demo answers from whatever database the backend is open on — not from an env var."""
    import api

    path = str(tmp_path / "demo.db")
    conn = db.connect(path)
    synthetic.seed_db(conn)
    conn.close()

    monkeypatch.setattr(api, "DB_PATH", path)
    with TestClient(api.app) as client:
        assert client.get("/demo").json() == {"demo": True}

    plain = str(tmp_path / "plain.db")
    c2 = db.connect(plain)
    db.init_db(c2)
    c2.close()
    monkeypatch.setattr(api, "DB_PATH", plain)
    with TestClient(api.app) as client:
        assert client.get("/demo").json() == {"demo": False}


def test_setup_refuses_to_seed_over_a_real_store(monkeypatch):
    """The one catastrophic outcome is seeding invented rows into the real record, so the
    setup script refuses a real path outright rather than trusting the launcher's env."""
    import demo_store_setup

    monkeypatch.setenv("HEALTH_DB", "health.db")
    with pytest.raises(SystemExit) as excinfo:
        demo_store_setup.main()
    assert "REFUSED" in str(excinfo.value) and "health.db" in str(excinfo.value)


def test_setup_refuses_an_unmarked_existing_database(tmp_path, monkeypatch):
    """A database sitting at the demo path that ISN'T marked is not ours to overwrite."""
    import demo_store_setup

    path = tmp_path / "demo.db"
    conn = db.connect(str(path))
    db.init_db(conn)
    conn.close()
    monkeypatch.setenv("HEALTH_DB", str(path))
    monkeypatch.setenv("HEALTH_IMAGING_DIR", str(tmp_path / "img"))
    monkeypatch.setenv("HEALTH_IMAGING_ARCHIVE", str(tmp_path / "arc"))
    monkeypatch.setenv("HEALTH_DOCUMENTS_DIR", str(tmp_path / "doc"))
    with pytest.raises(SystemExit) as excinfo:
        demo_store_setup.main()
    assert "not marked as a demo store" in str(excinfo.value)


def test_setup_refuses_a_real_audit_log(tmp_path, monkeypatch):
    """The audit log is the FIFTH real data source and the one that doesn't look like a
    store — it is a log file, not a folder, so the launcher forgot it and a demo window
    served the real send history (20 entries, payloads and all) under a badge saying the
    record was invented. Every other path can be right and this one wrong, so it is
    checked on its own."""
    import demo_store_setup

    for var, sub in (("HEALTH_DB", "demo.db"), ("HEALTH_IMAGING_DIR", "img"),
                     ("HEALTH_IMAGING_ARCHIVE", "arc"), ("HEALTH_DOCUMENTS_DIR", "doc")):
        monkeypatch.setenv(var, str(tmp_path / sub))
    monkeypatch.setenv("GATEWAY_AUDIT_LOG", "gateway_audit.log")
    with pytest.raises(SystemExit) as excinfo:
        demo_store_setup.main()
    assert "GATEWAY_AUDIT_LOG" in str(excinfo.value)


def test_launchers_redirect_every_real_source():
    """The launcher and the screenshot harness are the two places that decide which store
    the app opens, and neither is reachable by any other test here — demo.bat is batch and
    ui_shots.py starts its own process. A missing variable in either is silent and shows up
    as real data on a screen, so the assignments themselves are pinned."""
    root = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
    sources = ("HEALTH_DB", "HEALTH_IMAGING_DIR", "HEALTH_IMAGING_ARCHIVE",
               "HEALTH_DOCUMENTS_DIR", "GATEWAY_AUDIT_LOG")

    with open(os.path.join(root, "demo.bat"), encoding="utf-8") as fh:
        launcher = fh.read()
    for var in sources:
        assert f'set "{var}=%~dp0demo_store' in launcher, f"demo.bat leaves {var} on the real store"

    with open(os.path.join(root, "verify", "ui_shots.py"), encoding="utf-8") as fh:
        harness = fh.read()
    for var in sources:
        assert f'"{var}":' in harness, f"ui_shots.py leaves {var} on the real store"


def test_documents_are_seeded_as_scans(tmp_path, monkeypatch):
    """The reader shows the SCAN and only the scan, so a seeded document without a PDF
    opens on "No PDF for this document" and the page reads as broken - which is how the
    demo store shipped. Every document must therefore carry both halves: the PDF the
    reader displays and the text sidecar search reads."""
    import docstore

    n = synthetic.seed_documents(str(tmp_path))
    monkeypatch.setattr(docstore, "DOCS_DIR", str(tmp_path))

    assert docstore.available()
    rows = docstore.list_documents()
    assert len(rows) == n > 1
    assert rows == sorted(rows, key=lambda r: r["date"], reverse=True)   # newest first
    for row in rows:
        doc = docstore.get_document(row["id"])
        assert doc["formats"] == ["text", "pdf"], f"{row['title']} is missing a format"
        assert "INVENTED" in doc["text"]
        with open(docstore.pdf_path(row["id"]), "rb") as fh:
            assert fh.read(5) == b"%PDF-"


def test_seeded_documents_are_searchable_and_agree_with_the_seeded_chart(tmp_path, monkeypatch):
    """Search is the one consumer of the transcription, so a store whose text nothing finds
    is only half-seeded. The term is chosen deliberately: the alkaline phosphatase
    excursion these documents discuss is the same one seed_db writes into the chart, which
    is what lets the demo tell one story across pages instead of several unrelated ones."""
    import docstore

    synthetic.seed_documents(str(tmp_path))
    monkeypatch.setattr(docstore, "DOCS_DIR", str(tmp_path))

    hits = docstore.search("levothyroxine")
    assert len(hits) >= 3
    assert all(h["snippets"] for h in hits)
    # The column marker is a rendering instruction and must never reach a snippet.
    assert not any("|" in snip for h in hits for snip in h["snippets"])

    conn = db.connect(str(tmp_path / "demo.db"))
    synthetic.seed_db(conn)
    charted = {r["value"] for r in db.get_series(conn, "TSH")}
    assert 11.4 in charted, "the documents quote a peak the chart does not have"
    ferritin = {r["value"] for r in db.get_series(conn, "Ferritin")}
    assert {9.0, 52.0} <= ferritin, "the documents quote iron results the chart does not have"


def test_document_ids_are_stable_across_rebuilds(tmp_path):
    """A demo whose links moved every time the store was rebuilt would be worse than no
    demo - a bookmarked document, or a screenshot with a URL in it, would rot."""
    first = tmp_path / "a"
    second = tmp_path / "b"
    synthetic.seed_documents(str(first))
    synthetic.seed_documents(str(second))
    ids = []
    for folder in (first, second):
        with open(folder / "manifest.json", encoding="utf-8") as fh:
            ids.append([r["id"] for r in json.load(fh)])
    assert ids[0] == ids[1]


def test_reports_are_filed_where_an_imaging_disc_files_them(tmp_path):
    synthetic.seed_reports(str(tmp_path), "ACC1")
    written = os.path.join(str(tmp_path), "demo-disc", "other_content", "ACC1", "report.txt")
    assert os.path.isfile(written)
    with open(written, encoding="utf-8") as fh:
        body = fh.read()
    # It must announce itself as invented — someone reading it should never take it for a
    # real interpretation of a real study.
    assert "INVENTED" in body
    # And it needs the PDF a real disc files beside it: the reader shows the scan, so a
    # report with text alone renders an empty pane.
    scan = os.path.join(str(tmp_path), "demo-disc", "other_content", "ACC1", "reportFile.pdf")
    assert os.path.isfile(scan)
    with open(scan, "rb") as fh:
        assert fh.read(5) == b"%PDF-"
