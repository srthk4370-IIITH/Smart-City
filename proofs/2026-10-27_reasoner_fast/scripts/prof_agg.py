"""Aggregate GGML_HEXAGON_PROFILE=1 per-op usec over the decode batches (ops whose src dims have 1 token)."""
import re, sys, collections
lines = open(sys.argv[1], encoding="utf-8", errors="replace").read().splitlines()
batches, cur = [], None
for l in lines:
    if "profile-op OPBATCH" in l:
        m = re.search(r"n-ops (\d+).*usec (\d+)", l); cur = {"n": int(m.group(1)), "usec": int(m.group(2)), "ops": []}; batches.append(cur)
    elif "profile-op" in l and cur is not None:
        f = l.split("profile-op ", 1)[1].split("|")
        us = int(re.search(r"usec (\d+)", l).group(1))
        name = f[0]; tensor = f[1]
        kind = "lm_head" if "result_output" in tensor or "output.weight" in tensor or "token_embd" in tensor and name.startswith("MUL_MAT") else ""
        cur["ops"].append((name, tensor, f[2], us, kind))
dec = batches[2:]  # first = prompt prefill(s); keep decode batches
print(f"{len(batches)} batches; decode batches {len(dec)}; mean batch usec {sum(b['usec'] for b in dec)/len(dec):.0f}, mean sum(op usec) {sum(sum(o[3] for o in b['ops']) for b in dec)/len(dec):.0f}, ops/batch {sum(b['n'] for b in dec)/len(dec):.0f}")
agg = collections.Counter(); cnt = collections.Counter()
for b in dec:
    for name, t, dims, us, kind in b["ops"]:
        key = name + (" [lm_head]" if kind else "")
        if name.startswith("MUL_MAT"):
            w = re.sub(r"blk\.\d+\.", "blk.N.", t.split(" x ")[0].split("#")[-1]) if "#" in t else t.split(" x ")[0]
            key = name + " " + re.sub(r"blk\.\d+\.", "", w.split("->")[0])[:40]
        agg[key] += us; cnt[key] += 1
tot = sum(agg.values())
for k, v in agg.most_common(25):
    print(f"{v/len(dec)/1000:7.2f} ms/token  {100*v/tot:5.1f}%  x{cnt[k]//len(dec):3d}  {k}")
