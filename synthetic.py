"""
The INVENTED record — a whole fake person, for showing the app to someone else.

Why this exists rather than a "demo mode" switch in the UI
----------------------------------------------------------
The obvious design is a toggle that masks or fakes values on screen. It was rejected,
because it leaves the real record inside the running process: one route that forgets to
mask, one component that reads the unmasked value, and the thing you were demonstrating is
the thing you were hiding. It is also flatly impossible for the parts that matter most —
a DICOM slice can carry a name burned into its PIXELS, and a radiology report is prose.

So demo mode is a different STORE, not a different view. `demo.bat` points HEALTH_DB,
HEALTH_IMAGING_DIR, HEALTH_IMAGING_ARCHIVE and HEALTH_DOCUMENTS_DIR at a synthetic folder
and starts the app there. The real record isn't hidden from the process; it is unreachable
by it. That is the same argument, and the same mechanism, as verify/ui_shots.py — which
exists because a screenshot of this app is a picture of a medical record.

The invented record must be UNLIKE the real one
-----------------------------------------------
Not merely separate - UNLIKE. The first version of this seed was written to look plausible,
and plausible-for-this-project meant plausible-for-this-user: it carried the real record's
conditions, its medications and roughly its demographics, and five generated documents
elaborated all of it into prose. That is worse than showing nothing. A demo that mirrors the
real history discloses it while BOTH parties believe it is invented - the viewer takes it
for fiction, the owner takes the screen for safe, and nobody in the room corrects either of
them. The store isolation is worthless if the contents are a copy.

So the rule is: the demo person is a DIFFERENT PERSON, in demographics and in history, and
the content is checked against that by the only party who can check it. This is the one
control here that CANNOT be automated - verifying "unlike the real record" in code would
mean reading the real record, which is the access this whole feature exists to avoid. It is
a human rule, kept honest by being written down and by asking rather than assuming.

The banner has to be honest in the DANGEROUS direction
------------------------------------------------------
A banner driven by an env var could say DEMO while the process was actually open on the
real database — the failure that matters, since it would invite you to show the screen.
So the marker is written INTO the database by the seeder and read back out of whatever
database is open (`is_synthetic`). It travels with the data: a store without it is not
claimed to be a demo, and the marker cannot appear in the real record without someone
seeding over it.
"""

from __future__ import annotations

import hashlib
import json
import os
import random
import textwrap

import db as dbmod

# The marker, written into the seeded database and read back by GET /demo.
MARKER_KEY = "synthetic_record"

# Invented, and deliberately unlike a real name: whoever sees this screen should be able to
# tell at a glance that it is not somebody's record.
DEMO_NAME = "Demo Patient"

_ACCESSION = "DEMO000001"


def is_synthetic(conn) -> bool:
    """True when the OPEN database is a seeded demo store."""
    return dbmod.get_setting(conn, MARKER_KEY) == "1"


def _draws(start_year: int, n: int) -> list[str]:
    """n draw dates, roughly quarterly, oldest first — the cadence of real lab follow-up."""
    out = []
    y, m = start_year, 2
    for _ in range(n):
        out.append(f"{y}-{m:02d}-{(7 + (m * 3) % 20):02d}")
        m += 3
        if m > 12:
            m -= 12
            y += 1
    return out


