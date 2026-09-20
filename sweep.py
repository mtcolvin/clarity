"""
sweep.py — endpoint snapshot/diff harness (refactor safety net).

WHAT THIS IS
    A standalone script (NOT pytest) that drives the FastAPI app against a frozen
    COPY of health.db and records, per endpoint, {status, sha256, body}. Two
    captures of the same data must be byte-identical; `diff` proves a refactor
    changed no response by comparing sha256 per endpoint. Run via the project
    venv with the repo root on PYTHONPATH:

        .venv/Scripts/python.exe sweep.py capture <out.json>
        .venv/Scripts/python.exe sweep.py diff <a.json> <b.json>

THE DETERMINISTIC SET — four endpoints are EXCLUDED on purpose, because their
bodies can differ between two runs over byte-identical data, which would create
false positives that destroy the proof:
    * /summary/{metric} — routes through the swappable summarizer/narration engine
      (a model may run); its text is not a pure function of the stored data.
    * /changes — CLOCK-RELATIVE: its `moved` list membership is filtered by
      analysis.is_recent(observed_on), which defaults to date.today(). The surfaced
      set changes as the wall clock advances with zero data change.
    * /settings — kept excluded (the summarizer-engine radio's group + shape may
      still churn as settings are added/reworded). It USED to be environment-
      relative via a live Ollama-reachability `available` flag; that probe was
      removed with the Ollama summarizer, so /settings is deterministic again —
      it could be re-included on the next baseline refresh, but stays excluded
      here to avoid a baseline regen mid-batch.
    * /export/audit — FILE-RELATIVE: reads gateway_audit.log (not the DB the
      sweep copies), so its body reflects whatever sends the MACHINE has made,
      independent of the data snapshot. Any confirmed send between captures
      would drift the baseline with zero data change.

URL RULE — the metric/field path segment is percent-encoded with
    urllib.parse.quote(name, safe="/")
  so a RAW slash is preserved (the per-metric routes are declared `{metric:path}`,
  whose converter matches embedded slashes — e.g. "A/G Ratio"), while a space
  becomes %20 and a literal percent becomes %25. Encoding a slash to %2F would
  break {metric:path} matching, so "/" stays in the safe set.

STANDUP IS WRITE-BEARING — the app's lifespan runs init_db (additive migrations,
  metric-registry backfill) and seed_defaults (UPSERTs metric_config) on startup.
  So the harness NEVER stands up against the real DB: it copies health.db (plus any
  -wal/-shm/-journal sidecars, for a consistent copy) to a temp path, rebinds
  api.DB_PATH to the copy so lifespan's writes land on the COPY, runs the app, then
  deletes the copy. The real DB is only ever read (byte-copied) for the copy step.
  dependency_overrides is deliberately NOT used — it would redirect per-request
  connections but NOT lifespan's init_db/seed, which read api.DB_PATH directly.

OUTPUT IS HEALTH-DATA-DERIVED — capture writes the full bodies to the JSON file
  you name. Point it at a temp/scratch path OUTSIDE the repo tree; this corpus is
  untracked by design and must never be committed.
"""

from __future__ import annotations

import hashlib
import json
import os
import shutil
import sys
import tempfile
from contextlib import contextmanager
from urllib.parse import quote


# Endpoints excluded from the deterministic set (see the header for the why of each).
EXCLUDED = ("/summary", "/changes", "/settings", "/export/audit")

# The five per-metric deterministic GET families. Each is formatted with the
# percent-encoded metric segment.
PER_METRIC_FAMILIES = (
    "/flags/{seg}",
    "/history/{seg}",
    "/observations/{seg}",
    "/chart-config/{seg}",
    "/metric-settings/{seg}",
)

