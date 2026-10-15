"""Re-download exactly the TeamTrack files Gaffer uses, and verify them (size + SHA-256).

TeamTrack (Scott et al., 2024; MIT licence) is the Kaggle dataset `atomscott/teamtrack`. The
files we use are listed, with byte sizes and SHA-256 checksums, in
`data/teamtrack_manifest.json` (committed); videos land in `data/teamtrack/` (gitignored).

Modes:
    py scripts\\download_teamtrack.py --check     # verify local files only (no network)
    py scripts\\download_teamtrack.py             # download what is missing or wrong, verify
    py scripts\\download_teamtrack.py --list      # what else Kaggle has (soccer, per split)
    py scripts\\download_teamtrack.py --write-manifest   # maintainer: hash the local files

Listing works anonymously. Downloading needs a (free) Kaggle account: an API token from
kaggle.com -> Settings -> API, either as environment variables `KAGGLE_USERNAME` /
`KAGGLE_KEY` or as `~/.kaggle/kaggle.json` (`KAGGLE_CONFIG_DIR` overrides the folder). The
token is only sent to kaggle.com and never printed. Dependencies: `requests` (Apache 2.0).
"""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import sys
import zipfile
from collections import defaultdict
from pathlib import Path
from typing import Any

import requests

from gaffer.config import load_config, repo_path

DATASET = "atomscott/teamtrack"
API = "https://www.kaggle.com/api/v1"
KAGGLE_ROOT = "teamtrack/teamtrack"  # folder of the per-sport splits inside the dataset
MANIFEST = "data/teamtrack_manifest.json"
CHUNK = 1 << 20


class DownloadError(RuntimeError):
    """A file could not be fetched or failed verification."""


def sha256(path: Path) -> str:
    h = hashlib.sha256()
    with path.open("rb") as f:
        for block in iter(lambda: f.read(CHUNK), b""):
            h.update(block)
    return h.hexdigest()


def verify(entry: dict[str, Any]) -> str:
    """'ok', 'missing', 'size' or 'checksum' for one manifest entry."""
    p = repo_path(entry["local"])
    if not p.exists():
        return "missing"
    if p.stat().st_size != int(entry["bytes"]):
        return "size"
    return "ok" if sha256(p) == entry["sha256"] else "checksum"


def credentials() -> tuple[str, str]:
    """Kaggle username + key from the environment or kaggle.json (never printed)."""
    user, key = os.environ.get("KAGGLE_USERNAME"), os.environ.get("KAGGLE_KEY")
    if user and key:
        return user, key
    folder = Path(os.environ.get("KAGGLE_CONFIG_DIR", Path.home() / ".kaggle"))
    path = folder / "kaggle.json"
    if path.exists():
        try:
            d = json.loads(path.read_text(encoding="utf-8"))
            return str(d["username"]), str(d["key"])
        except (json.JSONDecodeError, KeyError) as exc:
            raise DownloadError(f"{path} is not a valid Kaggle token file") from exc
    raise DownloadError(
        "Kaggle credentials not found. Create an API token on kaggle.com (Settings -> API) "
        "and either set KAGGLE_USERNAME and KAGGLE_KEY, or save kaggle.json in ~/.kaggle/. "
        "Anonymous downloads are refused by Kaggle (HTTP 404); `--list` works without them.")


def download(entry: dict[str, Any], auth: tuple[str, str]) -> None:
    """Fetch one file into place (via a .part file), unzip if Kaggle zipped it, verify."""
    dest = repo_path(entry["local"])
    dest.parent.mkdir(parents=True, exist_ok=True)
    part = dest.with_name(dest.name + ".part")
    url = f"{API}/datasets/download/{DATASET}/{entry['kaggle']}"
    try:
        with requests.get(url, auth=auth, stream=True, timeout=120) as r:
            if r.status_code in (401, 403):
                raise DownloadError(f"Kaggle refused the credentials (HTTP {r.status_code})")
            if r.status_code != 200:
                raise DownloadError(f"HTTP {r.status_code} for {entry['kaggle']}")
            with part.open("wb") as f:
                for block in r.iter_content(CHUNK):
                    f.write(block)
    except requests.RequestException as exc:
        raise DownloadError(f"network error for {entry['kaggle']}: {exc}") from exc
    if zipfile.is_zipfile(part) and not dest.suffix == ".zip":
        with zipfile.ZipFile(part) as z:
            names = [n for n in z.namelist() if n.endswith(dest.name)]
            if not names:
                raise DownloadError(f"{entry['kaggle']}: zip without {dest.name}")
            with z.open(names[0]) as src, dest.open("wb") as out:
                while block := src.read(CHUNK):
                    out.write(block)
        part.unlink()
    else:
        part.replace(dest)
    status = verify(entry)
    if status != "ok":
        raise DownloadError(f"{dest} downloaded but failed verification ({status})")


def kaggle_listing() -> list[dict[str, Any]]:
    """Every file of the dataset (name, bytes), via the public listing endpoint."""
    files: list[dict[str, Any]] = []
    token = None
    try:
        while True:
            params: dict[str, Any] = {"pageSize": 200}
            if token:
                params["pageToken"] = token
            r = requests.get(f"{API}/datasets/list/{DATASET}", params=params, timeout=60)
            r.raise_for_status()
            d = r.json()
            files += [{"name": f["name"], "bytes": int(f.get("totalBytes") or 0)}
                      for f in d.get("datasetFiles", [])]
            token = d.get("nextPageTokenNullable") or d.get("nextPageToken")
            if not token:
                return files
    except (requests.RequestException, ValueError) as exc:
        raise DownloadError(f"could not list {DATASET}: {exc}") from exc