# (metric, unit, ref_low, ref_high, centre, spread) — the curated NAMES matter: metric_config
# seeds guideline thresholds and methodology notes by name, so a demo of a real metric shows
# the real gridlines rather than a bare chart.
# Bands are the FEMALE reference intervals, because the demo person is one: haemoglobin,
# haematocrit, creatinine and ferritin all differ by sex, and a female profile carrying male
# bands would be quietly wrong on the page a viewer reads most closely. It also means the
# chart draws WHO's 12.0 g/dL anaemia line rather than the 13.0 one (see #18).
#
# Hemoglobin, Ferritin and TSH are NOT here: each is seeded below with a shaped series, so
# the record tells a story rather than showing noise around a mean.
_SERIES = [
    ("Hematocrit", "%", 35.0, 45.0, 40.2, 1.5),
    ("White Blood Cell Count", "K/uL", 4.0, 10.5, 6.1, 1.1),
    ("Platelet Count", "K/uL", 150, 400, 268, 28),
    ("Sodium", "mmol/L", 135, 145, 139, 1.7),
    ("Potassium", "mmol/L", 3.5, 5.2, 4.1, 0.25),
    ("Creatinine Serum/Plasma", "mg/dL", 0.6, 1.1, 0.78, 0.07),
    ("Estimated GFR", "mL/min/1.73", 60, None, 89, 6),
    ("Blood Urea Nitrogen", "mg/dL", 7, 25, 13, 2.5),
    ("Alanine Aminotransferase", "U/L", 0, 50, 21, 6),
    ("Aspartate Aminotransferase", "U/L", 0, 40, 19, 5),
    ("Total Bilirubin", "mg/dL", 0.2, 1.2, 0.5, 0.15),
    ("Albumin", "g/dL", 3.5, 5.0, 4.2, 0.2),
    ("Cholesterol", "mg/dL", 0, 200, 188, 18),
    ("HDL", "mg/dL", 50, None, 61, 7),
    ("LDL Calculated", "mg/dL", 0, 130, 104, 15),
    ("Triglycerides", "mg/dL", 0, 150, 112, 28),
    ("hba1c", "%", 4.0, 5.6, 5.2, 0.2),
    ("Vitamin D 25-Hydroxy", "ng/mL", 30, 100, 36, 7),
]

# The two stories the demo tells, on the same draw dates as everything else.
#
#   Ferritin + Hemoglobin: an iron deficiency found in early 2024, treated, and RESOLVED —
#   a finding the app should now be quiet about.
#   TSH: a rise to 11.4 in mid-2025 that a dose change brought back down — the one the app
#   should flag loudly. Its peak clears the 10 uIU/mL guideline line seeded in
#   metric_config, so the threshold detector fires and the chart draws the gridline.
#
# Two shapes in one record is the point: a demo where everything is flagged teaches as
# little as one where nothing is.
_STORIES = [
    ("Hemoglobin", "g/dL", 12.0, 15.5,
     [11.2, 11.6, 12.5, 13.0, 13.3, 13.5, 13.4, 13.6, 13.5, 13.7, 13.6]),
    ("Ferritin", "ng/mL", 15, 150,
     [9.0, 22.0, 38.0, 52.0, 58.0, 61.0, 57.0, 66.0, 71.0, 68.0, 74.0]),
    ("TSH", "uIU/mL", 0.4, 4.5,
     [2.4, 2.8, 3.1, 4.6, 6.8, 11.4, 6.2, 3.4, 2.6, 2.2, 2.5]),
]


