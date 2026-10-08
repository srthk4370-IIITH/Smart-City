"""Merge raw min/max from parallel calibration shards and write AIMET-format activation encodings.

Usage: python merge_stats.py <published w4a16 model.encodings> <out.encodings> shard0.stats.json shard1.stats.json ...
Global range per tensor = min of shard mins, max of shard maxes (exactly what one long AIMET min/max
calibration over all shards' data would produce). Encodings use AIMET's calculate_delta_offset.
"""
import json, math, sys

sys.path.insert(0, __file__.rsplit("/", 1)[0] if "/" in __file__ else ".")
from calib_ort import aimet_encoding  # noqa: E402

pub_path, out_path, shards = sys.argv[1], sys.argv[2], sys.argv[3:]
lo, hi, toks = {}, {}, 0
for p in shards:
    s = json.load(open(p))
    toks += s["tokens"]
    for k, v in s["lo"].items():
        lo[k] = min(lo.get(k, math.inf), v)
    for k, v in s["hi"].items():
        hi[k] = max(hi.get(k, -math.inf), v)
    print(f"{p}: {s['tokens']} tokens, {len(s['lo'])} tensors")
# Genie requires the KV-cache input and output of a layer to share ONE quantization (the output is written
# back into the cache): tie past_{key,value}_N_in / _out to the union of their ranges, as AIMET does.
tied = 0
for k in list(lo):
    if k.startswith("past_") and k.endswith("_in"):
        o = k[:-3] + "_out"
        if o in lo:
            lo[k] = lo[o] = min(lo[k], lo[o])
            hi[k] = hi[o] = max(hi[k], hi[o])
            tied += 1
print(f"tied {tied} KV-cache in/out pairs")
pub = json.load(open(pub_path))
new, changed, ratios = [], 0, []
for e in pub["activation_encodings"]:
    e2 = dict(e)
    n = e["name"]
    if n in lo and n in hi and e.get("dtype") == "INT":
        s, off = aimet_encoding(lo[n], hi[n], e["bw"], e.get("is_sym", False))
        old = e["scale"][0] if isinstance(e["scale"], list) else e["scale"]
        if old:
            ratios.append(s / old)
        e2["scale"] = [s] if isinstance(e["scale"], list) else s
        e2["offset"] = [off] if isinstance(e["offset"], list) else off
        changed += 1
    new.append(e2)
pub["activation_encodings"] = new
pub["calibration"] = {"tokens": toks, "shards": len(shards), "tensors_recomputed": changed}
json.dump(pub, open(out_path, "w"))
ratios.sort()
q = lambda f: ratios[int(f * (len(ratios) - 1))] if ratios else 1
print(f"total {toks} calibration tokens; {changed} activation encodings recomputed; "
      f"new/published scale median {q(0.5):.3f} p5 {q(0.05):.3f} p95 {q(0.95):.3f} -> {out_path}")
