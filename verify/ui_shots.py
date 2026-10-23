"""
verify/ui_shots.py — take UI screenshots that CANNOT contain the real record.

    .venv/Scripts/python.exe verify/ui_shots.py --out shots \
        home:/ metrics:/metrics timeline:/timeline \
        rail:/metrics:.metric__rail

Why this exists
---------------
Verifying a UI change means looking at it, and looking at it means a screenshot,
and a screenshot of this app is a picture of the user's medical record — which
then lives in whatever context the screenshot was taken into (an assistant's
tool output, a bug report, a chat). That happened twice in one session: once on
the imaging viewer, where a scanned requisition carries a name, MRN and DOB
BURNED INTO the pixels, and once on the Timeline, where an intended stub silently
missed (the app calls 127.0.0.1, the stub matched localhost) and the real
entries rendered instead.

The fix that failed was a note in CLAUDE.md saying "be careful on the imaging
page". A note is not a control: it named one page, and the second slip was on a
different one. THIS is the control — the screenshotted app is wired to a
synthetic database and empty media folders, so there is no real record present
to capture, whatever page you point it at and however the wiring goes wrong.

How
---
Every real-data source in this app is already env-overridable, because the test
suite needed exactly this isolation:

    HEALTH_DB               -> the SQLite file            (api.py)
    HEALTH_IMAGING_DIR      -> the DICOM store            (dicom_store.py)
    HEALTH_IMAGING_ARCHIVE  -> the radiology reports      (reports.py)
    HEALTH_DOCUMENTS_DIR    -> the split hospital record  (docstore.py)
    GATEWAY_AUDIT_LOG       -> the external-send log      (gateway.py)

The last one is the one that reads as infrastructure rather than as a store, which
is exactly why it was missed here and in demo.bat: it holds the VERBATIM payload of
every external send, Settings renders it under "External sends", and left unset it
resolves to the real file at the repo root. A shot of that tab would then carry real
readings out of a harness whose whole promise is that it cannot.

This script points all five at a fresh temp directory, seeds the DB with
invented records, starts its own backend and its own Vite dev server against
them, shoots, and tears the whole thing down. It never touches the real files —
and it asserts that, loudly, before it starts anything.

The one production change it needed is HEALTH_DEV_ORIGINS (api.py), because CORS
is scoped to port 5173 and this server runs elsewhere. It only ADDS an origin.
"""

from __future__ import annotations

import argparse
import json
import os
import shutil
import socket
import subprocess
import sys
import tempfile
import time
import urllib.error
import urllib.request

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
API_PORT = 8123
WEB_PORT = 5199

# The real stores, by their DEFAULT paths — asserted against, so a mistake in the
# env plumbing below fails here instead of silently rendering the real record.
REAL_PATHS = ("health.db", "imaging_store", "imaging_archive", "documents_store",
              "gateway_audit.log")

# Every metric _seed() creates. The outside check below asserts the served list is a
# SUBSET of this, so a backend that somehow came up against the real DB is caught
# before a single screenshot is taken. Keep in step with _seed.
SYNTHETIC_METRICS = {"Hemoglobin", "Creatinine Serum/Plasma", "Sample Urine Analyte 24Hr",
                     "Sample Enzyme", "Sample Enzyme Zero Floor"}


