"""fit_diag.py: where does VRAM go for one QLoRA row of Qwen3.5-4B on the RTX 4050 (6 GB)?
Loads the model exactly as train_rsn3.py does (NF4 pre-quantized dir, bf16, r32 LoRA on TARGETS, AdamW8bit, non-reentrant
checkpointing), imports train_rsn3.loss_fn, and prints peak VRAM per phase + per decoder layer (recompute+backward).
usage: python fit_diag.py <len> [labels=500]   (env passes through to the trainer's levers via RSN3_* where applicable)"""
import json, os, sys, time
import torch
sys.path.insert(0, "/mnt/c/Users/hp/Desktop/qidk/proofs/2026-10-29_rsn_v3/kaggle")
import train_rsn3 as T

L = int(sys.argv[1]); NL = int(sys.argv[2]) if len(sys.argv) > 2 else 500
G = 2 ** 30
dev = torch.device("cuda", 0)
mem = lambda: round(torch.cuda.memory_allocated(dev) / G, 3)
peak = lambda: round(torch.cuda.max_memory_allocated(dev) / G, 3)
free, tot = torch.cuda.mem_get_info()
print("cuda free %.2f / %.2f GiB before load" % (free / G, tot / G))
from transformers import AutoModelForCausalLM
from peft import LoraConfig, get_peft_model
import bitsandbytes as bnb
m = AutoModelForCausalLM.from_pretrained(os.path.expanduser("~/models/qwen3.5-4b-nf4"), dtype=torch.bfloat16, device_map={"": 0}, low_cpu_mem_usage=True)
print("load", mem())
m.gradient_checkpointing_enable(gradient_checkpointing_kwargs={"use_reentrant": False})
m.enable_input_require_grads()
m.config.use_cache = False
m = get_peft_model(m, LoraConfig(r=32, lora_alpha=64, lora_dropout=0.05, target_modules=T.TARGETS, bias="none", task_type="CAUSAL_LM"))
params = [p for p in m.parameters() if p.requires_grad]
print("peft", mem(), "trainable %.1fM" % (sum(p.numel() for p in params) / 1e6))
print("attn impl", getattr(m.config, "_attn_implementation", "?"))
import argparse
lev = argparse.Namespace(head_cpu="head" in os.environ.get("LEVERS", ""), ckpt_offload="offload" in os.environ.get("LEVERS", ""),
                         mlp_chunk=int(os.environ.get("MLP_CHUNK", "0")))
if os.environ.get("CHECK"):   # numerics: original lm_head path vs streamed CE on the same hidden states
    inner0 = m.get_base_model()
    hs = (torch.randn(700, inner0.config.hidden_size, device=dev) * 2).to(torch.bfloat16).requires_grad_(True)
    ys = torch.randint(0, inner0.config.vocab_size, (700,), device=dev)
    from torch.utils.checkpoint import checkpoint   # exactly the trainer's original path (128-row checkpointed chunks)
    ce0 = lambda hc, yc: torch.nn.functional.cross_entropy(inner0.lm_head(hc).float(), yc, reduction="sum")
    ref = sum(checkpoint(ce0, hs[i:i + 128], ys[i:i + 128], use_reentrant=False) for i in range(0, 700, 128)); ref.backward()
    g0 = hs.grad.clone(); hs.grad = None
print("levers:", T.apply_fit_levers(m, lev, dev), "mem", mem())
if os.environ.get("CHECK"):
    new = T.HEAD.ce(hs, ys); new.backward()
    print("CHECK loss ref %.6f new %.6f rel %.2e | grad max|d| %.3e (max|g| %.3e) cos %.8f" % (ref.item(), new.item(), abs(ref.item() - new.item()) / ref.item(),
          (hs.grad.float() - g0.float()).abs().max().item(), g0.float().abs().max().item(),
          torch.nn.functional.cosine_similarity(hs.grad.float().flatten(), g0.float().flatten(), 0).item()))
    h32 = hs[:128].detach().float().requires_grad_(True)     # fp32 ground truth on 128 rows (W streamed in fp32 chunks)
    Wd = torch.cat(T.HEAD.pieces)
    lse = []; z = torch.cat([(h32 @ Wd[c:c + 32768].to(dev).float().t()) for c in range(0, Wd.shape[0], 32768)], 1)
    torch.nn.functional.cross_entropy(z, ys[:128], reduction="sum").backward()
    gt = h32.grad
    for nm, gg in (("orig", g0[:128]), ("stream", hs.grad[:128])):
        d = gg.float() - gt
        print("CHECK vs fp32 truth %s: rel-L2 err %.3e  max|d| %.3e" % (nm, (d.norm() / gt.norm()).item(), d.abs().max().item()))
    del hs, ys, g0, z, h32
opt = bnb.optim.AdamW8bit(params, lr=1e-4, weight_decay=0.01)
inner = m.get_base_model()
layers = inner.model.layers
calls = [0] * len(layers)
rec = {}
state = {"phase": "fwd", "last": None}


def pre(i):
    def h(mod, args, kw=None):
        if state["phase"] == "bwd":
            if state["last"] is not None:
                rec[state["last"]] = round(torch.cuda.max_memory_allocated(dev) / G, 3)
            torch.cuda.reset_peak_memory_stats(dev)
            state["last"] = i
        calls[i] += 1
    return h


for i, l in enumerate(layers):
    l.register_forward_pre_hook(pre(i))
src = torch.randint(1000, 200000, (L,), dtype=torch.int32)
lab = torch.full_like(src, -100); lab[-NL:] = src[-NL:]
m.train()
torch.cuda.reset_peak_memory_stats(dev)
t0 = time.time()
try:
    l, n = T.loss_fn(m, src, lab, dev)
    print("fwd: mem %.3f peak %.3f (activations kept %.3f)" % (mem(), peak(), mem()))
    state["phase"] = "bwd"
    torch.cuda.reset_peak_memory_stats(dev)
    (l / n).backward()
    rec[state["last"]] = peak()
    print("bwd: mem %.3f" % mem())
    torch.cuda.reset_peak_memory_stats(dev)
    opt.step(); opt.zero_grad(set_to_none=True)
    print("opt step: peak %.3f mem %.3f" % (peak(), mem()))
    print("time %.1f s, layer forward calls %s" % (time.time() - t0, sorted(set(calls))))
except Exception as e:
    print("FAIL", type(e).__name__, str(e)[:200])
    print("at layer (bwd order)", state["last"], "phase", state["phase"], "mem", mem(), "peak", peak())
types = getattr(inner.config, "layer_types", None) or ["?"] * len(layers)
print("per-layer peak during its recompute+backward (GiB):",
      json.dumps({"%d%s" % (k, types[k][0]): v for k, v in sorted(rec.items())}))
print("overall max", round(torch.cuda.max_memory_allocated(dev) / G, 3), "reserved", round(torch.cuda.max_memory_reserved(dev) / G, 3))
