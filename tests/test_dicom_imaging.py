"""
Local DICOM viewer (dicom_store + /imaging routes).

The load-bearing test here is PRIVACY: the sample DICOM files ship WITH a PatientName
(and other identifiers) in their headers, and the module must surface NONE of it — the
allowlist reads only known-safe tags, so PII is excluded by construction, not stripped.
Everything is local (a temp folder); no network, no gateway.
"""

from __future__ import annotations

import json
import os
import shutil

import pytest

import dicom_store

pydicom = pytest.importorskip("pydicom")
from pydicom.data import get_testdata_file  # noqa: E402


@pytest.fixture
def imaging_store(tmp_path, monkeypatch):
    """A temp imaging folder holding sample DICOM files, saved WITHOUT a .dcm extension
    (like a real hospital CD). Points dicom_store at it and clears its scan cache."""
    store = tmp_path / "imaging"
    store.mkdir()
    for i, name in enumerate(["CT_small.dcm", "MR_small.dcm"]):
        shutil.copy(get_testdata_file(name), store / f"IM{i:06d}")
    monkeypatch.setattr(dicom_store, "IMAGING_DIR", str(store))
    monkeypatch.setattr(dicom_store, "_scan_cache", {})
    return str(store)


def test_scan_groups_studies_and_series(imaging_store):
    studies = dicom_store.scan_studies()
    assert len(studies) == 2                       # CT and MR are distinct studies
    modalities = {s["Modality"] for st in studies for s in st["series"]}
    assert modalities == {"CT", "MR"}
    for st in studies:
        for s in st["series"]:
            assert s["n_slices"] >= 1


def test_render_slice_returns_png(imaging_store):
    series = dicom_store.scan_studies()[0]["series"][0]
    png = dicom_store.render_slice(series["id"], 0)
    assert png is not None
    assert png[:8] == b"\x89PNG\r\n\x1a\n"          # PNG magic number


def test_render_unknown_series_or_index_is_none(imaging_store):
    assert dicom_store.render_slice("nope", 0) is None
    series = dicom_store.scan_studies()[0]["series"][0]
    assert dicom_store.render_slice(series["id"], 9999) is None


def test_public_studies_carry_no_file_paths(imaging_store):
    """The client shape must not leak local file paths (nor any _internal key)."""
    blob = json.dumps(dicom_store.public_studies())
    assert '"_slices"' not in blob                 # the internal key (not the "n_slices" count)
    assert imaging_store not in blob               # no absolute paths from the store
    assert "IM0000" not in blob                    # no source filenames


def test_no_pii_tag_names_or_values_surface(imaging_store):
    """The sample files DO contain PatientName etc.; the surfaced metadata must contain
    neither the PII tag NAMES nor their VALUES. This is the allowlist proving itself."""
    # What the source actually holds (read directly, only in the test).
    ds = pydicom.dcmread(get_testdata_file("CT_small.dcm"))
    patient_name = str(ds.get("PatientName") or "")
    assert patient_name  # sanity: the sample really has a name to leak

    blob = json.dumps(dicom_store.public_studies())
    for tag in ("PatientName", "PatientID", "PatientBirthDate", "PatientAddress",
                "ReferringPhysicianName", "PerformingPhysicianName", "InstitutionName",
                "OperatorsName", "AccessionNumber"):
        assert tag not in blob, f"PII tag name leaked: {tag}"
    if patient_name:
        assert patient_name not in blob, "PII value leaked into surfaced metadata"


def test_only_allowlisted_keys_present(imaging_store):
    """Belt-and-suspenders: every surfaced key is on the allowlist (plus the structural
    id/n_slices/series). A future tag added to a _SAFE_* list is fine; anything else fails."""
    allowed_study = set(dicom_store._SAFE_STUDY_TAGS) | {"id", "series"}
    # pixel_spacing (mm per pixel) and default_window (the file's own display calibration)
    # are structural/geometric, surfaced for measurements and window-level drag.
    allowed_series = set(dicom_store._SAFE_SERIES_TAGS) | {
        "id", "n_slices", "pixel_spacing", "default_window", "value_units"}
    for st in dicom_store.public_studies():
        assert set(st) <= allowed_study, f"unexpected study key: {set(st) - allowed_study}"
        for s in st["series"]:
            assert set(s) <= allowed_series, f"unexpected series key: {set(s) - allowed_series}"