def _seed(db_path: str) -> None:
    """Invented records covering what the pages render. Nothing here is real."""
    sys.path.insert(0, ROOT)
    import db as dbmod

    conn = dbmod.connect(db_path)
    dbmod.init_db(conn)

    for d, v in [("2026-01-05", 14.8), ("2026-03-02", 15.2), ("2026-05-07", 13.1),
                 ("2026-06-18", 15.1)]:
        dbmod.add_observation(conn, "Hemoglobin", v, "g/dL", d, ref_low=13.4, ref_high=18.1)
    for d, v in [("2026-05-07", 0.92), ("2026-06-18", 0.85)]:
        dbmod.add_observation(conn, "Creatinine Serum/Plasma", v, "mg/dL", d,
                              ref_low=0.7, ref_high=1.3)

    # A wide-ratio, all-positive series (one acute spike over a quiet baseline), so the
    # chart's Linear/Log switch — and the amber notice that rides a log axis — actually
    # appear on a synthetic metric instead of only on a real one.
    for d, v in [("2026-01-05", 22.0), ("2026-03-02", 26.0), ("2026-05-07", 31.0),
                 ("2026-06-18", 850.0)]:
        dbmod.add_observation(conn, "Sample Enzyme", v, "U/L", d, ref_low=10, ref_high=40)

    # The same shape but with a band that FLOORS AT ZERO (ALT/bilirubin/LDL all do) —
    # and, like a real one, a band that CHANGED: some draws carry 0–50, later ones
    # 10–50. Zero has no place on a log axis, so this is the series that exercises the
    # clamped band edge; the mixed floor is what makes the whole band's bottom edge
    # ambiguous, which is a rendering case worth having in the harness.
    for d, v, lo in [("2026-01-05", 18.0, 0), ("2026-02-11", 24.0, 0),
                     ("2026-03-02", 31.0, 0), ("2026-04-09", 44.0, 10),
                     ("2026-05-07", 63.0, 10), ("2026-06-18", 711.0, 10)]:
        dbmod.add_observation(conn, "Sample Enzyme Zero Floor", v, "U/L", d,
                              ref_low=lo, ref_high=50)

    # A curated threshold on the wide-ratio metric, so the right-gutter ThresholdRail is
    # exercised on the SYMLOG axis — the rail reads the y-scale directly (useYAxisScale),
    # which makes scale + rail the one combination a chart change can silently break.
    dbmod.set_metric_config(conn, "Sample Enzyme", "thresholds",
                            '[{"cutoff": 200, "source": "SAMPLE"}]')

    dbmod.update_profile(conn, "female", "1980-04-12")
    for d, v in [("2026-06-21", 150.4), ("2026-07-06", 149.1), ("2026-07-27", 148.2)]:
        dbmod.add_profile_measurement(conn, "weight", v, "lb", d)

    dbmod.add_condition(conn, "Sample condition", onset_on="2025-11-02", notes="invented")
    dbmod.add_medication(conn, "Sample medication", dose="10 mg", frequency="once daily",
                         start_date="2025-11-05")
    dbmod.add_event(conn, "2026-02-14", "visit", "Sample visit", notes="invented")
    dbmod.add_immunization(conn, "Influenza (quadrivalent)", administered_on="2025-11-08",
                           dose_label="2025-26 season", amount="0.5 mL",
                           site="left deltoid", lot="SAMPLE1", notes="invented record")
    dbmod.add_immunization(conn, "Sample childhood vaccine")   # undated on purpose

    # A timed collection, so the metric picker has an <optgroup> to render — the picker's
    # grouping is otherwise invisible on a flat synthetic list.
    cid = dbmod.add_collection(conn, completed_on="2026-04-02", duration_hours=24.0,
                               volume_ml=1800.0, notes="sample collection")
    dbmod.add_observation(conn, "Sample Urine Analyte 24Hr", 120.0, "mg/24h", "2026-04-02",
                          ref_low=0, ref_high=150, collection_id=cid)
    import synthetic
    dbmod.set_setting(conn, synthetic.MARKER_KEY, "1")
    conn.commit()
    conn.close()


def _seed_documents(store: str) -> None:
    """Invented scanned documents, so the DOCUMENTS page can be reviewed at all. Without
    them the page shows an empty list whatever it is pointed at, so the only way to look at
    it was against the real record — the one thing this harness exists to make unnecessary.

    Shared with demo mode for the same reason the DICOM generator is (synthetic.py).

    Known limit, so nobody chases it: the reader embeds the PDF in an iframe and HEADLESS
    Chromium ships no PDF viewer, so a shot of an open document shows an empty pane. The
    list, the type filter and the search results all render; the scan itself has to be
    eyeballed in a real browser.
    """
    sys.path.insert(0, ROOT)
    import synthetic

    print("[shots] seeded %d synthetic documents" % synthetic.seed_documents(store))


