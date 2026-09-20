"""
Local radiology-report access — 100% on-machine, the same posture as dicom_store.

WHAT THIS IS. An imaging CD carries, beside the DICOM images, the radiologist's written
report (`other_content/<accession>/report.txt|.htm|reportFile.pdf`). That text exists NOWHERE
in the DICOM data — the only SR objects on these discs are radiation-dose reports, not
interpretations — so without this module the one document that says what the images MEAN is
invisible to the app.

PRIVACY POSTURE (charter prime directive). A report is free prose that OPENS with the
patient's name, date of birth and the facility — exactly the identifiers the charter forbids
from leaving the machine. Therefore:

  - Reading is local: files are read from a local folder and returned over loopback. No
    gateway, no network, no model. There is no external path here by construction.
  - A report is NEVER assembled into an export payload. The export bundle is built by
    explain.py from DB columns only; nothing here feeds it. Sending one would have to be a
    new, deliberately-built path through the gateway's preview/consent chain.
  - Nothing is written to the database. Reports are read-only files on disk, like the images.
  - The ACCESSION NUMBER is treated as an identifier (the charter names record numbers
    explicitly). It is used ONLY as an internal join key and is never returned by any
    function here: callers see an opaque `id` derived from it. File paths stay server-side
    for the same reason.

Deliberately NOT allowlist-filtered, unlike dicom_store's metadata: an allowlist selects
known-safe FIELDS, and a report has no fields — it is one block of prose whose clinical
content is the whole point. The protection is therefore the local-only boundary above, not
redaction; masking the prose would destroy the thing the user came to read.
"""

from __future__ import annotations

import hashlib
import os
import re
from html.parser import HTMLParser

# Where the non-DICOM contents of each imported disc live (import_imaging_cd.py writes here).
ARCHIVE_DIR = os.environ.get("HEALTH_IMAGING_ARCHIVE", "imaging_archive")

# Hospital systems write these in a Windows codepage far more often than UTF-8; try in order
# and keep the first that decodes. latin-1 cannot fail, so it is the guaranteed terminator.
_ENCODINGS = ("utf-8", "cp1252", "latin-1")

_TEXT_NAMES = ("report.txt",)
_HTML_NAMES = ("report.htm", "report.html")
_PDF_NAMES = ("reportFile.pdf", "report.pdf")
_CONTENT_DIR = "other_content"


def available() -> bool:
    """False when there's no archive folder — the route then degrades honestly rather than
    500-ing, exactly like dicom_store without pydicom."""
    return os.path.isdir(ARCHIVE_DIR)


def _short_id(value: str) -> str:
    """A stable, opaque handle for an accession number, so the identifier itself never
    appears in a URL or a response."""
    return hashlib.sha1(value.encode("utf-8")).hexdigest()[:12]


def _decode(raw: bytes) -> str:
    for enc in _ENCODINGS:
        try:
            return raw.decode(enc)
        except UnicodeDecodeError:
            continue
    return raw.decode("latin-1", errors="replace")


class _TextExtractor(HTMLParser):
    """Tags out, text through. Used only for the .htm fallback — every disc so far also ships
    a .txt, which is preferred because it needs no interpretation at all."""

    def __init__(self):
        super().__init__(convert_charrefs=True)
        self.parts: list[str] = []
        self._skip = 0

    def handle_starttag(self, tag, attrs):
        if tag in ("script", "style"):
            self._skip += 1
        elif tag in ("br", "p", "div", "tr", "table", "h1", "h2", "h3"):
            self.parts.append("\n")

    def handle_endtag(self, tag):
        if tag in ("script", "style") and self._skip:
            self._skip -= 1

    def handle_data(self, data):
        if not self._skip:
            self.parts.append(data)

    def text(self) -> str:
        out = "".join(self.parts)
        out = re.sub(r"[ \t ]+", " ", out)
        out = re.sub(r"\n\s*\n\s*\n+", "\n\n", out)
        return "\n".join(line.strip() for line in out.splitlines()).strip()


def _find(folder: str, names) -> str | None:
    for name in names:
        path = os.path.join(folder, name)
        if os.path.isfile(path):
            return path
    # Case-insensitive fallback: a disc burned on a case-preserving filesystem.
    try:
        actual = {n.lower(): n for n in os.listdir(folder)}
    except OSError:
        return None
    for name in names:
        if name.lower() in actual:
            return os.path.join(folder, actual[name.lower()])
    return None


