"""
import_imaging_cd.py — copy ONE imaging CD onto this machine, then verify it.

    python import_imaging_cd.py D: cd2

Why this exists: a hospital imaging CD holds two different kinds of thing, and they
belong in different places.

  * DICOM images  -> imaging_store/<label>/    (what the viewer scans)
  * everything else -> imaging_archive/<label>/  (reports, IHE_PDI web renditions,
    DICOMDIR manifest, index pages)

The split is deliberate: dicom_store.scan_studies walks and stat-checks EVERY file under
imaging_store on each folder-signature check, so dropping thousands of JPEGs and HTML
pages in there would slow every scan. Both trees are gitignored — these are medical
records and never leave the machine.

VERIFICATION is the point of the script, not the copying. It checks, in order:
  1. file count + byte total per area, source vs destination
  2. the disc's OWN DICOMDIR manifest — every IMAGE record it lists must be present
     (this is the only check that can catch an entire series the copy never saw)
  3. every copied DICOM parses AND its pixels decode (catches silent truncation)
  4. InstanceNumber continuity per series (catches a missing slice inside a series)

PRIVACY: this prints counts, sizes and structure only. It never prints patient,
physician or facility identifiers, even though the files it handles are full of them —
the DICOMDIR alone carries the patient name. Keep it that way if you edit this.

The vendor's bundled `cdviewer/` (Windows .exe/.dll) is skipped by default: it is
software, not records. Pass --include-viewer to archive it too.
"""

from __future__ import annotations

import argparse
import collections
import os
import shutil
import subprocess
import sys
import warnings

warnings.filterwarnings("ignore")

DICOM_SUBDIR_CANDIDATES = ("_STUDIES", "DICOM", "IMAGES")
SKIP_DIRS_DEFAULT = {"cdviewer"}

# Optical reads fail transiently — a marginal sector often reads fine on a later attempt.
# CD 2 threw 19 "device is not ready" errors at /R:1 /W:1 and then copied ALL of them at
# these settings, so patience here is the difference between a clean import and a false
# alarm. Cheap insurance: retries only cost time on files that were going to fail anyway.
ROBOCOPY_RETRIES = "5"
ROBOCOPY_WAIT_S = "3"

# Small, irreplaceable things are copied BEFORE the bulk. The radiology report is a few KB
# and exists nowhere else (not in the DICOM, not in the dose SR); IHE_PDI is hundreds of MB
# of lossy duplicates of images we already hold. Copying the report first means a disc that
# dies partway still yields the thing that can't be reconstructed.
PRIORITY_DIRS = ("other_content",)


def _walk_stats(path: str) -> tuple[int, int]:
    """(file count, total bytes) under path; (0, 0) if it doesn't exist."""
    n = total = 0
    for dirpath, _dirs, files in os.walk(path):
        for f in files:
            try:
                total += os.path.getsize(os.path.join(dirpath, f))
                n += 1
            except OSError:
                pass
    return n, total


def _copy_tree(src: str, dst: str) -> str | None:
    """Copy src -> dst. Returns None on success, or an error string on failure.

    Returns rather than RAISES on purpose. The first version raised, which aborted the
    whole import on the first bad sector — and because the bulk JPEG set is copied before
    the small files, that abort happened BEFORE the radiology report was ever reached. A
    failure in one area must not cost the areas that haven't been tried yet; the caller
    decides what's fatal (see copy_cd: a DICOM failure is, an archive failure isn't).

    robocopy's exit code is a bit-field where 0-7 all mean success (1 = 'files were
    copied'); only >=8 is a real failure. A naive check=True treats every success as error.
    """
    os.makedirs(dst, exist_ok=True)
    if shutil.which("robocopy"):
        r = subprocess.run(["robocopy", src, dst, "/E", "/R:" + ROBOCOPY_RETRIES,
                            "/W:" + ROBOCOPY_WAIT_S, "/NP", "/NFL", "/NDL"],
                           capture_output=True, text=True)
        if r.returncode >= 8:
            tail = "\n".join(l for l in (r.stdout or "").splitlines()
                             if "ERROR" in l or "FAILED" in l)[-500:]
            return f"robocopy exit {r.returncode}\n{tail}"
        return None
    try:
        shutil.copytree(src, dst, dirs_exist_ok=True)
        return None
    except Exception as e:                                   # noqa: BLE001 - reported, not raised
        return f"{type(e).__name__}: {e}"


def find_dicom_root(cd: str) -> str | None:
    for name in DICOM_SUBDIR_CANDIDATES:
        p = os.path.join(cd, name)
        if os.path.isdir(p):
            return p
    return None