def _seed_imaging(store: str, archive: str) -> None:
    """Invented DICOM slices, so the IMAGING page can be reviewed without pointing a
    browser at the real store. That page is the one that caused the burned-in-PII incident
    this harness exists for — a scanned requisition carries a name and MRN in the PIXELS,
    where no allowlist reaches — so having nothing synthetic to shoot meant the only way to
    look at it was the unsafe way.

    The generator is shared with demo mode (synthetic.py): both need an invented DICOM
    study, and two copies of that is two things to keep in step. It seeds a TALL series as
    well as a square one, which is what catches an aspect bug — every bundled sample is
    square.
    """
    sys.path.insert(0, ROOT)
    import synthetic

    accession = synthetic.seed_imaging(store)
    if accession:
        # The radiology report rides ON the study (timeline.build_imaging_entries links to
        # it, and Documents lists it): seeding the slices without it left both surfaces
        # half-populated, and the report link on the timeline entry pointing at nothing.
        synthetic.seed_reports(archive, accession)
        print("[shots] seeded synthetic DICOM (square + tall series) + its report")
    else:
        print("[shots] pydicom not installed - imaging page will show its empty state")


def _free(port: int) -> bool:
    with socket.socket() as s:
        return s.connect_ex(("127.0.0.1", port)) != 0


