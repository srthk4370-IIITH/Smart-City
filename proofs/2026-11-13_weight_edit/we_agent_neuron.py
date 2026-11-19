#!/usr/bin/env python3
"""Per-department neuron surgery for the agt_v3 domain agents (Llama-3.2-3B + snapshot LoRA). Owner 2026-11-13.

Decision point = the status value: prompt + '{"pattern": "<gold pattern>", "status": "'  (teacher-forced pattern).
A contrast spec picks two row sets from agt_v3 data and a token pair:
  calm_<role> : rows gold normal in calm families (A, must say normal)  vs rows gold warning of that role (B, must say warning);
                t+ = normal, t- = warning. Bad neuron: active in A much more than in B and pushing warning.
  over_<role> : rows gold warning of that role (A) vs gold critical (B); t+ = warning, t- = critical.
modes: profile (tables per spec) | eval (tweak list -> status accuracy at the decision point on dev rows + completion NLL)
tweaks: [{"L":..,"i":..,"f":..}] scale down_proj input feature i (== scaling column i of base + LoRA A), as we_neuron.py.
"""
import argparse, json, os, random, sys, time
import numpy as np
import torch

BASE = os.path.expanduser("~/models/llama-3.2-3b-instruct")
D = "/mnt/c/Users/hp/Desktop/qidk/proofs/2026-11-13_v3_data/agt_v3"
CALM_FAM = {"calm_routine", "hole_water", "ex_stable", "hole_power", "ex_event"}
STATUSES = ["normal", "warning", "critical", "sensor_fault"]


def rows(path, n=None):
    R = [json.loads(l) for l in open(path, encoding="utf-8")]
    return R if n is None else R[:n]


