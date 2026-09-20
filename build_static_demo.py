"""
build_static_demo.py — publish the demo as a folder of static files.

WHAT IT DOES. Starts a throwaway backend against the seeded DEMO store, walks every GET
route the frontend uses, writes each response to a file whose path mirrors the route,
builds the frontend in `static` mode (API_BASE -> ./api), and leaves a directory you can
upload anywhere that serves files. No server, no database, nothing to run or patch.

WHY A SNAPSHOT AND NOT A HOSTED BACKEND. A hosted demo means a machine to pay for and
keep patched, a write path open to the internet, and a reset job for when someone edits
the record. A folder of files has none of those and cannot be attacked in any
interesting way.

=== THE SAFETY RULE, WHICH IS THE WHOLE POINT OF THIS FILE ===

This script publishes its output to the open internet. If it ever read the real record,
the real record would BE the published artifact — the single worst outcome this project
has. So, exactly like `verify/ui_shots.py` and `demo_store_setup.py`, it does not trust
itself to be pointed at the right place:

  1. It refuses to run unless every store path is inside the demo store.
  2. It asserts the env BEFORE starting the backend, and then re-checks FROM OUTSIDE
     that the backend it started reports `GET /demo -> {"demo": true}`, because a
     marker inside the database is the one claim a mis-pointed process cannot fake.
  3. It refuses if the snapshot would contain the real audit log.

The second check exists because a previous incident in this project was precisely a
stub that looked right and was not.

USAGE
    .venv/Scripts/python.exe build_static_demo.py --out static-demo
    .venv/Scripts/python.exe build_static_demo.py --out static-demo --skip-frontend
"""
from __future__ import annotations

import argparse
import json
import re
import os
import shutil
import socket
import subprocess
import sys
import time
import urllib.error
import urllib.parse
import urllib.request

ROOT = os.path.dirname(os.path.abspath(__file__))
DEMO_STORE = os.path.join(ROOT, "demo_store")

# Search is a live query against the backend, so a static build can only answer terms it
# was told about. These are drawn from the seeded record's own story (the hypothyroidism
# and iron-deficiency threads in synthetic.py) so the demo's search actually finds
# something. Anything else reports "not part of this demo snapshot" rather than an error.
DEMO_SEARCHES = [
    "thyroid", "tsh", "levothyroxine", "ferritin", "iron",
    "hemoglobin", "anemia", "discharge", "consultation",
]


def _free_port() -> int:
    with socket.socket() as s:
        s.bind(("127.0.0.1", 0))
        return s.getsockname()[1]


def _demo_env() -> dict:
    """The store paths for the demo backend. ALL FIVE of them — the audit log included.

    The audit log is the fifth real data source and the one that has been forgotten
    before: it holds the verbatim payload of every external send from the real record.
    A snapshot that picked it up would publish that history under a banner saying the
    record is invented.
    """
    env = dict(os.environ)
    env.update({
        "HEALTH_DB": os.path.join(DEMO_STORE, "demo.db"),
        "HEALTH_IMAGING_DIR": os.path.join(DEMO_STORE, "imaging"),
        "HEALTH_IMAGING_ARCHIVE": os.path.join(DEMO_STORE, "archive"),
        "HEALTH_DOCUMENTS_DIR": os.path.join(DEMO_STORE, "documents"),
        "GATEWAY_AUDIT_LOG": os.path.join(DEMO_STORE, "gateway_audit.log"),
    })
    return env


def _assert_demo_paths(env: dict) -> None:
    """Refuse before anything starts if a store path points outside the demo store."""
    demo = os.path.abspath(DEMO_STORE)
    for key in ("HEALTH_DB", "HEALTH_IMAGING_DIR", "HEALTH_IMAGING_ARCHIVE",
                "HEALTH_DOCUMENTS_DIR", "GATEWAY_AUDIT_LOG"):
        value = os.path.abspath(env[key])
        if os.path.commonpath([value, demo]) != demo:
            sys.exit(f"REFUSING: {key} is outside the demo store ({value}).")
    if not os.path.isfile(env["HEALTH_DB"]):
        sys.exit("REFUSING: no demo database. Build it first:  python -m demo_store_setup")