def seed_db(conn) -> None:
    """Fill an EMPTY database with an invented record and stamp it as synthetic.

    Deterministic (a fixed seed), so the demo looks the same every time you show it and a
    screenshot taken today matches the one you took last week.
    """
    rng = random.Random(20260101)
    dbmod.init_db(conn)

    dates = _draws(2024, 11)
    for metric, unit, lo, hi, centre, spread in _SERIES:
        for i, d in enumerate(dates):
            # A gentle drift plus noise, so trends and personal-baseline flags have
            # something to find rather than a flat line.
            drift = (i - len(dates) / 2) * spread * 0.12
            value = centre + drift + rng.gauss(0, spread * 0.55)
            value = round(value, 2 if abs(centre) < 20 else 0)
            dbmod.add_observation(conn, metric, value, unit, d, ref_low=lo, ref_high=hi)

    for metric, unit, lo, hi, values in _STORIES:
        assert len(values) == len(dates), f"{metric}: {len(values)} values, {len(dates)} draws"
        for d, value in zip(dates, values):
            dbmod.add_observation(conn, metric, value, unit, d, ref_low=lo, ref_high=hi)

    # A censored result and a qualitative one, so those rendering paths appear too.
    dbmod.add_observation(conn, "Hepatitis C Antibody", None, "", "2025-03-12",
                          result_type="qualitative", value_text="Non-reactive",
                          normal_text="Non-reactive")
    dbmod.add_observation(conn, "Vitamin B12", 5.0, "pg/mL", "2025-03-12",
                          result_type="censored", operator="<", ref_low=200, ref_high=1100)

    dbmod.update_profile(conn, "female", "1979-11-30")
    for d, v in [("2025-01-11", 151.2), ("2025-04-19", 150.1), ("2025-08-02", 148.6),
                 ("2025-11-15", 149.4), ("2026-03-07", 148.0), ("2026-06-20", 147.6)]:
        dbmod.add_profile_measurement(conn, "weight", v, "lb", d)
    dbmod.add_profile_measurement(conn, "height", 64.0, "in", "2025-01-11")

    # One condition still active and one long resolved, so both statuses render — and so the
    # record reads as a history rather than as a list of current problems.
    dbmod.add_condition(conn, "Hypothyroidism", onset_on="2018-03-14",
                        notes="Diagnosed at the thyroid clinic; on replacement since.")
    dbmod.add_condition(conn, "Iron deficiency anaemia", onset_on="2024-02-13",
                        status="resolved", resolved_on="2024-11-20",
                        notes="Treated with a six-month course of oral iron.")
    dbmod.add_medication(conn, "Levothyroxine", dose="100 mcg", frequency="once daily",
                         start_date="2018-03-20",
                         notes="Increased from 75 mcg in June 2025 after a raised TSH.")
    dbmod.add_medication(conn, "Ferrous sulfate", dose="325 mg", frequency="once daily",
                         start_date="2024-02-20", end_date="2024-11-20",
                         notes="Stopped once ferritin had recovered.")

    dbmod.add_event(conn, "2025-06-04", "visit", "Thyroid review",
                    notes="Dose increased to 100 mcg; repeat TSH in eight weeks.")
    dbmod.add_event(conn, "2026-06-18", "visit", "Annual physical")

    dbmod.add_immunization(conn, "Influenza (quadrivalent)", administered_on="2025-11-08",
                           dose_label="2025-26 season", amount="0.5 mL",
                           site="left deltoid", lot="DEMO-1")
    dbmod.add_immunization(conn, "Tdap", administered_on="2023-08-23", amount="0.5 mL",
                           site="right deltoid", lot="DEMO-2")
    dbmod.add_immunization(conn, "Measles, mumps, rubella")   # undated, as a paper-card record

    cid = dbmod.add_collection(conn, completed_on="2026-04-02", duration_hours=24.0,
                               volume_ml=1800.0, notes="Routine 24-hour collection.")
    dbmod.add_observation(conn, "Urine Protein 24Hr", 84.0, "mg/24h", "2026-04-02",
                          ref_low=0, ref_high=150, collection_id=cid)
    dbmod.add_observation(conn, "Urine Creatinine 24Hr", 1.4, "g/24h", "2026-04-02",
                          ref_low=0.8, ref_high=1.8, collection_id=cid)

    dbmod.set_setting(conn, MARKER_KEY, "1")
    conn.commit()


