#!/usr/bin/env python3
"""Closed-form conditional weight edit (ROME/MEMIT style) for r3-2800 think-gating (owner 2026-11-13, attempt 2).

Why not projection (attempt 1, analysis/sweep1_score.json): W <- (I - a u u^T) W zeroes the think coordinate for EVERY
input, pulling think and close cases to the middle (easy margins fell 1.8-3.3 logits, hard thinking kept only .56-.81).

Edit here, per chosen layer L (mlp.down_proj, input = MLP key a in R^9216, output into the residual):
    targets   T: decision token after a TOOL result   -> output must move by r = -beta * s_L * u_L (toward "close")
    preserve  P: decision token after a USER message  -> output unchanged (hard first turns must keep thinking)
    general   C: key covariance over ALL tokens of the prompts -> unchanged in expectation
    dW = R_T K_T^T (K_T K_T^T + mu K_P K_P^T + lam * N_T/N_C * C)^-1          (2560 x 9216, rank <= |T|)
Applied in eval as a forward hook adding dW a to down_proj's output (identical to W' = W + dW).

modes
  collect  keys at the decision token for every point + C over all tokens of the first --cov-prompts prompts, per layer
           -> <out>_keys.pt ; also the gold-answer NLL rows list for the collateral check
  solve    dW per layer for a grid of (beta, lam) -> <out>_dw_<tag>.pt  (CPU)
  eval     p_close at decision points + teacher-forced NLL of gold assistant answers, with dW hooks -> json
"""
import argparse
import json
import os
import sys
import time

import numpy as np
import torch

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import we_think as WT  # noqa: E402


