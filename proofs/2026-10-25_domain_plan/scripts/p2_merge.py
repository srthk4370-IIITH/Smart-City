"""P2 TIES / DARE merges in delta space (CPU), written as a PEFT LoRA RELATIVE to mixA50 (runtime --lora-scaled X:1 on
ft_mixA50_q4_0.gguf). Task vectors on base v2: tc = dW(c49) - dW(v2), tv = dW(v21) - dW(v2); dW = (alpha/r) B A per module.
  candidate = v2 + M(wc*tc, wv*tv);   relative to mixA50 (= v2 + 0.5 tc):  R = M(...) - 0.5 tc  -> rank-K factorisation.
  TIES (Yadav 2023): trim each weighted vector to its top-d magnitudes, elect sign = sign(sum), keep agreeing entries, sum.
  DARE (Yu 2024): drop entries with prob p, rescale 1/(1-p), sum (seeded).
  python p2_merge.py --method ties --density 0.2 --out DIR [--wc 0.5 --wv 0.35 --rank 128]
  python p2_merge.py --method dare --p 0.9 --out DIR"""
import argparse, json, math, time
from pathlib import Path
import torch
from safetensors import safe_open
from safetensors.torch import save_file

H = Path.home() / "smartcity_runs"
AD = {"v2": H / "agents_v2/adapter", "c49": H / "agents_v2_topup3e/run2/checkpoints/checkpoint-49",
      "v21": H / "agents_v21/run1/checkpoints/checkpoint-621"}
ap = argparse.ArgumentParser()
ap.add_argument("--method", choices=("ties", "dare"), required=True); ap.add_argument("--out", required=True)
ap.add_argument("--density", type=float, default=0.2); ap.add_argument("--p", type=float, default=0.9)
ap.add_argument("--wc", type=float, default=0.5); ap.add_argument("--wv", type=float, default=0.35)
ap.add_argument("--rank", type=int, default=128); ap.add_argument("--seed", type=int, default=0)
a = ap.parse_args()
torch.set_num_threads(4)
cfg = {k: json.loads((d / "adapter_config.json").read_text()) for k, d in AD.items()}
F = {k: safe_open(str(d / "adapter_model.safetensors"), "pt") for k, d in AD.items()}
keys = sorted(k for k in F["v2"].keys() if k.endswith("lora_A.weight"))
g = torch.Generator().manual_seed(a.seed)


def dW(name, ka):
    s = cfg[name]["lora_alpha"] / cfg[name]["r"]
    return s * (F[name].get_tensor(ka.replace("lora_A", "lora_B")).float() @ F[name].get_tensor(ka).float())


def trim(t, d):
    k = max(1, int(d * t.numel()))
    thr = t.abs().flatten().kthvalue(t.numel() - k + 1).values
    return torch.where(t.abs() >= thr, t, torch.zeros_like(t))


out, stats, t0 = {}, {"energy_kept": [], "rel_to_mixA50_norm": []}, time.time()
for i, ka in enumerate(keys):
    w2 = dW("v2", ka)
    tc, tv = dW("c49", ka) - w2, dW("v21", ka) - w2
    xs = [a.wc * tc, a.wv * tv]
    if a.method == "ties":
        xs = [trim(x, a.density) for x in xs]
        sg = torch.sign(xs[0] + xs[1])
        M = sum(torch.where(torch.sign(x) == sg, x, torch.zeros_like(x)) for x in xs)
    else:
        M = sum(x * (torch.rand(x.shape, generator=g) >= a.p).float() / (1 - a.p) for x in xs)
    R = M - 0.5 * tc
    U, S, V = torch.svd_lowrank(R, q=a.rank, niter=4)
    B, A = U * S.sqrt(), (V * S.sqrt()).T
    rn = R.norm().item()
    stats["energy_kept"].append(float((S.square().sum() / max(rn ** 2, 1e-30)).item()))
    stats["rel_to_mixA50_norm"].append(rn / max((w2 + 0.5 * tc).norm().item(), 1e-30))
    out[ka] = A.contiguous().to(torch.bfloat16)
    out[ka.replace("lora_A", "lora_B")] = B.contiguous().to(torch.bfloat16)
    if i % 40 == 0:
        print(f"  {i}/{len(keys)} {time.time() - t0:.0f}s energy {stats['energy_kept'][-1]:.3f}", flush=True)
o = Path(a.out); o.mkdir(parents=True, exist_ok=True)
save_file(out, str(o / "adapter_model.safetensors"), metadata={"format": "pt"})
c = dict(cfg["v2"]); c.update(r=a.rank, lora_alpha=a.rank)
(o / "adapter_config.json").write_text(json.dumps(c, indent=1))
for fn in ("tokenizer.json", "tokenizer_config.json", "special_tokens_map.json"):
    if (AD["v2"] / fn).exists():
        (o / fn).write_bytes((AD["v2"] / fn).read_bytes())
e = stats["energy_kept"]; r = stats["rel_to_mixA50_norm"]
man = {"args": vars(a), "adapters": {k: str(v) for k, v in AD.items()}, "modules": len(keys),
       "energy_kept_min": min(e), "energy_kept_mean": sum(e) / len(e), "rel_norm_mean": sum(r) / len(r), "seconds": round(time.time() - t0)}
(o / "p2_merge.json").write_text(json.dumps(man, indent=1))
print(f"{a.method} -> {o}: modules {len(keys)}, SVD energy kept mean {man['energy_kept_mean']:.3f} min {min(e):.3f}, |R|/|mixA50 dW| {man['rel_norm_mean']:.3f}")