# The ten global deterministic GETs (no path params).
GLOBAL_ENDPOINTS = (
    "/metrics",
    "/metrics-coverage",
    "/overview",
    "/conditions",
    "/medications",
    "/events",
    "/profile",
    "/timeline",
    # The one-time global personal-baseline explainer's seen-flag. Deterministic
    # (a plain persisted boolean, no clock/environment dependence) — unlike
    # /settings it carries no live-probed `available` field, so it's swept.
    "/baseline-explainer",
    # The export handoff's capability gate (CLAUDE.md "The export handoff").
    # Same shape/reasoning as /baseline-explainer above: a plain persisted
    # boolean, deterministic, no live-probed field, so it's swept.
    "/export/enabled",
    # Saved export RESULTS — the model responses kept locally, joined to their
    # sends by audit_id. Deterministic: a plain DB read (no clock, no live probe,
    # no model call at read time), unlike its sibling /export/audit, which is
    # EXCLUDED above because it reads gateway_audit.log rather than the DB the
    # sweep copies. Was simply never added when the route shipped.
    "/export/results",
)

# SQLite sidecar suffixes to carry along so the copy is consistent if a WAL exists.
_SIDECAR_SUFFIXES = ("-wal", "-shm", "-journal")


def _encode_segment(name: str) -> str:
    """Percent-encode a metric/field name for a {metric:path} segment: raw slash
    preserved (safe="/"), space -> %20, literal % -> %25."""
    return quote(name, safe="/")


@contextmanager
def app_on_copy():
    """Stand up the FastAPI app against a fresh, consistent COPY of health.db.

    Copies health.db (+ sidecars) into a temp dir, rebinds api.DB_PATH to the copy
    BEFORE the app's lifespan runs (so init_db/seed_defaults write to the copy, not
    the real DB), yields a live TestClient, and on exit tears down the client and
    deletes the temp dir. The real DB is only read (byte-copied).
    """
    from fastapi.testclient import TestClient
    import api

    real_db = os.path.abspath(api.DB_PATH)
    tmpdir = tempfile.mkdtemp(prefix="sweep_db_")
    copy_db = os.path.join(tmpdir, "health.db")
    try:
        # Read-only byte copy of the main file + any sidecars present.
        shutil.copy2(real_db, copy_db)
        for suffix in _SIDECAR_SUFFIXES:
            side = real_db + suffix
            if os.path.exists(side):
                shutil.copy2(side, copy_db + suffix)

        # Rebind the path the app reads at lifespan/request time. api.DB_PATH is read
        # inside lifespan() and get_conn() at runtime (not at import/app-construction),
        # so setting it here — before the TestClient context enters and runs lifespan —
        # is what redirects the startup writes onto the copy.
        api.DB_PATH = copy_db

        with TestClient(api.app) as client:  # entering runs lifespan against the copy
            yield client
    finally:
        shutil.rmtree(tmpdir, ignore_errors=True)


def enumerate_endpoints(client) -> list[str]:
    """Build the deterministic endpoint list FROM the running app: the app's own
    canonical /metrics list drives the per-metric families; _MEASUREMENT_FIELDS
    drives /profile/history. Returns request paths (metric/field segments already
    percent-encoded). The total is derived (5*N + 2 + 10), never hardcoded."""
    import api

    resp = client.get("/metrics")
    resp.raise_for_status()
    metrics = [row["metric"] for row in resp.json()]

    endpoints: list[str] = []
    for metric in metrics:
        seg = _encode_segment(metric)
        for family in PER_METRIC_FAMILIES:
            endpoints.append(family.format(seg=seg))

    for field in api._MEASUREMENT_FIELDS:
        endpoints.append(f"/profile/history/{_encode_segment(field)}")

    endpoints.extend(GLOBAL_ENDPOINTS)

    n_metrics = len(metrics)
    expected = 5 * n_metrics + len(api._MEASUREMENT_FIELDS) + len(GLOBAL_ENDPOINTS)
    print(f"[enumerate] metrics (N) = {n_metrics}")
    print(f"[enumerate] per-metric families = {len(PER_METRIC_FAMILIES)} "
          f"-> {5 * n_metrics} endpoints")
    print(f"[enumerate] profile/history fields = {len(api._MEASUREMENT_FIELDS)}")
    print(f"[enumerate] global GETs = {len(GLOBAL_ENDPOINTS)}")
    print(f"[enumerate] excluded (not swept): {', '.join(EXCLUDED)}")
    print(f"[enumerate] total enumerated = {len(endpoints)} "
          f"(expected 5*{n_metrics}+{len(api._MEASUREMENT_FIELDS)}+{len(GLOBAL_ENDPOINTS)} "
          f"= {expected})")
    assert len(endpoints) == expected, "enumerated count != derived 5*N+2+10"
    return endpoints