def seed_imaging(store: str, tall: bool = True) -> str:
    """Invented DICOM slices in `store`. Returns the accession the reports are filed under.

    Built from pydicom's own bundled sample, re-stamped: one 24-slice axial series and (for
    the harness, which needs a NON-SQUARE image to catch aspect bugs) a 4-slice tall one in
    its own study. Every identifier the sample ships with is overwritten — the display
    allowlist means none of them would reach the client anyway, but nothing real-looking
    should be sitting in a folder either.

    Returns "" if pydicom isn't installed; the imaging page then shows its honest empty
    state, exactly as on a machine without the extras.
    """
    try:
        import pydicom
        from pydicom.data import get_testdata_file
    except Exception:
        return ""

    os.makedirs(store, exist_ok=True)
    src = get_testdata_file("CT_small.dcm")
    study = "1.2.826.0.1.3680043.8.498.20000000000000000000000000000001"
    series = "1.2.826.0.1.3680043.8.498.10000000000000000000000000000001"

    def stamp(ds, study_uid, series_uid, i, desc, series_desc, date, number):
        ds.PatientName = "SYNTHETIC^HARNESS"
        ds.PatientID = "SYNTH-0001"
        ds.PatientBirthDate = ""
        ds.ReferringPhysicianName = ""
        ds.InstitutionName = "Synthetic Imaging"
        ds.AccessionNumber = _ACCESSION
        ds.StudyInstanceUID = study_uid
        ds.SeriesInstanceUID = series_uid
        ds.SOPInstanceUID = f"{series_uid}.{i + 1}"
        ds.InstanceNumber = i + 1
        ds.StudyDate = date
        ds.StudyDescription = desc
        ds.SeriesDescription = series_desc
        ds.BodyPartExamined = "ABDOMEN"
        ds.SeriesNumber = number

    # Every slice used to be the SAME bytes, re-stamped. That is a stack of 24 identical
    # pictures: scrolling it changes nothing on screen and cine looks broken rather than
    # boring — it reads as "the viewer doesn't work," which is the opposite of what a demo
    # of a DICOM viewer should say. It also meant the prefetch, the cache and the cine
    # pacing were all being exercised against data that could never reveal an ordering bug.
    #
    # So vary it along z. The base sample supplies realistic CT texture and correct rescale
    # tags; on top of it goes one synthetic sphere, centred in the stack, whose radius grows
    # and shrinks as you scroll through it — which is how a round structure genuinely
    # behaves across slices, and makes the direction of travel obvious. It stays plainly
    # synthetic: one smooth blob, no pretence of anatomy.
    try:
        import numpy as np
    except Exception:
        np = None

    n_axial = 24
    for i in range(n_axial):
        ds = pydicom.dcmread(src)
        if np is not None:
            arr = ds.pixel_array.astype(np.int16)
            rows, cols = arr.shape
            yy, xx = np.ogrid[:rows, :cols]
            # A sphere of radius R centred at the middle slice: the radius of its
            # intersection with slice i is R*sqrt(1 - (dz/R)^2), zero once outside it.
            half = (n_axial - 1) / 2.0
            radius = min(rows, cols) * 0.28
            dz = (i - half) / half * radius
            cut = radius * radius - dz * dz
            if cut > 0:
                r = float(np.sqrt(cut))
                cy, cx = rows * 0.42, cols * 0.55
                mask = (yy - cy) ** 2 + (xx - cx) ** 2 <= r * r
                # +260 above local background sits well inside the sample's own window,
                # so it is visible at the default view without blowing the histogram out.
                arr[mask] = np.clip(arr[mask].astype(np.int32) + 260, -2000, 3000).astype(np.int16)
            # The sphere alone leaves the first and last slices IDENTICAL (it does not
            # reach either end), and two identical frames at the ends of a scrub are
            # exactly where you look to check the control is working. So a small marker
            # also tracks straight down the stack: every slice then differs from every
            # other, and which way you are travelling is readable from a single frame.
            my = int(rows * (0.15 + 0.70 * i / (n_axial - 1)))
            mx_ = int(cols * 0.16)
            arr[max(0, my - 3):my + 4, max(0, mx_ - 3):mx_ + 4] = 1400
            ds.PixelData = arr.tobytes()
        stamp(ds, study, series, i, "Synthetic CT abdomen", "Axial 5mm", "20260618", 1)
        ds.save_as(os.path.join(store, f"IM{i:06d}"), enforce_file_format=True)

    if not tall:
        return _ACCESSION

    # 512 × 1024 — realistic proportions for a coronal reformat, and TALLER than the stage,
    # which is the condition that clamps the image vertically. A square-only fixture can
    # never reach it, and that is exactly how an aspect bug shipped once.
    try:
        import numpy as np
    except Exception:
        return _ACCESSION
    tall_study = "1.2.826.0.1.3680043.8.498.20000000000000000000000000000002"
    tall_series = "1.2.826.0.1.3680043.8.498.10000000000000000000000000000002"
    for i in range(4):
        ds = pydicom.dcmread(src)
        arr = np.tile(ds.pixel_array, (8, 4)).astype(np.int16)
        # Vary this one along z as well. It is only four slices and exists mainly to catch
        # aspect bugs, but a viewer demo where a second series also refuses to change under
        # the scrubber teaches the same wrong lesson as the first one did.
        rows, cols = arr.shape
        my = int(rows * (0.2 + 0.6 * i / 3))
        mx_ = int(cols * (0.2 + 0.6 * i / 3))
        arr[max(0, my - 12):my + 13, max(0, mx_ - 12):mx_ + 13] = 1400
        ds.PixelData = arr.tobytes()
        ds.Rows, ds.Columns = int(arr.shape[0]), int(arr.shape[1])
        stamp(ds, tall_study, tall_series, i, "Synthetic CT coronal", "Coronal reformat",
              "20260612", 1)
        ds.save_as(os.path.join(store, f"TL{i:06d}"), enforce_file_format=True)
    return _ACCESSION