def pick(R, spec, n, seed):
    kind, role = spec.split("_", 1)
    rr = [r for r in R if role == "all" or r["role"] == role]
    if kind == "calm":
        A = [r for r in rr if r["gold"]["status"] == "normal" and r["family"] in CALM_FAM]
        B = [r for r in rr if r["gold"]["status"] == "warning"]
        tp, tm = "normal", "warning"
    else:
        A = [r for r in rr if r["gold"]["status"] == "warning"]
        B = [r for r in rr if r["gold"]["status"] == "critical"]
        tp, tm = "warning", "critical"
    rng = random.Random(seed)
    rng.shuffle(A); rng.shuffle(B)
    return A[:n], B[:n], tp, tm


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--mode", choices=("profile", "eval"), required=True)
    ap.add_argument("--adapter", required=True)
    ap.add_argument("--specs", default="calm_water,calm_power,over_power")
    ap.add_argument("--n", type=int, default=120)
    ap.add_argument("--out", required=True)
    ap.add_argument("--tweaks", default="none")
    ap.add_argument("--ev-n", type=int, default=400)
    a = ap.parse_args()
    from transformers import AutoModelForCausalLM, AutoTokenizer, BitsAndBytesConfig
    from peft import PeftModel
    tok = AutoTokenizer.from_pretrained(BASE)
    q = BitsAndBytesConfig(load_in_4bit=True, bnb_4bit_quant_type="nf4", bnb_4bit_use_double_quant=True, bnb_4bit_compute_dtype=torch.float16)
    m = AutoModelForCausalLM.from_pretrained(BASE, dtype=torch.float16, device_map={"": 0}, quantization_config=q, attn_implementation="sdpa")
    m = PeftModel.from_pretrained(m, a.adapter).eval()
    torch.set_grad_enabled(False)
    layers = m.base_model.model.model.layers
    NL = len(layers); FF = layers[0].mlp.down_proj.base_layer.in_features
    cap, tw = {}, {}

    def hook(L):
        def h(mod, inp):
            x = inp[0]
            cap[L] = x[0, -1].float()
            if L in tw:
                x = x.clone(); x[..., tw[L][0]] *= tw[L][1]
                return (x,)
        return h
    for L in range(NL):
        layers[L].mlp.down_proj.register_forward_pre_hook(hook(L))
    sid = {s: tok.encode(s, add_special_tokens=False)[0] for s in STATUSES}

    def decide(r):
        pre = r["prompt"] + '{"pattern": "%s", "status": "' % r["gold"]["pattern"]
        ids = tok(pre, add_special_tokens=False, return_tensors="pt").input_ids.cuda()
        lg = m(input_ids=ids, logits_to_keep=1).logits[0, -1].float()
        return {s: float(lg[t]) for s, t in sid.items()}

    t0 = time.time()
    if a.mode == "profile":
        R = rows(D + "/train.jsonl")
        import bitsandbytes.functional as BF
        g = m.base_model.model.model.norm.weight.float(); WU = m.base_model.model.lm_head.weight
        Weffs = []
        for L in range(NL):
            d = layers[L].mlp.down_proj
            W0 = BF.dequantize_4bit(d.base_layer.weight.data, d.base_layer.weight.quant_state).float()
            Weffs.append((W0 + d.scaling["default"] * (d.lora_B["default"].weight.float() @ d.lora_A["default"].weight.float())).cpu())   # CPU: on GPU they spilled VRAM (15 s/forward)
            del W0
        torch.cuda.empty_cache()
        summ = {}
        for spec in a.specs.split(","):
            A, B, tp, tm = pick(R, spec, a.n, 11)
            acts = {}
            for nm, S in (("A", A), ("B", B)):
                s = torch.zeros(NL, FF, device="cuda:0"); acc = 0
                for r in S:
                    lg = decide(r); s += torch.stack([cap[L] for L in range(NL)])
                    acc += max(lg, key=lg.get) == r["gold"]["status"]
                acts[nm] = (s / max(1, len(S))).cpu(); summ["%s_%s_acc" % (spec, nm)] = acc / max(1, len(S))
            dvec = g * (WU[sid[tp]].float() - WU[sid[tm]].float())
            dc = dvec.cpu(); ll = torch.stack([dc @ Weffs[L] for L in range(NL)])
            cA, cB = acts["A"] * ll, acts["B"] * ll
            idx = torch.argsort((cA - 0.5 * cB.clamp(max=0)).flatten())[:60]
            with open("%s_%s.tsv" % (a.out, spec), "w") as f:
                f.write("L\ti\tact_A\tact_B\tll\tcontrib_A\tcontrib_B\n")
                for q_ in idx.tolist():
                    L, i = divmod(q_, FF)
                    f.write("%d\t%d\t%.3f\t%.3f\t%.4f\t%.4f\t%.4f\n" % (L, i, acts["A"][L, i], acts["B"][L, i], ll[L, i], cA[L, i], cB[L, i]))
            print(spec, summ, "%.0fs" % (time.time() - t0), flush=True)
        json.dump(summ, open(a.out + "_summary.json", "w"), indent=1)
        return
    # eval: decision accuracy on dev rows per role + calm false alarms + over-grading + completion NLL
    R = rows(D + "/dev.jsonl")
    random.Random(5).shuffle(R); R = R[:a.ev_n]
    res = json.load(open(a.out)) if os.path.exists(a.out) else {}
    for f in a.tweaks.split(","):
        tag = "base" if f == "none" else os.path.basename(f).replace(".json", "")
        if tag in res:
            continue
        tw.clear()
        if f != "none":
            by = {}
            for t in json.load(open(f)):
                by.setdefault(t["L"], ([], [])); by[t["L"]][0].append(t["i"]); by[t["L"]][1].append(t["f"])
            for L, (ii, ff) in by.items():
                tw[L] = (torch.tensor(ii, device="cuda:0"), torch.tensor(ff, device="cuda:0", dtype=torch.float16))
        out, nll, nt = [], 0.0, 0
        for r in R:
            lg = decide(r); p = max(lg, key=lg.get)
            out.append({"id": r["id"], "role": r["role"], "family": r["family"], "gold": r["gold"]["status"], "pred": p})
            ids = tok(r["prompt"] + r["completion"], add_special_tokens=False, return_tensors="pt").input_ids.cuda()
            n0 = tok(r["prompt"], add_special_tokens=False, return_tensors="pt").input_ids.shape[1]
            lgs = m(input_ids=ids).logits[0, n0 - 1:-1].float()
            nll += float(torch.nn.functional.cross_entropy(lgs, ids[0, n0:], reduction="sum")); nt += ids.shape[1] - n0
        res[tag] = {"rows": out, "nll_per_tok": nll / nt}
        json.dump(res, open(a.out + ".part", "w")); os.replace(a.out + ".part", a.out)
        acc = sum(o["gold"] == o["pred"] for o in out) / len(out)
        fa = [o for o in out if o["gold"] == "normal"]
        print("eval %s acc %.3f false_alarm %.3f nll %.4f %.0fs" % (tag, acc, sum(o["pred"] != "normal" for o in fa) / max(1, len(fa)),
                                                                   nll / nt, time.time() - t0), flush=True)


if __name__ == "__main__":
    sys.exit(main())
