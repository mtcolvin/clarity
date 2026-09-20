"""
Local DICOM imaging support — 100% on-machine, mirroring pdf_import's posture.

PRIVACY POSTURE (charter prime directive). DICOM headers carry PatientName,
PatientBirthDate, PatientID (MRN), ReferringPhysicianName, InstitutionName — exactly the
identifiers the charter forbids from leaving the machine. This module therefore:

  - reads files ONLY from a local imaging folder; it never uploads, calls the gateway, or
    touches the network. A medical image also can't be reliably de-identified (PII can be
    BURNED INTO the pixels), so a hosted read is charter-prohibited outright — there is no
    external path here by construction.
  - surfaces metadata by an ALLOWLIST (`_SAFE_*_TAGS`): only known-safe tags are ever read
    out; every other tag — including all the PII ones — is excluded by construction, never
    read, never returned. This is the charter's allowlist-not-denylist rule. The PII tags
    are never even copied into a dict, so they can't leak into a response or a log.

No SQL, no network, no model. Pure local parse + render (pydicom + numpy + Pillow).
"""

from __future__ import annotations

import concurrent.futures as cf
import hashlib
import io
import json
import os
import threading
import time

import numpy as np

try:
    import pydicom
    from PIL import Image
    _AVAILABLE = True
except ImportError:  # pydicom/Pillow are core deps, but degrade honestly if missing
    _AVAILABLE = False


IMAGING_DIR = os.environ.get("HEALTH_IMAGING_DIR", "imaging_store")

# PNG encoding is the slowest step of a slice render, and it's pure cost here: the bytes
# travel over loopback to one local browser, so trading a bigger file for a faster encode
# is the right way round. Level 1 (vs Pillow's default 6) roughly halves encode time for a
# modest size increase — worth it when the client preloads a whole 400-slice series.
_PNG_COMPRESS_LEVEL = 1

# ---- The allowlist. Only these tags are ever read for display. Everything else — every
# patient/physician/facility identifier — is excluded by never being read. ----
_SAFE_STUDY_TAGS = ("StudyDate", "StudyDescription")
_SAFE_SERIES_TAGS = ("Modality", "SeriesDescription", "BodyPartExamined",
                     "SeriesNumber", "Rows", "Columns")

# Window/level presets, in HOUNSFIELD UNITS — which makes them CT-ONLY. HU is an absolute,
# calibrated scale (air -1000, water 0, dense bone ~+1000), so these numbers mean a specific
# tissue. MR has no equivalent: its signal is arbitrary and varies by sequence, scanner and
# coil, so a "bone 500/2000" window applied to MR data is not merely unhelpful, it renders a
# near-black frame while implying a calibration that doesn't exist. The client therefore
# offers these only for series whose values ARE in HU (see `value_units` on each series);
# everything else gets the file's own default window plus the drag gesture, which works on
# any scale. There are deliberately no "MR presets" — standard ones don't exist, because
# there's nothing absolute to anchor them to.
WINDOW_PRESETS_UNITS = "HU"
WINDOW_PRESETS = {
    "brain": {"wc": 40, "ww": 80},
    "soft-tissue": {"wc": 40, "ww": 400},
    "bone": {"wc": 500, "ww": 2000},
    "lung": {"wc": -600, "ww": 1500},
}


def available() -> bool:
    """False if pydicom/Pillow aren't installed — the route reports this honestly rather
    than 500-ing, exactly like pdf_import's OCR-extras degradation."""
    return _AVAILABLE


def _short_id(uid: str) -> str:
    """A stable, short, opaque handle for a UID — used in URLs so the long DICOM UID
    (an identifier, not something to surface) isn't the route key."""
    return hashlib.sha1(uid.encode("utf-8")).hexdigest()[:12]


def _fmt_date(raw) -> str | None:
    """DICOM DA is 'YYYYMMDD' → 'YYYY-MM-DD' (the app's date charter). None if absent/odd."""
    s = str(raw or "").strip()
    if len(s) == 8 and s.isdigit():
        return f"{s[0:4]}-{s[4:6]}-{s[6:8]}"
    return None


def _first_num(v) -> float | None:
    """First value of a DICOM element that may be single-valued or multi-valued (VR MV —
    WindowCenter/Width legitimately carry several presets). None if absent/unparseable."""
    if v is None:
        return None
    if hasattr(v, "__iter__") and not isinstance(v, str):
        v = v[0] if len(v) else None
    try:
        return float(v)
    except (TypeError, ValueError):
        return None


def _safe_meta(ds, tags) -> dict:
    """Read ONLY the allowlisted tags into a plain dict. A tag that's absent is omitted;
    no other tag is ever touched, so PII can't ride along."""
    out = {}
    for tag in tags:
        if tag in ds:
            val = ds.get(tag)
            out[tag] = _fmt_date(val) if tag == "StudyDate" else (
                None if val is None else (int(val) if tag in ("Rows", "Columns", "SeriesNumber")
                                           and str(val).strip().lstrip("-").isdigit() else str(val)))
    return out