_REPORT = """\
SYNTHETIC RADIOLOGY REPORT — INVENTED, NOT A REAL EXAMINATION

Patient:        Demo Patient
Examination:    CT ABDOMEN WITHOUT CONTRAST
Date:           2026-06-18

TECHNIQUE
Contiguous axial images were obtained through the abdomen. Coronal reformats were
generated. This text is invented for demonstration and describes no real study.

FINDINGS
Liver, spleen, pancreas and adrenal glands are unremarkable in this invented example.
No free fluid. No lymphadenopathy. Visualised bowel is normal in calibre.

IMPRESSION
Invented example report. No abnormality described.
"""


def seed_reports(archive: str, accession: str) -> None:
    """A radiology report filed the way a real imaging disc files one:
    <archive>/<disc>/other_content/<accession>/report.txt, plus the reportFile.pdf that
    sits beside it on a real disc. Nothing here is real - the point of the prose is to give
    the Documents page something to read.

    The PDF is not decoration. The reader shows the SCAN and only the scan (deliberately:
    the transcription is the lossy derivative), so a report with text and no PDF opens on
    "No PDF for this document" and the page reads as broken - which is exactly how the demo
    store shipped."""
    if not accession:
        return
    folder = os.path.join(archive, "demo-disc", "other_content", accession)
    os.makedirs(folder, exist_ok=True)
    with open(os.path.join(folder, "report.txt"), "w", encoding="utf-8") as fh:
        fh.write(_REPORT)
    _write_pdf(os.path.join(folder, "reportFile.pdf"), "Radiology report", [_REPORT])

# ---------------------------------------------------------------------------
# Scanned documents
#
# The Documents page merges two local sources: the radiology reports that ride on an
# imaging disc (reports.py) and the split hospital record (docstore.py). Seeding only the
# first left the page showing one item whose reader said "No PDF for this document" - a
# page that reads as broken, on a feature that is one of the better things here.
#
# The reader shows the SCAN and only the scan (see docstore.py / DocumentsPage), so a demo
# document has to BE a scan: rendered page images wrapped in a PDF, with a text sidecar
# beside them standing in for the OCR. Rendering uses Pillow, already a core dependency for
# the DICOM viewer, and Pillow's own bundled font - no system font, so the pages come out
# the same on any machine.
#
# The prose is invented but deliberately CONSISTENT with the rest of the seeded record: the
# alkaline phosphatase excursion these notes discuss is the same one seed_db() writes into
# the chart, and the CT they refer to is the study seed_imaging() writes. That is what makes
# the demo hang together - and it gives full-text search something true to find, since
# "alkaline phosphatase" then hits three documents that each say a different part of one
# story.
# ---------------------------------------------------------------------------

_PAGE_W, _PAGE_H = 1240, 1754          # A4 at 150 dpi
_MARGIN = 90
_WRAP = 92

_INVENTED = "INVENTED DEMONSTRATION DOCUMENT - NOT A REAL MEDICAL RECORD"

