"""CPU equivalence harness (speed/EQUIV.md): tiny random Qwen3.5 built from the real 4B text config (both layer types), real
tokenizer, real r3 rows, LoRA r32 on the trainer's 12 targets, torch fallback kernels (fla / causal_conv1d blocked: they need a GPU).
CUDA-only bits of the trainer's offload path are stubbed for CPU (pinned pool -> plain host tensors, CUDA RNG -> no-op)."""
import importlib.util
import json
import os
import resource
import sys
import types

sys.modules["fla"] = None
sys.modules["causal_conv1d"] = None
import torch  # noqa: E402

HERE = os.path.dirname(os.path.abspath(__file__))
TRAINER = os.environ.get("TRAINER", os.path.join(HERE, "..", "..", "2026-10-29_rsn_v3", "kaggle", "train_rsn3.py"))
DATA = os.path.join(HERE, "..", "data", "final")
BASE = os.path.expanduser("~/models/qwen3.5-4b")


def mem_guard(tag=""):
    av = int([l for l in open("/proc/meminfo") if l.startswith("MemAvailable")][0].split()[1]) // 1024
    if av < 600:
        print("ABORT: MemAvailable %d MB < 600 (%s)" % (av, tag), flush=True)
        sys.exit(9)
    return av


def load_trainer():
    spec = importlib.util.spec_from_file_location("train_rsn3", TRAINER)
    T = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(T)
    # CPU stubs for the offload path (GPU code unchanged)
    T._host_buf = lambda dtype: torch.empty(T._HOST_BUF // torch.empty(0, dtype=dtype).element_size(), dtype=dtype)
    torch.cuda.get_rng_state = lambda device=None: torch.zeros(1, dtype=torch.uint8)
    torch.cuda.set_rng_state = lambda s, device=None: None
    torch.cuda.current_stream = lambda device=None: types.SimpleNamespace(synchronize=lambda: None)
    return T


ROWS = os.path.join(HERE, "rows.pt")


def vocab_size():
    return len(torch.load(ROWS)["vocab"])


def tiny_model(dtype=torch.float32, dropout=0.0, layer_types=None, seed=0, vocab=None):
    from transformers import AutoConfig
    from transformers.models.qwen3_5.modeling_qwen3_5 import Qwen3_5ForCausalLM
    from peft import LoraConfig, get_peft_model
    full = json.load(open(os.path.join(BASE, "config.json")))["text_config"]
    lt = layer_types or ["linear_attention", "full_attention", "linear_attention", "full_attention"]
    full.update(hidden_size=64, intermediate_size=128, num_hidden_layers=len(lt), layer_types=lt, num_attention_heads=4,
                num_key_value_heads=2, head_dim=32, linear_num_key_heads=2, linear_num_value_heads=4, linear_key_head_dim=16,
                linear_value_head_dim=16, mtp_num_hidden_layers=0, vocab_size=vocab or vocab_size())
    full["rope_parameters"] = dict(full["rope_parameters"], mrope_section=[2, 1, 1])     # 32 * 0.25 / 2 = 4 frequencies
    cfg = AutoConfig.for_model(**full)
    cfg._attn_implementation = "sdpa"
    torch.manual_seed(seed)
    m = Qwen3_5ForCausalLM(cfg).to(dtype)
    with torch.no_grad():                    # RMSNorm weights are zero-centred: give them some spread; A_log/dt as real
        for n, p in m.named_parameters():
            if "norm" in n:
                p.normal_(0, 0.2)
    m.gradient_checkpointing_enable(gradient_checkpointing_kwargs={"use_reentrant": False})
    m.enable_input_require_grads()
    m.config.use_cache = False
    torch.manual_seed(seed + 1)
    m = get_peft_model(m, LoraConfig(r=32, lora_alpha=64, lora_dropout=dropout, target_modules=TARGETS, bias="none",
                                     task_type="CAUSAL_LM"))
    with torch.no_grad():                    # LoRA B starts at 0: randomise so every LoRA gradient is non-trivial
        for n, p in m.named_parameters():
            if "lora_B" in n:
                p.normal_(0, 0.02)
    m.train()
    return m


TARGETS = ["q_proj", "k_proj", "v_proj", "o_proj", "gate_proj", "up_proj", "down_proj", "in_proj_qkv", "in_proj_z", "in_proj_a",
           "in_proj_b", "out_proj"]


def real_rows(T=None, n_inc=6, n_chat=6):
    """the first real r3 train rows, tokenized once by the trainer's own encode (pretok.py -> rows.pt; ids remapped to a compact
    vocabulary of the ids that occur, so the tiny model needs no 248k-row embedding)"""
    R = torch.load(ROWS)["rows"]
    inc = [r for r in R if r["kind"] == "incident"][:n_inc]
    chat = [r for r in R if r["kind"] == "chat"][:n_chat]
    return [{"id": r["id"], "kind": r["kind"], "family": "", "hard": False, "ids": r["ids"], "labels": r["labels"]}
            for r in inc + chat], None


def lora_grads(model):
    return {n: (p.grad.detach().clone() if p.grad is not None else torch.zeros_like(p)) for n, p in model.named_parameters()
            if p.requires_grad}


def compare(g0, g1):
    """max abs diff, max abs diff / max |g0| per tensor (worst tensor), global relative L2"""
    mad, mrel, num, den = 0.0, 0.0, 0.0, 0.0
    for k in g0:
        d = (g0[k].double() - g1[k].double())
        mad = max(mad, float(d.abs().max()))
        mrel = max(mrel, float(d.abs().max() / g0[k].double().abs().max().clamp_min(1e-30)))
        num += float((d ** 2).sum())
        den += float((g0[k].double() ** 2).sum())
    return {"n_tensors": len(g0), "max_abs": mad, "max_rel_per_tensor": mrel, "rel_l2": (num / max(den, 1e-300)) ** 0.5}


def baseline_step(T, model, exs, micro_tokens, accum=16):
    """the trainer's current step body (--micro-tokens branch, scaler disabled): returns the summed per-row loss"""
    tot_l = 0.0
    for mb in T.micro_batches(exs, micro_tokens):
        res = T.loss_fn_batch(model, [e["ids"] for e in mb], [e["labels"] for e in mb], torch.device("cpu"))
        (sum(l / max(1, n) for l, n in res) / accum).backward()
        tot_l += sum(float(l) / max(1, n) for l, n in res)
    return tot_l


def peak_rss_mb():
    return resource.getrusage(resource.RUSAGE_SELF).ru_maxrss // 1024