def _read_header(path: str):
    """(path, dataset) for a DICOM file, or None if it isn't one. Header only —
    stop_before_pixels keeps this cheap; pixels are read when a slice is rendered."""
    if os.path.basename(path).upper() == "DICOMDIR":
        return None
    try:
        ds = pydicom.dcmread(path, stop_before_pixels=True, force=False)
    except Exception:
        return None                        # not a DICOM file
    if "SeriesInstanceUID" not in ds:
        return None                        # no series identity — can't be placed
    return path, ds


def _read_headers(paths: list[str]):
    """Yield (path, dataset) for every DICOM in `paths`, reading headers IN PARALLEL.

    The work is I/O-bound (thousands of small file reads), so threads help despite the
    GIL — pydicom releases it during reads. This matters at scale: a single-threaded scan
    of ~6,800 files took ~27 s, which is how long the Imaging page hung on the first load
    after a restart. Ordering is not preserved here; callers sort by InstanceNumber anyway.
    """
    if not paths:
        return
    workers = min(_SCAN_WORKERS, max(1, len(paths)))
    with cf.ThreadPoolExecutor(max_workers=workers) as pool:
        for result in pool.map(_read_header, paths, chunksize=32):
            if result is not None:
                yield result


# Cache the (expensive) scan keyed by a CHEAP folder signature, so scrolling slices
# doesn't re-dcmread every file each time. The signature is a stat-only walk (file count
# + newest mtime); when files are added/removed it changes and the scan re-runs, so the
# cache self-invalidates without a manual rescan.
#
# The signature walk is only cheap RELATIVE to a full re-scan — it still stats every file
# in the store (thousands), which profiling showed was ~118 ms of a ~150 ms slice render,
# i.e. 80% of the cost of showing an image. So the signature itself is revalidated at most
# once per _SIG_TTL_S; inside that window a cached scan is trusted outright. New files
# still appear on their own, just up to a couple of seconds later — a fine trade for
# renders that are ~10x faster, which is what makes preloading a whole series practical.
_scan_cache: dict[str, tuple[dict[str, tuple], list[dict], float]] = {}
_SIG_TTL_S = 2.0

# Header reads are I/O-bound, so more workers than cores is correct here.
_SCAN_WORKERS = 8

# PERSISTENT scan cache. The in-memory cache above dies with the process, so every backend
# restart paid the full scan again — ~27 s of blank Imaging page at ~6,800 files, and
# growing linearly as more discs are imported. This writes the finished scan next to the
# store, keyed by the folder signature, so a restart is instant and the scan only re-runs
# when the folder actually changes.
#
# The cache is PER-PARTITION (one entry per immediate subfolder of the store, plus "." for
# loose files at its root), because the store grows by whole folders: each imported disc is
# its own directory and never changes again. A single whole-store signature made ANY change
# invalidate EVERYTHING — importing a 6th disc re-read the 13,000 files of the first five,
# and that cost climbed with every import (20 s → 65 s over five discs). Partitioning means
# a new folder costs only its own files; the untouched ones are reused verbatim.
#
# WHAT'S IN IT: exactly what /imaging/studies already returns (allowlisted tags + opaque
# ids) plus the local file paths the server needs to render slices. No PII beyond what the
# app displays. It lives inside imaging_store/, which is gitignored, and is disposable —
# delete it and the next scan rebuilds it.
_CACHE_FILENAME = ".scan-cache.json"
# BUMP THIS whenever the cached series/study shape changes, or an older cache will be
# served with fields the client now expects (v2 added `value_units`; v3 switched the blob
# from one whole-store entry to per-partition entries holding unflattened instances).
_CACHE_VERSION = 3

# The pseudo-partition for files sitting directly in the store root (not under any
# subfolder). "." sorts before any real folder name, which keeps merge order identical to
# the old single os.walk (root files first, then subdirectories).
_ROOT_PARTITION = "."

# One scan at a time per folder. Without this, concurrent requests that all miss the cache
# each start their own full parallel scan — 8 threads apiece, thrashing the disk and making
# every one of them slower than a single scan would have been. Observed live: two overlapping
# /imaging/studies requests after an import both timed out past 100 s, while the same scan
# run once took 23 s. Losers of the race re-check the cache after waiting and get the
# winner's result for free (double-checked locking).
_scan_locks: dict[str, threading.Lock] = {}
_locks_guard = threading.Lock()


def _lock_for(root: str) -> threading.Lock:
    with _locks_guard:
        return _scan_locks.setdefault(root, threading.Lock())


def _cache_path(root: str) -> str:
    return os.path.join(root, _CACHE_FILENAME)


def _is_cache_file(name: str) -> bool:
    return name == _CACHE_FILENAME or name.endswith(_CACHE_FILENAME + ".tmp")