def capture(out_path: str) -> int:
    """Snapshot every deterministic endpoint to a single JSON file.

    Records {endpoint, status, sha256, body} per endpoint. The sha256 is over the
    response bytes AS RETURNED (resp.content) — never re-serialized — and the body
    is stored alongside from the start so a later diff can print it.
    """
    records: list[dict] = []
    with app_on_copy() as client:
        endpoints = enumerate_endpoints(client)
        for ep in endpoints:
            resp = client.get(ep)
            raw = resp.content  # bytes exactly as returned
            records.append({
                "endpoint": ep,
                "status": resp.status_code,
                "sha256": hashlib.sha256(raw).hexdigest(),
                "body": raw.decode("utf-8", errors="replace"),
            })

    payload = {"count": len(records), "records": records}
    with open(out_path, "w", encoding="utf-8") as f:
        json.dump(payload, f, ensure_ascii=False, indent=2)

    ok = sum(1 for r in records if r["status"] == 200)
    print(f"[capture] wrote {len(records)} records to {out_path}")
    print(f"[capture] 200 OK: {ok}  non-200: {len(records) - ok}")
    return 0


def _load(path: str) -> dict[str, dict]:
    with open(path, encoding="utf-8") as f:
        payload = json.load(f)
    return {r["endpoint"]: r for r in payload["records"]}


def diff(path_a: str, path_b: str) -> int:
    """Compare two capture files by sha256 per endpoint. Prints matched/differing
    counts; for each differing endpoint prints the key + both bodies. Also flags any
    endpoint present in one capture but not the other. Exits nonzero on any diff."""
    a = _load(path_a)
    b = _load(path_b)

    keys_a, keys_b = set(a), set(b)
    only_a = sorted(keys_a - keys_b)
    only_b = sorted(keys_b - keys_a)
    shared = sorted(keys_a & keys_b)

    matched = 0
    differing: list[str] = []
    for k in shared:
        if a[k]["sha256"] == b[k]["sha256"]:
            matched += 1
        else:
            differing.append(k)

    print(f"[diff] matched: {matched}")
    print(f"[diff] differing: {len(differing)}")
    if only_a:
        print(f"[diff] only in A ({len(only_a)}): {', '.join(only_a)}")
    if only_b:
        print(f"[diff] only in B ({len(only_b)}): {', '.join(only_b)}")

    for k in differing:
        print("\n" + "=" * 72)
        print(f"DIFF: {k}")
        print(f"  status A={a[k]['status']} B={b[k]['status']}")
        print(f"  sha256 A={a[k]['sha256']}")
        print(f"  sha256 B={b[k]['sha256']}")
        print("--- A body ---")
        print(a[k]["body"])
        print("--- B body ---")
        print(b[k]["body"])

    return 0 if (not differing and not only_a and not only_b) else 1


def _usage() -> int:
    print(__doc__.strip().splitlines()[0])
    print("usage:")
    print("  python sweep.py capture <out.json>")
    print("  python sweep.py diff <a.json> <b.json>")
    return 2


def main(argv: list[str]) -> int:
    if len(argv) < 2:
        return _usage()
    cmd = argv[1]
    if cmd == "capture" and len(argv) == 3:
        return capture(argv[2])
    if cmd == "diff" and len(argv) == 4:
        return diff(argv[2], argv[3])
    return _usage()


if __name__ == "__main__":
    # Force UTF-8 on stdout before printing anything. A differing record is printed with
    # its body, and the DB holds text this console's default cp1252 can't encode — a saved
    # model response containing a non-breaking hyphen (U+2011) was enough to raise
    # UnicodeEncodeError mid-report. The failure looked like the HARNESS breaking when it
    # had in fact found a legitimate 1-record difference and died describing it, which is
    # the worst way for a diff tool to fail: it hides the answer it just computed.
    # Capture is unaffected (it already writes its file as UTF-8) — this is console-only.
    try:
        sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    except (AttributeError, OSError):
        pass                              # non-reconfigurable stream: print as before
    sys.exit(main(sys.argv))
