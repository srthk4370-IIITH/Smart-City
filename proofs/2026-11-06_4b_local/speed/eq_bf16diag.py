"""bf16 diagnosis: where does shared-prefix differ from the baseline in bf16? Per layer-type model: GDN-only, attention-only,
mixed; and the mixed model with the continuation attention computed in fp32 (upcast q/k/v, output back to bf16)."""
import json
import sys
import types

import eqlib as E
import torch

T = E.load_trainer()
CPU = torch.device("cpu")
rows, _ = E.real_rows(T, n_inc=2, n_chat=2)
A = types.SimpleNamespace(micro_tokens=7424, shared_prefix_min=256, shared_prefix_cont=2048)
out = []
sdpa = torch.nn.functional.scaled_dot_product_attention


def sdpa32(q, k, v, attn_mask=None, **kw):
    if attn_mask is not None and not isinstance(attn_mask, torch.Tensor):      # the continuation call (CausalBias)
        return sdpa(q.float(), k.float(), v.float(), attn_mask=attn_mask, **kw).to(q.dtype)
    return sdpa(q, k, v, attn_mask=attn_mask, **kw)


for name, lt, up in [("GDN only", ["linear_attention"] * 4, False), ("attention only (CPU fp32 upcast in the trainer)", ["full_attention"] * 4, False),
                     ("mixed GDN + attention (CPU fp32 upcast in the trainer)", None, False)]:
    E.mem_guard(name)
    m = E.tiny_model(dtype=torch.bfloat16, layer_types=lt)
    lb = E.baseline_step(T, m, rows, 7424)
    gb = E.lora_grads(m)
    m.zero_grad(set_to_none=True)
    if up:
        torch.nn.functional.scaled_dot_product_attention = sdpa32
    ln = sum(float(l) / max(1, n) for (l, n), e in T.shared_prefix_step(m, rows, A, CPU, lambda t: (t / 16).backward()))
    torch.nn.functional.scaled_dot_product_attention = sdpa
    d = E.compare(gb, E.lora_grads(m))
    d.update(case="bf16 " + name, loss_rel_diff=abs(ln - lb) / abs(lb))
    out.append(d)
    print(json.dumps(d), flush=True)
    json.dump(out, open(sys.argv[1], "w"), indent=1)
    del m
    T.host_trim()
print("peak RSS %d MB" % E.peak_rss_mb())