def test_color_image_renders_as_rgb(tmp_path, monkeypatch):
    """An RGB secondary capture (scanned report / screenshot embedded as DICOM) has a
    trailing colour axis; the grayscale path crashed on it ('Too many dimensions'). It
    must render straight to an RGB PNG instead."""
    store = tmp_path / "img"
    store.mkdir()
    shutil.copy(get_testdata_file("SC_rgb.dcm"), store / "IM000001")
    monkeypatch.setattr(dicom_store, "IMAGING_DIR", str(store))
    monkeypatch.setattr(dicom_store, "_scan_cache", {})

    studies = dicom_store.scan_studies()
    assert studies, "the RGB image should still be a viewable series"
    png = dicom_store.render_slice(studies[0]["series"][0]["id"], 0)
    assert png is not None and png[:8] == b"\x89PNG\r\n\x1a\n"
    import io
    from PIL import Image
    assert Image.open(io.BytesIO(png)).mode == "RGB"   # colour, not coerced to grayscale


def test_non_image_series_are_filtered_out(tmp_path, monkeypatch):
    """A DICOM object with no Rows/Columns (Presentation State, Key Object Selection,
    Structured Report) carries no pixels and must NOT appear as a viewable series — it
    would only render broken. Synthesize a minimal PR-like object alongside a real image."""
    from pydicom.dataset import Dataset, FileMetaDataset
    from pydicom.uid import generate_uid, ExplicitVRLittleEndian

    store = tmp_path / "img"
    store.mkdir()
    # A real image series.
    shutil.copy(get_testdata_file("CT_small.dcm"), store / "IMG001")
    # A non-image object: same study, its own series, no Rows/Columns, no pixels.
    img = pydicom.dcmread(get_testdata_file("CT_small.dcm"))
    ds = Dataset()
    ds.file_meta = FileMetaDataset()
    ds.file_meta.TransferSyntaxUID = ExplicitVRLittleEndian
    ds.file_meta.MediaStorageSOPClassUID = generate_uid()
    ds.file_meta.MediaStorageSOPInstanceUID = generate_uid()
    ds.StudyInstanceUID = img.StudyInstanceUID          # same study as the image
    ds.SeriesInstanceUID = generate_uid()               # its own (non-image) series
    ds.Modality = "PR"
    ds.SeriesNumber = 99
    ds.save_as(str(store / "PR001"), enforce_file_format=True)

    monkeypatch.setattr(dicom_store, "IMAGING_DIR", str(store))
    monkeypatch.setattr(dicom_store, "_scan_cache", {})

    studies = dicom_store.scan_studies()
    assert len(studies) == 1
    modalities = [s["Modality"] for s in studies[0]["series"]]
    assert modalities == ["CT"]        # the PR series is gone; only the image remains


def test_series_carries_measurement_and_window_calibration(imaging_store):
    """PixelSpacing drives real-millimetre measurement; WindowCenter/Width give the
    client's window-level DRAG a starting point matching the server's own default render.
    Both are physical/display calibration — geometry, not identity."""
    series = {s["Modality"]: s for st in dicom_store.scan_studies() for s in st["series"]}
    ct = series["CT"]
    assert ct["pixel_spacing"] and len(ct["pixel_spacing"]) == 2
    assert all(v > 0 for v in ct["pixel_spacing"])
    # The CT sample carries a default window; shape is {wc, ww} or None, never partial.
    dw = ct["default_window"]
    assert dw is None or (dw["wc"] is not None and dw["ww"] is not None)


def test_value_units_distinguish_ct_from_mr(imaging_store):
    """The window presets are Hounsfield-unit windows, so they're CT-only: HU is an absolute
    scale, while MR signal is arbitrary and sequence-dependent. `value_units` is what lets
    the client hide them for MR instead of offering a 'bone 500/2000' window that renders a
    near-black frame and implies a calibration that doesn't exist."""
    series = {s["Modality"]: s for st in dicom_store.scan_studies() for s in st["series"]}
    assert series["CT"]["value_units"] == "HU" == dicom_store.WINDOW_PRESETS_UNITS
    assert series["MR"]["value_units"] != dicom_store.WINDOW_PRESETS_UNITS