class Backend:
    """A throwaway uvicorn on a free port, pointed at the demo store."""

    def __init__(self) -> None:
        self.port = _free_port()
        self.base = f"http://127.0.0.1:{self.port}"
        self.proc: subprocess.Popen | None = None

    def __enter__(self) -> "Backend":
        env = _demo_env()
        _assert_demo_paths(env)
        self.proc = subprocess.Popen(
            [sys.executable, "-m", "uvicorn", "api:app",
             "--host", "127.0.0.1", "--port", str(self.port), "--log-level", "warning"],
            cwd=ROOT, env=env,
            stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
        )
        for _ in range(120):
            try:
                with urllib.request.urlopen(f"{self.base}/demo", timeout=1) as r:
                    payload = json.load(r)
                break
            except Exception:
                if self.proc.poll() is not None:
                    sys.exit("The demo backend exited during startup.")
                time.sleep(0.25)
        else:
            sys.exit("The demo backend never answered.")

        # The load-bearing check: ask the RUNNING process what store it is on. The marker
        # lives in the database, so this cannot come back true for the real record.
        if payload.get("demo") is not True:
            self.__exit__(None, None, None)
            sys.exit("REFUSING: the backend does not report a demo store. Nothing captured.")
        print(f"  demo backend on {self.base}  (GET /demo -> demo:true)")
        return self

    def __exit__(self, *exc) -> None:
        if self.proc and self.proc.poll() is None:
            self.proc.terminate()
            try:
                self.proc.wait(timeout=10)
            except subprocess.TimeoutExpired:
                self.proc.kill()


# --- route -> filename -------------------------------------------------------------
# Both this script and `frontend/src/snapshot.js` compute this, and they MUST agree;
# `tests/test_static_demo_key.py` runs the JavaScript against this and requires identical
# output for the same routes.
#
# Why not simply mirror the URL. Three metrics here contain a slash ("AST/ALT Ratio"), so
# a mirrored path needs %2F in the request, and a great many static hosts — nginx, S3,
# GitHub Pages — reject or silently normalize an encoded slash. Sixteen more contain
# spaces, where the server decoding %20 then had to find a file literally named with a
# space. Both問 make correctness depend on the host's URL handling. A name containing only
# [A-Za-z0-9._-] depends on nothing.
#
# The hash is what keeps it injective: slugging alone maps "a/b" and "a b" to the same
# string. djb2 is not cryptographic and does not need to be — it is disambiguating file
# names, not protecting anything.
def route_key(route: str) -> str:
    h = 5381
    for ch in route:
        h = ((h * 33) ^ ord(ch)) & 0xFFFFFFFF
    digits = "0123456789abcdefghijklmnopqrstuvwxyz"
    b36 = ""
    n = h
    while n:
        n, r = divmod(n, 36)
        b36 = digits[r] + b36
    slug = re.sub(r"[^A-Za-z0-9._-]+", "-", route).strip("-")[:80]
    return f"{slug}-{b36 or '0'}"


class Snapshot:
    def __init__(self, base: str, out: str) -> None:
        self.base, self.out = base, out
        self.n_files = self.n_bytes = self.n_missing = 0

    def _write(self, rel: str, data: bytes) -> None:
        path = os.path.join(self.out, rel.lstrip("/"))
        os.makedirs(os.path.dirname(path), exist_ok=True)
        with open(path, "wb") as fh:
            fh.write(data)
        self.n_files += 1
        self.n_bytes += len(data)

    def _fetch(self, route: str) -> bytes | None:
        try:
            with urllib.request.urlopen(self.base + route, timeout=120) as r:
                return r.read()
        except urllib.error.HTTPError as e:
            # A route that legitimately has nothing to say (no PDF for this document) is
            # recorded as absent rather than failing the build: the client already has an
            # honest branch for it.
            self.n_missing += 1
            print(f"    - {route} -> {e.code} (skipped)")
            return None
        except Exception as e:
            self.n_missing += 1
            print(f"    - {route} -> {type(e).__name__} (skipped)")
            return None

    def json(self, route: str):
        """Capture a GET route as `<route>.json` and return the parsed body."""
        raw = self._fetch(route)
        if raw is None:
            return None
        self._write(f"{route_key(route)}.json", raw)
        try:
            return json.loads(raw)
        except json.JSONDecodeError:
            return None

    def binary(self, route: str, ext: str) -> None:
        raw = self._fetch(route)
        if raw is not None:
            self._write(f"{route_key(route)}.{ext}", raw)


