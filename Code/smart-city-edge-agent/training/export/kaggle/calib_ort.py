"""Activation-range calibration for the w4a16 NPU graph without AIMET's memory overhead.

AIMET's Calibration step for this recipe is plain running min/max of every quantised activation tensor
over the calibration data (quant_scheme min_max), turned into scale/offset by
aimet_onnx.common.quantsim.calculate_delta_offset. AIMET needs >30 GB to build its QuantSim for this 3B
graph (killed on Kaggle's 30 GiB box), so this script measures the same min/max directly:

  * runs the EXACT exported graph (model_dynamic.onnx, the one compiled on AI Hub) in ONNX Runtime with
    the fp32 weights read from model.data,
  * adds ReduceMin/ReduceMax nodes on every tensor that has an activation encoding, so only scalars leave
    the session (memory stays ~15-18 GB),
  * feeds inputs exactly like on the device: 128-token prefill chunks, 4096 context, left-padded zero KV
    cache, 4-D attention mask clipped to -50 and RoPE cos/sin from qai-hub-models' LlamaPositionProcessor,
  * uses OUR agent prompts + answers (train split) as calibration data.

Output: an encodings JSON = the published w4a16 encodings with every measured activation encoding
recomputed with AIMET's formula. Param (weight) encodings are taken from GPTQ later (merge_calibrated.py).

Usage: python calib_ort.py --ckpt <dir with model_dynamic.onnx+model.data> --hf <merged hf dir>
         --texts calib_texts.jsonl --encodings <published w4a16 model.encodings> --out out.encodings
         [--budget-min 150] [--max-samples 200]
"""
import argparse, json, math, os, time
from pathlib import Path

import numpy as np
import onnx
import onnxruntime as ort
import torch
from onnx import helper
from transformers import AutoConfig, AutoTokenizer

from qai_hub_models.models.templates.llama3.model import LlamaPositionProcessor

SEQ, CTX = 128, 4096
KEEP_PUBLISHED = {"attention_mask", "position_ids_cos", "position_ids_sin"}  # fixed, data-independent


def log(*a):
    print(time.strftime("%H:%M:%S"), *a, flush=True)


def build_stat_graph(ck: Path, names: list[str]) -> Path:
    m = onnx.load(str(ck / "model_dynamic.onnx"), load_external_data=False)
    keep_outputs = [o for o in m.graph.output if o.name.startswith("past_")]
    del m.graph.output[:]
    m.graph.output.extend(keep_outputs)
    for i, n in enumerate(names):
        for op in ("ReduceMin", "ReduceMax"):
            out = f"{n}::{op[-3:].lower()}"
            m.graph.node.append(helper.make_node(op, [n], [out], keepdims=0, name=f"calib_{op}_{i}"))
            m.graph.output.append(helper.make_empty_tensor_value_info(out))
    path = ck / "_calib_stats.onnx"
    onnx.save(m, str(path))  # initialisers keep their external refs into model.data
    return path


