#!/usr/bin/env python3
"""Weight-edit study for r3-2800 think-gating (owner 2026-11-13).

Decision point = chat prompt rendered with enable_thinking=True, which ends with an open "<think>\n". The model either closes
the block at once (empty think) or writes reasoning. Easy rows must never think; hard rows think per gold.

modes
  collect  forward each decision point, save last-token residual after every decoder layer (fp16) + P(close) -> <out>.npz/.jsonl
  sweep    same points, with the edit W <- (I - a u u^T) W applied to o_proj/out_proj/down_proj of chosen layers as forward
           hooks (identical maths to editing the weights: (I - a u u^T)(W x) = ((I - a u u^T) W) x); records P(close) only.
P(close) = P(</think>) + P("\n") * P(</think> | "\n")  (the template's empty block is "<think>\n\n</think>").
"""
import argparse
import json
import os
import random
import sys
import time

import numpy as np
import torch

BASE = os.path.expanduser("~/models/qwen3.5-4b")
AD = os.path.expanduser("~/smartcity_runs/KEEP_rsn3_4b_r3_s2800/ckpt_best_2800")
QIDK = "/mnt/c/Users/hp/Desktop/qidk"
TOOLS = QIDK + "/proofs/2026-11-06_4b_local/data/final/tools_r3.json"
TARGETS = ["q_proj", "k_proj", "v_proj", "o_proj", "gate_proj", "up_proj", "down_proj", "in_proj_qkv", "in_proj_z", "in_proj_a",
           "in_proj_b", "out_proj"]
WRITERS = ("o_proj", "out_proj", "down_proj")


def points(path, n_easy, n_hard, seed, easy_turn2_only=True):
    rows = [json.loads(l) for l in open(path, encoding="utf-8") if l.strip()]
    rows = [r for r in rows if "hard" in r]
    random.Random(seed).shuffle(rows)
    out, ne, nh = [], 0, 0
    for r in rows:
        if (r["hard"] and nh >= n_hard) or (not r["hard"] and ne >= n_easy):
            continue
        msgs = r["messages"]
        ai = [i for i, m in enumerate(msgs) if m["role"] == "assistant"]
        pts = []
        for t, i in enumerate(ai):
            if msgs[i - 1]["role"] not in ("user", "tool"):
                continue
            if not r["hard"] and easy_turn2_only and msgs[i - 1]["role"] != "tool":
                continue
            pts.append({"id": r["id"], "hard": bool(r["hard"]), "turn": t, "after": msgs[i - 1]["role"], "cut": i,
                        "gold_think": bool(msgs[i].get("reasoning_content")), "kind": r.get("kind") or r.get("family")})
        # test rows end with the tool message (no gold final assistant): the decision after the last tool counts too
        if msgs[-1]["role"] == "tool":
            pts.append({"id": r["id"], "hard": bool(r["hard"]), "turn": len(ai), "after": "tool", "cut": len(msgs),
                        "gold_think": None, "kind": r.get("kind") or r.get("family")})
        if not pts:
            continue
        for p in pts:
            p["_msgs"] = msgs[:p["cut"]]
        out += pts
        if r["hard"]:
            nh += 1
        else:
            ne += 1
    return out