def capture(base: str, out: str) -> Snapshot:
    snap = Snapshot(base, out)
    # Must encode EXACTLY as the browser's encodeURIComponent, because the route string
    # is what both sides hash into a filename. Python's default quote() escapes !'()*~
    # and JavaScript's does not — a metric like "Vitamin E (Alpha-tocopherol)" would then
    # hash differently here and in the client, and 404 in the published demo.
    q = lambda s: urllib.parse.quote(str(s), safe="-_.!~*'()")  # noqa: E731

    print("  index routes")
    for route in ("/demo", "/metrics", "/overview", "/changes", "/timeline", "/settings",
                  "/metrics-coverage", "/baseline-explainer", "/conditions", "/medications",
                  "/events", "/immunizations", "/collections", "/profile", "/documents",
                  "/reports", "/imaging/studies", "/export/enabled", "/export/audit",
                  "/export/results", "/export/drafts"):
        snap.json(route)

    print("  per-metric routes")
    metrics = snap.json("/metrics") or []
    for m in metrics:
        name = m["metric"]
        for tpl in ("/observations/{}", "/flags/{}", "/summary/{}", "/history/{}",
                    "/chart-config/{}", "/metric-settings/{}", "/metrics/{}/panel"):
            snap.json(tpl.format(q(name)))
    print(f"    {len(metrics)} metrics")

    print("  profile history")
    for field in ("weight", "height"):
        snap.json(f"/profile/history/{field}")

    print("  collections")
    for c in snap.json("/collections") or []:
        snap.json(f"/collections/{c['id']}/readings")

    print("  documents")
    docs = (snap.json("/documents") or {}).get("documents", [])
    for d in docs:
        snap.json(f"/documents/{q(d['id'])}")
        snap.binary(f"/documents/{q(d['id'])}/pdf", "pdf")
    print(f"    {len(docs)} documents")

    print("  reports")
    reports = (snap.json("/reports") or {}).get("reports", [])
    for r in reports:
        snap.json(f"/reports/{q(r['id'])}")
        snap.binary(f"/reports/{q(r['id'])}/pdf", "pdf")
    print(f"    {len(reports)} reports")

    print("  search terms")
    for term in DEMO_SEARCHES:
        snap.json(f"/documents/search?q={q(term)}")

    print("  imaging frames")
    studies = (snap.json("/imaging/studies") or {}).get("studies", [])
    n_slices = 0
    for study in studies:
        for series in study.get("series", []):
            sid, count = series["id"], series.get("n_slices") or 0
            for i in range(count):
                snap.binary(f"/imaging/series/{q(sid)}/frame/{i}", "bin")
                snap.binary(f"/imaging/series/{q(sid)}/slice/{i}", "png")
                n_slices += 1
    print(f"    {n_slices} slices from {len(studies)} studies")
    return snap


def build_frontend(out: str) -> None:
    print("  npm run build -- --mode static")
    npm = shutil.which("npm") or shutil.which("npm.cmd")
    if not npm:
        sys.exit("npm not found on PATH.")
    fe = os.path.join(ROOT, "frontend")
    dist = os.path.join(fe, "dist")
    subprocess.run([npm, "run", "build", "--", "--mode", "static"],
                   cwd=fe, check=True, shell=False)
    for name in os.listdir(dist):
        src, dst = os.path.join(dist, name), os.path.join(out, name)
        if os.path.isdir(src):
            shutil.copytree(src, dst, dirs_exist_ok=True)
        else:
            shutil.copy2(src, dst)


def serve(out: str, port: int) -> None:
    """Preview the built demo locally.

    This exists because `python -m http.server` is NOT adequate here, which is worth
    knowing before you conclude the demo is broken: its listen backlog is 5, and a page
    like Metrics opens a burst of parallel requests, so connections are REFUSED —
    surfacing in the client as "fetch failed" rather than as anything resembling a queue
    problem. A real static host has no such limit; only the preview did.
    """
    import functools
    from http.server import SimpleHTTPRequestHandler, ThreadingHTTPServer

    class Server(ThreadingHTTPServer):
        request_queue_size = 128
        daemon_threads = True

    handler = functools.partial(SimpleHTTPRequestHandler, directory=out)
    with Server(("127.0.0.1", port), handler) as httpd:
        print(f"Serving {out} at http://127.0.0.1:{port}/   (ctrl-c to stop)")
        try:
            httpd.serve_forever()
        except KeyboardInterrupt:
            print()


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--out", default="static-demo", help="output directory (recreated)")
    ap.add_argument("--skip-frontend", action="store_true",
                    help="capture the API snapshot only; don't run the Vite build")
    ap.add_argument("--serve", type=int, metavar="PORT", default=None,
                    help="serve an already-built demo on PORT instead of rebuilding")
    args = ap.parse_args()

    if args.serve is not None:
        target = os.path.abspath(args.out)
        if not os.path.isdir(target):
            sys.exit(f"Nothing built at {target}. Run without --serve first.")
        serve(target, args.serve)
        return

    out = os.path.abspath(args.out)
    if os.path.abspath(ROOT) == out:
        sys.exit("REFUSING: --out is the project root.")
    if os.path.exists(out):
        shutil.rmtree(out)
    os.makedirs(out)

    print(f"Building the static demo into {out}")
    with Backend() as backend:
        snap = capture(backend.base, os.path.join(out, "api"))

    if not args.skip_frontend:
        build_frontend(out)

    print(f"\n  {snap.n_files} files, {snap.n_bytes / 1e6:.1f} MB captured"
          f"{f', {snap.n_missing} routes skipped' if snap.n_missing else ''}")
    print(f"  Upload {out} to any static host. Preview it locally with:")
    print(f"      python build_static_demo.py --out {os.path.relpath(out, ROOT)} --serve 8080")
    print("  (use that rather than `python -m http.server`, whose 5-deep listen backlog")
    print("   refuses this app's parallel requests and looks like a broken demo)")


if __name__ == "__main__":
    main()
