"""Stage 1b: binary occupancy from the RAW zip (`sr_oc.csv`).

The cleaned SR-OC.csv lost the occupancy column (every value empty). The raw file keeps it as a
dict of per-sensor states inside the packed `data` list, e.g.
  "['1739770260', ' {""SR-OC-GW-KH95-01"": ""1""', ' ""SR-OC-GW-KH95-02"": ""1""}', ' 28.42', ' 43.08']"
Raw and clean files have identical row counts (same records), so raw is used only for occupancy.

Output: data/series/occupancy/<sensor>.csv  header: bucket,occ,occ_frac
  Raw encoding (meta data.xlsx): 0 = Occupied, 1 = Not occupied. Output uses 1 = occupied.
  occ      = 1 if the sensor reported occupied at least once in the 5-min bucket, else 0
  occ_frac = fraction of readings in the bucket that were occupied
"""
from __future__ import annotations

import argparse
import csv
import io
import json
import re
import zipfile
from collections import Counter, defaultdict
from datetime import datetime
from pathlib import Path

BUCKET = 300
PAIR = re.compile(r'(SR-OC-[A-Z0-9-]+)\W+(\d+)')


def main():
    root = Path(__file__).resolve().parents[1]
    ap = argparse.ArgumentParser()
    ap.add_argument("--zip", default=str(root.parents[1] / "SCRC-IHub-Data Collection.zip"))
    ap.add_argument("--out", default=str(root / "data" / "series" / "occupancy"))
    a = ap.parse_args()
    out = Path(a.out); out.mkdir(parents=True, exist_ok=True)
    acc = defaultdict(lambda: defaultdict(lambda: [0, 0]))  # sensor -> bucket -> [occupied, total]
    gw_of = {}
    values = Counter()
    rows = bad = 0
    with zipfile.ZipFile(a.zip) as z:
        with z.open("SCRC-IHub-Data Collection/sr_oc.csv") as raw:
            for r in csv.DictReader(io.TextIOWrapper(raw, encoding="utf-8", errors="replace", newline="")):
                rows += 1
                try:
                    b = int(datetime.fromisoformat(r["Timestamp"]).timestamp() // BUCKET) * BUCKET
                except (ValueError, KeyError):
                    bad += 1
                    continue
                pairs = PAIR.findall(r.get("data", ""))
                if not pairs:
                    bad += 1
                    continue
                for sensor, v in pairs:
                    values[v] += 1
                    if v not in ("0", "1"):
                        continue
                    s = acc[sensor][b]
                    s[0] += v == "0"; s[1] += 1  # raw encoding per meta data.xlsx: 0 = Occupied, 1 = Not occupied
                    gw_of[sensor] = r["Node_id"]
    report = {"rows": rows, "unparsed_rows": bad, "value_counts": dict(values), "sensors": {}}
    for sensor, buckets in acc.items():
        with open(out / f"{sensor}.csv", "w", newline="") as o:
            w = csv.writer(o)
            w.writerow(["bucket", "occ", "occ_frac"])
            occ1 = 0
            for b in sorted(buckets):
                o1, t = buckets[b]
                w.writerow([b, 1 if o1 else 0, round(o1 / t, 3)])
                occ1 += 1 if o1 else 0
        report["sensors"][sensor] = {"gateway": gw_of[sensor], "buckets": len(buckets),
                                     "occupied_bucket_frac": round(occ1 / len(buckets), 3)}
    (out.parent / "_occupancy_report.json").write_text(json.dumps(report, indent=1))
    print(json.dumps({k: v for k, v in report.items() if k != "sensors"}), len(report["sensors"]), "sensors")


if __name__ == "__main__":
    main()