_DOCUMENTS = [
    {
        "date": "2018-03-20",
        "title": "Specialist consultation",
        "pages": ["""\
Referred by the general practitioner with tiredness, cold intolerance and a raised
thyroid stimulating hormone on a routine screen.

HISTORY
Six months of fatigue, worse in the afternoons. Feels the cold more than she used
to. No neck swelling, no difficulty swallowing, no palpitations. No family history
reported.

EXAMINATION
Thyroid not enlarged and not tender. Pulse 62 and regular. No tremor.

RESULTS
Thyroid stimulating hormone raised on two occasions eight weeks apart. Free T4 at
the lower end of its range. Thyroid peroxidase antibodies positive.

ASSESSMENT
Primary hypothyroidism. Discussed that replacement is usually lifelong and that the
dose is set by how the blood tests respond rather than by how she feels on any one
day.

PLAN
Start levothyroxine 75 micrograms once daily, taken on an empty stomach. Repeat
thyroid function in eight weeks. Continue under the general practitioner once
stable.
"""],
    },
    {
        "date": "2024-02-20",
        "title": "Clinic note",
        "pages": ["""\
Attends to discuss a full blood count and iron studies taken two weeks ago.

RESULTS DISCUSSED
Haemoglobin 11.2 g/dL (reference 12.0 - 15.5). Ferritin 9 ng/mL (reference 15 -
150). Thyroid function stable on the current dose.

HISTORY
Tired, though she notes she is always tired and had put it down to the thyroid.
Heavy periods for the last year or so. Diet mixed, little red meat. No blood in the
stool, no weight loss, no abdominal pain.

ASSESSMENT
Iron deficiency with a mild anaemia. The low ferritin is the more useful of the two
numbers here - it is the one that fell first and it will be the one to follow.

PLAN
Start ferrous sulfate 325 mg once daily with orange juice, away from the
levothyroxine, which iron can interfere with. Repeat the full blood count and
ferritin in three months. Referred to gynaecology to discuss the periods.
"""],
    },
    {
        "date": "2024-11-20",
        "title": "Laboratory report",
        "pages": ["""\
FULL BLOOD COUNT AND IRON STUDIES - repeat after treatment

Haemoglobin              | 13.0 g/dL     (12.0 - 15.5)
Haematocrit              | 39.8 %        (35.0 - 45.0)
Mean cell volume         | 88 fL         (80 - 100)
Ferritin                 | 52 ng/mL      (15 - 150)
Transferrin saturation   | 28 %          (20 - 50)

COMMENT
Haemoglobin has risen from 11.2 g/dL and is now within its reference range. Ferritin
has risen from 9 ng/mL to 52 ng/mL over nine months of oral iron. Both are within
range and the trend is upward.

Specimen collected 2024-11-20. Reported 2024-11-20.
"""],
    },
    {
        "date": "2025-06-04",
        "title": "Clinic note",
        "pages": ["""\
THYROID REVIEW

Attends after a thyroid stimulating hormone of 11.4 mIU/L, up from 6.8 three months
earlier and from 2.4 at the start of last year.

HISTORY
More tired again over the spring. Taking the levothyroxine every morning; recently
started taking it with breakfast rather than before it, and has been taking a
calcium supplement at the same time. No missed doses otherwise.

ASSESSMENT
Under-replacement. Discussed that both calcium and iron reduce how much
levothyroxine is absorbed when taken together with it, and that timing alone can
account for a change of this size.

PLAN
Increase levothyroxine to 100 micrograms once daily. Take it on an empty stomach and
leave four hours before any calcium. Repeat thyroid function in eight weeks.
"""],
    },
    {
        "date": "2026-06-20",
        "title": "Discharge summary",
        "pages": ["""\
REASON FOR ATTENDANCE
Self-limiting central abdominal pain, investigated and resolved. Attended 2026-06-18,
discharged the same day.

PROBLEM LIST
  1. Central abdominal pain - resolved, no cause identified
  2. Hypothyroidism - on levothyroxine 100 micrograms, stable since 2025
  3. Iron deficiency anaemia - treated and resolved in 2024
  4. No other active problems

INVESTIGATIONS THIS ADMISSION
CT abdomen without contrast: no acute abnormality. Full blood count, renal and liver
panels unremarkable. Thyroid stimulating hormone within its reference range on the
current dose.
""", """\
MEDICATION ON DISCHARGE
  Levothyroxine 100 micrograms once daily - unchanged
No new medication started. Nothing stopped. The ferrous sulfate course finished in
2024 and has not been restarted.

FOLLOW-UP
General practitioner to continue annual thyroid function tests, and to check
haemoglobin and ferritin at the same time given the history.

The patient was given a copy of this summary and understands to seek review if the
abdominal pain returns.
"""],
    },
]


# Pillow's bundled font covers Latin-1 and little else, so a typographic dash or quote
# draws as a tofu box. The prose is stored with the real characters (it is also written out
# as the text sidecar, where they belong) and folded to ASCII only at DRAW time.
_FONT_SAFE = str.maketrans({"\u2014": "-", "\u2013": "-", "\u2018": "'", "\u2019": "'",
                            "\u201c": '"', "\u201d": '"', "\u2026": "...", "\u00a0": " "})


def _reflow(text: str) -> list[str]:
    """Source paragraphs as layout lines, ready to wrap.

    The prose above is hard-wrapped so it reads in the editor, and wrapping ALREADY-wrapped
    lines a second time leaves a ragged short line after every one of them. So a paragraph
    is re-joined first and wrapped once. A heading (ALL CAPS) and a table row (leading
    space, or a `|`) are layout, not prose, and pass through untouched.
    """
    out, para = [], []
    for line in text.splitlines():
        stripped = line.strip()
        # A run of two spaces means the line was laid out (a label block, a column), and
        # laid-out text must not be reflowed into a paragraph.
        structural = ((not stripped) or line.startswith(" ") or "|" in line
                      or stripped.isupper() or "  " in stripped)
        if structural:
            if para:
                out.append(" ".join(para))
                para = []
            out.append(line.rstrip())
        else:
            para.append(stripped)
    if para:
        out.append(" ".join(para))
    return out


