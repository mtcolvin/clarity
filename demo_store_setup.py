"""
Build (or reuse) the demo store: `python -m demo_store_setup`.

Run by demo.bat before it starts the servers. Separate from synthetic.py so that module
stays importable by the API without doing anything on import, and separate from demo.bat so
the logic is testable and readable rather than batch script.

It takes its paths from the SAME environment variables the backend will, which is the point:
if the launcher's env is wrong, the seed lands wherever the backend would have looked, and
the mistake is visible instead of silent. It also REFUSES to seed anything that isn't
plainly a demo path — the one catastrophic outcome here is seeding invented rows over a real
record, so that is checked rather than trusted.
"""

from __future__ import annotations

import os
import sys

import db
import synthetic

# The real stores, by their default names. Seeding into any of these would write invented
# readings into a real medical record, so it is refused outright — the same shape of guard
# verify/ui_shots.py makes before it starts a backend.
#
# gateway_audit.log is in this list for a reason worth stating: it is the FIFTH data source,
# and the only one that is not a "store" in the obvious sense, so it was the one the demo
# launcher forgot. It holds the verbatim payload of every external send — real readings,
# real findings, and on a full-picture send the report prose and condition notes too — and
# Settings reads it back. A demo process left pointing at the real file shows all of that
# under a badge saying the record is invented, which is exactly the lie demo mode exists to
# prevent. (Observed: the demo instance served 20 real entries.)
REAL_PATHS = ("health.db", "imaging_store", "imaging_archive", "documents_store",
              "gateway_audit.log")


def _refuse_real(label: str, path: str) -> str:
    full = os.path.abspath(path)
    for real in REAL_PATHS:
        if full == os.path.abspath(real):
            raise SystemExit(
                f"REFUSED: {label} points at {real}, which is REAL. The demo must never "
                f"write to — or read from — the record it exists to avoid showing.")
    return full


def main() -> int:
    db_path = _refuse_real("HEALTH_DB", os.environ.get("HEALTH_DB", "demo_store/demo.db"))
    imaging = _refuse_real("HEALTH_IMAGING_DIR",
                           os.environ.get("HEALTH_IMAGING_DIR", "demo_store/imaging"))
    archive = _refuse_real("HEALTH_IMAGING_ARCHIVE",
                           os.environ.get("HEALTH_IMAGING_ARCHIVE", "demo_store/archive"))
    documents = _refuse_real("HEALTH_DOCUMENTS_DIR",
                             os.environ.get("HEALTH_DOCUMENTS_DIR", "demo_store/documents"))
    # Not seeded — nothing writes it until a send happens — but checked here because this
    # is where the launcher's env is vetted, and an unset value silently means the real log.
    audit = _refuse_real("GATEWAY_AUDIT_LOG",
                         os.environ.get("GATEWAY_AUDIT_LOG", "demo_store/gateway_audit.log"))

    for folder in (os.path.dirname(db_path), imaging, archive, documents,
                   os.path.dirname(audit)):
        if folder:
            os.makedirs(folder, exist_ok=True)

    if os.path.exists(db_path):
        conn = db.connect(db_path)
        try:
            if synthetic.is_synthetic(conn):
                print(f"[demo] reusing {db_path}")
                return 0
        finally:
            conn.close()
        # A database that exists but carries no marker is not ours to overwrite.
        raise SystemExit(
            f"REFUSED: {db_path} exists but is not marked as a demo store. "
            f"Delete it deliberately if you meant to rebuild the demo.")

    print(f"[demo] seeding {db_path}")
    conn = db.connect(db_path)
    try:
        synthetic.seed_db(conn)
    finally:
        conn.close()

    accession = synthetic.seed_imaging(imaging)
    if accession:
        synthetic.seed_reports(archive, accession)
        print(f"[demo] seeded synthetic imaging + one report ({accession})")
    else:
        print("[demo] pydicom not installed - the imaging page will show its empty state")

    # The Documents page merges BOTH local document sources, so seeding only the imaging
    # disc's report left it showing a single item and an empty reader. See synthetic.py.
    print(f"[demo] seeded {synthetic.seed_documents(documents)} scanned documents")
    print("[demo] done")
    return 0


if __name__ == "__main__":
    sys.exit(main())
