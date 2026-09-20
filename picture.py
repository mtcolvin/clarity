"""
picture.py — the deterministic CONTEXT assembler for the full-picture export handoff.

Sibling to explain.py. Where explain.py assembles ONE metric's bundle (readings,
findings, thresholds), this module assembles everything a metric bundle structurally
cannot carry: the conditions the person lives with, the medications they take, the
dated events on their timeline, their physical measurements, and the radiology the
imaging store holds. A lab value read without them is read blind — a creatinine trend
means something different on a drug that raises it, and an out-of-range result three
days after a procedure is not the same finding as the same number out of nowhere.

Like explain.py it is PURE: it takes already-fetched rows and returns a dict. No SQL,
no provider call, no network — api.py gathers the substrate and the hosted call runs
from there through the privacy gateway.

PRIVACY POSTURE (CLAUDE.md "The export handoff"). Three separate footings, deliberately
not conflated:

  * The DB half (profile / conditions / medications / events) is Model-A structural
    cleanliness: assembled from named columns, never from a name/DOB/MRN/physician/
    facility column. `date_of_birth` is READ (age is computed from it) and NEVER
    COPIED — `assemble_context` takes the profile row and emits `age_years`, so the
    DOB is structurally incapable of reaching the payload. The user approved sending
    age and biological sex; both are medically load-bearing and neither is on the
    charter's PII list. Note this DOES change the #18 line "sex never leaves the
    machine" — a deliberate, documented change, not a drift.

  * The IMAGING half rides dicom_store's existing display allowlist (StudyDate /
    StudyDescription / Modality / BodyPartExamined and counts). Every PII tag a DICOM
    header carries is excluded by never being read, exactly as on the viewer.

  * The REPORT half has NO structural footing and does not pretend to. A radiology
    report is one block of prose with no fields: an allowlist has nothing to select
    and the gateway's regex scrub cannot catch an arbitrary clinician's name (the
    charter concedes this). So report text is included ONLY as text the user has
    reviewed and EDITED in the preview — `assemble_context` receives the approved
    strings from the caller and never reads a report file itself. Human redaction at
    the chokepoint is the control here; the scrub is belt-and-suspenders behind it.
    A report's `id` is deliberately NOT carried into the payload: it is derived from
    the accession number (an identifier the charter names) and tells the model
    nothing, so it stays a client-side handle only.
"""

from __future__ import annotations

from datetime import date


def age_years(date_of_birth: str | None, as_of: str | None) -> int | None:
    """Whole years between a birth date and `as_of`, or None when either is missing or
    unparseable. This is the ONLY thing the date of birth is used for: the caller hands
    in the profile row, this returns an age, and the DOB itself is never placed in the
    returned bundle — so it cannot reach an outbound payload by any code path here."""
    if not date_of_birth or not as_of:
        return None
    try:
        born = date.fromisoformat(date_of_birth)
        today = date.fromisoformat(as_of)
    except (TypeError, ValueError):
        return None
    years = today.year - born.year
    if (today.month, today.day) < (born.month, born.day):
        years -= 1
    return years if years >= 0 else None


def _prose(value) -> str | None:
    """One free-text field as it should appear in the payload: stripped, and None when
    nothing is left.

    Whitespace-only counts as EMPTY. The preview's editor tells the user that clearing a
    box removes that text, and a box holding a single space looks cleared — so treating
    it as content would send something the user believes they deleted. Same rule
    assemble_reports applies to report text, applied to the shorter prose for the same
    reason."""
    text = (value or "").strip()
    return text or None


def _measurements(rows: list[dict]) -> list[dict]:
    """Weight/height history oldest-first, as stored — value and unit exactly as entered
    (no lb/kg conversion), the same honesty the observations table keeps."""
    out = [{"recorded_on": r.get("recorded_on"), "value": r.get("value"),
            "unit": r.get("unit")} for r in rows]
    out.sort(key=lambda r: r["recorded_on"] or "")
    return out


def assemble_profile(profile_row: dict | None, weight_rows: list[dict],
                     height_rows: list[dict], as_of: str | None) -> dict:
    """The person-level context: biological sex, age in whole years, and the physical
    measurement histories. `profile_row` is db.get_profile()'s output (sex,
    date_of_birth) — the DOB is consumed by age_years and dropped."""
    row = profile_row or {}
    return {
        "sex": row.get("sex"),
        "age_years": age_years(row.get("date_of_birth"), as_of),
        "weight": _measurements(weight_rows),
        "height": _measurements(height_rows),
    }