def copy_cd(cd: str, label: str, include_viewer: bool,
            extra_skip: set[str] | None = None) -> dict:
    """Copy the disc into the two trees. Returns the per-area plan for verification."""
    store = os.path.join("imaging_store", label)
    archive = os.path.join("imaging_archive", label)
    dicom_root = find_dicom_root(cd)
    if dicom_root is None:
        raise SystemExit(f"No DICOM directory found on {cd} "
                         f"(looked for {', '.join(DICOM_SUBDIR_CANDIDATES)}).")

    skip = set() if include_viewer else set(SKIP_DIRS_DEFAULT)
    skip |= (extra_skip or set())
    plan = {"dicom": (dicom_root, store), "archive": [], "errors": []}

    # ORDER MATTERS on failing media: smallest-and-irreplaceable first, bulk last.
    # 1) loose root files (DICOMDIR is the manifest every later check depends on)
    os.makedirs(archive, exist_ok=True)
    for entry in sorted(os.listdir(cd)):
        src = os.path.join(cd, entry)
        if os.path.isfile(src):
            try:
                shutil.copy2(src, os.path.join(archive, entry))
            except Exception as e:                           # noqa: BLE001
                plan["errors"].append((entry, f"{type(e).__name__}: {e}"))
    print(f"copied root files -> {archive}")

    # 2) priority dirs (the radiology report — a few KB, and it exists nowhere else)
    dirs = [e for e in sorted(os.listdir(cd)) if os.path.isdir(os.path.join(cd, e))]
    ordered = ([d for d in dirs if d in PRIORITY_DIRS]
               + [d for d in dirs if d not in PRIORITY_DIRS])

    for entry in ordered:
        src = os.path.join(cd, entry)
        if entry in skip or os.path.samefile(src, dicom_root):
            continue
        dst = os.path.join(archive, entry)
        print(f"copying archive {src}  ->  {dst}")
        err = _copy_tree(src, dst)
        plan["archive"].append((src, dst))
        if err:
            # Non-fatal: keep going so later areas (and the DICOM) still get copied. The
            # per-area byte comparison in verify() reports exactly what's short.
            plan["errors"].append((entry, err))
            print(f"  !! {entry} had read failures — continuing; see the summary")

    # 3) the DICOM itself last, since it's the biggest — and a failure here IS fatal.
    print(f"copying DICOM   {dicom_root}  ->  {store}")
    err = _copy_tree(dicom_root, store)
    if err:
        plan["errors"].append(("DICOM", err))
        print(f"  !! DICOM read failures — retrying once more before giving up")
        err = _copy_tree(dicom_root, store)                  # robocopy resumes what's missing
        if err:
            plan["errors"].append(("DICOM (retry)", err))
    return plan