def aimet_encoding(lo, hi, bw, sym):
    """aimet_onnx.common.quantsim.calculate_delta_offset (+ gate_min_max), scalar case."""
    lo, hi = min(float(lo), 0.0), max(float(hi), 0.0)
    if hi - lo < 1e-5:
        hi = lo + 1e-5
    steps = 2 ** bw - 1
    if sym and lo < 0:
        pos = math.floor(steps / 2)
        absmax = max(abs(lo), abs(hi))
        return absmax / pos, int(-pos - 1)
    delta = (hi - lo) / steps
    return delta, int(round(lo / delta))


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--ckpt", required=True)
    ap.add_argument("--hf", required=True)
    ap.add_argument("--texts", required=True)
    ap.add_argument("--encodings", required=True)
    ap.add_argument("--out", required=True)
    ap.add_argument("--budget-min", type=float, default=150)
    ap.add_argument("--max-samples", type=int, default=200)
    ap.add_argument("--threads", type=int, default=os.cpu_count())
    ap.add_argument("--shard", default="0/1", help="i/n: process texts[i::n] (parallel Kaggle sessions)")
    ap.add_argument("--opt", choices=["basic", "all"], default="all")
    a = ap.parse_args()
    ck = Path(a.ckpt)
    t_start = time.time()

    pub = json.load(open(a.encodings))
    acts = pub["activation_encodings"]
    g = onnx.load(str(ck / "model_dynamic.onnx"), load_external_data=False)
    produced = {o for nd in g.graph.node for o in nd.output} | {i.name for i in g.graph.input}
    names = [e["name"] for e in acts if e["name"] in produced and e["name"] not in KEEP_PUBLISHED]
    log(f"{len(acts)} activation encodings, measuring {len(names)}")
    del g
    stat_path = build_stat_graph(ck, names)

    so = ort.SessionOptions()
    so.intra_op_num_threads = a.threads
    # ENABLE_ALL lets MLAS use its fast NCHWc kernels for the 1x1 Convs; tensors we measure keep a second
    # consumer (the Reduce node) so fusions cannot remove them.
    so.graph_optimization_level = (ort.GraphOptimizationLevel.ORT_ENABLE_ALL if a.opt == "all"
                                   else ort.GraphOptimizationLevel.ORT_ENABLE_BASIC)
    log("creating ORT session ...")
    sess = ort.InferenceSession(str(stat_path), so, providers=["CPUExecutionProvider"])
    log(f"session ready ({(time.time() - t_start) / 60:.1f} min)")
    in_names = [i.name for i in sess.get_inputs()]
    out_names = [o.name for o in sess.get_outputs()]
    stat_out = [o for o in out_names if "::" in o]

    cfg = AutoConfig.from_pretrained(a.hf)
    tok = AutoTokenizer.from_pretrained(a.hf)
    pos = LlamaPositionProcessor(context_length=CTX, config=cfg)
    L = cfg.num_hidden_layers
    kvh, hd = cfg.num_key_value_heads, cfg.hidden_size // cfg.num_attention_heads

    lo = {n: math.inf for n in names}
    hi = {n: -math.inf for n in names}
    si_, sn_ = (int(x) for x in a.shard.split("/"))
    texts = [json.loads(l)["text"] for l in open(a.texts, encoding="utf-8")][: a.max_samples][si_::sn_]
    log(f"shard {a.shard}: {len(texts)} texts")
    runs = toks = 0
    for si, text in enumerate(texts):
        ids = tok("<|begin_of_text|>" + text, add_special_tokens=False)["input_ids"][: CTX - SEQ]
        kcache = [np.zeros((kvh, 1, hd, 0), np.float32) for _ in range(L)]
        vcache = [np.zeros((kvh, 1, 0, hd), np.float32) for _ in range(L)]
        for c0 in range(0, len(ids), SEQ):
            chunk = ids[c0:c0 + SEQ]
            n, cur = len(chunk), kcache[0].shape[-1]
            pad = CTX - SEQ - cur
            mask2d = torch.tensor([[0] * pad + [1] * cur + [0] * (SEQ - n) + [1] * n], dtype=torch.float32)
            pids = (torch.cumsum(mask2d, dim=1, dtype=torch.int32) - 1).clip(0, CTX - 1)[:, -SEQ:]
            m4, cos, sin = pos(mask2d, pids)
            feed = {"input_ids": np.array([[0] * (SEQ - n) + chunk], np.int32),
                    "attention_mask": m4.numpy().astype(np.float32),
                    "position_ids_cos": cos.numpy().astype(np.float32),
                    "position_ids_sin": sin.numpy().astype(np.float32)}
            for l in range(L):
                feed[f"past_key_{l}_in"] = np.concatenate([np.zeros((kvh, 1, hd, pad), np.float32), kcache[l]], axis=-1)
                feed[f"past_value_{l}_in"] = np.concatenate([np.zeros((kvh, 1, pad, hd), np.float32), vcache[l]], axis=-2)
            feed = {k: v for k, v in feed.items() if k in in_names}
            res = dict(zip(out_names, sess.run(out_names, feed)))
            for o in stat_out:
                nm, kind = o.rsplit("::", 1)
                v = float(res[o])
                if kind == "min":
                    lo[nm] = min(lo[nm], v)
                else:
                    hi[nm] = max(hi[nm], v)
            for l in range(L):
                kcache[l] = np.concatenate([kcache[l], res[f"past_key_{l}_out"][..., -n:]], axis=-1)
                vcache[l] = np.concatenate([vcache[l], res[f"past_value_{l}_out"][..., -n:, :]], axis=-2)
            runs += 1
            toks += n
        el = (time.time() - t_start) / 60
        log(f"sample {si + 1}/{len(texts)}: {len(ids)} tok | total {toks} tok, {runs} runs, {el:.1f} min")
        if el > a.budget_min:
            log("time budget reached")
            break
        if (si + 1) % 3 == 0:
            write(pub, acts, lo, hi, a.out, toks)  # checkpoint partial results

    write(pub, acts, lo, hi, a.out, toks)
    log(f"done: {toks} calibration tokens in {(time.time() - t_start) / 60:.1f} min -> {a.out}")


def write(pub, acts, lo, hi, out, toks):
    # raw running min/max (merged across shards later: min of mins, max of maxes)
    json.dump({"tokens": toks, "lo": {k: v for k, v in lo.items() if math.isfinite(v)},
               "hi": {k: v for k, v in hi.items() if math.isfinite(v)}}, open(out + ".stats.json", "w"))
    new, changed, ratios = [], 0, []
    for e in acts:
        e2 = dict(e)
        n = e["name"]
        if n in lo and math.isfinite(lo[n]) and math.isfinite(hi[n]) and e.get("dtype") == "INT":
            s, off = aimet_encoding(lo[n], hi[n], e["bw"], e.get("is_sym", False))
            old = e["scale"][0] if isinstance(e["scale"], list) else e["scale"]
            if old:
                ratios.append(s / old)
            e2["scale"] = [s] if isinstance(e["scale"], list) else s
            e2["offset"] = [off] if isinstance(e["offset"], list) else off
            changed += 1
        new.append(e2)
    o = dict(pub)
    o["activation_encodings"] = new
    o["calibration"] = {"tokens": toks, "tensors_recomputed": changed, "method": "ORT min/max, AIMET delta/offset"}
    json.dump(o, open(out, "w"))
    r = np.array(ratios) if ratios else np.array([1.0])
    log(f"  wrote {out}: {changed} encodings recomputed; new/published scale median {np.median(r):.3f} "
        f"p5 {np.percentile(r, 5):.3f} p95 {np.percentile(r, 95):.3f}")


if __name__ == "__main__":
    main()
