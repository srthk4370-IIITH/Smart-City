"""item 1, second part (split from eq_shared.py to keep host RAM low): --head-cpu stand-in through the shared path, and the
yardsticks: the baseline's own batching noise (micro-batched vs one row per forward) in fp32 and in bf16, vs shared prefix."""
import json
import sys
import types

import eqlib as E
import torch

T = E.load_trainer()
E.mem_guard("start")
CPU = torch.device("cpu")
rows, _ = E.real_rows(T, n_inc=4, n_chat=3)
A = types.SimpleNamespace(micro_tokens=7424, shared_prefix_min=256, shared_prefix_cont=2048)
out = {"rows": [(r["kind"], len(r["ids"])) for r in rows], "cases": []}


def run_new(m, exs):
    tot = 0.0
    for (l, n), e in T.shared_prefix_step(m, exs, A, CPU, lambda t: (t / 16).backward()):
        tot += float(l) / max(1, n)
    return tot


def per_row(m, exs):
    tot = 0.0
    for e in exs:
        l, n = T.loss_fn(m, e["ids"], e["labels"], CPU)
        (l / max(1, n) / 16).backward()
        tot += float(l) / max(1, n)
    return tot


def record(name, lb, gb, ln, gn):
    d = E.compare(gb, gn)
    d.update(case=name, loss_base=lb, loss_new=ln, loss_rel_diff=abs(ln - lb) / abs(lb))
    out["cases"].append(d)
    print(json.dumps(d), flush=True)
    json.dump(out, open(sys.argv[1], "w"), indent=1)


# --head-cpu stand-in: embeddings = a row gather of the tied weight, loss = CE on the selected hidden rows (the plumbing of the
# HEAD path; _StreamCE itself is GPU-only and unchanged), with ckpt-offload (CPU stubs) + mlp-chunk 512
ml = E.tiny_model()
T.apply_fit_levers(ml, types.SimpleNamespace(head_cpu=False, ckpt_offload=True, mlp_chunk=512, offload_min=0, mlp_chunk_min=0), CPU)
W = ml.get_base_model().model.embed_tokens.weight


class Shim:
    def embed(self, x2d):
        return W.detach()[x2d.long()].clone().requires_grad_(torch.is_grad_enabled())

    def ce(self, hs, ys):
        return torch.nn.functional.cross_entropy((hs @ W.detach().t()).float(), ys, reduction="sum")


T.HEAD = Shim()
NOFF = []
_orig = T._OffloadCkptN
T._OffloadCkptN = types.SimpleNamespace(apply=lambda *x: (NOFF.append(1), _orig.apply(*x))[1])   # count: the offload path is used
lb = E.baseline_step(T, ml, rows, 7424)
gb = E.lora_grads(ml)
ml.zero_grad(set_to_none=True)
ln = run_new(ml, rows)
record("head-cpu stand-in + offload + mlp-chunk 512: baseline vs shared (%d layer forwards via _OffloadCkptN)" % len(NOFF), lb, gb, ln,
       E.lora_grads(ml))
T._OffloadCkptN = _orig
T.HEAD, T.OFFLOAD_MIN = None, 0
del ml, W
T.host_trim()
for dt in (torch.float32, torch.bfloat16):
    E.mem_guard(str(dt))
    m = E.tiny_model(dtype=dt)
    l1 = E.baseline_step(T, m, rows, 7424)
    g1 = E.lora_grads(m)
    m.zero_grad(set_to_none=True)
    l0 = per_row(m, rows)
    g0 = E.lora_grads(m)
    m.zero_grad(set_to_none=True)
    l2 = run_new(m, rows)
    g2 = E.lora_grads(m)
    n = str(dt).split(".")[-1]
    record("%s yardstick: baseline micro-batched vs baseline one row per forward" % n, l1, g1, l0, g0)
    record("%s: baseline micro-batched vs shared prefix" % n, l1, g1, l2, g2)
    del m, g0, g1, g2
    T.host_trim()
out["peak_rss_mb"] = E.peak_rss_mb()
json.dump(out, open(sys.argv[1], "w"), indent=1)
print("peak RSS %d MB" % out["peak_rss_mb"])