def _render_pages(title: str, pages: list[str]) -> list:
    """Each page of a document as an image, styled as a plain scanned form. Off-white
    rather than pure white and grey rather than black, because that is what a scan looks
    like and the reader shows the scan.

    A line containing `|` is a two-column row drawn at fixed x positions, which is how the
    lab report keeps its columns: the bundled font is proportional, so space-padded columns
    would come out crooked. Using Pillow's own font rather than a system one is what makes
    these pages identical on any machine."""
    from PIL import Image, ImageDraw, ImageFont

    head = ImageFont.load_default(size=34)
    body = ImageFont.load_default(size=23)
    small = ImageFont.load_default(size=19)
    out = []
    for n, raw in enumerate(pages, 1):
        text = raw.translate(_FONT_SAFE)
        img = Image.new("L", (_PAGE_W, _PAGE_H), 246)
        draw = ImageDraw.Draw(img)
        y = _MARGIN
        draw.text((_MARGIN, y), _INVENTED, font=small, fill=120)
        y += 46
        draw.text((_MARGIN, y), title.upper(), font=head, fill=40)
        y += 52
        draw.line((_MARGIN, y, _PAGE_W - _MARGIN, y), fill=160, width=2)
        y += 34
        for line in _reflow(text):
            if "|" in line:
                label, _, value = line.partition("|")
                draw.text((_MARGIN + 20, y), label.strip(), font=body, fill=45)
                draw.text((_MARGIN + 560, y), value.strip(), font=body, fill=45)
                y += 33
                continue
            for piece in (textwrap.wrap(line, _WRAP) or [""]):
                draw.text((_MARGIN, y), piece, font=body, fill=45)
                y += 33
        draw.text((_PAGE_W - 270, _PAGE_H - _MARGIN), "Pag. %d di %d" % (n, len(pages)),
                  font=small, fill=120)
        out.append(img)
    return out


def _write_pdf(path: str, title: str, pages: list[str]) -> bool:
    """Render `pages` to a PDF at `path`. False if Pillow can't do it - the document then
    stays text-only, the same honest degradation the imaging seed makes without pydicom."""
    try:
        imgs = _render_pages(title, pages)
    except Exception:
        return False
    imgs[0].save(path, "PDF", resolution=150.0, save_all=True, append_images=imgs[1:])
    return True


def seed_documents(store: str) -> int:
    """The split hospital record: one PDF + one text sidecar per document, plus the
    manifest docstore.py reads. Returns how many documents were written.

    Ids are a hash of the bundle name and page range, exactly as ingest_documents.py
    derives them, so the demo store has the shape of a real one and the ids are STABLE
    across rebuilds - a demo whose links changed every run would be worse than no demo.
    """
    os.makedirs(store, exist_ok=True)
    rows, first = [], 1
    for spec in _DOCUMENTS:
        n_pages = len(spec["pages"])
        last = first + n_pages - 1
        doc_id = hashlib.sha1(("demo-bundle:%d-%d" % (first, last)).encode()).hexdigest()[:12]
        # `|` marks a two-column row for the renderer. It is layout, not content, so the
        # sidecar - which is what search reads and quotes back in a snippet - gets spaces.
        body = "\n".join(spec["pages"]).replace(" | ", "   ")
        text = "%s\n\n%s\n\n%s" % (_INVENTED, spec["title"].upper(), body)
        with open(os.path.join(store, doc_id + ".txt"), "w", encoding="utf-8") as fh:
            fh.write(text.strip())
        _write_pdf(os.path.join(store, doc_id + ".pdf"), spec["title"], spec["pages"])
        rows.append({"id": doc_id, "date": spec["date"], "title": spec["title"],
                     "title_it": None, "n_pages": n_pages,
                     "source": "demo-bundle", "source_pages": [first, last]})
        first = last + 1
    with open(os.path.join(store, "manifest.json"), "w", encoding="utf-8") as fh:
        json.dump(rows, fh, indent=1, ensure_ascii=False)
    return len(rows)
