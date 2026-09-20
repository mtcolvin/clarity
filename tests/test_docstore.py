"""
docstore.py — local access to the imported, split-up hospital record.

What these pin, in priority order:

1. NO LOCAL PATH ESCAPES. Callers address a document by opaque id; the store's own file
   paths stay server-side (the same rule reports.py applies to the accession number).
2. An id that isn't in the manifest CANNOT be turned into a filesystem read. The id
   reaches an os.path.join, so a traversal attempt has to be refused by the manifest
   check rather than by luck about what exists on disk.
3. Listing reads NO document text. The list route is metadata-only by design — a page
   that lists 47 documents should not pull 47 scanned records' prose into memory.
4. A missing or corrupt store degrades honestly instead of raising. It is a disposable
   derived artifact; a broken one should cost the Documents page, not the whole API.

Every test builds its own tiny store in tmp_path; the autouse fixture in conftest keeps
the real documents_store (the user's actual hospital record) out of reach regardless.
"""

from __future__ import annotations

import json
import os

import docstore


_seq = iter(range(1000))


def _store(tmp_path, monkeypatch, rows, texts=None, pdfs=None):
    """Build a throwaway store: manifest + optional .txt/.pdf sidecars. Each call gets a
    FRESH directory — reusing one let a previous call's sidecars leak into the next and
    made the formats test pass a file it hadn't written."""
    root = tmp_path / f"docs{next(_seq)}"
    root.mkdir()
    (root / "manifest.json").write_text(json.dumps(rows), encoding="utf-8")
    for doc_id, text in (texts or {}).items():
        (root / f"{doc_id}.txt").write_text(text, encoding="utf-8")
    for doc_id in (pdfs or []):
        (root / f"{doc_id}.pdf").write_bytes(b"%PDF-1.4 fake")
    monkeypatch.setattr(docstore, "DOCS_DIR", str(root))
    return root


ROW = {"id": "abc123", "date": "2025-07-29", "title": "Discharge summary",
       "title_it": "Lettera di dimissione", "n_pages": 4, "source": "record",
       "source_pages": [1, 4]}


def test_no_local_path_is_ever_returned(tmp_path, monkeypatch):
    root = _store(tmp_path, monkeypatch, [ROW], {"abc123": "Referto."}, ["abc123"])
    listed = docstore.list_documents()[0]
    detail = docstore.get_document("abc123")
    blob = json.dumps([listed, detail])
    assert str(root) not in blob
    assert ".pdf" not in blob and ".txt" not in blob
    # The path IS available server-side — this is about what callers get, not capability.
    assert docstore.pdf_path("abc123").endswith("abc123.pdf")


def test_an_unknown_id_cannot_reach_the_filesystem(tmp_path, monkeypatch):
    """The id is concatenated into a path, so the manifest check is the actual guard."""
    _store(tmp_path, monkeypatch, [ROW], {"abc123": "Referto."}, ["abc123"])
    for bogus in ("deadbeef", "../../health", "..\\..\\health", "abc123/../abc123"):
        assert docstore.get_document(bogus) is None
        assert docstore.pdf_path(bogus) is None


def test_listing_reads_no_document_text(tmp_path, monkeypatch):
    """Metadata-only listing is a deliberate discipline, not an accident of this data.

    Proved by making the sidecar UNREADABLE — a directory where the .txt should be — so
    any attempt to read it raises. list_documents() has no try/except around text, so a
    future refactor that starts reading here fails loudly instead of quietly costing a
    47-document page 47 scanned records' worth of prose."""
    root = _store(tmp_path, monkeypatch, [ROW])
    (root / "abc123.txt").mkdir()
    assert docstore.list_documents()[0]["id"] == "abc123"
    # ...and the detail path, which DOES read it, survives the same unreadable sidecar.
    assert docstore.get_document("abc123")["text"] == ""


def test_listing_is_newest_first_with_undated_last(tmp_path, monkeypatch):
    rows = [dict(ROW, id="a", date="2025-06-21"), dict(ROW, id="b", date="2025-07-29"),
            dict(ROW, id="c", date=None)]
    _store(tmp_path, monkeypatch, rows)
    assert [r["id"] for r in docstore.list_documents()] == ["b", "a", "c"]