def test_route_reports_the_units_its_presets_are_in(client, imaging_store):
    """The client decides per series whether presets apply, so the units they're expressed
    in must come from the server rather than 'CT' being hardcoded in the frontend."""
    body = client.get("/imaging/studies").json()
    assert body["presets_units"] == "HU"
    units = {s["Modality"]: s["value_units"] for st in body["studies"] for s in st["series"]}
    assert units["CT"] == "HU" and units["MR"] != "HU"


def test_route_surfaces_calibration_fields(client, imaging_store):
    s = client.get("/imaging/studies").json()["studies"][0]["series"][0]
    assert "pixel_spacing" in s and "default_window" in s


# --------------------------------------------------------------- persistent scan cache

def test_scan_persists_and_survives_a_restart(imaging_store):
    """The in-memory cache dies with the process, so a backend restart used to pay the full
    scan again (~27 s at 6,800 files). The scan is now persisted next to the store; dropping
    the in-memory cache simulates a restart and must NOT trigger a rescan."""
    fresh = dicom_store.scan_studies()
    assert os.path.exists(dicom_store._cache_path(imaging_store))

    # Simulate a restart: memory cache gone, cache FILE intact.
    dicom_store._scan_cache.clear()
    restored = dicom_store.scan_studies()

    def shape(sts):
        return sorted((st.get("StudyDate"), len(st["series"]),
                       sum(s["n_slices"] for s in st["series"])) for st in sts)
    assert shape(restored) == shape(fresh)
    # The restored tree must still carry usable file paths, not just metadata.
    assert dicom_store.render_slice(restored[0]["series"][0]["id"], 0) is not None


def test_cache_file_excluded_from_folder_signature(imaging_store):
    """The cache lives INSIDE the store, so counting it in the signature would change the
    signature the moment it's written — permanently invalidating the cache it describes.
    The signature must be identical before and after the cache exists."""
    cache = dicom_store._cache_path(imaging_store)
    if os.path.exists(cache):
        os.unlink(cache)
    before = dicom_store._partition_signatures(imaging_store)
    dicom_store._scan_cache.clear()
    dicom_store.scan_studies()                       # writes the cache
    assert os.path.exists(cache)
    assert dicom_store._partition_signatures(imaging_store) == before


def test_new_files_invalidate_the_persisted_cache(imaging_store, tmp_path):
    """Adding a study must still be picked up — the cache is keyed by folder signature, so
    a real change has to defeat it."""
    dicom_store.scan_studies()
    n_before = len(dicom_store.scan_studies())

    shutil.copy(get_testdata_file("MR_small.dcm"), os.path.join(imaging_store, "NEW001"))
    dicom_store._scan_cache.clear()                  # only the memory cache; file stays
    after = dicom_store.scan_studies()
    assert len(after) >= n_before                    # the added file is seen, not masked


def test_concurrent_cold_callers_run_one_scan(imaging_store, monkeypatch):
    """Concurrent cache misses must share ONE scan. Without the per-folder lock each
    caller launched its own 8-thread scan and they thrashed each other — observed live as
    two overlapping /imaging/studies requests both exceeding 100 s when a single scan took
    23 s. Losers of the race wait, then read the winner's cached result."""
    import threading

    calls = []
    real = dicom_store._rescan
    monkeypatch.setattr(dicom_store, "_rescan",
                        lambda root: (calls.append(1), real(root))[1])

    dicom_store._scan_cache.clear()
    cache = dicom_store._cache_path(imaging_store)
    if os.path.exists(cache):
        os.unlink(cache)

    out = {}
    threads = [threading.Thread(target=lambda i=i: out.__setitem__(i, len(dicom_store.scan_studies())))
               for i in range(4)]
    for t in threads:
        t.start()
    for t in threads:
        t.join()

    assert len(calls) == 1, f"expected 1 rescan, got {len(calls)}"
    assert len(set(out.values())) == 1      # every caller saw the same tree


def _into_subfolder(store: str, name: str) -> str:
    """Move the fixture's loose files into a subfolder — the real store's layout, where each
    imported disc is its own directory. Returns the subfolder path."""
    sub = os.path.join(store, name)
    os.makedirs(sub, exist_ok=True)
    for f in sorted(os.listdir(store)):
        src = os.path.join(store, f)
        if os.path.isfile(src) and f.startswith("IM"):
            shutil.move(src, os.path.join(sub, f))
    return sub


