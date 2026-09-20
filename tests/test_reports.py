"""
Radiology reports (reports.py + /reports routes).

The load-bearing tests here are the two boundaries the module exists behind:
  - the ACCESSION NUMBER and local FILE PATHS never reach a response (the accession is a
    record number, which the privacy charter names explicitly), and
  - a report is read from a LOCAL folder and served over loopback — there is no gateway,
    no network, no model, and nothing is written to the database.

Everything runs against a synthetic archive in a temp folder; conftest's autouse fixture
points ARCHIVE_DIR away from the user's real reports for every other test in the suite.
"""

from __future__ import annotations

import json
import os

import pytest
from fastapi.testclient import TestClient

import api
import reports

ACCESSION = "ATCAN9999001"
BODY = "REFERTO\nPaziente: Mario Rossi\nEsame: TC del torace\n\nConclusioni: nulla di rilevante."


@pytest.fixture
def archive(tmp_path, monkeypatch):
    """A synthetic imaging archive laid out like a real disc:
    <archive>/<disc>/other_content/<accession>/report.txt|reportFile.pdf"""
    def make(disc, accession=ACCESSION, text=BODY, html=None, pdf=b"%PDF-1.4 fake"):
        folder = tmp_path / "archive" / disc / "other_content" / accession
        folder.mkdir(parents=True, exist_ok=True)
        if text is not None:
            # cp1252 is what the real discs use — the decoder must handle it.
            (folder / "report.txt").write_bytes(text.encode("cp1252"))
        if html is not None:
            (folder / "report.htm").write_bytes(html.encode("cp1252"))
        if pdf is not None:
            (folder / "reportFile.pdf").write_bytes(pdf)
        return folder

    monkeypatch.setattr(reports, "ARCHIVE_DIR", str(tmp_path / "archive"))
    # No imaging store in these tests, so there are no studies to link to; the link path
    # has its own test below.
    return make


def test_scan_finds_a_report(archive):
    archive("cd1")
    found = reports.list_reports()
    assert len(found) == 1
    assert found[0]["formats"] == ["text", "pdf"]


def test_the_same_exam_on_two_discs_is_one_report(archive):
    """One exam can be delivered across two discs — this library's 2025-06-30 study covers
    cd2 AND cd3, both carrying a byte-identical report. That must list ONCE, not twice."""
    archive("cd2")
    archive("cd3")
    found = reports.list_reports()
    assert len(found) == 1
    assert found[0]["n_discs"] == 2


def test_accession_and_paths_never_reach_a_response(archive, tmp_path):
    """The accession is a record number (the charter names those explicitly) and a file path
    is server-only. Both are used internally; neither may appear in what leaves the server."""
    archive("cd1")
    import json
    blob = json.dumps(reports.list_reports()) + json.dumps(reports.get_report(
        reports.list_reports()[0]["id"]))
    assert ACCESSION not in blob
    assert str(tmp_path) not in blob
    assert "report.txt" not in blob
    # The id is opaque — derived from the accession, not the accession itself.
    assert reports.list_reports()[0]["id"] != ACCESSION


def test_report_text_is_returned_verbatim(archive):
    archive("cd1")
    got = reports.get_report(reports.list_reports()[0]["id"])
    assert got["source"] == "text"
    assert got["text"] == BODY          # exactly as written, nothing summarised or stripped


def test_html_report_is_extracted_when_there_is_no_txt(archive):
    """Some discs ship only the .htm. Tags out, text through — and script/style contents
    must not leak into the reading pane."""
    archive("cd1", text=None,
            html="<html><style>p{color:red}</style><body><p>Referto</p>"
                 "<p>Conclusioni: nulla.</p><script>var x=1</script></body></html>")
    got = reports.get_report(reports.list_reports()[0]["id"])
    assert got["source"] == "html"
    assert "Referto" in got["text"] and "Conclusioni: nulla." in got["text"]
    assert "color:red" not in got["text"] and "var x" not in got["text"]


def test_unknown_id_is_none_not_an_error(archive):
    archive("cd1")
    assert reports.get_report("nosuchid") is None
    assert reports.pdf_path("nosuchid") is None


def test_a_folder_without_a_report_is_not_listed(archive, tmp_path):
    """A disc's bundled `js/` folder sits beside the report folders and must not be mistaken
    for one."""
    archive("cd1")
    junk = tmp_path / "archive" / "cd1" / "other_content" / "js"
    junk.mkdir(parents=True)
    (junk / "exec.js").write_text("var x = 1")
    assert len(reports.list_reports()) == 1


def test_available_is_false_without_an_archive(tmp_path, monkeypatch):
    monkeypatch.setattr(reports, "ARCHIVE_DIR", str(tmp_path / "nothing here"))
    assert reports.available() is False
    assert reports.list_reports() == []


# ------------------------------------------------------------------------------ routes

def test_routes_serve_list_text_and_pdf(archive):
    archive("cd1")
    client = TestClient(api.app)

    index = client.get("/reports").json()
    assert index["available"] is True and len(index["reports"]) == 1
    rid = index["reports"][0]["id"]

    detail = client.get(f"/reports/{rid}").json()
    assert detail["text"] == BODY

    pdf = client.get(f"/reports/{rid}/pdf")
    assert pdf.status_code == 200
    assert pdf.headers["content-type"] == "application/pdf"
    # Same rule as rendered slices: a medical document must not linger in the disk cache.
    assert pdf.headers["cache-control"] == "no-store"
    assert pdf.content.startswith(b"%PDF")


