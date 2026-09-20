# Clarity

A local-first personal health record. It keeps your labs, vitals, imaging, clinical
documents and history on one timeline, on your own machine, and points at the things
in your own data that stand out — so you can ask better questions at your next
appointment.

**Clarity does not diagnose, and is not a medical device.** It surfaces and describes;
it never tells you what a result means for your health. Every finding is framed as
something to raise with a clinician. See [Safety](#safety-surface-never-diagnose).

---

## Why it exists

Your medical history arrives scattered: lab results in one portal, imaging on a disc,
a discharge summary as a 200-page scan, and nothing that puts them side by side. Most
apps that fix this want your records on their servers.

Clarity runs entirely on your machine. There is no account, no sync, no server, and no
telemetry. The database is a SQLite file in the project folder. Nothing leaves the
machine unless you explicitly send it, and when you do, you see exactly what is going
and approve it first.

## What it does

- **Labs and vitals** — one time-series for every numeric measurement, charted with
  the reference range for *that specific result* (ranges vary by lab, age and sex, so
  they are stored per reading rather than per metric).
- **Flags what stands out** — out of range, drifting over time, unusual *for you*
  against your own baseline, a jump bigger than assay noise, or a value that crossed a
  published guideline cutoff. All computed deterministically; see
  [Detectors](#detectors).
- **Computed metrics** — ratios and derived values your lab does not print (BUN:Cr,
  non-HDL, AST/ALT, calculated osmolality and others), computed from your stored
  analytes and honest about missing inputs: if an input is absent for a draw, that date
  is omitted rather than faked.
- **DICOM imaging viewer** — reads a hospital CD or exported study, with window/level
  applied in the browser, PACS-convention keyboard and mouse, distance and angle
  measurement, and ROI statistics in real units. It follows the DICOM VOI LUT spec and
  excludes out-of-field pixels from statistics, which is the difference between a
  region mean that is right and one that is off by hundreds of Hounsfield units.
- **Documents and reports** — scanned records and radiology reports, full-text
  searchable. The reader shows you the scan itself, never a transcription.
- **Timeline** — labs, imaging, conditions, medications, events and immunizations on
  one dated line.
- **Profile** — biological sex, age, weight and height history.

## Privacy

Privacy is the project's first priority, ahead of features and convenience. The rules
are written down in [`CLAUDE.md`](CLAUDE.md) and enforced in code:

- **Nothing is sent anywhere without per-action confirmation.** There is one gateway
  module that every outbound model call must route through — a single chokepoint, so
  privacy is never reimplemented per feature.
- **You see the whole payload before it leaves.** Not a summary, not a hash: the
  complete outbound content, plus the instruction being sent with it. Confirmation is
  bound to the exact bytes you reviewed, so nothing can change between preview and
  send.
- **Identifiers are excluded by construction, not stripped.** Payloads are built by
  *inclusion* against an allowlist. Your name, date of birth and record numbers are
  never read by the code that assembles them — the date of birth is consumed to compute
  an age and never copied.
- **Every external send is logged locally, verbatim**, and readable in Settings.
- **The imaging viewer and document reader have no external path at all.** A medical
  image can carry identifiers burned into its pixels, which no allowlist can reach, so
  those features never touch the network.

Hosted model access is **off by default**, and is a capability toggle you can switch
back off as easily as on.

## Safety: surface, never diagnose

Clarity computes facts about your numbers — out of range, slope, deviation from your
own baseline, crossing a cited guideline line. It does not interpret what those facts
mean for your health. It names no conditions and suggests no treatment. A flag means
"look at this," never "you have this."

There is one deliberate, opt-in exception: if you explicitly send a bundle to an
external model, that model may raise hedged possibilities to discuss with a clinician.
It is off by default, previewed, confirmed per send, and clearly labelled as model
reasoning. The app itself never does this.

**This is not a substitute for professional medical advice.** Talk to your doctor.

## Install

Requires **Python 3.13** and **Node 20+**.

```bash
python -m venv .venv
.venv\Scripts\activate            # Windows;  source .venv/bin/activate elsewhere
pip install -r requirements.txt

cd frontend && npm install
```

## Run

On Windows, double-click **`start.bat`** — it launches both servers in their own
windows, waits for the ports, and opens the browser. Or manually:

```bash
uvicorn api:app --reload          # API + interactive docs at http://127.0.0.1:8000/docs
cd frontend && npm run dev        # dashboard at http://localhost:5173
```

**Demo mode** — `demo.bat` runs the app against a wholly invented record on separate
ports, so you can show it to someone without your own history on screen. The demo record
is a different person by design, and the app reads a marker inside the database to label
itself, so a demo window can never quietly be showing real data.

**Publishing a demo** — `build_static_demo.py` snapshots every GET response from a
demo-store backend into a folder of files, builds the frontend to read them, and leaves a
directory you can upload to any static host. No server, no database, nothing to patch;
the published demo is read-only and writes are refused in the client. It refuses to run
against anything but the demo store, and re-checks from outside that the backend it
started reports a demo marker before capturing a byte.

```bash
python build_static_demo.py --out static-demo
python build_static_demo.py --out static-demo --serve 8080   # preview it
```

Use that `--serve` rather than `python -m http.server`: the latter's 5-deep listen backlog
refuses this app's parallel requests, which reaches the browser as "fetch failed" and reads
as a broken demo.

`.github/workflows/demo.yml` publishes it to this repository's own GitHub Pages site on
every push — tests, seed, build, then a check that the built artifact actually renders
before anything is deployed. Enable it once under **Settings → Pages → Source: GitHub
Actions**. The demo store is generated during the run and is not in this repository, so
there is no committed record for the workflow to publish.

## Detectors

| Function | Catches |
|---|---|
| `flag_out_of_range` | value outside this result's reference range |
| `personal_baseline_z` | abnormal *for you* — robust z-score (median + MAD) against your own history |
| `linear_trend` | least-squares slope drifting over time, even while every value stays in range |
| `mann_kendall` | monotonic trend, no linearity assumption |
| `rcv_delta` | a jump bigger than combined assay + biological noise |
| `clinical_threshold_crossing` | latest value crossed a published guideline cutoff |
| `flag_threshold_level` | latest value is standing on a cutoff's concerning side |

All of them are pure functions over plain numbers, in `analysis.py`. They touch no
database and no model. Guideline cutoffs are curated with sources cited; the rules for
that live in `.claude/skills/threshold-curation/SKILL.md`.

## Architecture

Strictly separated layers, each independently testable:

| Module | Role |
|---|---|
| `schema.sql`, `db.py` | persistence only — the only module that runs SQL |
| `analysis.py` | pure detection math — no SQL, no model, no I/O |
| `gateway.py` | the privacy chokepoint — the only module that may call a model |
| `narrate.py` | turns finished flags into plain language; computes nothing |
| `api.py` | HTTP transport — no analysis math, no SQL |
| `dicom_store.py`, `reports.py`, `docstore.py` | local imaging, reports, documents |
| `picture.py`, `explain.py` | deterministic export-payload assembly |
| `frontend/` | React + Recharts dashboard |

The core rule is **detect deterministically, narrate later**: a model may restate or
reason about what the engine found, but never computes a number the interface presents
as fact.

## Tests

```bash
pytest                            # 432 tests, hermetic (no API key needed)
python demo.py                    # end-to-end smoke check on an in-memory DB
cd frontend && npm run smoke      # mounts every page under StrictMode; backend must be up
```

Screenshots of the UI go through `verify/ui_shots.py`, which starts its own backend
against synthetic data — never the real record.

## Status and limitations

Clarity is a personal project, built around one person's record and published because
the architecture may be useful to others. Be aware:

- **Single-user and local by design.** No accounts, no multi-user support, no cloud.
- **Readings are entered manually.** PDF lab import was built and then removed — it was
  wrong too often to trust, and a per-lab-layout parser is an endless treadmill.
  Automated ingestion (FHIR / portal export) is the obvious next step and does not
  exist yet.
- **Windows-first.** The launchers are batch files; the Python and the frontend are
  portable.
- **Not packaged.** You run it from a checkout with a virtualenv.

## License

**GNU Affero General Public License v3.0** — see [`LICENSE`](LICENSE).

AGPL rather than a permissive license on purpose: section 13 means anyone who runs a
modified version of Clarity as a network service has to publish their changes. For a
health-records tool whose entire value proposition is that it runs on your own machine
and sends nothing anywhere, a silently-modified hosted fork is precisely the outcome
worth preventing.

Copyright (C) 2026 mtcolvin.
