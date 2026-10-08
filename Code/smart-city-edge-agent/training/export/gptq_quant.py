"""GPTQ for the device's exact weight format: per-output-channel symmetric int4 (q in [-8, 7]).

Step 0 showed the device's plain round-to-nearest int4 weights alone cost ~20 points of pattern accuracy
(94 % -> 74 % on host, activations kept in bf16). GPTQ (Frantar et al., 2022) quantises each layer
column by column and pushes every rounding error onto the not-yet-quantised columns using the inverse
Hessian of that layer's inputs, so the layer's *output* is preserved rather than each weight.

Key property used here: the output weights lie EXACTLY on the int4 grid  W' = s * q.  When AI Hub later
quantises W' with the same per-channel scale s, round(W'/s) = q, so the device reproduces these integers
bit for bit - GPTQ's accuracy carries over to the NPU unchanged.

Calibration uses OUR training prompts + answers (train split only; the test split stays held out),
because the agent prompts look nothing like generic web text.

Outputs
  <out>/qweights.safetensors   "<hf_name>.q" int8 [out, in] and "<hf_name>.s" fp32 [out] for every
                                q/k/v/o/gate/up/down projection
  <out>/merged/                HF checkpoint whose projection weights are s*q (for host evaluation)

Usage: python gptq_quant.py --merged <hf_dir> --out <dir> [--nsamples 128] [--damp 0.01]
"""
from __future__ import annotations

import argparse
import json
import math
import random
import shutil
import time
from collections import defaultdict
from pathlib import Path

import torch
from safetensors.torch import save_file
from transformers import AutoTokenizer

ROOT = Path(__file__).resolve().parents[2]
QMIN, QMAX = -8, 7
GROUPS = [["self_attn.q_proj", "self_attn.k_proj", "self_attn.v_proj"], ["self_attn.o_proj"],
          ["mlp.gate_proj", "mlp.up_proj"], ["mlp.down_proj"]]


def row_scale(w: torch.Tensor) -> torch.Tensor:
    """AIMET min_max symmetric per-channel scale for 4 bits."""
    return torch.maximum(w.max(dim=1).values / QMAX, -w.min(dim=1).values / -QMIN).clamp_min(1e-10)


@torch.no_grad()
def gptq(W: torch.Tensor, H: torch.Tensor, damp: float, block: int = 128):
    """W [out, in] fp32 on GPU, H [in, in] fp32. Returns (q int8 [out,in], s fp32 [out])."""
    W = W.clone()
    s = row_scale(W)
    cols = W.shape[1]
    dead = torch.diag(H) == 0
    H[dead, dead] = 1
    W[:, dead] = 0
    perm = torch.argsort(torch.diag(H), descending=True)          # act-order
    W, H = W[:, perm], H[perm][:, perm]
    H += damp * torch.mean(torch.diag(H)) * torch.eye(cols, device=H.device)
    Hinv = torch.linalg.cholesky(torch.cholesky_inverse(torch.linalg.cholesky(H)), upper=True)
    Q = torch.zeros_like(W, dtype=torch.int8)
    sc = s.unsqueeze(1)
    for i1 in range(0, cols, block):
        i2 = min(i1 + block, cols)
        W1 = W[:, i1:i2].clone()
        Err = torch.zeros_like(W1)
        Hi = Hinv[i1:i2, i1:i2]
        for i in range(i2 - i1):
            w = W1[:, i:i + 1]
            q = torch.clamp(torch.round(w / sc), QMIN, QMAX)
            Q[:, i1 + i] = q[:, 0].to(torch.int8)
            err = (w - q * sc) / Hi[i, i]
            W1[:, i:] -= err @ Hi[i:i + 1, i:]
            Err[:, i:i + 1] = err
        W[:, i2:] -= Err @ Hinv[i1:i2, i2:]
    inv = torch.argsort(perm)
    return Q[:, inv].contiguous(), s