def _load_disk_partitions(root: str) -> dict[str, dict]:
    """The persisted per-partition scans for `root` as {partition: {signature, studies}},
    or {} if absent/unreadable/schema-drifted. Corruption is a miss, never an error — the
    cache is only ever a reconstructible optimisation."""
    try:
        with open(_cache_path(root), encoding="utf-8") as fh:
            blob = json.load(fh)
    except (OSError, json.JSONDecodeError):
        return {}
    if blob.get("version") != _CACHE_VERSION:
        return {}
    parts = blob.get("partitions")
    if not isinstance(parts, dict):
        return {}
    out: dict[str, dict] = {}
    for name, entry in parts.items():
        try:
            studies = entry["studies"]
            for st in studies:
                for s in st["series"]:
                    # Instances persist as compact [path, instance_number, n_frames] lists.
                    s["_instances"] = [(str(p), int(i), int(n)) for p, i, n in s["_instances"]]
            out[str(name)] = {"signature": tuple(entry["signature"]), "studies": studies}
        except (TypeError, ValueError, KeyError):
            continue                    # one unusable partition doesn't discard the others
    return out


def _save_disk_partitions(root: str, sigs: dict[str, tuple], raw: dict[str, list]) -> None:
    """Best-effort persist of every partition's RAW (unflattened) scan. A read-only or full
    disk must not break imaging, so failures are swallowed — the in-memory cache still does
    its job for this process."""
    tmp = _cache_path(root) + ".tmp"
    blob = {"version": _CACHE_VERSION,
            "partitions": {p: {"signature": list(sigs[p]), "studies": raw[p]} for p in raw}}
    try:
        with open(tmp, "w", encoding="utf-8") as fh:
            json.dump(blob, fh, default=str)
        os.replace(tmp, _cache_path(root))      # atomic: no half-written cache is ever read
    except OSError:
        try:
            os.unlink(tmp)
        except OSError:
            pass


def _partition_signatures(root: str) -> dict[str, tuple]:
    """{partition: (file count, newest mtime)} — cheap per-folder change detection.

    One stat-only walk of the whole store, bucketed by immediate subfolder, so a change is
    localised to the folder it happened in. The persisted cache file lives INSIDE the store
    and is excluded: counting it would change the signature the moment it's written,
    permanently invalidating the very cache it describes.
    """
    sigs: dict[str, tuple] = {}
    for dirpath, _dirs, files in os.walk(root):
        rel = os.path.relpath(dirpath, root)
        part = _ROOT_PARTITION if rel in (".", "") else rel.split(os.sep)[0]
        for name in files:
            if _is_cache_file(name):
                continue
            try:
                st = os.stat(os.path.join(dirpath, name))
            except OSError:
                continue
            n, newest = sigs.get(part, (0, 0.0))
            sigs[part] = (n + 1, max(newest, st.st_mtime))
    return sigs


def _partition_paths(root: str, part: str) -> list[str]:
    """Every file belonging to one partition. The root pseudo-partition is its loose files
    ONLY (non-recursive) — a subfolder's files belong to that subfolder."""
    if part == _ROOT_PARTITION:
        try:
            names = sorted(os.listdir(root))
        except OSError:
            return []
        paths = [os.path.join(root, n) for n in names if not _is_cache_file(n)]
        return [p for p in paths if os.path.isfile(p)]
    base = os.path.join(root, part)
    return [os.path.join(dp, n) for dp, _d, files in os.walk(base) for n in files
            if not _is_cache_file(n)]


def scan_studies(root: str | None = None) -> list[dict]:
    """Walk the imaging folder and group files into studies → series → ordered slices,
    keyed off DICOM tags (so filenames / missing extensions don't matter). Returns a
    list of studies carrying ONLY allowlisted metadata plus opaque ids and slice counts.
    Empty list if the folder is missing or holds no DICOM. Cached per subfolder, in memory
    and on disk; only one scan runs at a time per folder."""
    root = root or IMAGING_DIR
    if not _AVAILABLE or not os.path.isdir(root):
        return []

    fast = _cached_scan(root)
    if fast is not None:
        return fast

    # Cache miss: serialise so concurrent callers don't each launch a full scan.
    with _lock_for(root):
        again = _cached_scan(root)      # a racing caller may have finished while we waited
        if again is not None:
            return again
        return _rescan(root)


def _cached_scan(root: str) -> list[dict] | None:
    """The in-memory or on-disk cached scan for `root`, or None if a rebuild is needed.
    Cheap: exactly one signature walk, and none at all inside the TTL."""
    now = time.monotonic()
    cached = _scan_cache.get(root)
    if cached and now - cached[2] < _SIG_TTL_S:
        return cached[1]                               # inside the TTL: skip the walk

    sigs = _partition_signatures(root)
    if cached and cached[0] == sigs:                   # unchanged: refresh the check time
        _scan_cache[root] = (sigs, cached[1], now)
        return cached[1]

    # Second chance before the expensive path: a scan persisted by an earlier process.
    from_disk = _studies_from_disk(root, sigs)
    if from_disk is not None:
        _scan_cache[root] = (sigs, from_disk, now)
        return from_disk
    return None                     # nothing usable — caller must _rescan() under the lock


