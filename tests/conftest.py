"""
Shared pytest fixtures for the Clarity test suite.

Flat imports (import db / api / metric_config) — the repo root is on PYTHONPATH.
Every test runs against a SYNTHETIC, throwaway DB built from schema.sql; the real
health.db is never opened. The schema_root fixture pins schema.sql by absolute
path so tests don't depend on the working directory (db.init_db otherwise reads
"schema.sql" relative to CWD).
"""

from __future__ import annotations

import os
import shutil
import tempfile

import pytest

import db
import api
import dicom_store
import docstore
import gateway
import metric_config
import reports

_SIDECARS = ("-wal", "-shm", "-journal")
_REPO_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))


@pytest.fixture(autouse=True)
def _isolate_audit_log(tmp_path, monkeypatch):
    """Redirect the gateway audit log to a per-test temp file for EVERY test.

    Without this, any test that drives gateway.complete end-to-end (the mocked
    hosted tests, the local-engine paths) appends to the REAL gateway_audit.log
    in the repo root — polluting the user's transparency record with entries
    for sends that never actually happened. Found via the /export/audit reader:
    each pytest run was adding a fake external-send pair to the real log."""
    monkeypatch.setattr(gateway, "_AUDIT_LOG", str(tmp_path / "audit_test.log"))


@pytest.fixture(autouse=True)
def _isolate_imaging_store(tmp_path, monkeypatch):
    """Point the DICOM store at an empty per-test folder for EVERY test. Without this,
    any test touching /timeline (which now includes imaging entries) or /imaging would
    read the REAL imaging_store — the user's actual medical images — making tests
    non-hermetic and their output data-dependent. Tests that WANT sample DICOM override
    this by re-monkeypatching IMAGING_DIR (see test_dicom_imaging.py)."""
    monkeypatch.setattr(dicom_store, "IMAGING_DIR", str(tmp_path / "imaging_empty"))
    monkeypatch.setattr(dicom_store, "_scan_cache", {})


@pytest.fixture(autouse=True)
def _isolate_report_archive(tmp_path, monkeypatch):
    """Same hermeticity rule as the imaging store, for the same reason: without this, any
    test hitting /reports or /imaging/studies (which links studies to their reports) would
    read the REAL imaging_archive — the user's actual radiology reports, prose containing
    their name and DOB. Tests that WANT a report override this by re-monkeypatching
    ARCHIVE_DIR (see test_reports.py)."""
    monkeypatch.setattr(reports, "ARCHIVE_DIR", str(tmp_path / "archive_empty"))


@pytest.fixture(autouse=True)
def _isolate_document_store(tmp_path, monkeypatch):
    """Same hermeticity rule as the imaging store and report archive, for the same reason:
    without this, any test hitting /documents would read the REAL documents_store — the
    user's split-up hospital record, prose carrying their name, DOB and record number on
    every page. Tests that WANT a document override this by re-monkeypatching DOCS_DIR
    (see test_docstore.py)."""
    monkeypatch.setattr(docstore, "DOCS_DIR", str(tmp_path / "documents_empty"))


@pytest.fixture
def schema_root() -> str:
    """Absolute path to schema.sql at the repo root, so init_db is CWD-independent."""
    return os.path.join(_REPO_ROOT, "schema.sql")


@pytest.fixture
def temp_db():
    """A throwaway DB file path inside a temp dir. Teardown removes the dir and any
    WAL/SHM sidecars."""
    tmpdir = tempfile.mkdtemp(prefix="ht_test_")
    try:
        yield os.path.join(tmpdir, "test.db")
    finally:
        shutil.rmtree(tmpdir, ignore_errors=True)


@pytest.fixture
def db_conn(temp_db, schema_root):
    """A connection to a freshly-initialized synthetic DB (db-layer fixture)."""
    conn = db.connect(temp_db)
    db.init_db(conn, schema_path=schema_root)
    try:
        yield conn
    finally:
        conn.close()


@pytest.fixture
def client(temp_db):
    """A TestClient bound to a synthetic DB. Rebinds api.DB_PATH to the temp DB
    BEFORE lifespan runs (so init_db + link_seed_keys + seed_defaults build the
    synthetic schema), and RESTORES the original on teardown — api.DB_PATH is
    module-level mutable state, so unrestored rebinding bleeds across tests."""
    from fastapi.testclient import TestClient

    original = api.DB_PATH
    api.DB_PATH = temp_db
    try:
        with TestClient(api.app) as c:
            yield c
    finally:
        api.DB_PATH = original


# --- builder helpers (plain functions; tests import and call them) -------------

def _lowest_dependency_seed_name() -> str:
    """The threshold-bearing SEED entry whose `thresholds` key carries the fewest
    thresholds — introspected, never hardcoded, so it tracks SEED edits. Restricted
    to entries that actually HAVE thresholds: display-only SEED entries (a
    methodology_note with no thresholds, #9) would otherwise win at zero and hand
    the rename-survival tests a metric with no detector config to survive — the
    opposite of what they assert."""
    threshold_bearing = [
        name for name in metric_config.SEED if metric_config.SEED[name].get("thresholds")
    ]
    return min(
        threshold_bearing,
        key=lambda name: len(metric_config.SEED[name]["thresholds"]),
    )


def make_seeded_metric_with_obs(conn) -> str:
    """Build a complete SEED-linked metric WITH an observation, via public funcs:
    add an observation under a SEED name (mints the registry row with seed_key set),
    link seed keys, then seed config. Returns the chosen metric name so a test can
    reference it without re-deriving. Commits."""
    name = _lowest_dependency_seed_name()
    db.add_observation(
        conn, metric=name, value=1.0, unit="x", observed_on="2020-01-01",
        seed_keys=metric_config.SEED.keys(),
    )
    db.link_seed_keys(conn, metric_config.SEED.keys())
    metric_config.seed_defaults(conn)
    conn.commit()
    return name


def make_orphan_metric(conn, name: str) -> str:
    """Create a registry-present, zero-observation metric (get_or_create_metric does
    not self-commit, so commit here). Returns the name."""
    db.get_or_create_metric(conn, name, seed_keys=())
    conn.commit()
    return name
