"""
docstore.py — local access to imported clinical DOCUMENTS, sibling to reports.py.

Where reports.py serves the radiologist's report that rides on an imaging CD, this
serves everything else a hospital hands over: a discharge summary, an ER record, an
operative report, a pathology report, the nursing chart, the lab printouts. Those
arrive as one enormous scanned PDF per admission — 209 pages in the case this was
built for — which is unreadable as a single object. An offline ingest splits the
bundle on the per-document page counter hospital forms print in their footer, OCRs each
piece, and writes one PDF + one text sidecar per document into DOCS_DIR, plus a manifest.
(That offline builder has since been removed — see ROADMAP "Dropped". This module serves
the store it produced; the store itself is unaffected.)

PRIVACY: 100% local, no external path by construction — identical posture to
reports.py, and for the same reason. These documents open with the patient's name,
date of birth and record number, and their clinical content is the entire point, so
there is nothing to allowlist: an allowlist selects safe FIELDS and a discharge
summary has none. The LOCAL-ONLY boundary is the protection here, not redaction.
This module never imports gateway, never touches the network, and never writes to the
database. A document is not assembled into an export payload — the export bundle is
built by picture.py/explain.py from DB columns and user-edited text, and adding one of
these would have to be a new, deliberately-built path through the preview/consent chain.

Local file paths stay server-side: callers address a document by its opaque `id`
(derived from the source bundle plus its page range), never by path — the same rule
reports.py applies to the accession number, pinned by a test.

The store is DISPOSABLE. It is rebuilt from the source PDFs by the ingest script and
holds no state the DB depends on, so it is gitignored exactly like imaging_store/ and
imaging_archive/.
"""

from __future__ import annotations

import json
import os
import unicodedata

DOCS_DIR = os.environ.get("HEALTH_DOCUMENTS_DIR", "documents_store")

_MANIFEST = "manifest.json"
_ENCODINGS = ("utf-8", "cp1252", "latin-1")


def available() -> bool:
    """Whether an ingested document store exists. False degrades the route honestly
    rather than erroring, the same way missing OCR extras do."""
    return os.path.isfile(os.path.join(DOCS_DIR, _MANIFEST))


def _decode(raw: bytes) -> str:
    for enc in _ENCODINGS:
        try:
            return raw.decode(enc)
        except UnicodeDecodeError:
            continue
    return raw.decode("utf-8", errors="replace")


def _manifest() -> list[dict]:
    """The manifest as written by the ingest, or [] when there is no store. A corrupt
    manifest yields [] rather than raising: this is a disposable derived artifact, and
    a broken one should degrade the Documents page, not take down the API."""
    try:
        raw = open(os.path.join(DOCS_DIR, _MANIFEST), "rb").read()
        rows = json.loads(_decode(raw))
    except (OSError, ValueError):
        return []
    return rows if isinstance(rows, list) else []


def _public(row: dict) -> dict:
    """The shape safe to serialize. `source` and `source_pages` describe which bundle
    and which pages a document came from — provenance, no path, so a reader can find
    the original in the physical record."""
    return {
        "id": row.get("id"),
        "date": row.get("date"),
        "title": row.get("title") or "Clinical document",
        "title_original": row.get("title_it"),
        "n_pages": row.get("n_pages") or 0,
        "source": row.get("source"),
        "source_pages": row.get("source_pages"),
    }


def list_documents() -> list[dict]:
    """Every ingested document, NEWEST FIRST. Metadata only — no document text is read
    to build this, so listing the page never pulls clinical prose it doesn't need
    (the same discipline reports.list_reports keeps)."""
    rows = [_public(r) for r in _manifest() if r.get("id")]
    rows.sort(key=lambda r: (r["date"] or "", r["id"]), reverse=True)
    return rows