def _studies_from_disk(root: str, sigs: dict[str, tuple]) -> list[dict] | None:
    """The studies tree rebuilt entirely from the persisted cache, or None if ANY partition
    is missing or stale (the caller then rescans, reusing whichever partitions DID match).
    Merging is pure in-memory work — no file is read."""
    parts = _load_disk_partitions(root)
    if not sigs or set(parts) != set(sigs) or any(parts[p]["signature"] != sigs[p] for p in sigs):
        return None
    return _finalize({p: parts[p]["studies"] for p in parts})


def _rescan(root: str) -> list[dict]:
    """The expensive path: rebuild the studies tree, reading headers ONLY for partitions
    whose signature changed. Call only while holding the folder's lock (see scan_studies),
    so one scan can't overlap another."""
    sigs = _partition_signatures(root)
    on_disk = _load_disk_partitions(root)
    raw: dict[str, list] = {}
    for part, sig in sigs.items():
        hit = on_disk.get(part)
        if hit is not None and hit["signature"] == sig:
            raw[part] = hit["studies"]          # unchanged folder: reuse, read nothing
        else:
            raw[part] = _scan_partition(root, part)
    result = _finalize(raw)                     # does not mutate `raw`
    _scan_cache[root] = (sigs, result, time.monotonic())
    _save_disk_partitions(root, sigs, raw)
    return result


def _scan_partition(root: str, part: str) -> list[dict]:
    """RAW studies for ONE partition: allowlisted metadata plus each series' instance list,
    deliberately NOT yet ordered, flattened or filtered. That happens after partitions are
    merged (`_finalize`), so a study or series spread across two folders still comes out as
    one correctly-ordered series rather than two half ones."""
    studies: dict[str, dict] = {}
    for path, ds in _read_headers(_partition_paths(root, part)):
        study_uid = str(ds.get("StudyInstanceUID", "")) or "(no study uid)"
        series_uid = str(ds.get("SeriesInstanceUID", ""))
        study = studies.setdefault(study_uid, {
            "id": _short_id(study_uid), **_safe_meta(ds, _SAFE_STUDY_TAGS), "series": {},
        })
        if series_uid not in study["series"]:
            # PixelSpacing = [row_mm, col_mm]: physical geometry, allowlist-safe (it says
            # how big a pixel is, nothing about the patient). Needed for real-millimetre
            # distance measurement; null when the modality doesn't calibrate (some US/SC).
            ps = ds.get("PixelSpacing")
            try:
                pixel_spacing = [float(ps[0]), float(ps[1])] if ps is not None else None
            except (TypeError, ValueError, IndexError):
                pixel_spacing = None
            # The file's own WindowCenter/Width — display calibration, allowlist-safe. The
            # renderer already falls back to it server-side; surfacing it lets the client's
            # window/level DRAG start from the same values instead of a guess.
            dw = _first_num(ds.get("WindowCenter")), _first_num(ds.get("WindowWidth"))
            study["series"][series_uid] = {
                "id": _short_id(series_uid), **_safe_meta(ds, _SAFE_SERIES_TAGS),
                "pixel_spacing": pixel_spacing,
                "default_window": ({"wc": dw[0], "ww": dw[1]}
                                   if dw[0] is not None and dw[1] is not None else None),
                # What this series' pixel values ARE ("HU" for CT, else the file's
                # RescaleType, else "raw"). Drives two honesty rules on the client: the
                # HU window presets are offered only when values are actually HU, and ROI
                # statistics are labelled with the real units rather than assuming HU.
                "value_units": _value_units(ds),
                "_instances": [],
            }
        series = study["series"][series_uid]
        n_frames = int(ds.get("NumberOfFrames", 1) or 1)
        inst = ds.get("InstanceNumber", 0)
        try:
            inst = int(inst)
        except (TypeError, ValueError):
            inst = 0
        series["_instances"].append((path, inst, n_frames))

    # Series dicts become a plain list — the uid keys were only needed while grouping, and
    # the persisted form should carry no UID (an identifier) at all.
    return [{**{k: v for k, v in st.items() if k != "series"},
             "series": list(st["series"].values())} for st in studies.values()]