def keys_hook(store, li, want_cov):
    def h(mod, inp, out):
        a = inp[0][0].detach()                 # [T, 9216]
        store["key"][li] = a[-1].float().cpu()
        if want_cov:
            af = a.float()
            store["C"][li] += (af.T @ af).cpu() if store["C"][li].device.type == "cpu" else af.T @ af
            store["nC"][li] += af.shape[0]
    return h


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--mode", choices=("collect", "solve", "eval"), required=True)
    ap.add_argument("--data", default="")
    ap.add_argument("--n-easy", type=int, default=200)
    ap.add_argument("--n-hard", type=int, default=150)
    ap.add_argument("--seed", type=int, default=11)
    ap.add_argument("--layers", default="16,20")
    ap.add_argument("--cov-prompts", type=int, default=40)
    ap.add_argument("--out", required=True)
    ap.add_argument("--dirs", default="")
    ap.add_argument("--grid", default="", help="solve: json list of {tag, layers, beta, lam, mu}")
    ap.add_argument("--dw", default="", help="eval: comma list of dw files (one config each; 'none' = base)")
    ap.add_argument("--nll-rows", type=int, default=40)
    a = ap.parse_args()
    LAY = [int(x) for x in a.layers.split(",")]

    if a.mode == "solve":
        K = torch.load(a.out + "_keys.pt")
        U = np.load(a.dirs)["u"]
        meta = K["meta"]
        tgt = [i for i, m in enumerate(meta) if m["after"] == "tool"]
        pre = [i for i, m in enumerate(meta) if m["after"] == "user"]
        for g in json.load(open(a.grid)):
            dws = {}
            for L in g["layers"]:
                dv = "cuda:0" if torch.cuda.is_available() else "cpu"
                KT = K["keys"][L][tgt].float().T.to(dv)          # 9216 x nT
                KP = K["keys"][L][pre].float().T.to(dv)
                C = (K["C"][L] / K["nC"][L]).float().to(dv)      # mean outer product per token
                C_tr = float(C.diagonal().mean()) * g["lam"] * KT.shape[1]
                u = torch.tensor(U[L], dtype=torch.float32, device=dv)
                s = float(K["resid_norm"][L])                     # typical residual norm at L
                R = (-g["beta"] * s * u)[:, None].expand(-1, KT.shape[1])   # 2560 x nT (same push for every target)
                A = C.mul_(g["lam"] * KT.shape[1])
                A.addmm_(KT, KT.T).addmm_(KP, KP.T, alpha=g.get("mu", 1.0))
                A.diagonal().add_(g.get("ridge", 1e-2) * C_tr)        # ridge in units of the mean key power per dim
                dW = torch.linalg.solve(A, (R @ KT.T).T).T          # R KT^T A^-1  (A symmetric)
                fit_t = (dW @ KT).T @ (-u) / s                      # achieved push along -u (in units of s) per target
                fit_p = (dW @ KP).T @ (-u) / s
                dws[L] = dW.float().cpu()
                print("   rel |dW|/|W_down| ~ %.4f" % (float(dW.norm()) / 1.0), flush=True)
                print("%s L%d: |dW| %.3g, push targets mean %.3f (want %.3f), preserve mean %.4f max %.4f" % (
                    g["tag"], L, dW.norm(), fit_t.mean(), g["beta"], fit_p.mean(), fit_p.abs().max()), flush=True)
            torch.save({"cfg": g, "dW": dws}, "%s_dw_%s.pt" % (a.out, g["tag"]))
        return

    pts = WT.points(a.data, a.n_easy, a.n_hard, a.seed, easy_turn2_only=False)
    pts = [p for p in pts if p["after"] in ("tool", "user")]
    print("%d points: after tool %d, after user %d" % (len(pts), sum(p["after"] == "tool" for p in pts),
                                                         sum(p["after"] == "user" for p in pts)), flush=True)
    tools_all = json.load(open(WT.TOOLS, encoding="utf-8"))["chat"]
    tok, m, layers = WT.load()
    close_id = tok.convert_tokens_to_ids("</think>")
    nl_id = tok.encode("\n", add_special_tokens=False)[0]
    downs = {L: layers[L].mlp.down_proj for L in range(32)}

    def enc(msgs):
        s = tok.apply_chat_template(msgs, tools=tools_all, tokenize=False, add_generation_prompt=True, enable_thinking=True)
        assert s.endswith("<think>\n")
        return tok(s, add_special_tokens=False, return_tensors="pt").input_ids

    def p_close(ids):
        with torch.no_grad():
            o = m(input_ids=ids, use_cache=True, logits_to_keep=1)
            pr = torch.softmax(o.logits[0, -1].float(), -1)
            pc, pn = float(pr[close_id]), float(pr[nl_id])
            p2 = 0.0
            if pn > 0.02:
                o2 = m(input_ids=torch.tensor([[nl_id]], device="cuda:0"), past_key_values=o.past_key_values, use_cache=True,
                       logits_to_keep=1)
                p2 = float(torch.softmax(o2.logits[0, -1].float(), -1)[close_id])
        return pc + pn * p2

    t0 = time.time()
    if a.mode == "collect":
        store = {"key": {}, "C": {L: torch.zeros(9216, 9216) for L in LAY}, "nC": {L: 0 for L in LAY}}   # CPU: VRAM spill made it 27 s/point
        rn = {L: [] for L in LAY}
        res_cap = {}
        hooks = []
        cov_on = {"on": True}
        for L in LAY:
            hooks.append(downs[L].register_forward_hook(
                lambda mod, inp, out, L=L: cap_key(L, inp[0][0])))
            hooks.append(layers[L].register_forward_hook(
                lambda mod, inp, out, L=L: res_cap.__setitem__(L, float((out[0] if isinstance(out, tuple) else out)[0, -1].float().norm()))))
        def cap_key(L, x):
            store["key"][L] = x[-1].detach().float().cpu()
            if cov_on["on"]:
                xc = x.detach().float().cpu()                   # CPU accumulate (first --cov-prompts prompts only)
                store["C"][L].addmm_(xc.T, xc)
                store["nC"][L] += x.shape[0]
        keys = {L: [] for L in LAY}
        meta = []
        for k, p in enumerate(pts):
            ids = enc(p["_msgs"])
            if ids.shape[1] > 12000:
                continue
            cov_on["on"] = k < a.cov_prompts
            pc = p_close(ids.cuda())
            for L in LAY:
                keys[L].append(store["key"][L]); rn[L].append(res_cap[L])
            meta.append({kk: v for kk, v in p.items() if kk != "_msgs"} | {"p_close": pc})
            if k % 50 == 0:
                print("collect %d/%d %.0fs" % (k, len(pts), time.time() - t0), flush=True)
        torch.save({"keys": {L: torch.stack(keys[L]) for L in LAY}, "C": {L: store["C"][L] for L in LAY},
                    "nC": store["nC"], "resid_norm": {L: float(np.median(rn[L])) for L in LAY}, "meta": meta}, a.out + "_keys.pt")
        print("collect done %d points %.0fs" % (len(meta), time.time() - t0), flush=True)
        return

    # ---- eval
    nll_src = [json.loads(l) for l in open(a.data, encoding="utf-8") if l.strip()]
    nll_src = [r for r in nll_src if "hard" in r][-a.nll_rows:]          # tail rows: not used as points (points = shuffled head)
    cur = {"dW": {}}
    for L in range(32):
        downs[L].register_forward_hook(lambda mod, inp, out, L=L: out + (inp[0].float() @ cur["dW"][L].T).to(out.dtype)
                                       if L in cur["dW"] else out)
    inner = m.base_model.model.model
    head = m.base_model.model.lm_head

    def nll(r):
        msgs = r["messages"]
        full = tok.apply_chat_template(msgs, tools=tools_all, tokenize=False, enable_thinking=True)
        ids = tok(full, add_special_tokens=False, return_tensors="pt").input_ids.cuda()
        if ids.shape[1] > 9000:
            return None
        lab = torch.full_like(ids, -100)
        st = (ids[0] == tok.convert_tokens_to_ids("<|im_start|>")).nonzero().flatten().tolist()
        txt = [tok.decode(ids[0, s + 1:s + 3]) for s in st]
        for j, s in enumerate(st):
            if txt[j].startswith("assistant"):
                e = st[j + 1] if j + 1 < len(st) else ids.shape[1]
                lab[0, s + 3:e] = ids[0, s + 3:e]
        y = lab[0, 1:]
        mk = y != -100
        with torch.no_grad():
            hs = inner(input_ids=ids).last_hidden_state[0, :-1]
            lg = head(hs[mk]).float()                          # logits only at answer tokens (248k vocab)
        return float(torch.nn.functional.cross_entropy(lg, y[mk], reduction="sum")), int(mk.sum())

    res = json.load(open(a.out)) if os.path.exists(a.out) else {}
    encs = [enc(p["_msgs"]) for p in pts]
    for f in a.dw.split(","):
        tag = "base" if f == "none" else torch.load(f)["cfg"]["tag"]
        if tag in res:
            continue
        cur["dW"] = {} if f == "none" else {L: w.to("cuda:0", torch.float32) for L, w in torch.load(f)["dW"].items()}
        rows = []
        for p, ids in zip(pts, encs):
            if ids.shape[1] > 12000:
                continue
            rows.append({"id": p["id"], "turn": p["turn"], "after": p["after"], "hard": p["hard"], "gold_think": p["gold_think"],
                         "p_close": p_close(ids.cuda())})
        tl = [x for x in (nll(r) for r in nll_src) if x]
        res[tag] = {"rows": rows, "nll_per_tok": sum(x[0] for x in tl) / sum(x[1] for x in tl), "nll_tokens": sum(x[1] for x in tl)}
        json.dump(res, open(a.out + ".part", "w"))
        os.replace(a.out + ".part", a.out)
        print("eval %s nll %.4f %.0fs" % (tag, res[tag]["nll_per_tok"], time.time() - t0), flush=True)


if __name__ == "__main__":
    sys.exit(main())
