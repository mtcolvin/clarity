"""
timeline.py — read-only aggregation layer for the Timeline view.

Merges several sources (conditions, medications, events, lab observations) into one
chronological list of TimelineEntry records the API serializes. It ORCHESTRATES the
existing layers — reads through db.py, and for the lab "notable" count reuses the
pure analysis engine — but adds no SQL and no new detection math of its own (the
same way analysis.py returns Flag dataclasses the API serializes).

Extensibility: each source is a builder function `(conn, ctx) -> list[TimelineEntry]`
in SOURCES. Adding Documents later is just one more builder
appended to SOURCES, emitting the same TimelineEntry shape — the merge/sort and the
client's render/filter machinery are untouched.
"""

from __future__ import annotations

from dataclasses import dataclass, field

from db import (
    list_conditions,
    list_medications,
    list_events,
    list_immunizations,
    list_collections,
    list_observations,
    list_metrics_with_units,
    get_series,
    get_metric_settings,
)
from analysis import analyze_history, analyze_series, _denoise
import dicom_store
import reports


@dataclass
class TimelineEntry:
    """One dated thing on the Timeline. `kind` is the source category (drives the
    filter + visual marker); `subtype` is a within-kind label (onset/resolved,
    started/ended, or an event_type). `detail` is the source-specific payload for
    the expanded view; `link` is an in-app nav target; `ref_id` is the source row
    id (events use it for edit/delete).

    Every entry carries EQUAL visual weight. An earlier build ranked entries into
    presentational tiers (dot size, type weight) from structural facts; that was removed at
    the user's direction — deciding what deserves attention is the reader's job, and the
    filters are the tool for it. Nothing here should imply one dated fact matters more than
    another."""
    date: str                       # ISO 'YYYY-MM-DD' — the sort key
    kind: str                       # 'condition' | 'medication' | 'event' | 'lab'
    title: str
    subtype: str | None = None
    detail: dict = field(default_factory=dict)
    link: str | None = None
    ref_id: int | None = None


# The notable flag kinds for the lab count. personal_range is DELIBERATELY excluded:
# in personal-baseline mode a chronic lab-range exceedance is reframed to personal_range
# (info), so it does NOT inflate the notable count — only a genuine break (personal_baseline)
# or a fresh threshold/delta does.
_NOTABLE_KINDS = ("out_of_range", "personal_baseline", "threshold", "delta")


def _display_value(row: dict) -> str:
    """Compact display of a reading, per result_type (mirrors the table's rendering),
    so the client can show lab detail without re-deriving it.

    Numeric/censored values pass through `_denoise` (round-to-10): a DERIVED metric's
    value is a raw float, so a subtraction like Total − Direct yields 0.7000000000000001
    for what is really 0.7. Denoising collapses that binary tail while leaving every clean
    stored value byte-identical (122.0 stays 122.0) — the same treatment the flag messages
    and the client's chart/table already apply, so the timeline panel no longer shows the
    15-digit noise."""
    t = row.get("result_type") or "numeric"
    unit = row.get("unit") or ""
    suffix = f" {unit}" if unit else ""
    if t == "qualitative":
        return row.get("value_text") or ""
    if t == "censored":
        return f"{row.get('operator') or ''}{_denoise(row.get('value'))}{suffix}"
    return f"{_denoise(row.get('value'))}{suffix}"


def _notable_dates(conn, metric_config: dict,
                   derived_series: dict[str, list[dict]] | None = None) -> dict[str, set[str]]:
    """Map each date -> the set of metrics whose reading that day is notable, using
    the SAME engine the rest of the app uses, mode-resolved per metric. Reuses
    analyze_history (per-reading out_of_range / personal_baseline across the whole
    history, pb-aware) plus the latest-only threshold/delta from analyze_series. No
    new math here — just collecting the engine's dated flags of notable kinds.

    Stored metrics (get_series) and derived metrics (their computed series, injected
    via derived_series) are treated identically, so a derived metric's notable reading
    (e.g. Non-HDL past its threshold) bumps the same per-date count."""
    notable: dict[str, set[str]] = {}
    stored = [(info["metric"], get_series(conn, info["metric"]))
              for info in list_metrics_with_units(conn)]
    derived = list((derived_series or {}).items())
    for metric, series in stored + derived:
        mode = get_metric_settings(conn, metric)["personal_baseline_mode"]
        cfg = metric_config.get(metric, {})
        # Uncapped history flags (out_of_range + personal_baseline, pb-aware), plus
        # the dated threshold/delta from the current-state pass.
        flags = analyze_history(metric, series, max_results=10**9, personal_baseline_mode=mode)
        flags += [f for f in analyze_series(metric, series, personal_baseline_mode=mode, **cfg)
                  if f.kind in ("threshold", "delta")]
        for f in flags:
            if f.kind in _NOTABLE_KINDS and f.observed_on:
                notable.setdefault(f.observed_on, set()).add(metric)
    return notable