def verify(cd: str, label: str, plan: dict, include_viewer: bool) -> bool:
    import pydicom

    store = os.path.join("imaging_store", label)
    archive = os.path.join("imaging_archive", label)
    ok = True

    print("\n--- 1. counts and bytes ------------------------------------------")
    areas = [("DICOM", plan["dicom"][0], store)] + [(os.path.basename(s), s, d)
                                                    for s, d in plan["archive"]]
    for name, src, dst in areas:
        sn, sb = _walk_stats(src)
        dn, db = _walk_stats(dst)
        good = (sn == dn and sb == db)
        ok &= good
        print(f"  {name:<16} src {sn:>6} / {sb:>13,}   dst {dn:>6} / {db:>13,}   "
              f"{'OK' if good else 'MISMATCH'}")

    # Loose root files (DICOMDIR, index.htm, ...) land directly in the archive root.
    for entry in sorted(os.listdir(cd)):
        src = os.path.join(cd, entry)
        if os.path.isfile(src):
            dst = os.path.join(archive, entry)
            good = os.path.exists(dst) and os.path.getsize(dst) == os.path.getsize(src)
            ok &= good
            print(f"  {entry:<16} {os.path.getsize(src):>13,} bytes            "
                  f"{'OK' if good else 'MISMATCH'}")

    print("\n--- 2. DICOMDIR manifest cross-check -----------------------------")
    dicomdir = os.path.join(archive, "DICOMDIR")
    if not os.path.exists(dicomdir):
        print("  no DICOMDIR on this disc — skipping (checks 3 and 4 still apply)")
    else:
        dd = pydicom.dcmread(dicomdir)
        kinds = collections.Counter(str(r.get("DirectoryRecordType", "?"))
                                    for r in dd.DirectoryRecordSequence)
        print(f"  manifest records: {dict(kinds)}")
        listed = set()
        for rec in dd.DirectoryRecordSequence:
            if str(rec.get("DirectoryRecordType", "")) == "IMAGE":
                fid = rec.get("ReferencedFileID")
                if fid is None:
                    continue
                parts = list(fid) if not isinstance(fid, str) else [fid]
                listed.add(str(parts[-1]).upper())          # filename is unique per disc
        have = {f.upper() for _dp, _d, fs in os.walk(store) for f in fs}
        missing = listed - have
        ok &= not missing
        print(f"  images listed {len(listed)} · present {len(listed) - len(missing)} · "
              f"MISSING {len(missing)}  {'OK' if not missing else 'FAIL'}")
        for m in sorted(missing)[:10]:
            print(f"     missing: {m}")

    print("\n--- 3. integrity (every file parses + decodes) -------------------")
    bad_header, bad_pixels, non_image = [], [], 0
    series = collections.defaultdict(list)
    scanned = 0
    for dirpath, _d, files in os.walk(store):
        for f in files:
            p = os.path.join(dirpath, f)
            scanned += 1
            try:
                ds = pydicom.dcmread(p)
            except Exception as e:
                bad_header.append((p, type(e).__name__))
                continue
            if not ds.get("Rows"):
                non_image += 1          # SR / PR / KO carry no pixels — expected
                continue
            uid = str(ds.get("SeriesInstanceUID", ""))
            try:
                series[uid].append(int(ds.get("InstanceNumber", 0) or 0))
            except (TypeError, ValueError):
                pass
            try:
                _ = ds.pixel_array
            except Exception as e:
                bad_pixels.append((p, type(e).__name__))
    ok &= not bad_header and not bad_pixels
    print(f"  scanned {scanned} · unreadable {len(bad_header)} · undecodable {len(bad_pixels)}"
          f" · non-image objects {non_image}  "
          f"{'OK' if not bad_header and not bad_pixels else 'FAIL'}")
    for p, e in (bad_header + bad_pixels)[:10]:
        print(f"     {e}: {os.path.basename(p)}")

    print("\n--- 4. per-series slice continuity -------------------------------")
    gaps = 0
    for uid, inst in series.items():
        s = sorted(inst)
        missing_n = len(set(range(s[0], s[-1] + 1)) - set(s))
        gaps += missing_n
    ok &= gaps == 0
    print(f"  image series {len(series)} · missing instances {gaps}  "
          f"{'OK' if gaps == 0 else 'FAIL'}")

    if plan.get("errors"):
        print("\n--- copy errors encountered (non-fatal areas continued) -----------")
        for area, msg in plan["errors"]:
            print(f"  {area}: {msg.splitlines()[0] if msg else '?'}")
        print("  If an area is short above, re-run the same command — robocopy resumes and\n"
              "  a marginal sector often reads on a later attempt.")

    if not include_viewer and os.path.isdir(os.path.join(cd, "cdviewer")):
        n, b = _walk_stats(os.path.join(cd, "cdviewer"))
        print(f"\n  note: skipped cdviewer/ ({n} files, {b/1024/1024:.1f} MB) — vendor "
              f"software, not records. Use --include-viewer to archive it.")
    return ok


def main() -> int:
    ap = argparse.ArgumentParser(description="Copy and verify one imaging CD.")
    ap.add_argument("drive", help="CD drive or folder, e.g. D:")
    ap.add_argument("label", help="destination label, e.g. cd2")
    ap.add_argument("--skip-dir", action="append", default=[], metavar="NAME",
                    help="skip an archive area (repeatable). Use when a disc shares an "
                         "accession with one already imported, so e.g. IHE_PDI would be a "
                         "byte-identical duplicate of hundreds of MB.")
    ap.add_argument("--fresh", action="store_true",
                    help="delete any existing copy for this label first (default: resume)")
    ap.add_argument("--include-viewer", action="store_true",
                    help="also archive the vendor's cdviewer/ software")
    args = ap.parse_args()

    cd = args.drive if args.drive.endswith(("\\", "/")) else args.drive + os.sep
    if not os.path.isdir(cd):
        raise SystemExit(f"{cd} is not readable — is the disc mounted?")
    # A non-empty label is allowed and RESUMES (robocopy copies only what's missing) —
    # that's the documented fix for a marginal disc. --fresh forces a clean start instead.
    for tree in ("imaging_store", "imaging_archive"):
        dest = os.path.join(tree, args.label)
        if os.path.exists(dest) and os.listdir(dest):
            if args.fresh:
                print(f"--fresh: removing {dest}")
                shutil.rmtree(dest)
            else:
                print(f"note: {dest} exists — resuming (only missing files are copied)")

    plan = copy_cd(cd, args.label, args.include_viewer, set(args.skip_dir))
    ok = verify(cd, args.label, plan, args.include_viewer)
    print("\n" + ("ALL CHECKS PASSED — safe to eject." if ok else
                  "SOME CHECKS FAILED — do NOT eject; see above."))
    return 0 if ok else 1


if __name__ == "__main__":
    sys.exit(main())