def _finalize(raw_by_partition: dict[str, list]) -> list[dict]:
    """Merge every partition's raw studies into the final tree: one entry per study, its
    series ordered, each series' instances flattened into an ordered slice list.

    Merging is by the study/series id (a deterministic hash of the UID), so the same study
    appearing in two folders lands in ONE entry. Partitions are merged in sorted order and
    the instance sort is stable, which reproduces the ordering the old single whole-store
    walk produced. `raw_by_partition` is NOT mutated — it gets written back to the cache.
    """
    studies: dict[str, dict] = {}
    for part in sorted(raw_by_partition):
        for st in raw_by_partition[part]:
            target = studies.setdefault(st["id"], {
                **{k: v for k, v in st.items() if k != "series"}, "series": {},
            })
            for s in st["series"]:
                existing = target["series"].get(s["id"])
                if existing is None:
                    target["series"][s["id"]] = {
                        **{k: v for k, v in s.items() if k != "_instances"},
                        "_instances": list(s["_instances"]),
                    }
                else:
                    existing["_instances"].extend(s["_instances"])

    result = []
    for study in studies.values():
        series_list = []
        for s in study["series"].values():
            # Only IMAGE series are viewable. Non-image DICOM objects — Presentation State
            # (PR), Key Object Selection (KO), Structured Reports (SR) — carry no pixels and
            # have no Rows/Columns; they'd only show as broken "series". Require both.
            if not (s.get("Rows") and s.get("Columns")):
                s.pop("_instances", None)
                continue
            # Flatten instances → an ordered slice list of (path, frame). Sorted by
            # InstanceNumber so slices read head-to-toe as acquired.
            insts = sorted(s.pop("_instances"), key=lambda i: i[1])
            slices = [(path, f) for path, _inst, n_frames in insts for f in range(n_frames)]
            s["n_slices"] = len(slices)
            s["_slices"] = slices
            series_list.append(s)
        if not series_list:
            continue  # a study with no image series (e.g. only PR/KO) is not viewable
        series_list.sort(key=lambda s: s.get("SeriesNumber") or 0)
        study["series"] = series_list
        result.append(study)
    result.sort(key=lambda st: st.get("StudyDate") or "", reverse=True)
    return result


def public_studies(root: str | None = None) -> list[dict]:
    """The studies tree with all internal keys (`_slices`, which holds local file paths)
    stripped — the exact shape safe to serialize to the client. File paths stay on the
    server; the client addresses slices by series id + index only."""
    return [
        {**{k: v for k, v in st.items() if k != "series"},
         "series": [{k: v for k, v in s.items() if not k.startswith("_")}
                    for s in st["series"]]}
        for st in scan_studies(root)
    ]


def _find_slices(series_id: str, root: str | None = None) -> list[tuple[str, int]]:
    """The ordered (path, frame) list for a series id, or [] if unknown."""
    for study in scan_studies(root):
        for s in study["series"]:
            if s["id"] == series_id:
                return s["_slices"]
    return []


class PixelDecodeError(RuntimeError):
    """A slice's pixels couldn't be decoded — almost always a compressed transfer syntax
    (JPEG2000/JPEG-LS) needing an optional decoder this install doesn't have. Surfaced as
    a clear, actionable message rather than a 500."""


def _load_frame(series_id: str, index: int, root: str | None = None):
    """(ds, arr, is_colour) for one slice, or None if the series/index is unknown. `arr` is
    frame-selected but NOT rescaled. Shared by the renderer and the ROI statistics so the
    two can never disagree about which pixels a slice actually is."""
    slices = _find_slices(series_id, root)
    if not (0 <= index < len(slices)):
        return None
    path, frame = slices[index]
    ds = pydicom.dcmread(path)
    try:
        arr = ds.pixel_array
    except Exception as e:  # compressed syntax with no decoder installed, or a corrupt file
        ts = getattr(getattr(ds, "file_meta", None), "TransferSyntaxUID", None)
        raise PixelDecodeError(
            f"This slice's pixel data could not be decoded"
            f"{f' ({ts.name})' if ts is not None else ''}. Compressed DICOM (JPEG2000/JPEG-LS) "
            f"needs an optional decoder: pip install pylibjpeg pylibjpeg-openjpeg") from e

    samples = int(ds.get("SamplesPerPixel", 1) or 1)
    photometric = str(ds.get("PhotometricInterpretation", ""))
    # COLOUR (RGB secondary captures — a scanned requisition embedded as DICOM) has 3+
    # samples/pixel and a trailing colour axis.
    if samples >= 3 or (arr.ndim >= 3 and arr.shape[-1] in (3, 4)):
        rgb = arr[frame] if arr.ndim == 4 else arr
        if photometric.startswith("YBR"):
            try:
                from pydicom.pixels import convert_color_space
                rgb = convert_color_space(rgb, photometric, "RGB")
            except Exception:
                pass  # best-effort; fall back to the raw samples
        return ds, rgb, True
    # GRAYSCALE. A 3-D array here is a multi-frame stack (with or without a NumberOfFrames
    # tag) — index the requested frame.
    if arr.ndim == 3:
        arr = arr[frame]
    return ds, arr, False