def load():
    from transformers import AutoModelForCausalLM, AutoTokenizer, BitsAndBytesConfig
    from peft import LoraConfig, get_peft_model, set_peft_model_state_dict, get_peft_model_state_dict
    from safetensors.torch import load_file
    tok = AutoTokenizer.from_pretrained(BASE)
    ac = json.load(open(os.path.join(AD, "adapter_config.json")))
    q = BitsAndBytesConfig(load_in_4bit=True, bnb_4bit_quant_type="nf4", bnb_4bit_use_double_quant=True,
                           bnb_4bit_compute_dtype=torch.bfloat16)
    m = AutoModelForCausalLM.from_pretrained(BASE, dtype=torch.bfloat16, device_map={"": 0}, low_cpu_mem_usage=True,
                                             quantization_config=q, attn_implementation="sdpa")
    m = get_peft_model(m, LoraConfig(r=ac["r"], lora_alpha=ac["lora_alpha"], lora_dropout=0.0, target_modules=TARGETS,
                                     bias="none", task_type="CAUSAL_LM"))
    sd = load_file(os.path.join(AD, "adapter_model.safetensors"), device="cuda:0")
    set_peft_model_state_dict(m, sd)
    cur = get_peft_model_state_dict(m)
    diff = max(float((cur[k].float() - sd[k].float()).abs().max()) for k in sd)
    assert len(cur) == len(sd) and diff == 0.0, "adapter load mismatch %s %d/%d" % (diff, len(cur), len(sd))
    m.eval()
    layers = None
    for n, mod in m.named_modules():
        if n.endswith(".layers") and isinstance(mod, torch.nn.ModuleList) and len(mod) == 32 and "visual" not in n:
            layers = mod
            lname = n
    assert layers is not None
    print("loaded: adapter %d tensors exact, layers at %s" % (len(sd), lname), flush=True)
    return tok, m, layers


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--mode", choices=("collect", "sweep"), required=True)
    ap.add_argument("--data", required=True)
    ap.add_argument("--n-easy", type=int, default=300)
    ap.add_argument("--n-hard", type=int, default=300)
    ap.add_argument("--seed", type=int, default=7)
    ap.add_argument("--out", required=True)
    ap.add_argument("--dirs", default="", help="npz with u[32,2560] (unit rows) for sweep")
    ap.add_argument("--configs", default="", help="json list of {name, layers:[..], alpha}")
    ap.add_argument("--max-tok", type=int, default=12000)
    a = ap.parse_args()
    pts = points(a.data, a.n_easy, a.n_hard, a.seed)
    print("%d decision points (%d easy, %d hard)" % (len(pts), sum(not p["hard"] for p in pts), sum(p["hard"] for p in pts)),
          flush=True)
    tools = json.load(open(TOOLS, encoding="utf-8"))["chat"]
    tok, m, layers = load()
    close_id = tok.convert_tokens_to_ids("</think>")
    nl_id = tok.encode("\n", add_special_tokens=False)
    assert len(nl_id) == 1
    nl_id = nl_id[0]

    cap = {}

    def mk_cap(i):
        def h(mod, inp, out):
            o = out[0] if isinstance(out, tuple) else out
            cap[i] = o[0, -1].detach().float().cpu()
        return h

    edit = {"u": None, "alpha": 0.0}

    def proj_hook(li):
        def h(mod, inp, out):
            u = edit["u"][li]
            if u is None or edit["alpha"] == 0.0:
                return out
            u = u.to(out.dtype)
            return out - edit["alpha"] * (out @ u).unsqueeze(-1) * u
        return h

    hooks = []
    if a.mode == "collect":
        for i, L in enumerate(layers):
            hooks.append(L.register_forward_hook(mk_cap(i)))
    else:
        U = np.load(a.dirs)["u"]
        UT = [torch.tensor(U[i], device="cuda:0") for i in range(32)]
        configs = json.load(open(a.configs))
        for i, L in enumerate(layers):
            for n, mod in L.named_modules():
                if n.split(".")[-1] in WRITERS:
                    hooks.append(mod.register_forward_hook(proj_hook(i)))

    def p_close(ids):
        with torch.no_grad():
            o = m(input_ids=ids, use_cache=True, logits_to_keep=1)
            pr = torch.softmax(o.logits[0, -1].float(), -1)
            pc, pn = float(pr[close_id]), float(pr[nl_id])
            top = int(pr.argmax())
            p2 = 0.0
            if pn > 0.02:
                o2 = m(input_ids=torch.tensor([[nl_id]], device="cuda:0"), past_key_values=o.past_key_values, use_cache=True,
                       logits_to_keep=1)
                p2 = float(torch.softmax(o2.logits[0, -1].float(), -1)[close_id])
        return pc + pn * p2, top

    enc = []
    for p in pts:
        s = tok.apply_chat_template(p["_msgs"], tools=tools, tokenize=False, add_generation_prompt=True, enable_thinking=True)
        assert s.endswith("<think>\n"), s[-40:]
        ids = tok(s, add_special_tokens=False, return_tensors="pt").input_ids
        enc.append(ids if ids.shape[1] <= a.max_tok else None)

    t0 = time.time()
    if a.mode == "collect":
        H = np.zeros((len(pts), 32, 2560), np.float16)
        rec = []
        for k, (p, ids) in enumerate(zip(pts, enc)):
            if ids is None:
                rec.append(None)
                continue
            pc, top = p_close(ids.cuda())
            H[k] = torch.stack([cap[i] for i in range(32)]).numpy().astype(np.float16)
            rec.append({kk: v for kk, v in p.items() if kk != "_msgs"} | {"p_close": pc, "top": tok.decode([top]),
                                                                             "ntok": int(ids.shape[1])})
            if k % 50 == 0:
                print("collect %d/%d %.0fs" % (k, len(pts), time.time() - t0), flush=True)
        keep = [k for k, r in enumerate(rec) if r is not None]
        np.savez(a.out + ".npz", H=H[keep])
        with open(a.out + ".jsonl", "w") as f:
            for k in keep:
                f.write(json.dumps(rec[k]) + "\n")
        print("collect done: %d points, %.0fs" % (len(keep), time.time() - t0), flush=True)
    else:
        res = {}
        if os.path.exists(a.out):
            res = json.load(open(a.out))
        for c in configs:
            if c["name"] in res:
                continue
            edit["u"] = [UT[i] if i in c["layers"] else None for i in range(32)]
            edit["alpha"] = float(c["alpha"])
            row = []
            for p, ids in zip(pts, enc):
                if ids is None:
                    continue
                pc, _ = p_close(ids.cuda())
                row.append({"id": p["id"], "turn": p["turn"], "hard": p["hard"], "gold_think": p["gold_think"], "p_close": pc})
            res[c["name"]] = {"cfg": c, "rows": row}
            json.dump(res, open(a.out + ".part", "w"))
            os.replace(a.out + ".part", a.out)
            print("sweep %s done %.0fs" % (c["name"], time.time() - t0), flush=True)
    for h in hooks:
        h.remove()


if __name__ == "__main__":
    sys.exit(main())
