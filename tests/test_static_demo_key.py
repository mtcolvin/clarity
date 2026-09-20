"""
The static demo's route -> filename function exists TWICE: once in
`build_static_demo.py` (which writes the files) and once in
`frontend/src/snapshot.js` (which asks for them). They must agree for every route.

This is the same hazard, and the same remedy, as `tests/test_frame_payload.py`: a
divergence raises nothing anywhere. The crawler would write a file, the client would
request a different name, and the published demo would show empty pages — visible only
by loading the built artifact and looking, which is precisely the check nobody repeats
after a one-character edit.

So: run the JavaScript under node against the Python, over routes chosen to hit every
character class that differs between the two languages' escaping rules.
"""
from __future__ import annotations

import json
import os
import pathlib
import shutil
import subprocess

import pytest

import build_static_demo

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
SNAPSHOT_JS = os.path.join(ROOT, "frontend", "src", "snapshot.js")

# Every one of these is a real shape the crawler emits, plus the awkward characters this
# record actually contains: a slash inside a metric name, spaces, parentheses (which
# Python's quote() escapes and JavaScript's encodeURIComponent does not), and a query.
ROUTES = [
    "/metrics",
    "/demo",
    "/observations/Albumin",
    "/observations/AST%2FALT%20Ratio",
    "/observations/BUN%2FCreatinine%20Ratio",
    "/observations/Creatinine%20Serum%2FPlasma",
    "/observations/Vitamin%20E%20(Alpha-tocopherol)",
    "/observations/Thyroid-Stimulating%20Hormone",
    "/metrics/Ferritin/panel",
    "/metric-settings/Hemoglobin",
    "/profile/history/weight",
    "/collections/3/readings",
    "/documents/search?q=thyroid",
    "/documents/search?q=vitamin%20d",
    "/documents/1ff476cef8ea/pdf",
    "/imaging/series/eac2d0f7006b/frame/0",
    "/imaging/series/eac2d0f7006b/slice/23",
    "/" + "x" * 200,            # past the 80-char slug truncation
    "/????",                    # slug collapses to empty; only the hash remains
]


@pytest.fixture(scope="module")
def js_keys() -> dict[str, str]:
    node = shutil.which("node")
    if not node:
        pytest.skip("node not available")
    script = (
        "import { routeKey } from %s;\n"
        "const routes = %s;\n"
        "console.log(JSON.stringify(Object.fromEntries(routes.map(r => [r, routeKey(r)]))));\n"
    # node's ESM loader needs a file:// URL, not a bare Windows path.
    ) % (json.dumps(pathlib.Path(SNAPSHOT_JS).as_uri()), json.dumps(ROUTES))
    out = subprocess.run(
        [node, "--input-type=module", "-e", script],
        capture_output=True, text=True, timeout=60,
    )
    if out.returncode != 0:
        pytest.fail(f"node failed: {out.stderr.strip()}")
    return json.loads(out.stdout)


def test_python_and_javascript_agree_on_every_route(js_keys):
    mismatched = {
        route: (build_static_demo.route_key(route), js_keys[route])
        for route in ROUTES
        if build_static_demo.route_key(route) != js_keys[route]
    }
    assert not mismatched, (
        "build_static_demo.route_key and snapshot.js routeKey disagree — the published "
        f"demo would 404 on these routes: {mismatched}"
    )


def test_keys_are_filesystem_and_url_safe():
    """The entire point of hashing rather than mirroring the URL: no character in the
    name can be reinterpreted by a filesystem or a static host."""
    for route in ROUTES:
        key = build_static_demo.route_key(route)
        assert key, route
        assert all(c.isalnum() or c in "._-" for c in key), key
        assert "/" not in key and "%" not in key and " " not in key


def test_distinct_routes_get_distinct_keys():
    """Slugging alone is NOT injective — '/a/b' and '/a b' slug identically — which is
    why the hash is appended. Pin that the pair actually separates."""
    assert build_static_demo.route_key("/a/b") != build_static_demo.route_key("/a b")
    keys = [build_static_demo.route_key(r) for r in ROUTES]
    assert len(set(keys)) == len(keys)