def _to_stored_units(ds, arr):
    """Apply the file's rescale so values are in the modality's real units (Hounsfield for
    CT). This is what makes an ROI mean meaningful rather than a raw detector number."""
    return (arr.astype(np.float32) * float(ds.get("RescaleSlope", 1) or 1)
            + float(ds.get("RescaleIntercept", 0) or 0))


def _apply_voi(arr, ds, wc: float, ww: float):
    """Map values to 0..255 using the DICOM VOI LUT function (PS3.3 C.11.2.1).

    The DEFAULT is LINEAR, and its exact form matters: it is defined over (w − 1) centred
    on (c − 0.5), NOT w centred on c. This module previously used the simpler c ± w/2 form
    (which is the separate LINEAR_EXACT function), so renders differed from a conforming
    viewer by up to 4 of 255 grey levels on a narrow window — the error scales as 1/w, so
    it was invisible at bone (w=2000) and largest at brain (w=80). Honours an explicit
    VOILUTFunction when the file specifies one.
    """
    fn = str(ds.get("VOILUTFunction", "") or "").strip().upper()

    if fn == "SIGMOID":                                   # PS3.3 C.11.2.1.3.1
        return 255.0 / (1.0 + np.exp(-4.0 * (arr - wc) / max(ww, 1e-6)))

    if fn == "LINEAR_EXACT":                              # PS3.3 C.11.2.1.3.2
        lo, hi = wc - ww / 2.0, wc + ww / 2.0
        return np.clip((arr - lo) / max(hi - lo, 1e-6), 0.0, 1.0) * 255.0

    # LINEAR (the default when VOILUTFunction is absent) — PS3.3 C.11.2.1.2.
    c = wc - 0.5
    w = max(ww - 1.0, 1e-6)
    return np.clip((arr - c) / w + 0.5, 0.0, 1.0) * 255.0


# Below this many Hounsfield units, a CT value is not a measurement of anything.
#
# The HU scale is defined with water at 0 and air at −1000, and there is no material below
# that — the practical floor of real data (including noise around air) sits near −1024. The
# lowest LEGITIMATE values measured across this library's own series are about −1050. So a
# value far beneath that is a vendor SENTINEL for "outside the reconstructed field of view",
# not tissue. −1500 leaves ~450 HU of headroom below real air noise before anything is
# excluded, while catching every sentinel actually present here: −2048, −3024 and −8192.
_HU_OUT_OF_FIELD = -1500.0

# ...and only for a genuine CT reconstruction. The floor argument is about the HU scale, which
# only means anything in a real CT image. A SECONDARY CAPTURE stored with Modality=CT — a
# screenshot of a dose report or a vendor console — carries arbitrary numbers that merely LOOK
# like HU: one here has 13.5% of its pixels below the floor spread over 209 distinct values,
# i.e. picture content, not a sentinel fill. Masking that would black out a chunk of the
# screenshot. Real CT images in this library all report CT Image Storage.
_CT_IMAGE_SOP_CLASSES = {
    "1.2.840.10008.5.1.4.1.1.2",        # CT Image Storage
    "1.2.840.10008.5.1.4.1.1.2.1",      # Enhanced CT Image Storage
}


def _padding_mask(ds, raw):
    """Boolean mask of pixels OUTSIDE the reconstructed field of view, or None if there are
    none. Two sources, because relying on the declared one alone left most of this library
    unprotected:

    1. PixelPaddingValue (PS3.3 C.7.5.1.1.2), the declared case. A conforming viewer excludes
       it; rendering it as an ordinary value puts a bogus block of extreme numbers around the
       image and skews any ROI overlapping it.
    2. UNDECLARED sentinels, found by the HU floor above. Many scanners fill the out-of-field
       corners with a constant and never emit the tag: one whole study here (10 series) is
       padded at −2048 HU over 21–72% of every slice with no PixelPaddingValue at all, and
       several reformats use −1024 or −8192. Those pixels were being treated as data.

    The DICOM standard leaves values outside the reconstruction circle UNDEFINED, so drawing
    them as black is the honest reading — they are not measurements, and the alternative is
    displaying an arbitrary vendor constant as though it were tissue. Note the one visible
    consequence: at an extreme window (wide enough to include −2048), a naive viewer lights
    that region up as grey and this one keeps it black. That is deliberate.

    Source 1 is compared against RAW stored values, the space the tag is defined in; source 2
    in Hounsfield units, the space the floor is defined in — and only for a genuine CT image
    actually in HU, since MR/other signal is arbitrary and a secondary capture's numbers only
    look like HU (see the two constants above).
    """
    masks = []

    pv = ds.get("PixelPaddingValue")
    if pv is not None:
        try:
            pv = int(pv)
            limit = ds.get("PixelPaddingRangeLimit")
            if limit is not None:
                lo, hi = sorted((pv, int(limit)))
                masks.append((raw >= lo) & (raw <= hi))
            else:
                masks.append(raw == pv)
        except (TypeError, ValueError):
            pass

    if _value_units(ds) == "HU" and str(ds.get("SOPClassUID", "")) in _CT_IMAGE_SOP_CLASSES:
        masks.append(_to_stored_units(ds, raw) < _HU_OUT_OF_FIELD)

    if not masks:
        return None
    mask = masks[0]
    for extra in masks[1:]:
        mask = mask | extra
    return mask if mask.any() else None