def list_soccer(manifest: list[dict[str, Any]]) -> dict[str, Any]:
    """Soccer clips on Kaggle per view and split: count, time range, size, and which we have."""
    have = {Path(e["local"]).stem for e in manifest}
    groups: dict[tuple[str, str], list[dict[str, Any]]] = defaultdict(list)
    for f in kaggle_listing():
        parts = f["name"].split("/")
        if f["name"].startswith(KAGGLE_ROOT + "/soccer_") and len(parts) >= 6:
            groups[(parts[2], parts[3])].append(f)
    out = {}
    for (view, split), fs in sorted(groups.items()):
        vids = sorted(Path(f["name"]).stem for f in fs if f["name"].endswith(".mp4"))
        out[f"{view}/{split}"] = {
            "clips": len(vids), "first": vids[0] if vids else None,
            "last": vids[-1] if vids else None,
            "matches": sorted({"_".join(v.split("_")[1:3]) for v in vids}),
            "megabytes": round(sum(f["bytes"] for f in fs) / 1e6, 1),
            "already_local": sum(v in have for v in vids)}
    return out


KAGGLE_SPLIT = {("top", "eval2"): "val"}  # Kaggle split per (view, clip set); default "test"
MANUAL_NOTE = ("downloaded manually by the user from the Kaggle dataset atomscott/teamtrack "
               "(15 Oct 2026); second eval set (teamtrack.clip_sets.eval2)")


def write_manifest(cfg: dict[str, Any], old: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """Hash every TeamTrack file under data/teamtrack/. Entries already in the manifest are
    kept as they are (re-verified); new files get their Kaggle path from their clip set."""
    from gaffer.teamtrack import NAME_RE, clip_set  # noqa: PLC0415

    root = repo_path(cfg["paths"]["teamtrack"])
    known = {e["local"]: e for e in old}
    entries = []
    for vname, view in cfg["teamtrack"]["views"].items():
        folder = root / view["folder"]
        for kind, ext in (("videos", ".mp4"), ("annotations", ".csv")):
            for p in sorted((folder / kind).glob(f"*{ext}")):
                local = p.relative_to(repo_path(".")).as_posix()
                if local in known:
                    if verify(known[local]) != "ok":
                        raise DownloadError(f"{local} no longer matches the manifest")
                    entries.append(known[local])
                    continue
                m = NAME_RE.match(p.stem)
                cs = clip_set(vname, cfg, float(m["start"])) if m else None
                split = KAGGLE_SPLIT.get((vname, cs), "test")
                e = {"kaggle": f"{KAGGLE_ROOT}/{view['folder']}/{split}/{kind}/{p.name}",
                     "local": local, "bytes": p.stat().st_size, "sha256": sha256(p)}
                if cs == "eval2":
                    e["note"] = MANUAL_NOTE
                entries.append(e)
    return entries


def main(argv: list[str] | None = None) -> int:
    cfg = load_config()
    ap = argparse.ArgumentParser(description="Download + verify the TeamTrack files we use")
    g = ap.add_mutually_exclusive_group()
    g.add_argument("--check", action="store_true", help="verify local files only")
    g.add_argument("--list", action="store_true", help="list soccer clips available on Kaggle")
    g.add_argument("--write-manifest", action="store_true", help="hash local files (maintainer)")
    args = ap.parse_args(argv)
    mpath = repo_path(MANIFEST)
    try:
        if args.write_manifest:
            old = json.loads(mpath.read_text(encoding="utf-8"))["files"] if mpath.exists() else []
            entries = write_manifest(cfg, old)
            mpath.write_text(json.dumps({
                "dataset": DATASET, "licence": "MIT",
                "note": "26 files downloaded 9 Oct 2026 (dev + first eval set); 30 files with a "
                        "'note' downloaded manually by the user on 15 Oct 2026 (second eval set, "
                        "Kaggle soccer_top/val and soccer_side/test)",
                "files": entries}, indent=1), encoding="utf-8")
            print(f"{len(entries)} files, {sum(e['bytes'] for e in entries) / 1e6:.1f} MB "
                  f"-> {mpath}")
            return 0
        if not mpath.exists():
            raise DownloadError(f"{mpath} missing (it is committed with the repo)")
        manifest = json.loads(mpath.read_text(encoding="utf-8"))["files"]
        if args.list:
            for k, v in list_soccer(manifest).items():
                print(f"{k:20s} {v['clips']:3d} clips {v['first']} .. {v['last']}  "
                      f"{v['megabytes']:8.1f} MB  matches {v['matches']}  local "
                      f"{v['already_local']}")
            return 0
        status = {e["local"]: verify(e) for e in manifest}
        bad = [e for e in manifest if status[e["local"]] != "ok"]
        total = sum(e["bytes"] for e in manifest)
        print(f"{len(manifest) - len(bad)}/{len(manifest)} files verified "
              f"({total / 1e6:.1f} MB in the manifest)")
        for e in bad:
            print(f"  {status[e['local']]:8s} {e['local']}")
        if args.check or not bad:
            return 0 if not bad else 1
        auth = credentials()
        for i, e in enumerate(bad, 1):
            print(f"[{i}/{len(bad)}] {e['kaggle']} ({e['bytes'] / 1e6:.1f} MB)", flush=True)
            download(e, auth)
        print("all files downloaded and verified")
        return 0
    except DownloadError as exc:
        print(f"ERROR: {exc}", file=sys.stderr)
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