def test_a_missing_or_corrupt_store_degrades_honestly(tmp_path, monkeypatch):
    monkeypatch.setattr(docstore, "DOCS_DIR", str(tmp_path / "nope"))
    assert docstore.available() is False
    assert docstore.list_documents() == []
    assert docstore.get_document("abc123") is None

    root = tmp_path / "broken"
    root.mkdir()
    (root / "manifest.json").write_text("{ this is not json", encoding="utf-8")
    monkeypatch.setattr(docstore, "DOCS_DIR", str(root))
    assert docstore.available() is True          # the file exists...
    assert docstore.list_documents() == []       # ...but a bad manifest is not a crash


def test_formats_reflect_what_is_actually_on_disk(tmp_path, monkeypatch):
    _store(tmp_path, monkeypatch, [ROW], {"abc123": "Referto."})   # text, no pdf
    assert docstore.get_document("abc123")["formats"] == ["text"]
    _store(tmp_path, monkeypatch, [ROW], {}, ["abc123"])           # pdf, no text
    assert docstore.get_document("abc123")["formats"] == ["pdf"]


def test_cp1252_text_decodes_without_raising(tmp_path, monkeypatch):
    """Real discs here are cp1252, same as the report archive."""
    root = _store(tmp_path, monkeypatch, [ROW])
    (root / "abc123.txt").write_bytes("Referto: perdita ematica pi\xf9 estesa.".encode("cp1252"))
    assert "estesa" in docstore.get_document("abc123")["text"]


# ----------------------------------------------------------------------- the API routes

def test_routes_serve_and_404_correctly(client, tmp_path, monkeypatch):
    _store(tmp_path, monkeypatch, [ROW], {"abc123": "Referto clinico."}, ["abc123"])
    index = client.get("/documents").json()
    assert index["available"] and len(index["documents"]) == 1
    assert index["documents"][0]["title"] == "Discharge summary"
    # Provenance travels; paths do not.
    assert index["documents"][0]["source_pages"] == [1, 4]
    assert "documents_store" not in client.get("/documents").text

    assert client.get("/documents/abc123").json()["text"] == "Referto clinico."
    assert client.get("/documents/abc123/pdf").status_code == 200
    assert client.get("/documents/abc123/pdf").headers["Cache-Control"] == "no-store"
    assert client.get("/documents/nope").status_code == 404
    assert client.get("/documents/nope/pdf").status_code == 404


def test_documents_route_is_honest_when_no_store_exists(client):
    """The conftest fixture points DOCS_DIR at an empty temp dir, so this is the
    no-store case — it must answer, not error."""
    r = client.get("/documents")
    assert r.status_code == 200
    body = r.json()
    assert body["available"] is False and body["documents"] == [] and body["reason"]


def test_the_real_document_store_is_never_read_in_tests():
    """Guards the conftest fixture itself: if it stops being applied, this trips instead
    of tests silently reading the user's actual hospital record."""
    assert "documents_store" != os.path.basename(docstore.DOCS_DIR)


# ------------------------------------------------------------------------------- search
# Search is why the OCR transcription is kept at all now that the reader shows the PDF
# (the text is no longer a reading surface). These pin that it finds things, that it
# can't be turned into "match everything", and that it covers BOTH local sources.

def test_search_finds_matches_and_ranks_by_count(tmp_path, monkeypatch):
    rows = [dict(ROW, id="a", title="Discharge summary"),
            dict(ROW, id="b", title="Lab report"),
            dict(ROW, id="c", title="Unrelated")]
    _store(tmp_path, monkeypatch, rows,
           {"a": "milza rotta; milza asportata; milza", "b": "milza", "c": "nothing here"})
    hits = docstore.search("milza")
    assert [h["id"] for h in hits] == ["a", "b"]        # most matches first
    assert hits[0]["n_matches"] == 3 and hits[1]["n_matches"] == 1
    assert "milza" in hits[0]["snippets"][0]


def test_search_is_case_insensitive_and_literal(tmp_path, monkeypatch):
    _store(tmp_path, monkeypatch, [ROW], {"abc123": "Frattura della MILZA (a rima multipla)"})
    assert docstore.search("milza")[0]["n_matches"] == 1
    # Literal, not regex: a stray bracket is a character to find, never a pattern to compile.
    assert docstore.search("(a rima")[0]["n_matches"] == 1
    assert docstore.search("[unclosed") == []


def test_a_too_short_query_matches_nothing(tmp_path, monkeypatch):
    """Guard against the degenerate case: a 1-character query would otherwise return the
    entire corpus, which is worse than useless on a medical record."""
    _store(tmp_path, monkeypatch, [ROW], {"abc123": "aaaa"})
    assert docstore.search("a") == []
    assert docstore.search("") == []
    assert docstore.search("   ") == []
    assert docstore.snippets("aaaa", "a") == (0, [])