def _value_units(ds) -> str:
    """What the rescaled values ARE, per the file itself — never guessed beyond CT's
    well-defined Hounsfield convention."""
    rt = str(ds.get("RescaleType", "") or "").strip()
    if rt:
        return rt
    return "HU" if str(ds.get("Modality", "")) == "CT" else "raw"


def roi_stats(series_id: str, index: int, x: int, y: int, w: int, h: int,
              root: str | None = None) -> dict | None:
    """Descriptive statistics for a rectangular region of one slice: mean/SD/min/max in the
    modality's real units, pixel count, and physical area. None if the series/index is
    unknown; ValueError for a colour image (pixel statistics are meaningless on RGB) or an
    empty rectangle.

    This is MEASUREMENT, not interpretation — the same footing as the distance/angle tools.
    It reports what the pixels are; it says nothing about what they mean."""
    loaded = _load_frame(series_id, index, root)
    if loaded is None:
        return None
    ds, arr, is_colour = loaded
    if is_colour:
        raise ValueError("Pixel statistics are only meaningful for grayscale images.")

    # Clamp to the image so an out-of-bounds drag is truncated, not an error.
    x0, y0 = max(0, int(x)), max(0, int(y))
    x1, y1 = min(arr.shape[1], int(x) + int(w)), min(arr.shape[0], int(y) + int(h))
    if x1 <= x0 or y1 <= y0:
        raise ValueError("The selected region is empty or outside the image.")

    raw_region = arr[y0:y1, x0:x1]
    region = _to_stored_units(ds, raw_region)

    # EXCLUDE padding: those pixels are outside the reconstructed field of view, not
    # measurements. Including them fabricates a minimum (typically about -2048 HU) and drags
    # the mean, which would quietly misreport any region touching the out-of-field ring.
    padding = _padding_mask(ds, raw_region)
    n_padding = 0
    if padding is not None and padding.any():
        if padding.all():
            raise ValueError("That region is entirely outside the scanned field of view.")
        n_padding = int(padding.sum())
        region = region[~padding]

    ps = ds.get("PixelSpacing")
    try:
        area = float(region.size) * float(ps[0]) * float(ps[1]) if ps is not None else None
    except (TypeError, ValueError, IndexError):
        area = None
    return {
        "mean": round(float(region.mean()), 1),
        "sd": round(float(region.std()), 1),
        "min": round(float(region.min()), 1),
        "max": round(float(region.max()), 1),
        "n_pixels": int(region.size),
        "n_excluded": n_padding,
        "area_mm2": round(area, 1) if area is not None else None,
        "units": _value_units(ds),
    }


# --- raw frame payload (client-side windowing) ----------------------------------------
#
# The viewer used to fetch a WINDOWED PNG per slice, which made every cached frame specific
# to one window: changing window/level threw the whole series away and refetched it (a
# measured 9.4 s for a 984-slice series), which is why the preload had to be gated behind a
# drag. No conventional DICOM viewer has that problem, because none of them cache a picture
# — desktop viewers (RadiAnt, Horos, Weasis) and web ones (Cornerstone/OHIF) alike decode
# the pixel VALUES once and window them on the client, per frame, as you drag.
#
# So this sends values. One self-describing blob per frame:
#
#     [4-byte little-endian header length][UTF-8 JSON header][pixel bytes][packed mask bytes]
#
# The pixels are the file's OWN stored integers, not rescaled floats: that is the DICOM
# encoding itself, it is exact, and it is half the bytes of float32. The client applies
# slope/intercept, the VOI function and the MONOCHROME1 inversion — the same arithmetic
# this module does, restated in frame.js, with the two pinned against each other by a test.
#
# The out-of-field mask is sent EXPLICITLY, one bit per pixel, rather than left for the
# client to recompute. It is not derivable from the pixels alone (it depends on
# PixelPaddingValue, the SOP class, and the HU floor rule — see _padding_mask), and a
# sentinel value written into the pixel data could collide with real data. 32 KB on a 512²
# slice, and only when a slice actually has padding.
_FRAME_DTYPES = {
    ("i", 1): "i1", ("u", 1): "u1", ("i", 2): "i2", ("u", 2): "u2",
    ("i", 4): "i4", ("u", 4): "u4",
}