def test_new_subfolder_reuses_the_other_partitions_cache(imaging_store, monkeypatch):
    """THE point of per-partition caching: importing a disc must re-read only the NEW folder.

    A single whole-store signature made any change invalidate everything, so a 6th disc
    re-read the 13,000 files of the first five — a cost that grew with every import (20 s →
    65 s over five discs). Here the existing files sit in their own subfolder; adding a
    second subfolder must read only the added file's header."""
    _into_subfolder(imaging_store, "cd1")
    dicom_store._scan_cache.clear()
    before = dicom_store.scan_studies()
    assert before, "sanity: the moved files are still found inside a subfolder"

    read = []
    real = dicom_store._read_header
    monkeypatch.setattr(dicom_store, "_read_header", lambda p: (read.append(p), real(p))[1])

    os.mkdir(os.path.join(imaging_store, "cd2"))
    shutil.copy(get_testdata_file("MR_small.dcm"), os.path.join(imaging_store, "cd2", "IM000000"))
    dicom_store._scan_cache.clear()                  # force the signature walk + rescan
    after = dicom_store.scan_studies()

    assert len(read) == 1, f"only the new folder should be re-read, got {read}"
    assert os.path.join("cd2", "") in read[0]
    # The reused partition is still fully usable — metadata AND the file paths behind it.
    assert len(after) >= len(before)
    assert dicom_store.render_slice(after[0]["series"][0]["id"], 0) is not None


def test_series_split_across_two_folders_merges_into_one(imaging_store):
    """Partitioning must not fragment a study: the same series present in two subfolders (a
    duplicated disc, or one study delivered across discs) has to merge into ONE series
    carrying both slices — not two half-series, which is what per-folder scanning would give
    if the merge were naive."""
    sub = _into_subfolder(imaging_store, "a")
    for f in os.listdir(sub):                        # keep only the CT, so one study is expected
        ds = pydicom.dcmread(os.path.join(sub, f), stop_before_pixels=True)
        if ds.Modality != "CT":
            os.unlink(os.path.join(sub, f))
    os.mkdir(os.path.join(imaging_store, "b"))
    shutil.copy(get_testdata_file("CT_small.dcm"), os.path.join(imaging_store, "b", "IM000000"))
    dicom_store._scan_cache.clear()

    studies = dicom_store.scan_studies()
    assert len(studies) == 1
    assert len(studies[0]["series"]) == 1             # one series, not one per folder
    assert studies[0]["series"][0]["n_slices"] == 2   # both copies present


def test_corrupt_cache_is_a_miss_not_a_crash(imaging_store):
    """A truncated or schema-drifted cache must degrade to a rescan. It's an optimisation,
    never a source of truth."""
    dicom_store.scan_studies()
    with open(dicom_store._cache_path(imaging_store), "w", encoding="utf-8") as fh:
        fh.write("{not valid json")
    dicom_store._scan_cache.clear()
    assert len(dicom_store.scan_studies()) >= 1      # rebuilt without raising


# ------------------------------------------------------------------- ROI statistics

def test_roi_stats_are_real_pixel_values(imaging_store):
    """The ROI must be computed from the file's OWN pixel data + rescale — a mean taken
    from the windowed PNG would be display grey, i.e. a fiction. Checked by comparing
    against the same region read straight from the source with pydicom."""
    ct = next(s for st in dicom_store.scan_studies() for s in st["series"]
              if s["Modality"] == "CT")
    stats = dicom_store.roi_stats(ct["id"], 0, 10, 10, 20, 20)
    assert stats["n_pixels"] == 400
    assert stats["units"] == "HU"                    # CT rescales to Hounsfield
    assert stats["min"] <= stats["mean"] <= stats["max"]

    ds = pydicom.dcmread(get_testdata_file("CT_small.dcm"))
    expected = (ds.pixel_array[10:30, 10:30].astype(float)
                * float(ds.RescaleSlope) + float(ds.RescaleIntercept))
    assert stats["mean"] == round(float(expected.mean()), 1)
    assert stats["area_mm2"] is not None and stats["area_mm2"] > 0