def test_snippets_are_capped_and_contextual(tmp_path, monkeypatch):
    text = "x" * 200 + " milza " + "y" * 200
    n, snips = docstore.snippets(text, "milza")
    assert n == 1 and len(snips) == 1
    assert snips[0].startswith("…") and snips[0].endswith("…")   # elided on both sides
    assert len(snips[0]) < len(text)
    many, capped = docstore.snippets("milza " * 50, "milza")
    assert many == 50 and len(capped) == docstore.MAX_SNIPPETS   # count is full, list is capped


def test_search_route_covers_documents_and_reports(client, tmp_path, monkeypatch):
    import reports as reports_store
    _store(tmp_path, monkeypatch, [ROW], {"abc123": "lesione dissecante carotide sinistra"})
    folder = tmp_path / "archive" / "cd1" / "other_content" / "ACC1"
    folder.mkdir(parents=True)
    (folder / "report.txt").write_text("controllo dissezione carotide", encoding="utf-8")
    monkeypatch.setattr(reports_store, "ARCHIVE_DIR", str(tmp_path / "archive"))

    body = client.get("/documents/search?q=carotide").json()
    kinds = {h["kind"] for h in body["results"]}
    assert kinds == {"document", "report"}, "search must span BOTH local sources"
    assert all(h["snippets"] for h in body["results"])

    assert client.get("/documents/search?q=x").json()["results"] == []
    assert client.get("/documents/search").json()["results"] == []


def test_search_route_is_not_shadowed_by_the_id_route(client, tmp_path, monkeypatch):
    """/documents/search must not be parsed as a document whose id is 'search'. FastAPI
    matches in definition order, so this trips if the routes are ever reordered."""
    _store(tmp_path, monkeypatch, [ROW], {"abc123": "milza"})
    r = client.get("/documents/search?q=milza")
    assert r.status_code == 200 and "results" in r.json()


def test_accents_are_always_folded(tmp_path, monkeypatch):
    """OCR drops accents routinely and no query becomes ambiguous by ignoring them, so
    this fold is unconditional — not part of the approximate fallback."""
    _store(tmp_path, monkeypatch, [ROW], {"abc123": "perdita ematica più estesa"})
    hits = docstore.search("piu estesa")
    assert hits and hits[0]["approximate"] is False


def test_confusable_folding_is_a_FALLBACK_not_the_default(tmp_path, monkeypatch):
    """The ordering is the whole design. Folding "50"->"so" and "12"->"lz" buys about one
    extra document across real queries but will match English prose once English records
    land, so it runs only when the exact pass found nothing at all."""
    _store(tmp_path, monkeypatch, [dict(ROW, id="a"), dict(ROW, id="b")],
           {"a": "creatinina 1.2 mg/dL", "b": "creatlnina mangled by OCR"})
    exact = docstore.search("creatinina")
    assert [h["id"] for h in exact] == ["a"], "an exact hit must not drag in fuzzy ones"
    assert exact[0]["approximate"] is False

    # Only when nothing matches exactly does the fold run — and it says so. The query
    # here appears VERBATIM in neither document (note the digit 1), so the exact pass is
    # genuinely empty; a query that happens to be present would be found exactly and the
    # fallback would correctly never run.
    fuzzy = docstore.search("creat1nina")
    assert {h["id"] for h in fuzzy} == {"a", "b"}
    assert all(h["approximate"] for h in fuzzy)


def test_snippets_come_from_the_original_text_not_the_folded_form(tmp_path, monkeypatch):
    """Folding is length-preserving so offsets stay valid, which is what lets the snippet
    be cut from the REAL text. A snippet showing the mangled comparison form would be
    actively misleading."""
    _store(tmp_path, monkeypatch, [ROW], {"abc123": "Referto: MILZA a rima multipla"})
    hits = docstore.search("mllza")
    assert hits and "MILZA" in hits[0]["snippets"][0]


def test_search_route_reports_approximate(client, tmp_path, monkeypatch):
    _store(tmp_path, monkeypatch, [ROW], {"abc123": "lesione dissecante carotide"})
    exact = client.get("/documents/search?q=carotide").json()["results"]
    assert exact and exact[0]["approximate"] is False
    fuzzy = client.get("/documents/search?q=carotlde").json()["results"]
    assert fuzzy and fuzzy[0]["approximate"] is True