# ----------------------------------------------------------------------------- source builders

def build_condition_entries(conn, ctx) -> list[TimelineEntry]:
    """An onset entry per condition that has an onset date, and a separate resolved
    entry only when the condition is resolved AND has a resolved date. A condition
    with no onset_on is omitted (no date to place it — its data still lives in C/M).
    So an active condition yields just an onset entry; no resolved entry appears
    until it has a resolved_on."""
    out: list[TimelineEntry] = []
    for c in list_conditions(conn):
        base = {"name": c["name"], "status": c["status"], "icd10": c["icd10"], "notes": c["notes"]}
        if c["onset_on"]:
            out.append(TimelineEntry(date=c["onset_on"], kind="condition", subtype="onset",
                                     title=f"Condition: {c['name']}", detail=base,
                                     link="/profile?tab=conditions"))
        if c["status"] == "resolved" and c["resolved_on"]:
            out.append(TimelineEntry(date=c["resolved_on"], kind="condition", subtype="resolved",
                                     title=f"Resolved: {c['name']}", detail=base,
                                     link="/profile?tab=conditions"))
    return out


def build_medication_entries(conn, ctx) -> list[TimelineEntry]:
    """A started entry per medication that has a start date, and an ended entry only
    when it has an end date. A medication with no start_date is omitted; an active
    medication (no end_date) yields just a started entry — no ended entry until it
    has an end_date."""
    out: list[TimelineEntry] = []
    for m in list_medications(conn):
        base = {"name": m["name"], "dose": m["dose"], "frequency": m["frequency"],
                "notes": m["notes"], "active": m["active"]}
        if m["start_date"]:
            out.append(TimelineEntry(date=m["start_date"], kind="medication", subtype="started",
                                     title=f"Started {m['name']}", detail=base,
                                     link="/profile?tab=conditions"))
        if m["end_date"]:
            out.append(TimelineEntry(date=m["end_date"], kind="medication", subtype="ended",
                                     title=f"Ended {m['name']}", detail=base,
                                     link="/profile?tab=conditions"))
    return out


def build_event_entries(conn, ctx) -> list[TimelineEntry]:
    """One entry per event. Events stay in the Timeline (edit/delete via the inline
    form), so they carry ref_id (the row id) and no external link."""
    out: list[TimelineEntry] = []
    for e in list_events(conn):
        out.append(TimelineEntry(date=e["event_date"], kind="event", subtype=e["event_type"],
                                 title=e["title"],
                                 detail={"event_type": e["event_type"], "notes": e["notes"]},
                                 ref_id=e["id"]))
    return out


def build_immunization_entries(conn, ctx) -> list[TimelineEntry]:
    """One entry per immunization THAT HAS A DATE.

    An undated record is deliberately omitted, the same rule a condition with no onset
    follows: the Timeline places things in time, and a record whose date is unknown has
    no place to go. Inventing one (created_at, "today", a guessed year) would put a
    fabricated point on the line — the record still lives on the Profile tab, which is
    where undated entries are readable. The tab is also where it's edited, so the entry
    links there rather than carrying a ref_id the Timeline could edit."""
    out: list[TimelineEntry] = []
    for i in list_immunizations(conn):
        if not i["administered_on"]:
            continue
        out.append(TimelineEntry(
            date=i["administered_on"], kind="immunization",
            title=i["vaccine"],
            detail={"vaccine": i["vaccine"], "dose_label": i["dose_label"],
                    "site": i["site"], "lot": i["lot"], "notes": i["notes"]},
            link="/profile?tab=immunizations", ref_id=i["id"]))
    return out


def build_lab_entries(conn, ctx) -> list[TimelineEntry]:
    """One entry per date that has lab readings: 'Lab panel, N results; M notable'.
    The notable count comes from ctx['notable'] (the engine, pb-aware). Expandable
    detail lists each reading; the client links each to /metrics?metric=<name>."""
    notable = ctx["notable"]
    by_date: dict[str, list[dict]] = {}
    for r in list_observations(conn):
        by_date.setdefault(r["observed_on"], []).append(r)
    # Derived metrics are computed, not stored, so they aren't in list_observations —
    # inject each computed row (tagged with its metric name, the one field the compute
    # rows lack) so a lab panel lists the derived value alongside the stored readings
    # it's computed from, exactly as a lab report prints it.
    for metric, series in (ctx.get("derived_series") or {}).items():
        for r in series:
            by_date.setdefault(r["observed_on"], []).append({**r, "metric": metric})

    out: list[TimelineEntry] = []
    for date, rows in by_date.items():
        notable_metrics = notable.get(date, set())
        readings = [{"metric": r["metric"], "display": _display_value(r),
                     "notable": r["metric"] in notable_metrics} for r in rows]
        ncount = sum(1 for r in readings if r["notable"])
        n = len(rows)
        title = f"Lab panel, {n} result{'s' if n != 1 else ''}; {ncount} notable"
        out.append(TimelineEntry(date=date, kind="lab", title=title,
                                 detail={"count": n, "notable": ncount, "readings": readings}))
    return out