def get_document(doc_id: str) -> dict | None:
    """One document with its extracted text, or None for an unknown id. Text is read on
    DEMAND. The id is checked against the manifest rather than used to build a path, so
    a caller cannot walk out of the store with a crafted id."""
    row = next((r for r in _manifest() if r.get("id") == doc_id), None)
    if row is None:
        return None
    out = _public(row)
    out["text"] = ""
    path = os.path.join(DOCS_DIR, doc_id + ".txt")
    if os.path.isfile(path):
        try:
            out["text"] = _decode(open(path, "rb").read()).strip()
        except OSError:
            pass
    out["formats"] = ["text"] if out["text"] else []
    if pdf_path(doc_id):
        out["formats"].append("pdf")
    return out


SNIPPET_PAD = 60
MAX_SNIPPETS = 3
MIN_QUERY = 2

# Accents are folded ALWAYS: OCR drops and invents diacritics routinely, and no query
# becomes ambiguous by ignoring them.
#
# LANGUAGE-AGNOSTIC BY CONSTRUCTION. This was a hand-written table of the accented
# characters one corpus happened to contain, which silently did nothing for every
# language outside it — a Czech, Polish, Turkish or Vietnamese record would not have
# folded at all. Unicode already knows how to take a diacritic off any letter, so ask it
# rather than enumerate.
#
# The catch, and why this is per-character: NFD decomposition is NOT length-preserving
# ("à" becomes TWO code points, a base letter plus a combining mark), and the whole
# search depends on folded offsets indexing the ORIGINAL text so snippets are cut from
# real prose. So each character is decomposed on its own and collapsed back to its base
# ONLY when the remainder is pure combining marks — always exactly one character out for
# one character in.
def _strip_marks(ch: str) -> str:
    d = unicodedata.normalize("NFD", ch)
    if len(d) > 1 and all(unicodedata.combining(c) for c in d[1:]):
        return d[0]
    return ch


# Letters that carry their stroke INSIDE the glyph rather than as a combining mark, so
# Unicode has nothing to decompose. Short and closed-ended (there are only a handful in
# Latin scripts); anything not here simply stays as it is, which is the honest failure.
# One-to-one only: "ß" would fold to "ss" and break the length invariant above, so it
# is deliberately absent.
_STROKED = {"ø": "o", "ł": "l", "đ": "d", "ħ": "h", "ı": "i", "ſ": "s"}


def _fold_char(ch: str) -> str:
    return _STROKED.get(ch) or _strip_marks(ch)


_FOLD_CACHE: dict[str, str] = {}

# Glyph pairs OCR commonly confuses. Applied ONLY as a fallback pass (see
# `search`), never by default.
#
# This is what "make the OCR better for search" reduced to after measuring that the engine
# knobs do not help: tessdata_best came out FLAT on this corpus (337 -> 331 known strings,
# better on some terms and worse on others) and rendering at scale 4.0 was 8.9% WORSE. The
# errors that remain are character confusions, so tolerating them at MATCH time is cheaper
# than chasing them at OCR time.
#
# Why fallback and not default: measured over eight real queries, folding found exactly ONE
# extra document — while "50" folds to "so" and "12" to "lz", which will start matching
# English prose the moment English records land in the store. A tiny recall gain is not
# worth a permanent precision cost, but it IS worth having when the alternative is finding
# nothing at all. (Measured on the corpus this was built against: folding found exactly one
# extra document across eight real queries, while "50" folds to "so" and "12" to "lz".)
_CONFUSABLE = str.maketrans({
    "1": "l", "i": "l", "|": "l", "!": "l",      # 1 / i / | / ! <-> l
    "0": "o",                                     # 0 <-> O
    "5": "s", "$": "s",                           # 5 / $ <-> S
    "8": "b",                                     # 8 <-> B
})


def _fold(s: str, confusable: bool = False) -> str:
    """Lowercase and strip diacritics; optionally fold confusable glyphs too. Used ONLY
    for comparison — displayed text and snippets always come from the original string.

    Length-preserving in every branch (see _strip_marks), which is what lets the caller
    index the ORIGINAL text with an offset found in the folded one."""
    lowered = s.lower()
    out = "".join(
        _FOLD_CACHE[c] if c in _FOLD_CACHE else _FOLD_CACHE.setdefault(c, _fold_char(c))
        for c in lowered
    )
    return out.translate(_CONFUSABLE) if confusable else out


