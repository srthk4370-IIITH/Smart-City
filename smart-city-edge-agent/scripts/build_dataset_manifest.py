"""Create a reproducible manifest for the supplied raw sensor CSVs."""
from __future__ import annotations

import argparse
import csv
import hashlib
import json
from datetime import datetime, timezone
from pathlib import Path

EXPECTED = ("aq.csv", "em.csv", "sr-aq.csv", "sr-em.csv", "sr_oc.csv", "we.csv", "wm-wf.csv", "wm-wd.csv", "wm-wl.csv", "wn.csv", "cm.csv")


def sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for block in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def manifest(data_dir: Path, output: Path) -> None:
    if not data_dir.is_dir():
        raise SystemExit(f"Dataset directory does not exist: {data_dir}")
    files = []
    for path in sorted(data_dir.glob("*.csv")):
        with path.open("r", encoding="utf-8-sig", errors="replace", newline="") as handle:
            header = next(csv.reader(handle), [])
        files.append({"name": path.name, "bytes": path.stat().st_size, "sha256": sha256(path), "header": header})
    found = {item["name"] for item in files}
    payload = {
        "manifest_version": "1.0",
        "created_at_utc": datetime.now(timezone.utc).isoformat(),
        "dataset_root": str(data_dir.resolve()),
        "expected_files_missing": sorted(set(EXPECTED) - found),
        "files": files,
        "notes": [
            "This manifest records integrity, not data licensing or field units.",
            "Do not use aq.csv to invent CO2: only sr-aq.csv has a measured CO2 column.",
        ],
    }
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(json.dumps(payload, indent=2) + "\n", encoding="utf-8")
    print(f"Wrote {output} ({len(files)} CSV files)")


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--data-dir", type=Path, required=True)
    parser.add_argument("--output", type=Path, default=Path("data/manifests/dataset_manifest.json"))
    args = parser.parse_args()
    manifest(args.data_dir, args.output)