def calib_samples(tok, n: int):
    rows = [json.loads(l) for l in open(ROOT / "data" / "sft" / "train.jsonl", encoding="utf-8")]
    random.Random(0).shuffle(rows)
    by = defaultdict(list)
    for r in rows:
        by[(r["role"], r.get("pattern"))].append(r)
    keys = sorted(by, key=str)
    out, i = [], 0
    while len(out) < n:                       # round-robin over (role, pattern) for coverage
        k = keys[i % len(keys)]
        if by[k]:
            r = by[k].pop()
            ids = tok(r["prompt"] + r["completion"], add_special_tokens=False, return_tensors="pt").input_ids
            out.append(ids[:, :1024])
        i += 1
    return out


class Shards:
    """Lazy tensor access to a sharded safetensors checkpoint (memory-mapped, nothing preloaded)."""
    def __init__(self, d: Path):
        from safetensors import safe_open
        self.d = d
        idx = d / "model.safetensors.index.json"
        if idx.is_file():
            self.where = json.load(open(idx))["weight_map"]
        else:
            self.where = {}
            for f in d.glob("*.safetensors"):
                with safe_open(str(f), framework="pt") as fh:
                    self.where.update({k: f.name for k in fh.keys()})
        self._open = safe_open

    def get(self, name: str) -> torch.Tensor:
        with self._open(str(self.d / self.where[name]), framework="pt") as fh:
            return fh.get_tensor(name)


def write_merged(src: Path, dst: Path, qdir: Path, chunk_bytes: int = 1 << 30):
    """HF checkpoint copy with projection weights replaced by s*q, written in ~1 GB shards."""
    from safetensors.torch import save_file
    sh = Shards(src)
    dst.mkdir(parents=True, exist_ok=True)
    for f in src.iterdir():
        if f.is_file() and not f.name.endswith(".safetensors") and f.name != "model.safetensors.index.json":
            shutil.copy(f, dst / f.name)
    qcache = {}
    def quantised(name):
        li = int(name.split(".")[2])
        if li not in qcache:
            qcache.clear()
            from safetensors import safe_open
            with safe_open(str(qdir / f"layer_{li:02d}.safetensors"), framework="pt") as fh:
                qcache[li] = {k: fh.get_tensor(k) for k in fh.keys()}
        d = qcache[li]
        return (d[name + ".q"].float() * d[name + ".s"].unsqueeze(1)).to(torch.bfloat16)
    names = sorted(sh.where)
    buf, size, n, wmap = {}, 0, 0, {}
    def flush():
        nonlocal buf, size, n
        if buf:
            fn = f"model-{n:05d}.safetensors"
            save_file(buf, str(dst / fn), metadata={"format": "pt"})
            wmap.update({k: fn for k in buf})
            buf, size, n = {}, 0, n + 1
    for k in names:
        is_proj = k.startswith("model.layers.") and k.endswith("_proj.weight")
        t = quantised(k[:-len(".weight")] + ".weight") if is_proj else sh.get(k)
        buf[k] = t.contiguous()
        size += t.numel() * t.element_size()
        if size >= chunk_bytes:
            flush()
    flush()
    json.dump({"metadata": {}, "weight_map": wmap}, open(dst / "model.safetensors.index.json", "w"))


