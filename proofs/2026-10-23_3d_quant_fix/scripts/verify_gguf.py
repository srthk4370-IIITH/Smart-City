"""Check an f16 GGUF (convert_hf_to_gguf.py output) against the merged HF folder on ALL tensors:
GGUF value == f16(merged bf16 value) (with llama.cpp's Q/K RoPE row permutation). Optional 2nd folder: per-tensor
relative change between two merged models (e.g. 3d vs v2) -> weight-delta stats.
  python verify_gguf.py <f16.gguf> <merged_dir> <out.json> [<other_merged_dir>]"""
import json, sys, re
import numpy as np, torch
from safetensors import safe_open
from pathlib import Path
sys.path.insert(0, str(Path.home() / "gpu_work/llama.cpp/gguf-py"))
import gguf

src, mdir, out = sys.argv[1], Path(sys.argv[2]), sys.argv[3]
other = Path(sys.argv[4]) if len(sys.argv) > 4 else None
cfg = json.loads((mdir / "config.json").read_text())
NH, NKV = cfg["num_attention_heads"], cfg["num_key_value_heads"]
MAP = {"attn_q": "self_attn.q_proj", "attn_k": "self_attn.k_proj", "attn_v": "self_attn.v_proj", "attn_output": "self_attn.o_proj",
       "ffn_gate": "mlp.gate_proj", "ffn_up": "mlp.up_proj", "ffn_down": "mlp.down_proj", "attn_norm": "input_layernorm",
       "ffn_norm": "post_attention_layernorm"}
TOP = {"token_embd.weight": "model.embed_tokens.weight", "output.weight": "lm_head.weight", "output_norm.weight": "model.norm.weight"}


class Folder:
    def __init__(self, d):
        self.map = json.loads((d / "model.safetensors.index.json").read_text())["weight_map"]
        self.h = {fn: safe_open(str(d / fn), "pt") for fn in set(self.map.values())}
    def get(self, k):
        return self.h[self.map[k]].get_tensor(k)


def permute(w, n):
    return w.reshape(n, 2, w.shape[0] // n // 2, *w.shape[1:]).swapaxes(1, 2).reshape(w.shape)


M = Folder(mdir); O = Folder(other) if other else None
r = gguf.GGUFReader(src)
res, bad, seen = {}, [], set()
for t in r.tensors:
    m = re.match(r"blk\.(\d+)\.(\w+)\.weight$", t.name)
    hf = f"model.layers.{m.group(1)}.{MAP[m.group(2)]}.weight" if m and m.group(2) in MAP else TOP.get(t.name)
    if hf is None:
        res[t.name] = {"skipped": "no HF counterpart (generated)", "type": t.tensor_type.name}; continue
    seen.add(hf)
    w = M.get(hf)
    if m and m.group(2) == "attn_q": w = permute(w, NH)
    if m and m.group(2) == "attn_k": w = permute(w, NKV)
    g = np.asarray(t.data).reshape(w.shape)
    exp = w.to(torch.float16 if g.dtype == np.float16 else torch.float32).numpy()
    eq = bool(np.array_equal(g, exp))
    e = {"type": t.tensor_type.name, "equal": eq}
    if not eq:
        d = np.abs(g.astype(np.float32) - exp.astype(np.float32)); e.update(n_diff=int((d > 0).sum()), max_abs=float(d.max())); bad.append(t.name)
    if O is not None:
        wo = O.get(hf).float(); wm = M.get(hf).float()
        e["rel_change_vs_other"] = float((wm - wo).norm() / wo.norm())
        e["frac_elems_changed_vs_other"] = float((wm != wo).float().mean())
    res[t.name] = e
missing = sorted(set(M.map) - seen)
summ = {"gguf": src, "merged": str(mdir), "n_gguf_tensors": len(r.tensors), "n_checked": sum("equal" in v for v in res.values()),
        "n_equal": sum(v.get("equal", False) for v in res.values()), "not_equal": bad, "hf_tensors_not_in_gguf": missing,
        "all_equal": not bad and not missing}
if O is not None:
    rc = [v["rel_change_vs_other"] for v in res.values() if "rel_change_vs_other" in v]
    summ["rel_change_vs_other"] = {"other": str(other), "median": float(np.median(rc)), "max": float(np.max(rc)), "mean": float(np.mean(rc))}
Path(out).write_text(json.dumps({"summary": summ, "per_tensor": res}, indent=1))
print(json.dumps(summ, indent=1))