def test_routes_404_on_an_unknown_report(archive):
    archive("cd1")
    client = TestClient(api.app)
    assert client.get("/reports/nosuchid").status_code == 404
    assert client.get("/reports/nosuchid/pdf").status_code == 404


def test_index_degrades_honestly_without_an_archive(tmp_path, monkeypatch):
    monkeypatch.setattr(reports, "ARCHIVE_DIR", str(tmp_path / "nothing here"))
    body = TestClient(api.app).get("/reports").json()
    assert body["available"] is False
    assert body["reports"] == []
    assert body["reason"]


def test_a_report_with_no_pdf_reports_only_text(archive):
    archive("cd1", pdf=None)
    client = TestClient(api.app)
    rid = client.get("/reports").json()["reports"][0]["id"]
    assert client.get(f"/reports/{rid}").json()["formats"] == ["text"]
    assert client.get(f"/reports/{rid}/pdf").status_code == 404


# --------------------------------------------------------------------- timeline entries

def _study_with_report(archive, tmp_path, monkeypatch):
    """A synthetic archive report plus a DICOM study carrying the matching accession."""
    pydicom = pytest.importorskip("pydicom")
    from pydicom.data import get_testdata_file

    archive("cd1")
    store = tmp_path / "images"
    store.mkdir()
    ds = pydicom.dcmread(get_testdata_file("CT_small.dcm"))
    ds.AccessionNumber = ACCESSION
    ds.save_as(str(store / "IM000000"), enforce_file_format=True)

    import dicom_store
    monkeypatch.setattr(dicom_store, "IMAGING_DIR", str(store))
    monkeypatch.setattr(dicom_store, "_scan_cache", {})


def test_the_report_rides_on_its_imaging_entry(archive, tmp_path, monkeypatch):
    """A report is NOT a separate dated event — it is the written half of the same exam, so
    it belongs INSIDE the imaging entry rather than as a second row that happens to share a
    date. Two rows made one thing look like two."""
    _study_with_report(archive, tmp_path, monkeypatch)

    timeline = TestClient(api.app).get("/timeline").json()
    assert [e for e in timeline if e["kind"] == "report"] == [], "no separate report entry"

    imaging = [e for e in timeline if e["kind"] == "imaging"]
    assert len(imaging) == 1
    attached = imaging[0]["detail"]["reports"]
    assert len(attached) == 1
    assert attached[0]["id"] == reports.list_reports()[0]["id"]
    assert "pdf" in attached[0]["formats"]

    # No report PROSE reaches the timeline — only the id and its formats.
    assert BODY not in json.dumps(timeline)


def test_timeline_entries_carry_no_presentational_ranking(archive, tmp_path, monkeypatch):
    """Every entry reads with equal weight. The old `prominence` tier is gone from the
    payload entirely — deciding what deserves attention is the reader's job, and the kind
    filters are the tool for it."""
    _study_with_report(archive, tmp_path, monkeypatch)
    timeline = TestClient(api.app).get("/timeline").json()
    assert timeline
    assert all("prominence" not in e for e in timeline)


def test_a_study_without_a_report_carries_an_empty_list(archive, tmp_path, monkeypatch):
    """An imaging study whose disc carried no report still renders — the field is present
    and empty rather than missing, so the client needs no special case."""
    pydicom = pytest.importorskip("pydicom")
    from pydicom.data import get_testdata_file

    archive("cd1", accession="SOMETHINGELSE")
    store = tmp_path / "images"
    store.mkdir()
    ds = pydicom.dcmread(get_testdata_file("CT_small.dcm"))
    ds.AccessionNumber = "NOTMATCHING"
    ds.save_as(str(store / "IM000000"), enforce_file_format=True)
    import dicom_store
    monkeypatch.setattr(dicom_store, "IMAGING_DIR", str(store))
    monkeypatch.setattr(dicom_store, "_scan_cache", {})

    imaging = [e for e in TestClient(api.app).get("/timeline").json() if e["kind"] == "imaging"]
    assert len(imaging) == 1
    assert imaging[0]["detail"]["reports"] == []
    assert len(reports.list_reports()) == 1       # still listed as a document


# ------------------------------------------------------------- linking reports to studies

def test_report_links_to_its_study_by_accession(archive, tmp_path, monkeypatch):
    """The accession is the only reliable link: the archive and the image store do NOT agree
    on folder names (the first disc is `cd1` in one and `cd-import` in the other), so a
    folder-name join would be wrong. Build a DICOM study carrying the accession and check the
    report finds it."""
    pydicom = pytest.importorskip("pydicom")
    from pydicom.data import get_testdata_file

    archive("cd1")
    store = tmp_path / "images"
    store.mkdir()
    ds = pydicom.dcmread(get_testdata_file("CT_small.dcm"))
    ds.AccessionNumber = ACCESSION
    ds.save_as(str(store / "IM000000"), enforce_file_format=True)

    import dicom_store
    monkeypatch.setattr(dicom_store, "IMAGING_DIR", str(store))
    monkeypatch.setattr(dicom_store, "_scan_cache", {})

    study_id = dicom_store.scan_studies()[0]["id"]
    assert reports.reports_by_study().get(study_id) == [reports.list_reports()[0]["id"]]

    # ...and the imaging route surfaces it, so the viewer can offer the report beside images.
    studies = TestClient(api.app).get("/imaging/studies").json()["studies"]
    assert studies[0]["report_ids"] == [reports.list_reports()[0]["id"]]
    # The accession still doesn't leak through the imaging route.
    assert ACCESSION not in str(studies)
