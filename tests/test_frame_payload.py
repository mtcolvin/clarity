"""
The raw-frame payload (dicom_store.frame_payload) and its client-side counterpart.

The load-bearing test here is PARITY. Moving window/level into the browser means the VOI
arithmetic now exists TWICE — once in dicom_store._apply_voi, once in frontend/src/dicom/
frame.js — and a silent divergence would show as a subtly wrong grey on a medical image,
which is the kind of bug nobody notices and everybody trusts. So the JS is executed (via
node) over the same inputs as the Python and the two are required to agree.

Everything is local: a temp folder, pydicom's own sample files, no network.
"""

from __future__ import annotations

import json
import os
import pathlib
import shutil
import subprocess

import pytest

import dicom_store

pydicom = pytest.importorskip("pydicom")
np = pytest.importorskip("numpy")
from pydicom.data import get_testdata_file  # noqa: E402

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
FRAME_JS = os.path.join(ROOT, "frontend", "src", "dicom", "frame.js")


@pytest.fixture
def store(tmp_path, monkeypatch):
    d = tmp_path / "imaging"
    d.mkdir()
    shutil.copy(get_testdata_file("CT_small.dcm"), d / "IM000000")
    monkeypatch.setattr(dicom_store, "IMAGING_DIR", str(d))
    monkeypatch.setattr(dicom_store, "_scan_cache", {})
    return str(d)


def _series_id() -> str:
    return dicom_store.scan_studies()[0]["series"][0]["id"]


def _parse(payload: bytes):
    n = int.from_bytes(payload[:4], "little")
    header = json.loads(payload[4:4 + n])
    body = payload[4 + n:]
    count = header["rows"] * header["cols"]
    dt = np.dtype("<" + header["dtype"])
    pixels = np.frombuffer(body[:count * dt.itemsize], dtype=dt)
    mask_bytes = body[count * dt.itemsize:]
    return header, pixels, mask_bytes


def test_payload_describes_itself(store):
    header, pixels, mask_bytes = _parse(dicom_store.frame_payload(_series_id(), 0))
    assert header["rows"] * header["cols"] == pixels.size
    assert header["dtype"] in {"i1", "u1", "i2", "u2"}
    assert header["voi"] in {"LINEAR", "LINEAR_EXACT", "SIGMOID"}
    # This sample declares no padding, so no mask rides along and none is claimed.
    assert header["masked"] is False
    assert mask_bytes == b""


def test_pixels_start_8_byte_aligned(store):
    """A JavaScript typed array cannot be viewed at an arbitrary offset — `new Int16Array(
    buf, offset, n)` throws unless the offset is a multiple of the element size — and the
    header's length is whatever its JSON happens to be. So the header is padded, and this
    pins it: without the padding the payload worked or failed on the PARITY of a description
    of itself (the square test series rendered, the tall one reported an undecodable slice,
    from the same code path)."""
    payload = dicom_store.frame_payload(_series_id(), 0)
    n = int.from_bytes(payload[:4], "little")
    assert (4 + n) % 8 == 0
    # The padding is whitespace, so the header still parses as JSON.
    assert json.loads(payload[4:4 + n])["rows"] > 0


def test_unknown_series_or_index_is_none(store):
    assert dicom_store.frame_payload("nope", 0) is None
    assert dicom_store.frame_payload(_series_id(), 9999) is None


def test_default_window_matches_the_png_path(store):
    """A slice must not change appearance depending on which route drew it. Asserted at the
    BEHAVIOUR level rather than by comparing numbers: rendering the PNG at the window the
    frame payload declares as its default must be byte-identical to rendering it with no
    window at all. (This sample declares none, so the default is data-derived — which is the
    case worth pinning, since it is the one where the two paths could drift.)"""
    sid = _series_id()
    header, _, _ = _parse(dicom_store.frame_payload(sid, 0))
    assert dicom_store.render_slice(sid, 0, wc=header["default_wc"], ww=header["default_ww"])         == dicom_store.render_slice(sid, 0)


def test_mask_is_packed_msb_first(tmp_path, monkeypatch):
    """A padded slice carries one BIT per pixel, MSB-first within each byte — the order
    numpy's packbits uses and the order frame.js unpacks. Off-by-one here would black out
    the wrong pixels, which is why it is pinned rather than assumed."""
    d = tmp_path / "imaging"
    d.mkdir()
    ds = pydicom.dcmread(get_testdata_file("CT_small.dcm"))
    arr = ds.pixel_array.copy()
    arr[0, :4] = 0                       # a run we will declare as padding
    ds.PixelData = arr.tobytes()
    ds.PixelPaddingValue = 0
    ds.save_as(str(d / "PAD000"), enforce_file_format=True)
    monkeypatch.setattr(dicom_store, "IMAGING_DIR", str(d))
    monkeypatch.setattr(dicom_store, "_scan_cache", {})

    header, _, mask_bytes = _parse(dicom_store.frame_payload(_series_id(), 0))
    assert header["masked"] is True
    bits = np.unpackbits(np.frombuffer(mask_bytes, dtype=np.uint8))
    expected = (arr.reshape(-1) == 0)
    assert bits[:expected.size].astype(bool).tolist() == expected.tolist()


@pytest.mark.parametrize("fn", ["LINEAR", "LINEAR_EXACT", "SIGMOID"])
def test_voi_matches_the_javascript(fn):
    """THE parity test: dicom_store._apply_voi and frame.js's voiGrey must produce the same
    greys. Executed, not eyeballed — node runs the real module over the same inputs."""
    node = shutil.which("node")
    if node is None:
        pytest.skip("node is not installed")

    values = [-3024.0, -1024.0, -500.0, -100.0, -1.0, 0.0, 1.0, 40.0, 100.0, 400.0,
              1000.0, 3071.0]
    windows = [(40.0, 80.0), (40.0, 400.0), (300.0, 1500.0), (-600.0, 1600.0), (0.0, 1.0)]

    class _DS(dict):
        def get(self, k, default=None):
            return {"VOILUTFunction": fn}.get(k, default)

    script = (
        f"const m = await import({json.dumps(pathlib.Path(FRAME_JS).as_uri())});"
        f"const vals = {json.dumps(values)};"
        f"const wins = {json.dumps(windows)};"
        "const out = [];"
        f"for (const [wc, ww] of wins) for (const v of vals) out.push(m.voiGrey(v, wc, ww, {json.dumps(fn)}));"
        "console.log(JSON.stringify(out));"
    )
    got = json.loads(subprocess.run(
        [node, "--input-type=module", "-e", script],
        capture_output=True, text=True, check=True).stdout)

    want = []
    for wc, ww in windows:
        arr = np.array(values, dtype=np.float32)
        want.extend(dicom_store._apply_voi(arr, _DS(), wc, ww).tolist())

    assert len(got) == len(want)
    for g, w in zip(got, want):
        assert abs(g - w) < 1e-3, f"{fn}: js {g} vs py {w}"