def _synth_padded_ct(store, pad_value=-3024):
    """A CT with PixelPaddingValue set, half padding / half a constant real value. Real CTs
    pad the corners outside the reconstruction circle; a synthetic split is easier to assert
    on and exercises the same code path."""
    import numpy as np
    ds = pydicom.dcmread(get_testdata_file("CT_small.dcm"))
    arr = np.full((ds.Rows, ds.Columns), 1024, dtype=ds.pixel_array.dtype)  # -> 0 HU
    arr[:, : ds.Columns // 2] = pad_value + 1024                            # -> pad_value HU
    ds.PixelData = arr.tobytes()
    ds.RescaleSlope, ds.RescaleIntercept = 1, -1024
    ds.PixelPaddingValue = int(pad_value + 1024)
    ds.save_as(os.path.join(store, "PAD001"), enforce_file_format=True)


def test_window_uses_the_dicom_linear_function(imaging_store):
    """The default VOI function is LINEAR (PS3.3 C.11.2.1.2), defined over (w-1) centred on
    (c-0.5) — NOT c +/- w/2, which is the separate LINEAR_EXACT function. Using the wrong one
    shifted renders by up to 4 of 255 grey levels on a narrow window (the error scales as
    1/w, so it was worst at brain w=80). Compared against an independent implementation."""
    import numpy as np
    ds = pydicom.dcmread(get_testdata_file("CT_small.dcm"))
    hu = (ds.pixel_array.astype(np.float32) * float(ds.RescaleSlope)
          + float(ds.RescaleIntercept))
    for wc, ww in ((40, 80), (40, 400), (500, 2000)):
        c, w = wc - 0.5, ww - 1.0
        expected = np.clip((hu - c) / w + 0.5, 0.0, 1.0) * 255.0
        got = dicom_store._apply_voi(hu, ds, float(wc), float(ww))
        assert np.abs(got - expected).max() < 1e-6, f"window {wc}/{ww} deviates"


def test_padding_is_excluded_from_roi_statistics(tmp_path, monkeypatch):
    """PixelPaddingValue marks pixels OUTSIDE the reconstructed field of view — they aren't
    measurements. Including them fabricates a minimum and drags the mean: on a real slice
    straddling the field edge this made the mean wrong by ~1500 HU."""
    store = tmp_path / "img"
    store.mkdir()
    _synth_padded_ct(str(store))
    monkeypatch.setattr(dicom_store, "IMAGING_DIR", str(store))
    monkeypatch.setattr(dicom_store, "_scan_cache", {})

    s = dicom_store.scan_studies()[0]["series"][0]
    cols = s["Columns"]
    # A box spanning both halves: left is padding, right is real 0 HU.
    stats = dicom_store.roi_stats(s["id"], 0, 0, 0, cols, 10)
    assert stats["n_excluded"] > 0
    assert stats["mean"] == 0.0 and stats["min"] == 0.0   # padding gone, only real data left
    assert stats["n_pixels"] == stats["n_excluded"]       # half and half


def test_roi_entirely_in_padding_is_refused(tmp_path, monkeypatch):
    """All-padding means nothing was measured — say so rather than report the padding value
    as a result."""
    store = tmp_path / "img"
    store.mkdir()
    _synth_padded_ct(str(store))
    monkeypatch.setattr(dicom_store, "IMAGING_DIR", str(store))
    monkeypatch.setattr(dicom_store, "_scan_cache", {})
    s = dicom_store.scan_studies()[0]["series"][0]
    with pytest.raises(ValueError, match="outside the scanned field"):
        dicom_store.roi_stats(s["id"], 0, 0, 0, s["Columns"] // 2, 10)


def test_padding_renders_black_not_as_data(tmp_path, monkeypatch):
    """Padding must not render as image data — at -3024 HU it would paint a bright or dark
    band that looks like anatomy."""
    import io
    import numpy as np
    from PIL import Image
    store = tmp_path / "img"
    store.mkdir()
    _synth_padded_ct(str(store))
    monkeypatch.setattr(dicom_store, "IMAGING_DIR", str(store))
    monkeypatch.setattr(dicom_store, "_scan_cache", {})
    s = dicom_store.scan_studies()[0]["series"][0]
    png = dicom_store.render_slice(s["id"], 0, wc=0, ww=400)
    px = np.array(Image.open(io.BytesIO(png)))
    half = s["Columns"] // 2
    assert px[:, :half].max() == 0            # padding half is black
    assert px[:, half:].min() > 0             # real half is not


def _synth_unpadded_ct(store, fill_hu=-2048, sop_class="1.2.840.10008.5.1.4.1.1.2"):
    """A CT that fills its out-of-field half with a sentinel but declares NO PixelPaddingValue
    — the common real case: one whole study in this library is filled at -2048 HU over 21-72%
    of every slice with the tag absent."""
    import numpy as np
    ds = pydicom.dcmread(get_testdata_file("CT_small.dcm"))
    arr = np.full((ds.Rows, ds.Columns), 1024, dtype=ds.pixel_array.dtype)   # -> 0 HU
    arr[:, : ds.Columns // 2] = fill_hu + 1024
    ds.PixelData = arr.tobytes()
    ds.RescaleSlope, ds.RescaleIntercept = 1, -1024
    if "PixelPaddingValue" in ds:
        del ds.PixelPaddingValue
    ds.SOPClassUID = sop_class
    ds.file_meta.MediaStorageSOPClassUID = sop_class
    ds.save_as(os.path.join(store, "NOPAD01"), enforce_file_format=True)


def _one_series(store, monkeypatch):
    monkeypatch.setattr(dicom_store, "IMAGING_DIR", str(store))
    monkeypatch.setattr(dicom_store, "_scan_cache", {})
    return dicom_store.scan_studies()[0]["series"][0]


def test_undeclared_out_of_field_fill_is_excluded(tmp_path, monkeypatch):
    """Most out-of-field padding in this library is NOT declared. Relying on
    PixelPaddingValue alone left 10 series treating a -2048 HU sentinel as data: it lit up as
    grey at a wide window, and an ROI straddling the field edge reported a mean wrong by 584
    HU with a fabricated -2048 minimum. Nothing real sits below -1500 HU (air is -1000)."""
    import io
    import numpy as np
    from PIL import Image
    store = tmp_path / "img"
    store.mkdir()
    _synth_unpadded_ct(str(store))
    s = _one_series(store, monkeypatch)
    half = s["Columns"] // 2

    # Wide enough to include -2048 — where an unmasked sentinel becomes visible grey.
    px = np.array(Image.open(io.BytesIO(dicom_store.render_slice(s["id"], 0, wc=-500, ww=6000))))
    assert px[:, :half].max() == 0, "undeclared out-of-field fill must render black"
    assert px[:, half:].min() > 0, "real data must be untouched"

    stats = dicom_store.roi_stats(s["id"], 0, 0, 0, s["Columns"], 10)
    assert stats["n_excluded"] == half * 10
    assert stats["mean"] == 0.0 and stats["min"] == 0.0


def test_secondary_capture_is_never_treated_as_hounsfield(tmp_path, monkeypatch):
    """The HU floor is an argument about the HU scale, so it applies only to a real CT image.
    A SECONDARY CAPTURE stored with Modality=CT — a screenshot of a dose report — carries
    numbers that merely look like HU: one here has 13.5% of its pixels below the floor across
    209 distinct values, i.e. picture content. Masking it would black out the screenshot."""
    store = tmp_path / "img"
    store.mkdir()
    _synth_unpadded_ct(str(store), sop_class="1.2.840.10008.5.1.4.1.1.7")  # Secondary Capture
    s = _one_series(store, monkeypatch)
    stats = dicom_store.roi_stats(s["id"], 0, 0, 0, s["Columns"], 10)
    assert stats["n_excluded"] == 0, "a screenshot's low values are content, not a sentinel"


def test_real_air_is_not_mistaken_for_padding(tmp_path, monkeypatch):
    """The floor must sit well clear of legitimate data. Air is -1000 HU and noise around it
    reaches about -1050 in this library's own series; excluding that would bias an air ROI
    upward. -1500 leaves ~450 HU of headroom."""
    store = tmp_path / "img"
    store.mkdir()
    _synth_unpadded_ct(str(store), fill_hu=-1050)      # noisy air, NOT a sentinel
    s = _one_series(store, monkeypatch)
    stats = dicom_store.roi_stats(s["id"], 0, 0, 0, s["Columns"], 10)
    assert stats["n_excluded"] == 0
    assert stats["min"] == -1050.0                      # the air reading survives intact


def test_roi_clamps_to_image_bounds(imaging_store):
    """A drag off the edge is truncated to the image, not an error."""
    ct = next(s for st in dicom_store.scan_studies() for s in st["series"]
              if s["Modality"] == "CT")
    stats = dicom_store.roi_stats(ct["id"], 0, -50, -50, 10_000, 10_000)
    assert stats["n_pixels"] == ct["Rows"] * ct["Columns"]


def test_roi_rejects_empty_region_and_unknown_series(imaging_store):
    ct = next(s for st in dicom_store.scan_studies() for s in st["series"]
              if s["Modality"] == "CT")
    with pytest.raises(ValueError):
        dicom_store.roi_stats(ct["id"], 0, 5, 5, 0, 0)
    assert dicom_store.roi_stats("deadbeef", 0, 0, 0, 5, 5) is None


def test_roi_route(client, imaging_store):
    series = client.get("/imaging/studies").json()["studies"]
    ct = next(s for st in series for s in st["series"] if s["Modality"] == "CT")
    r = client.get(f"/imaging/series/{ct['id']}/slice/0/roi?x=10&y=10&w=20&h=20")
    assert r.status_code == 200
    body = r.json()
    assert body["n_pixels"] == 400 and body["units"] == "HU"
    # Empty region → 400 (a client mistake), unknown series → 404.
    assert client.get(f"/imaging/series/{ct['id']}/slice/0/roi"
                      "?x=0&y=0&w=0&h=0").status_code == 400
    assert client.get("/imaging/series/nope/slice/0/roi?x=0&y=0&w=5&h=5").status_code == 404


def test_roi_refuses_colour_images(tmp_path, monkeypatch):
    """Pixel statistics on RGB would be meaningless, so it's refused with a reason rather
    than silently averaging colour channels."""
    store = tmp_path / "img"
    store.mkdir()
    shutil.copy(get_testdata_file("SC_rgb.dcm"), store / "IM000001")
    monkeypatch.setattr(dicom_store, "IMAGING_DIR", str(store))
    monkeypatch.setattr(dicom_store, "_scan_cache", {})
    s = dicom_store.scan_studies()[0]["series"][0]
    with pytest.raises(ValueError, match="grayscale"):
        dicom_store.roi_stats(s["id"], 0, 0, 0, 10, 10)


# ----------------------------------------------------------------- timeline entries

def test_timeline_carries_imaging_entries(client, imaging_store):
    """Each locally-stored study appears on the timeline at its StudyDate, linking to the
    viewer with the study preselected. Allowlisted facts only — no PII in the entry."""
    entries = [e for e in client.get("/timeline").json() if e["kind"] == "imaging"]
    assert len(entries) == 2                      # the CT and MR sample studies
    by_date = {e["date"]: e for e in entries}
    ct = by_date["2004-01-19"]
    assert ct["title"].startswith("CT imaging")
    assert ct["link"].startswith("/imaging?study=")
    assert ct["detail"]["n_series"] == 1 and ct["detail"]["n_images"] >= 1
    # Every entry carries equal weight — no presentational ranking field is emitted.
    assert "prominence" not in ct
    blob = json.dumps(entries)
    assert "PatientName" not in blob and "_slices" not in blob


def test_timeline_empty_store_has_no_imaging_entries(client):
    """Hermeticity + honesty: with no imaging folder (the conftest default), the timeline
    simply has no imaging entries — no errors, no phantom studies."""
    entries = [e for e in client.get("/timeline").json() if e["kind"] == "imaging"]
    assert entries == []


# ------------------------------------------------------------------------ routes

def test_route_lists_studies(client, imaging_store):
    r = client.get("/imaging/studies")
    assert r.status_code == 200
    body = r.json()
    assert body["available"] is True
    assert len(body["studies"]) == 2
    assert "brain" in body["presets"] and "bone" in body["presets"]


def test_route_renders_a_png_slice(client, imaging_store):
    studies = client.get("/imaging/studies").json()["studies"]
    series_id = studies[0]["series"][0]["id"]
    r = client.get(f"/imaging/series/{series_id}/slice/0")
    assert r.status_code == 200
    assert r.headers["content-type"] == "image/png"
    assert r.content[:8] == b"\x89PNG\r\n\x1a\n"


def test_route_unknown_slice_404(client, imaging_store):
    studies = client.get("/imaging/studies").json()["studies"]
    series_id = studies[0]["series"][0]["id"]
    assert client.get(f"/imaging/series/{series_id}/slice/9999").status_code == 404
    assert client.get("/imaging/series/deadbeef/slice/0").status_code == 404
