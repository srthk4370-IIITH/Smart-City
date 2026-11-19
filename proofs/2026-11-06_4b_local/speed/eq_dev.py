"""dev-loss pass with --shared-prefix (dev_losses) vs the current per-row loss_fn pass: per-row loss sums and the logged
DEV metrics (sum loss / sum label tokens per kind), no grad, model.eval(), fp32 and bf16. usage: eq_dev.py <out.json>"""
import json
import sys
import types

import eqlib as E
import torch

T = E.load_trainer()
CPU = torch.device("cpu")
rows, _ = E.real_rows(T, n_inc=5, n_chat=5)
out = []
for dt in (torch.float32, torch.bfloat16):
    E.mem_guard(str(dt))
    m = E.tiny_model(dtype=dt, dropout=0.05)          # dropout on: model.eval() must switch it off on both paths
    m.eval()
    res = {}
    for name, sp in (("per-row (current)", False), ("shared prefix", True)):
        a = types.SimpleNamespace(shared_prefix=sp, shared_prefix_min=256, shared_prefix_cont=2048, micro_tokens=7424)
        with torch.no_grad():
            res[name] = {d["id"]: (l, n, d["kind"]) for d, l, n in T.dev_losses(m, rows, a, CPU)}
    b, s = res["per-row (current)"], res["shared prefix"]
    assert b.keys() == s.keys() and all(b[k][1] == s[k][1] for k in b)
    rel = max(abs(s[k][0] - b[k][0]) / abs(b[k][0]) for k in b)
    met = {}
    for nm, R in res.items():
        acc = [0.0] * 4
        for l, n, kind in R.values():
            j = 0 if kind == "incident" else 2
            acc[j] += l
            acc[j + 1] += n
        met[nm] = {"dev_incident": acc[0] / acc[1], "dev_chat": acc[2] / acc[3]}
    d = {"dtype": str(dt).split(".")[-1], "rows": len(b), "max_row_loss_rel_diff": rel, "metrics": met,
         "clusters": [(p, len(c)) for p, c in T.prefix_clusters(rows, 256)]}
    out.append(d)
    print(json.dumps(d), flush=True)
    del m
    T.host_trim()
json.dump(out, open(sys.argv[1], "w"), indent=1)
print("peak RSS %d MB" % E.peak_rss_mb())
