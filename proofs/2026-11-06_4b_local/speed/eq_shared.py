"""item 1: --shared-prefix equivalence. Baseline = the trainer's current step body (micro_batches + loss_fn_batch); new =
shared_prefix_step / shared_prefix_loss. Loss and every LoRA gradient compared (fp32, LoRA dropout 0), plus a bf16 run with the
baseline's own batching noise as the yardstick."""
import json
import sys
import time
import types

import eqlib as E
import torch

T = E.load_trainer()
E.mem_guard("start")
CPU = torch.device("cpu")
rows, tok = E.real_rows(T, n_inc=5, n_chat=4)
inc = [r for r in rows if r["kind"] == "incident"]
chat = [r for r in rows if r["kind"] == "chat"]
print("rows:", [(r["kind"], len(r["ids"])) for r in rows], flush=True)
print("LCP chat %d, incident %d" % (min(T.lcp_len(chat[0]["ids"], r["ids"]) for r in chat[1:]),
                                    min(T.lcp_len(inc[0]["ids"], r["ids"]) for r in inc[1:])), flush=True)


def mk(base, tail_src, drop_prefix_labels=False, i=0):
    """a row = base row (with its labels) + the last 300 tokens of another row: the shared prefix then CONTAINS labels"""
    ids = torch.cat([base["ids"], tail_src["ids"][-300:]])
    lab = torch.cat([base["labels"], tail_src["labels"][-300:]])
    if drop_prefix_labels:
        lab = lab.clone()
        lab[:len(base["ids"])] = -100
    return {"id": "lab%d" % i, "kind": "incident", "family": "", "hard": False, "ids": ids, "labels": lab}


lab_rows = [mk(inc[0], inc[1], i=0), mk(inc[0], inc[2], i=1), mk(inc[0], chat[0], i=2), mk(inc[0], inc[3], True, i=3)]
A = types.SimpleNamespace(micro_tokens=7424, shared_prefix_min=256, shared_prefix_cont=2048)
CASES = [("chat group (4 chat rows)", chat, {}),
         ("incident group (5 incident rows)", inc, {}),
         ("mixed step (5 incident + 4 chat = 9 rows)", inc + chat, {}),
         ("mixed, small continuation batches (cont 1500)", inc + chat, {"shared_prefix_cont": 1500}),
         ("single-row group (1 chat row: falls back to baseline)", chat[:1], {}),
         ("prefix contains labels (4 rows = 1 incident row + different tails; one row with prefix labels masked)", lab_rows, {}),
         ("micro-tokens 0 (one row per forward)", inc[:3] + chat[:3], {"micro_tokens": 0})]


def run_new(m, exs, a):
    tot = 0.0
    for (l, n), e in T.shared_prefix_step(m, exs, a, CPU, lambda t: (t / 16).backward()):
        tot += float(l) / max(1, n)
    return tot


def base(m, exs, mt):
    if mt:
        return E.baseline_step(T, m, exs, mt)
    tot = 0.0
    for e in exs:
        l, n = T.loss_fn(m, e["ids"], e["labels"], CPU)
        (l / max(1, n) / 16).backward()
        tot += float(l) / max(1, n)
    return tot


out = {"rows": [(r["kind"], len(r["ids"])) for r in rows], "cases": []}


def record(name, lb, gb, ln, gn, extra=None):
    d = E.compare(gb, gn)
    d.update(case=name, loss_base=lb, loss_new=ln, loss_rel_diff=abs(ln - lb) / abs(lb))
    d.update(extra or {})
    out["cases"].append(d)
    print(json.dumps(d), flush=True)


m = E.tiny_model()
for name, exs, kw in CASES:
    E.mem_guard(name)
    a = types.SimpleNamespace(**dict(vars(A), **kw))
    cl = [(p, len(c)) for p, c in T.prefix_clusters(exs, a.shared_prefix_min)]
    m.zero_grad(set_to_none=True)
    t0 = time.time()
    lb = base(m, exs, a.micro_tokens)
    tb = time.time() - t0
    gb = E.lora_grads(m)
    m.zero_grad(set_to_none=True)
    t0 = time.time()
    ln = run_new(m, exs, a)
    tn = time.time() - t0
    record(name, lb, gb, ln, E.lora_grads(m), {"clusters_(prefix,rows)": cl, "cpu_s_base": round(tb, 1), "cpu_s_new": round(tn, 1)})

# forced split of ONE row (k = 1): prefix 3000 tokens of a chat row, continuation from its state
E.mem_guard("split")
e = chat[1]
m.zero_grad(set_to_none=True)
lb = base(m, [e], 7424)
gb = E.lora_grads(m)
m.zero_grad(set_to_none=True)
res = T.shared_prefix_loss(m, [e], 3000, CPU, 7424, lambda t: (t / 16).backward())
record("one row split at token 3000 (k = 1)", lb, gb, float(res[0][0]) / res[0][1], E.lora_grads(m))

# with the 6 GB levers inside the shared path: ckpt-offload (CPU stubs) + mlp-chunk 512, thresholds, and a --head-cpu stand-in
E.mem_guard("levers")
for name, lev, head in [("levers: offload + mlp-chunk 512 (min 0)", dict(offload_min=0, mlp_chunk_min=0), False),
                        ("levers: offload-min 3000, mlp-chunk-min 3000", dict(offload_min=3000, mlp_chunk_min=3000), False),
                        ("head-cpu stand-in (embed = row gather, CE on selected rows) + offload + mlp-chunk", dict(offload_min=0, mlp_chunk_min=0), True)]:
    ml = E.tiny_model()
    T.apply_fit_levers(ml, types.SimpleNamespace(head_cpu=False, ckpt_offload=True, mlp_chunk=512, **lev), CPU)
    if head:
        W = ml.get_base_model().model.embed_tokens.weight

        class Shim:
            def embed(self, x2d):
                return W.detach()[x2d.long()].clone().requires_grad_(torch.is_grad_enabled())

            def ce(self, hs, ys):
                return torch.nn.functional.cross_entropy((hs @ W.detach().t()).float(), ys, reduction="sum")
        T.HEAD = Shim()
    exs = inc[:4] + chat[:3]
    lb = E.baseline_step(T, ml, exs, 7424)
    gb = E.lora_grads(ml)
    ml.zero_grad(set_to_none=True)
    ln = run_new(ml, exs, A)
    record(name, lb, gb, ln, E.lora_grads(ml))
    T.HEAD, T.OFFLOAD_MIN = None, 0
    del ml
    T.host_trim()

del m
T.host_trim()
# bf16: the baseline's own batching noise (micro-batched vs one row per forward) vs shared
E.mem_guard("bf16")
mb = E.tiny_model(dtype=torch.bfloat16)
exs = inc[:4] + chat[:3]
mb.zero_grad(set_to_none=True)
l1 = base(mb, exs, 7424)
g1 = E.lora_grads(mb)
mb.zero_grad(set_to_none=True)
l0 = base(mb, exs, 0)
g0 = E.lora_grads(mb)
mb.zero_grad(set_to_none=True)
l2 = run_new(mb, exs, A)
g2 = E.lora_grads(mb)
record("bf16 yardstick: baseline micro-batched vs baseline one row per forward", l1, g1, l0, g0)
record("bf16: baseline micro-batched vs shared prefix", l1, g1, l2, g2)
out["peak_rss_mb"] = E.peak_rss_mb()
json.dump(out, open(sys.argv[1], "w"), indent=1)
print("peak RSS %d MB" % out["peak_rss_mb"])