def assemble_conditions(rows: list[dict]) -> list[dict]:
    """Conditions oldest-onset-first. `notes` is the USER's own annotation and travels
    verbatim — it is free text, so it is one of the fields the preview exists to let
    them read before it leaves."""
    out = [{"name": r.get("name"), "icd10": r.get("icd10"), "status": r.get("status"),
            "onset_on": r.get("onset_on"), "resolved_on": r.get("resolved_on"),
            "notes": _prose(r.get("notes"))} for r in rows]
    out.sort(key=lambda r: (r["onset_on"] or "", r["name"] or ""))
    return out


def assemble_medications(rows: list[dict]) -> list[dict]:
    """Medications oldest-start-first. `active` is carried through as db.list_medications
    derives it (end_date IS NULL), never recomputed here — this module states no fact the
    caller didn't already establish."""
    out = [{"name": r.get("name"), "dose": r.get("dose"), "frequency": r.get("frequency"),
            "start_date": r.get("start_date"), "end_date": r.get("end_date"),
            "active": r.get("active"), "notes": _prose(r.get("notes"))} for r in rows]
    out.sort(key=lambda r: (r["start_date"] or "", r["name"] or ""))
    return out


def assemble_events(rows: list[dict]) -> list[dict]:
    """Timeline events oldest-first. Both `title` and `notes` are user free text."""
    out = [{"date": r.get("event_date"), "type": r.get("event_type"),
            "title": _prose(r.get("title")), "notes": _prose(r.get("notes"))} for r in rows]
    out.sort(key=lambda r: (r["date"] or "", r["title"] or ""))
    return out


def assemble_imaging(studies: list[dict]) -> list[dict]:
    """One row per locally-stored DICOM study, from dicom_store.public_studies() — whose
    tags are ALREADY allowlisted (StudyDate / StudyDescription / Modality /
    BodyPartExamined / counts), so every PII tag in the header is excluded by never
    having been read. The study `id` is a DICOM UID: it identifies the exam to this
    machine's viewer and means nothing to a model, so it is not carried."""
    out = []
    for st in studies:
        series = st.get("series") or []
        out.append({
            "study_date": st.get("StudyDate"),
            "description": st.get("StudyDescription"),
            "modalities": sorted({s["Modality"] for s in series if s.get("Modality")}),
            "body_parts": sorted({s["BodyPartExamined"] for s in series
                                  if s.get("BodyPartExamined")}),
            "n_series": len(series),
            "n_images": sum(s.get("n_slices") or 0 for s in series),
        })
    out.sort(key=lambda r: r["study_date"] or "")
    return out


def assemble_reports(approved: list[dict]) -> list[dict]:
    """Radiology report text the user reviewed and approved in the preview.

    `approved` is [{study_date, study_description, text}] built by the caller from the
    user's edited drafts — this function reads no file and resolves no id. A blank text
    means the user emptied the box, which is a decision to send nothing for that report,
    so the row is dropped entirely rather than sent as an empty string."""
    out = [{"study_date": r.get("study_date"),
            "study_description": r.get("study_description"),
            "text": (r.get("text") or "").strip()} for r in approved]
    out = [r for r in out if r["text"]]
    out.sort(key=lambda r: r["study_date"] or "")
    return out


def assemble_context(*, profile_row, weight_rows, height_rows, conditions, medications,
                     events, imaging_studies, approved_reports, as_of) -> dict:
    """The whole non-metric half of a full-picture export, as the top-level keys the
    gateway's `export_metrics` allowlist names individually. Keys are ALWAYS present
    (empty list / null fields when there's nothing) so the preview can honestly render
    "Conditions (0)" rather than silently omitting a section the reader would then not
    know to look for."""
    return {
        "profile": assemble_profile(profile_row, weight_rows, height_rows, as_of),
        "conditions": assemble_conditions(conditions),
        "medications": assemble_medications(medications),
        "events": assemble_events(events),
        "imaging": assemble_imaging(imaging_studies),
        "reports": assemble_reports(approved_reports),
    }