def _wait(url: str, proc: subprocess.Popen, what: str, timeout: float = 60) -> None:
    end = time.time() + timeout
    while time.time() < end:
        if proc.poll() is not None:
            raise SystemExit(f"{what} exited early (code {proc.returncode}).")
        try:
            urllib.request.urlopen(url, timeout=2).read(1)
            return
        except (urllib.error.URLError, ConnectionError, TimeoutError, OSError):
            time.sleep(0.4)
    raise SystemExit(f"{what} did not come up at {url}.")


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--out", default="shots", help="directory for the PNGs")
    ap.add_argument("--click", action="append", default=[], metavar="SELECTOR",
                    help="click this before probing/shooting (repeatable, in order) — the "
                         "only way to reach a state that lives behind a control")
    ap.add_argument("--probe", action="append", default=[], metavar="SELECTOR",
                    help="print each matching element's box instead of only shooting it "
                         "(repeatable) — layout facts without moving a picture anywhere")
    ap.add_argument("--pref", action="append", default=[], metavar="KEY=VALUE",
                    help="seed a localStorage view preference before load, e.g. "
                         "--pref ht-chart-scale=log (repeatable)")
    ap.add_argument("--dark", action="store_true",
                    help="shoot in the DARK theme (emulates prefers-color-scheme: dark)")
    ap.add_argument("targets", nargs="+",
                    help="name:path[:cssSelector] — selector shoots that element only")
    args = ap.parse_args()

    try:
        from playwright.sync_api import sync_playwright
    except ImportError:
        raise SystemExit("playwright is required: pip install playwright && playwright install")

    tmp = tempfile.mkdtemp(prefix="ht-shots-")
    db_path = os.path.join(tmp, "synthetic.db")
    dirs = {k: os.path.join(tmp, k) for k in ("imaging", "archive", "documents")}
    for d in dirs.values():
        os.makedirs(d, exist_ok=True)

    env = {
        **os.environ,
        "HEALTH_DB": db_path,
        "HEALTH_IMAGING_DIR": dirs["imaging"],
        "HEALTH_IMAGING_ARCHIVE": dirs["archive"],
        "HEALTH_DOCUMENTS_DIR": dirs["documents"],
        "GATEWAY_AUDIT_LOG": os.path.join(tmp, "gateway_audit.log"),
        "HEALTH_DEV_ORIGINS": f"http://localhost:{WEB_PORT},http://127.0.0.1:{WEB_PORT}",
    }

    # The guard, stated as an assertion rather than a comment: every store this
    # backend can reach must be inside the temp dir.
    for key in ("HEALTH_DB", "HEALTH_IMAGING_DIR", "HEALTH_IMAGING_ARCHIVE",
                "HEALTH_DOCUMENTS_DIR", "GATEWAY_AUDIT_LOG"):
        target = os.path.abspath(env[key])
        assert target.startswith(os.path.abspath(tmp)), f"{key} escapes the temp root"
        for real in REAL_PATHS:
            assert target != os.path.abspath(os.path.join(ROOT, real)), \
                f"{key} points at the REAL {real}"

    for port, what in ((API_PORT, "api"), (WEB_PORT, "web")):
        if not _free(port):
            raise SystemExit(f"port {port} is busy — the {what} server needs it.")

    _seed(db_path)
    _seed_imaging(dirs["imaging"], dirs["archive"])
    _seed_documents(dirs["documents"])
    print(f"[shots] synthetic store at {tmp}")

    api = subprocess.Popen(
        [sys.executable, "-m", "uvicorn", "api:app", "--port", str(API_PORT)],
        cwd=ROOT, env=env, stdout=subprocess.DEVNULL, stderr=subprocess.STDOUT)
    web = None
    try:
        _wait(f"http://127.0.0.1:{API_PORT}/metrics", api, "backend")
        # Confirm from the OUTSIDE that this backend is serving the synthetic set,
        # not the real one — the assertions above prove the env, this proves the
        # process actually took it.
        served = json.loads(urllib.request.urlopen(
            f"http://127.0.0.1:{API_PORT}/metrics", timeout=5).read())
        names = {m["metric"] for m in served}
        assert names <= SYNTHETIC_METRICS, \
            f"backend is NOT serving the synthetic DB (saw {len(names)} metrics)"
        print(f"[shots] backend on :{API_PORT} serving {len(names)} synthetic metrics")

        web = subprocess.Popen(
            ["npm.cmd" if os.name == "nt" else "npm", "run", "dev", "--",
             "--port", str(WEB_PORT), "--strictPort"],
            cwd=os.path.join(ROOT, "frontend"),
            env={**env, "VITE_API_BASE": f"http://127.0.0.1:{API_PORT}"},
            stdout=subprocess.DEVNULL, stderr=subprocess.STDOUT)
        _wait(f"http://localhost:{WEB_PORT}/", web, "vite")
        print(f"[shots] web on :{WEB_PORT}")

        os.makedirs(args.out, exist_ok=True)
        with sync_playwright() as p:
            browser = p.chromium.launch()
            # The app's default theme choice is "system", resolved through matchMedia, so
            # emulating the OS preference is all it takes to shoot the dark theme. Without
            # this the dark theme could only be checked against the REAL record — which is
            # the one thing this harness exists to make unnecessary.
            page = browser.new_page(viewport={"width": 1400, "height": 1000},
                                    device_scale_factor=2,
                                    color_scheme="dark" if args.dark else "light")
            # View preferences live in localStorage (prefs.js, theme.js), and some of
            # them change what a page RENDERS — a chart's log axis and the amber notice
            # that rides it, for one. Seeding them here is what keeps such a view
            # checkable without pointing a browser at the real record. Written from an
            # init script so the value is present before the app's first read.
            for pref in args.pref:
                key, _, value = pref.partition("=")
                page.add_init_script(
                    f"try {{ localStorage.setItem({json.dumps(key)}, "
                    f"{json.dumps(value)}) }} catch (e) {{}}")
            for spec in args.targets:
                name, path, sel = (spec.split(":", 2) + [None])[:3]
                page.goto(f"http://localhost:{WEB_PORT}{path}")
                page.wait_for_timeout(2500)
                for sel_click in args.click:
                    el = page.query_selector(sel_click)
                    if el is None:
                        print(f"[click] !! {name}: no element matches {sel_click}")
                        continue
                    el.click()
                    page.wait_for_timeout(1200)
                    print(f"[click] {name}: {sel_click}")
                for sel_probe in args.probe:
                    boxes = page.eval_on_selector_all(sel_probe, """
                        els => els.map(e => {
                          const r = e.getBoundingClientRect();
                          const nat = e.width && e.height ? ` natural=${e.width}x${e.height}` : '';
                          return `${e.tagName.toLowerCase()}.${e.className || '-'} `
                               + `${r.width.toFixed(1)}x${r.height.toFixed(1)}${nat}`;
                        })
                    """)
                    for b in boxes:
                        print(f"[probe] {name}: {b}")
                out = os.path.join(args.out, f"{name}.png")
                if sel:
                    el = page.query_selector(sel)
                    if el is None:
                        print(f"[shots] !! {name}: no element matches {sel}")
                        continue
                    el.screenshot(path=out)
                else:
                    page.screenshot(path=out, full_page=True)
                print(f"[shots] {out}")
            browser.close()
    finally:
        for proc in (web, api):
            if proc and proc.poll() is None:
                proc.terminate()
                try:
                    proc.wait(timeout=10)
                except subprocess.TimeoutExpired:
                    proc.kill()
        shutil.rmtree(tmp, ignore_errors=True)
        print("[shots] torn down")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
