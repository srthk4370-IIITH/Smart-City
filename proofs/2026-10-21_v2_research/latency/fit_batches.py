"""Fit the v2 on-device batch time into prefill and decode parts (no device access).

For every batch of the v2 device eval (test_all + host400, htpd 8 x 1408, DRAFT + PREFIX_CACHE + LEGACY_PREFILL):
  prefill_ms ~ a + b * (sum of uncached prompt tokens)          uncached = prompt_tokens - system turn of the role
  decode_ms  = batch_ms - prefill_ms ~ c + d * (max generated tokens in the batch)
Prompt token counts come from data/sft_v2/test.jsonl (prompt_tokens field, same tokenizer).
WSL: ~/venvs/train/bin/python fit_batches.py   -> fit_batches.json
"""
import json, os, collections, statistics as st
H = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.abspath(os.path.join(H, "..", "..", ".."))
SYS = {"air_quality": 300, "water": 308, "power": 300, "occupancy": 262, "weather": 287, "hvac": 348}  # fit_check.json
pt = {}
for l in open(os.path.join(ROOT, "Code/smart-city-edge-agent/data/sft_v2/test.jsonl"), encoding="utf-8"):
    r = json.loads(l)
    pt[r["id"]] = (r["prompt_tokens"], r["role"])

def ols(x, y):
    mx, my = st.mean(x), st.mean(y)
    b = sum((a - mx) * (c - my) for a, c in zip(x, y)) / sum((a - mx) ** 2 for a in x)
    a = my - b * mx
    res = [c - (a + b * v) for v, c in zip(x, y)]
    return a, b, (sum(e * e for e in res) / len(res)) ** .5

rows = []
for f in ["test_all", "host400"]:
    b = collections.OrderedDict()
    for l in open(os.path.join(ROOT, "proofs/2026-10-20_v2_post/device", f, "samples.jsonl"), encoding="utf-8"):
        r = json.loads(l)
        b.setdefault((r["batch_s"], r["prefill_ms"]), []).append(r)
    for (bs, pf), rs in b.items():
        if any(r["id"] not in pt for r in rs):
            continue
        roles = [pt[r["id"]][1] for r in rs]
        unc = sum(pt[r["id"]][0] - SYS[pt[r["id"]][1]] for r in rs)
        tot = sum(pt[r["id"]][0] for r in rs)
        mt = max(r["tokens"] for r in rs)
        rows.append(dict(size=len(rs), unc=unc, tot=tot, pf=pf, dec=bs * 1000 - pf, maxtok=mt, roles=len(set(roles)),
                         runaway=mt >= 300, src=f))
ok = [r for r in rows if r["size"] == 8 and not r["runaway"]]
a, b, e = ols([r["unc"] for r in ok], [r["pf"] for r in ok])
c, d, e2 = ols([r["maxtok"] for r in ok], [r["dec"] for r in ok])
a2, b2, e3 = ols([r["tot"] for r in ok], [r["pf"] for r in ok])
out = dict(batches=len(rows), used=len(ok), runaway_batches=sum(r["runaway"] for r in rows),
           prefill_fit_uncached=dict(intercept_ms=round(a), ms_per_token=round(b, 3), rmse_ms=round(e)),
           prefill_fit_total=dict(intercept_ms=round(a2), ms_per_token=round(b2, 3), rmse_ms=round(e3)),
           decode_fit=dict(intercept_ms=round(c), ms_per_max_token=round(d, 1), rmse_ms=round(e2)),
           medians=dict(uncached_tokens=st.median(r["unc"] for r in ok), total_tokens=st.median(r["tot"] for r in ok),
                        prefill_ms=st.median(r["pf"] for r in ok), decode_ms=st.median(r["dec"] for r in ok),
                        max_tokens=st.median(r["maxtok"] for r in ok), roles_per_batch=st.median(r["roles"] for r in ok)),
           runaway=dict(decode_ms_median=st.median(r["dec"] for r in rows if r["runaway"]) if any(r["runaway"] for r in rows) else None))
print(json.dumps(out, indent=1))
json.dump(out, open(os.path.join(H, "fit_batches.json"), "w"), indent=1)
