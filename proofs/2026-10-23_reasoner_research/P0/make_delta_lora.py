#!/usr/bin/env python3
"""Low-rank DELTA LoRA between two PEFT LoRAs that share the same base: delta = W(new) - W(old).

Both adapters here are LoRAs over base Llama-3.2-3B-Instruct (the 3d top-up starts from the v2 adapter and keeps
training the same A/B matrices), so  W_new - W_old = s*(B_new A_new - B_old A_old)  exactly, rank <= 2r.
Applied on top of the merged OLD model (v2 GGUF), this delta reproduces the merged NEW model (3d) up to the
truncation below and the base quantisation.

Per module: U = [B_new, -B_old] (out x 2r), V = [A_new; A_old] (2r x in); thin QR of U and V^T, SVD of the
2r x 2r core, keep the top --rank singular values. Writes a PEFT adapter (r=rank, lora_alpha=rank -> scale 1)
that convert_lora_to_gguf.py reads, plus delta_stats.json (energy kept per module, Frobenius norms).

usage (WSL, ~/venvs/train): python make_delta_lora.py --old ADAPTER_DIR --new ADAPTER_DIR --rank 16 --out DIR
"""
import argparse, json, os, re

import torch
from safetensors import safe_open
from safetensors.torch import save_file


def load(d):
    f = safe_open(os.path.join(d, "adapter_model.safetensors"), "pt")
    cfg = json.load(open(os.path.join(d, "adapter_config.json")))
    return {k: f.get_tensor(k) for k in f.keys()}, cfg


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--old", required=True)
    ap.add_argument("--new", required=True)
    ap.add_argument("--rank", type=int, default=16)
    ap.add_argument("--out", required=True)
    a = ap.parse_args()
    old, co = load(a.old)
    new, cn = load(a.new)
    assert set(old) == set(new), "adapters have different tensors"
    so = co["lora_alpha"] / co["r"]
    sn = cn["lora_alpha"] / cn["r"]
    assert not co.get("use_rslora") and not cn.get("use_rslora")
    mods = sorted({re.sub(r"\.lora_[AB]\.weight$", "", k) for k in old})
    out, stats = {}, {}
    tot_kept = tot_all = 0.0
    for m in mods:
        Ao, Bo = old[m + ".lora_A.weight"].double(), old[m + ".lora_B.weight"].double()
        An, Bn = new[m + ".lora_A.weight"].double(), new[m + ".lora_B.weight"].double()
        U = torch.cat([sn * Bn, -so * Bo], dim=1)          # out x 2r
        V = torch.cat([An, Ao], dim=0)                     # 2r x in
        Qu, Ru = torch.linalg.qr(U)                        # out x 2r, 2r x 2r
        Qv, Rv = torch.linalg.qr(V.T)                      # in x 2r, 2r x 2r
        Uc, S, Vch = torch.linalg.svd(Ru @ Rv.T)           # core
        k = a.rank
        sq = S[:k].sqrt()
        B = (Qu @ Uc[:, :k]) * sq                          # out x k
        A = (sq[:, None] * Vch[:k]) @ Qv.T                 # k x in
        e_all = float((S ** 2).sum())
        e_kept = float((S[:k] ** 2).sum())
        tot_all += e_all
        tot_kept += e_kept
        stats[m] = {"fro_delta": e_all ** 0.5, "energy_kept": e_kept / e_all if e_all else 1.0,
                    "fro_old_lora": float(torch.linalg.matrix_norm(so * Bo @ Ao))}
        out[m + ".lora_A.weight"] = A.float().contiguous()
        out[m + ".lora_B.weight"] = B.float().contiguous()
    os.makedirs(a.out, exist_ok=True)
    save_file(out, os.path.join(a.out, "adapter_model.safetensors"))
    cfg = dict(cn)
    cfg.update({"r": a.rank, "lora_alpha": a.rank, "lora_dropout": 0.0, "use_rslora": False, "use_dora": False})
    json.dump(cfg, open(os.path.join(a.out, "adapter_config.json"), "w"), indent=1)
    summary = {"old": a.old, "new": a.new, "rank": a.rank, "scale_old": so, "scale_new": sn, "modules": len(mods),
               "energy_kept_total": tot_kept / tot_all,
               "min_energy_kept": min(v["energy_kept"] for v in stats.values()),
               "mean_rel_delta_vs_old_lora": sum(v["fro_delta"] / v["fro_old_lora"] for v in stats.values()) / len(stats)}
    json.dump({"summary": summary, "per_module": stats}, open(os.path.join(a.out, "delta_stats.json"), "w"), indent=1)
    print(json.dumps(summary, indent=1))


if __name__ == "__main__":
    main()