def snippets(text: str, query: str, limit: int = MAX_SNIPPETS,
             confusable: bool = False) -> tuple[int, list[str]]:
    """(total matches, up to `limit` context snippets) for a confusion-tolerant,
    case-insensitive substring search. Plain substring, not regex: the query comes from a
    user typing a drug or analyte name, and a stray '(' should find a parenthesis, not
    raise.

    Matching is accent-insensitive always, and with `confusable` also folds the glyph
    pairs Tesseract confuses, so an OCR slip like "creatlnina" is still found by
    "creatinina". Folding is length-preserving — every mapping is one character to one
    character — so offsets into the folded string index the ORIGINAL text directly, and
    the snippet returned is the real text, never the mangled comparison form."""
    if len(query.strip()) < MIN_QUERY:
        return 0, []
    # Precompose FIRST. Folding is per-character and therefore blind to a diacritic
    # stored as a SEPARATE combining mark ("e" + U+0301): it would survive the fold and
    # a user typing the unaccented word would find nothing. NFC joins those pairs back
    # into single characters that _fold can then strip. It runs on `text` — not on a
    # copy — precisely because the snippet is cut from this same string further down, so
    # the offsets keep pointing at what is actually returned.
    text = unicodedata.normalize("NFC", text)
    query = unicodedata.normalize("NFC", query)
    hay, needle = _fold(text, confusable), _fold(query.strip(), confusable)
    hits, out, start = 0, [], 0
    while True:
        i = hay.find(needle, start)
        if i < 0:
            break
        hits += 1
        if len(out) < limit:
            a, b = max(0, i - SNIPPET_PAD), min(len(text), i + len(needle) + SNIPPET_PAD)
            out.append(("…" if a else "") + " ".join(text[a:b].split()) + ("…" if b < len(text) else ""))
        start = i + len(needle)
    return hits, out


def _scan(query: str, confusable: bool) -> list[dict]:
    out = []
    for row in _manifest():
        doc_id = row.get("id")
        if not doc_id:
            continue
        path = os.path.join(DOCS_DIR, doc_id + ".txt")
        if not os.path.isfile(path):
            continue
        try:
            text = _decode(open(path, "rb").read())
        except OSError:
            continue
        n, snips = snippets(text, query, confusable=confusable)
        if n:
            out.append({**_public(row), "n_matches": n, "snippets": snips,
                        "approximate": confusable})
    out.sort(key=lambda r: (-r["n_matches"], r["date"] or ""))
    return out


def search(query: str) -> list[dict]:
    """Documents whose text contains `query`, most matches first.

    This is the OTHER reason the transcription is kept at all (the reader shows the PDF,
    not the text — see the module header on why OCR prose is not a reading surface): 47
    documents over 221 pages are unnavigable without it. Scanning every sidecar on each
    query is deliberate — the whole corpus is ~420 KB, so an index would be machinery for
    a search that already completes in milliseconds.

    Two passes. The first is exact (accent-insensitive). Only if it finds NOTHING does the
    second fold OCR-confusable glyphs and try again, flagging its results `approximate`.
    That ordering is the point: folding buys about one extra document across a set of real
    queries, but makes "50" match "so" — a cost worth paying only when the alternative is
    an empty result."""
    if len(query.strip()) < MIN_QUERY:
        return []
    return _scan(query, False) or _scan(query, True)


def pdf_path(doc_id: str) -> str | None:
    """The local PDF path for a document, or None. Server-side only — the client
    addresses the PDF by id, never by path. Manifest-checked like get_document, so an
    arbitrary id can't be turned into a filesystem read."""
    if not any(r.get("id") == doc_id for r in _manifest()):
        return None
    path = os.path.join(DOCS_DIR, doc_id + ".pdf")
    return path if os.path.isfile(path) else None