def _accession_to_study() -> dict[str, dict]:
    """{accession: study info} for the imported images, by reading ONE header per study.

    The AccessionNumber is the only reliable link between a report folder and its images: the
    archive and the image store do NOT agree on folder names (the first disc is `cd1` in the
    archive and `cd-import` in the store), and one exam can span two discs (this library's
    2025-06-30 study covers cd2 AND cd3, which is why both carry the same report). Matching on
    the accession is exact where a folder-name join would be wrong on both counts.

    This deliberately reads a tag outside dicom_store's display allowlist. It stays here, in
    the module that needs it, and the value never leaves this function — only the opaque study
    id and the already-allowlisted date/description do.
    """
    try:
        import pydicom

        import dicom_store
    except ImportError:
        return {}
    out: dict[str, dict] = {}
    for study in dicom_store.scan_studies():
        series = study.get("series") or []
        if not series or not series[0].get("_slices"):
            continue
        try:
            ds = pydicom.dcmread(series[0]["_slices"][0][0], stop_before_pixels=True)
        except Exception:
            continue
        accession = str(ds.get("AccessionNumber", "") or "").strip()
        if accession:
            out.setdefault(accession, {
                "study_id": study["id"],
                "study_date": study.get("StudyDate"),
                "study_description": study.get("StudyDescription"),
            })
    return out


def _scan_folders(root: str) -> dict[str, dict]:
    """{accession: {folder, formats, discs}} for every report folder in the archive."""
    found: dict[str, dict] = {}
    try:
        discs = sorted(os.listdir(root))
    except OSError:
        return found
    for disc in discs:
        content = os.path.join(root, disc, _CONTENT_DIR)
        if not os.path.isdir(content):
            continue
        try:
            entries = sorted(os.listdir(content))
        except OSError:
            continue
        for accession in entries:
            folder = os.path.join(content, accession)
            if not os.path.isdir(folder):
                continue
            text_path = _find(folder, _TEXT_NAMES) or _find(folder, _HTML_NAMES)
            pdf_path = _find(folder, _PDF_NAMES)
            if not text_path and not pdf_path:
                continue        # e.g. the disc's bundled `js/` folder — not a report
            # The SAME exam delivered on two discs appears twice, byte-identical. Keep one
            # entry and remember it came from both, rather than listing a duplicate report.
            entry = found.setdefault(accession, {
                "folder": folder, "text_path": text_path, "pdf_path": pdf_path, "discs": [],
            })
            entry["discs"].append(disc)
            entry["text_path"] = entry["text_path"] or text_path
            entry["pdf_path"] = entry["pdf_path"] or pdf_path
    return found


def _records(root: str | None = None) -> dict[str, dict]:
    """{report_id: record} — the internal shape, carrying paths and the accession."""
    root = root or ARCHIVE_DIR
    if not os.path.isdir(root):
        return {}
    links = _accession_to_study()
    out: dict[str, dict] = {}
    for accession, info in _scan_folders(root).items():
        link = links.get(accession, {})
        formats = []
        if info["text_path"]:
            formats.append("text")
        if info["pdf_path"]:
            formats.append("pdf")
        out[_short_id(accession)] = {
            "id": _short_id(accession),
            "study_id": link.get("study_id"),
            "study_date": link.get("study_date"),
            "study_description": link.get("study_description"),
            "formats": formats,
            "n_discs": len(info["discs"]),
            "_accession": accession,
            "_text_path": info["text_path"],
            "_pdf_path": info["pdf_path"],
        }
    return out


def _public(record: dict) -> dict:
    """Strip every internal key — the accession and the local file paths stay on the server."""
    return {k: v for k, v in record.items() if not k.startswith("_")}


def list_reports(root: str | None = None) -> list[dict]:
    """Every report found, newest study first. Metadata only — no report TEXT is read here, so
    listing the page never pulls clinical prose into memory it doesn't need."""
    records = [_public(r) for r in _records(root).values()]
    records.sort(key=lambda r: (r.get("study_date") or "", r["id"]), reverse=True)
    return records


def get_report(report_id: str, root: str | None = None) -> dict | None:
    """One report with its extracted text, or None if the id is unknown. Text is read on
    DEMAND — the list route doesn't touch it."""
    record = _records(root).get(report_id)
    if record is None:
        return None
    out = _public(record)
    path = record["_text_path"]
    out["text"] = ""
    out["source"] = None
    if path:
        try:
            raw = _decode(open(path, "rb").read())
        except OSError:
            raw = ""
        if path.lower().endswith((".htm", ".html")):
            parser = _TextExtractor()
            parser.feed(raw)
            out["text"] = parser.text()
            out["source"] = "html"
        else:
            out["text"] = "\n".join(line.rstrip() for line in raw.splitlines()).strip()
            out["source"] = "text"
    return out


def pdf_path(report_id: str, root: str | None = None) -> str | None:
    """The local PDF path for a report, or None. Server-side only — the client addresses the
    PDF by report id, never by path."""
    record = _records(root).get(report_id)
    return record["_pdf_path"] if record else None


def reports_by_study(root: str | None = None) -> dict[str, list[str]]:
    """{study_id: [report_id, ...]} so the imaging viewer can link a study to its report."""
    out: dict[str, list[str]] = {}
    for record in _records(root).values():
        if record["study_id"]:
            out.setdefault(record["study_id"], []).append(record["id"])
    return out
