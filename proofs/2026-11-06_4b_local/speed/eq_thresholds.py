"""item 2: --offload-min / --mlp-chunk-min are exact. Same tiny model + real rows + the trainer's micro-batch step; LoRA gradients
and loss compared between the live config (offload + mlp-chunk 512 on every forward) and threshold settings."""
import json
import sys
import time
import types

import eqlib as E
import torch

T = E.load_trainer()
E.mem_guard("start")
rows, _ = E.real_rows(T, n_inc=5, n_chat=3)
print("rows:", [(r["kind"], len(r["ids"])) for r in rows], flush=True)
MT = 7424
cfgs = [("none (HF checkpoint only)", None),
        ("live: offload + mlp-chunk 512, min 0/0", dict(offload_min=0, mlp_chunk_min=0)),
        ("offload-min 4096, mlp-chunk-min 4096", dict(offload_min=4096, mlp_chunk_min=4096)),
        ("offload-min 6000, mlp-chunk-min 3000", dict(offload_min=6000, mlp_chunk_min=3000)),
        ("thresholds above every forward (1e9)", dict(offload_min=10 ** 9, mlp_chunk_min=10 ** 9))]
res = {}
for name, c in cfgs:
    E.mem_guard(name)
    m = E.tiny_model()
    if c is not None:
        a = types.SimpleNamespace(head_cpu=False, ckpt_offload=True, mlp_chunk=512, **c)
        print(name, "->", T.apply_fit_levers(m, a, torch.device("cpu")), flush=True)
    else:
        T.OFFLOAD_MIN = 0
    t0 = time.time()
    loss = E.baseline_step(T, m, rows, MT)
    res[name] = (loss, E.lora_grads(m), time.time() - t0)
    print("%-42s loss %.9f  %.1f s" % (name, loss, res[name][2]), flush=True)
    del m
ref = cfgs[1][0]
out = {"rows": [(r["kind"], len(r["ids"])) for r in rows], "micro_tokens": MT,
       "forwards_padded_tokens": [len(mb) * len(mb[0]["ids"]) for mb in T.micro_batches(rows, MT)], "vs": ref, "results": []}
for name, _ in cfgs:
    l, g, t = res[name]
    d = E.compare(res[ref][1], g)
    d.update(config=name, loss=l, loss_abs_diff=abs(l - res[ref][0]), cpu_s=round(t, 1))
    out["results"].append(d)
    print(json.dumps(d), flush=True)
json.dump(out, open(sys.argv[1], "w"), indent=1)
print("peak RSS %d MB" % E.peak_rss_mb())