def main():
    from transformers import AutoConfig
    from transformers.models.llama.modeling_llama import LlamaDecoderLayer, LlamaRotaryEmbedding
    ap = argparse.ArgumentParser()
    ap.add_argument("--merged", required=True)
    ap.add_argument("--out", required=True)
    ap.add_argument("--nsamples", type=int, default=128)
    ap.add_argument("--damp", type=float, default=0.01)
    ap.add_argument("--merged-only", action="store_true", help="only (re)write <out>/merged from <out>/q")
    a = ap.parse_args()
    out, src = Path(a.out), Path(a.merged)
    qdir = out / "q"
    qdir.mkdir(parents=True, exist_ok=True)
    if a.merged_only:
        write_merged(src, out / "merged", qdir)
        print("merged written", flush=True)
        return
    dev = torch.device("cuda")
    t_start = time.time()
    tok = AutoTokenizer.from_pretrained(a.merged, local_files_only=True)
    cfg = AutoConfig.from_pretrained(a.merged, local_files_only=True)
    cfg._attn_implementation = "sdpa"
    sh = Shards(src)

    samples = calib_samples(tok, a.nsamples)
    print(f"calibration: {len(samples)} samples, {sum(x.shape[1] for x in samples)} tokens (train split)", flush=True)
    emb = sh.get("model.embed_tokens.weight")
    inps = [torch.nn.functional.embedding(x, emb).to(dev, torch.float16) for x in samples]
    del emb
    pos = [torch.arange(x.shape[1], device=dev).unsqueeze(0) for x in samples]
    rotary = LlamaRotaryEmbedding(config=cfg).to(dev)

    report = []
    for li in range(cfg.num_hidden_layers):
        t0 = time.time()
        with torch.device(dev):
            layer = LlamaDecoderLayer(cfg, li).to(torch.bfloat16)
        pre = f"model.layers.{li}."
        layer.load_state_dict({k[len(pre):]: sh.get(k) for k in sh.where if k.startswith(pre)})
        layer.eval()
        mods = dict(layer.named_modules())
        qstore = {}

        def run(xs, keep=True):
            outs = []
            with torch.no_grad():
                for x, p in zip(xs, pos):
                    pe = rotary(x.to(torch.bfloat16), p)
                    y = layer(x.to(torch.bfloat16), position_ids=p, position_embeddings=pe)[0]
                    if keep:
                        outs.append(y.to(torch.float16))
            return outs

        for group in GROUPS:
            Hs = {n: None for n in group}
            cnt = {n: 0 for n in group}
            hooks = []
            for n in group:
                def hook(m, inp, _o, n=n):
                    x = inp[0].reshape(-1, inp[0].shape[-1]).float()
                    Hs[n] = x.T @ x if Hs[n] is None else Hs[n].addmm_(x.T, x)
                    cnt[n] += x.shape[0]
                hooks.append(mods[n].register_forward_hook(hook))
            run(inps, keep=False)
            for h in hooks:
                h.remove()
            for n in group:
                m = mods[n]
                W = m.weight.data.float()
                H = Hs[n].mul_(2.0 / cnt[n])
                s_rtn = row_scale(W)
                Wr = torch.clamp(torch.round(W / s_rtn.unsqueeze(1)), QMIN, QMAX) * s_rtn.unsqueeze(1)
                e_rtn = float(torch.trace((W - Wr) @ H @ (W - Wr).T))
                del Wr
                q, s_ = gptq(W, H, a.damp)
                Wq = q.float() * s_.unsqueeze(1)
                m.weight.data = Wq.to(m.weight.dtype)
                name = f"model.layers.{li}.{n}.weight"
                qstore[name + ".q"] = q.cpu()
                qstore[name + ".s"] = s_.float().cpu()
                report.append({"layer": li, "module": n, "rtn": e_rtn})
                del W, Wq, H
            Hs.clear()
            torch.cuda.empty_cache()
        inps = run(inps)
        save_file(qstore, str(qdir / f"layer_{li:02d}.safetensors"))
        del layer, mods, qstore
        torch.cuda.empty_cache()
        print(f"layer {li:2d} quantised in {time.time() - t0:5.1f}s", flush=True)

    json.dump(report, open(out / "gptq_report.json", "w"))
    print(f"GPTQ done in {(time.time() - t_start) / 60:.1f} min; writing merged checkpoint ...", flush=True)
    write_merged(src, out / "merged", qdir)
    print(f"saved {out / 'merged'}", flush=True)


if __name__ == "__main__":
    main()