def build_collection_entries(conn, ctx) -> list[TimelineEntry]:
    """One entry per timed collection (24h urine, etc.) at its completion date. The
    collection's ANALYTES already appear in the same-date lab panel; this entry marks the
    collection event itself and its shared volume/duration. Links to the Collections tab."""
    def _num(v):  # drop a trailing .0 so 1750.0 reads as 1750
        return int(v) if isinstance(v, float) and v.is_integer() else v

    out: list[TimelineEntry] = []
    for c in list_collections(conn):
        kind_label = "24-hour urine" if c["kind"] == "24h_urine" else c["kind"]
        bits = []
        if c["volume_ml"] is not None:
            bits.append(f"{_num(c['volume_ml'])} mL")
        if c["duration_hours"] is not None:
            bits.append(f"{_num(c['duration_hours'])} h")
        title = f"{kind_label} collection" + (f" · {' · '.join(bits)}" if bits else "")
        out.append(TimelineEntry(
            date=c["completed_on"], kind="collection", subtype=c["kind"], title=title,
            detail={"volume_ml": c["volume_ml"], "duration_hours": c["duration_hours"],
                    "n_readings": c["n_readings"], "notes": c["notes"]},
            link="/profile?tab=collections"))
    return out


def build_imaging_entries(conn, ctx) -> list[TimelineEntry]:
    """One entry per locally-stored DICOM study at its StudyDate, linking to the viewer
    with that study preselected. Reads the local imaging folder only (dicom_store's
    allowlisted scan — no PII enters the entry: study date/description, modalities, and
    counts). An undated study can't be placed on a timeline and is skipped; `conn` is
    unused (the imaging store is files, not DB).

    The radiologist's REPORT rides on this entry (`detail["reports"]`) rather than being an
    entry of its own. A report is not a separate event that happened to share a date — it is
    part of the study, the written half of the same exam, so splitting them into two timeline
    rows made one thing look like two. Only the report's opaque id and available formats
    travel here; no report prose (which opens with the patient's name and DOB) enters the
    timeline at all."""
    by_study = reports.reports_by_study() if reports.available() else {}
    report_meta = {r["id"]: r for r in reports.list_reports()} if by_study else {}
    out: list[TimelineEntry] = []
    for st in dicom_store.public_studies():
        date = st.get("StudyDate")
        if not date:
            continue
        modalities = sorted({s["Modality"] for s in st["series"] if s.get("Modality")})
        n_images = sum(s["n_slices"] for s in st["series"])
        desc = st.get("StudyDescription")
        label = "/".join(modalities) if modalities else "Imaging"
        title = f"{label} imaging" + (f" — {desc}" if desc else "")
        study_reports = [{"id": rid, "formats": report_meta.get(rid, {}).get("formats", [])}
                         for rid in by_study.get(st["id"], [])]
        out.append(TimelineEntry(
            date=date, kind="imaging", subtype=modalities[0] if modalities else None,
            title=title,
            detail={"n_series": len(st["series"]), "n_images": n_images,
                    "modalities": modalities, "reports": study_reports},
            link=f"/imaging?study={st['id']}"))
    return out


# The source registry. Append a new builder here (same signature, same TimelineEntry
# shape) to add a section — with no other change.
SOURCES = [
    build_condition_entries,
    build_medication_entries,
    build_event_entries,
    build_immunization_entries,
    build_collection_entries,
    build_lab_entries,
    build_imaging_entries,
]

# Same-date tiebreak order (purely cosmetic determinism when several things share a day).
# A collection sorts just before its own lab panel (they share the completion date).
_KIND_ORDER = {"condition": 0, "medication": 1, "event": 2, "immunization": 3,
               "collection": 4, "imaging": 5, "lab": 6}


def build_timeline(conn, metric_config: dict,
                   derived_series: dict[str, list[dict]] | None = None) -> list[TimelineEntry]:
    """Merge every source into one newest-first list. Read-only; the client handles
    filtering and the oldest-first flip in memory.

    `derived_series` (metric -> computed series, injected by the caller so this module
    stays free of the derived registry) gives derived metrics parity with stored ones:
    they count toward a date's notable tally and appear as lab-panel line items."""
    ctx = {"notable": _notable_dates(conn, metric_config, derived_series),
           "derived_series": derived_series or {}}
    entries: list[TimelineEntry] = []
    for build in SOURCES:
        entries.extend(build(conn, ctx))
    # Stable sort: kind order first (tiebreak), then date descending (newest first).
    entries.sort(key=lambda e: _KIND_ORDER.get(e.kind, 9))
    entries.sort(key=lambda e: e.date, reverse=True)
    return entries