def frame_payload(series_id: str, index: int, root: str | None = None) -> bytes | None:
    """One slice's pixel VALUES plus everything needed to window them, or None if the
    series/index is unknown. Colour slices return None too — window/level is a grayscale
    concept, so the client keeps using the PNG route for those (see render_slice)."""
    loaded = _load_frame(series_id, index, root)
    if loaded is None:
        return None
    ds, arr, is_colour = loaded
    if is_colour:
        return None

    kind = _FRAME_DTYPES.get((arr.dtype.kind, arr.dtype.itemsize))
    if kind is None:                      # float or an exotic width: let the PNG path serve it
        return None

    padding = _padding_mask(ds, arr)      # RAW space, before any rescale
    dwc, dww = ds.get("WindowCenter"), ds.get("WindowWidth")
    default_wc = _first_num(dwc)
    default_ww = _first_num(dww)
    if default_wc is None or default_ww is None:
        # No declared window: derive one from the data, EXCLUDING padding so an out-of-field
        # ring can't stretch the range and wash out the anatomy. Same rule as render_slice.
        real = _to_stored_units(ds, arr)
        if padding is not None and (~padding).any():
            real = real[~padding]
        default_wc = float((real.min() + real.max()) / 2)
        default_ww = float(max(real.max() - real.min(), 1))

    header = {
        "rows": int(arr.shape[0]),
        "cols": int(arr.shape[1]),
        "dtype": kind,
        "slope": float(ds.get("RescaleSlope", 1) or 1),
        "intercept": float(ds.get("RescaleIntercept", 0) or 0),
        "invert": str(ds.get("PhotometricInterpretation", "")) == "MONOCHROME1",
        "voi": str(ds.get("VOILUTFunction", "") or "").strip().upper() or "LINEAR",
        "default_wc": float(default_wc),
        "default_ww": float(default_ww),
        "masked": padding is not None,
    }
    blob = json.dumps(header, separators=(",", ":")).encode("utf-8")
    # PAD the header so the pixels start on an 8-byte boundary. A JavaScript typed array
    # cannot be VIEWED at an arbitrary offset into an ArrayBuffer — `new Int16Array(buf,
    # offset, n)` throws unless the offset is a multiple of the element size — and the
    # header's length is whatever the JSON happens to be. Without this the payload works or
    # fails depending on the parity of a description of itself: the square test series
    # rendered and the tall one reported an undecodable slice, from the same code path.
    # 8 covers every element width this can carry, so it can't come back on i4/u4 either.
    blob += b" " * (-(4 + len(blob)) % 8)
    parts = [len(blob).to_bytes(4, "little"), blob,
             np.ascontiguousarray(arr).tobytes()]
    if padding is not None:
        parts.append(np.packbits(padding.reshape(-1)).tobytes())
    return b"".join(parts)


def render_slice(series_id: str, index: int, wc: float | None = None,
                 ww: float | None = None, root: str | None = None) -> bytes | None:
    """Render one slice to PNG bytes, applying window/level. None if the series/index is
    unknown. Rescales to Hounsfield units when slope/intercept are present (CT), honours
    the file's own default window when no wc/ww is given, and inverts MONOCHROME1. Colour
    slices render straight to RGB (window/level is a grayscale concept)."""
    loaded = _load_frame(series_id, index, root)
    if loaded is None:
        return None
    ds, arr, is_colour = loaded

    if is_colour:
        buf = io.BytesIO()
        Image.fromarray(arr.astype(np.uint8)[..., :3], mode="RGB").save(
            buf, format="PNG", compress_level=_PNG_COMPRESS_LEVEL)
        return buf.getvalue()

    # Padding is identified in RAW stored values, before the rescale below.
    padding = _padding_mask(ds, arr)
    arr = _to_stored_units(ds, arr)

    if wc is None or ww is None:
        dwc, dww = ds.get("WindowCenter"), ds.get("WindowWidth")
        if dwc is not None and dww is not None:
            wc = float(dwc[0] if hasattr(dwc, "__iter__") and not isinstance(dwc, str) else dwc)
            ww = float(dww[0] if hasattr(dww, "__iter__") and not isinstance(dww, str) else dww)
        else:
            # No declared window: derive one from the data, EXCLUDING padding so an
            # out-of-field ring can't stretch the range and wash out the anatomy.
            real = arr[~padding] if padding is not None and (~padding).any() else arr
            wc = float((real.min() + real.max()) / 2)
            ww = float(max(real.max() - real.min(), 1))

    out = _apply_voi(arr, ds, float(wc), float(ww))
    if str(ds.get("PhotometricInterpretation", "")) == "MONOCHROME1":
        out = 255 - out  # MONOCHROME1: min sample is white → invert for normal display
    if padding is not None:
        # After any inversion, so padding is black either way — it isn't image data.
        out = np.where(padding, 0.0, out)

    buf = io.BytesIO()
    Image.fromarray(out.astype(np.uint8), mode="L").save(
        buf, format="PNG", compress_level=_PNG_COMPRESS_LEVEL)
    return buf.getvalue()
