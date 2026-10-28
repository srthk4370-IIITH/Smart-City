"""Verify a merge_lowmem.py output on ALL tensors.

mode peft:  for every decoder layer, rebuild that layer's 7 projections from the base bf16 weights, wrap them
            with the installed PEFT (PeftModel + set_peft_model_state_dict + merge_and_unload, the code path of
            post/merge_v2.py) and compare every merged tensor with the merge_lowmem output; every non-LoRA tensor
            must equal the base; lm_head must equal embed_tokens.
mode ref:   compare every tensor of merge_lowmem output A with a reference merged folder B (merge_v2.py output).
  python verify_merge.py peft <adapter_dir> <merged_lowmem_dir> <out.json>
  python verify_merge.py ref  <merged_A> <merged_B> <out.json>
"""
import json, sys, time
from pathlib import Path
import torch
from safetensors import safe_open

BASE = Path("/home/hp_srthk4370/models/llama-3.2-3b-instruct")


class Folder:
    def __init__(self, d):
        d = Path(d)
        self.map = json.loads((d / "model.safetensors.index.json").read_text())["weight_map"]
        self.h = {fn: safe_open(str(d / fn), "pt") for fn in set(self.map.values())}

    def get(self, k):
        return self.h[self.map[k]].get_tensor(k)


def cmp(a, b):
    eq = a.dtype == b.dtype and a.shape == b.shape and torch.equal(a, b)
    if eq:
        return {"equal": True}
    d = (a.float() - b.float()).abs()
    return {"equal": False, "dtype": [str(a.dtype), str(b.dtype)], "n_diff": int((d > 0).sum()), "max_abs": float(d.max()),
            "rel_fro": float(d.norm() / b.float().norm())}


def mode_ref(A, B, out):
    a, b = Folder(A), Folder(B)
    keys = sorted(set(a.map) | set(b.map))
    res, bad = {}, []
    for k in keys:
        if k not in a.map or k not in b.map:
            bad.append(k); res[k] = {"equal": False, "missing_in": "A" if k not in a.map else "B"}; continue
        r = cmp(a.get(k), b.get(k)); res[k] = r
        if not r["equal"]:
            bad.append(k)
    summ = {"mode": "ref", "A": A, "B": B, "n_tensors": len(keys), "n_equal": len(keys) - len(bad), "not_equal": bad[:50],
            "all_bit_identical": not bad}
    Path(out).write_text(json.dumps({"summary": summ, "per_tensor": res}, indent=1))
    print(json.dumps(summ, indent=1))


def mode_peft(adir, M, out):
    import torch.nn as nn
    from peft import LoraConfig, PeftModel, set_peft_model_state_dict
    import peft
    adir = Path(adir)
    cfgd = json.loads((adir / "adapter_config.json").read_text())
    cfgd["task_type"] = None
    cfgd["inference_mode"] = True
    cfg = LoraConfig(**{k: v for k, v in cfgd.items() if k in LoraConfig.__dataclass_fields__})
    lora = {}
    with safe_open(str(adir / "adapter_model.safetensors"), "pt") as f:
        for k in f.keys():
            lora[k] = f.get_tensor(k)
    base, mer = Folder(BASE), Folder(M)
    nl = 1 + max(int(k.split(".")[2]) for k in base.map if k.startswith("model.layers."))
    PROJ = {"self_attn": ["q_proj", "k_proj", "v_proj", "o_proj"], "mlp": ["gate_proj", "up_proj", "down_proj"]}
    res, bad, n_lora = {}, [], 0
    t0 = time.time()
    for i in range(nl):
        layer = nn.Module()
        for grp, projs in PROJ.items():
            g = nn.Module()
            for p in projs:
                w = base.get(f"model.layers.{i}.{grp}.{p}.weight")
                lin = nn.Linear(w.shape[1], w.shape[0], bias=False, dtype=w.dtype)
                lin.weight.data.copy_(w)
                setattr(g, p, lin)
            setattr(layer, grp, g)
        mini = nn.Module(); mini.model = nn.Module(); mini.model.layers = nn.ModuleDict({str(i): layer})
        pm = PeftModel(mini, cfg)                   # autocast_adapter_dtype=True as in from_pretrained
        sd = {k: v for k, v in lora.items() if f".layers.{i}." in k}
        r = set_peft_model_state_dict(pm, sd)
        unexpected = [k for k in r.unexpected_keys]
        assert not unexpected, unexpected[:5]
        merged = pm.merge_and_unload()
        for grp, projs in PROJ.items():
            for p in projs:
                k = f"model.layers.{i}.{grp}.{p}.weight"
                ref = getattr(getattr(merged.model.layers[str(i)], grp), p).weight.data
                c = cmp(mer.get(k), ref); c["peft_dtype"] = str(ref.dtype); res[k] = c; n_lora += 1
                if not c["equal"]:
                    bad.append(k)
        del pm, merged, mini, layer
    for k in sorted(mer.map):
        if k in res:
            continue
        ref = base.get("model.embed_tokens.weight") if k == "lm_head.weight" else base.get(k)
        c = cmp(mer.get(k), ref); res[k] = c
        if not c["equal"]:
            bad.append(k)
    missing = sorted(set(base.map) - set(mer.map))
    summ = {"mode": "peft", "peft_version": peft.__version__, "torch": torch.__version__, "adapter": str(adir), "merged": M,
            "n_tensors": len(res), "n_lora_merged_checked": n_lora, "n_adapter_pairs": sum(k.endswith("lora_A.weight") for k in lora),
            "missing_vs_base": missing, "n_equal": len(res) - len(bad), "not_equal": bad[:50], "all_bit_identical": not bad and not missing,
            "seconds": round(time.time() - t0, 1)}
    Path(out).write_text(json.dumps({"summary": summ, "per_tensor": res}, indent=1))
    print(json.dumps(summ, indent=1))


if __name__ == "__main__":
    m = sys.argv[1]
    (mode_peft if m == "peft" else mode_ref)(*sys.argv[2:5])
