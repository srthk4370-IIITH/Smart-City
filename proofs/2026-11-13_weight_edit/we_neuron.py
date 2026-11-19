#!/usr/bin/env python3
"""Neuron-level weight surgery on r3-2800 (owner idea 2026-11-13: Claude reads the weights and tweaks them one by one).

Every MLP neuron i in layer L writes W_down[:, i] * a_i into the residual stream. Its direct push on a target logit
difference is  ll_i = W_down_eff[:, i] . (g * (W_U[t+] - W_U[t-]))   (logit lens through the final RMSNorm gain g; r3 LoRA folded).
Tables (analysis/neurons_*.tsv) give, per neuron: activation in each context, ll_i, and contribution = activation * ll_i.

think : decision token of chat turns; contexts T = after a tool result (gold: no think), U = after a user message with gold think.
        t+ = </think>, t- = mean of the tokens the model starts thinking with. Bad neuron: pushes toward thinking in T, not needed in U.
trust : r3-format incidents where the agent's claim is right (status == gold severity, gold != normal), and the same prompt with the
        agent's status flipped to "normal" (counterfactual). Position = the severity value with the gold title fixed. t+ = first token of
        the gold severity, t- = "normal". Bad neuron: activation shifted by the wrong claim in the direction that pushes "normal".

modes: profile (tables) | eval (tweak list -> think + trust metrics + gold-answer NLL on separate rows)
tweak list json: [{"L": 20, "i": 1234, "f": 0.0}, ...]  f scales the neuron's output (0 = ablate, 2 = double); identical to scaling
column i of down_proj (base + LoRA A[:, i]), which is how it is written into weights later.
"""
import argparse, json, os, random, re, sys, time
import numpy as np
import torch

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import we_think as WT  # noqa: E402

QD = "/mnt/c/Users/hp/Desktop/qidk/proofs"
R3INC = QD + "/2026-11-06_4b_local/data/final/incidents_train.jsonl"     # profile (r3 knows these)
R4 = QD + "/2026-11-12_topup_r4/data/final/train_new.jsonl"               # eval (unseen by r3)
AG = re.compile(r"(  agent: pattern=\S+ status=)(\S+)( cause=)(\S+)( confidence=\S+\n)((?:  - .*\n)*)")


LOWER = {"critical": "warning", "warning": "normal"}


def trust_pairs(path, n, seed, flip="normal"):
    """flip=normal: agent wrongly says normal; flip=under: agent grades one level too low (critical->warning, warning->normal)"""
    rows = []
    for l in open(path, encoding="utf-8"):
        r = json.loads(l)
        if r.get("tools") != "incident":
            continue
        a = json.loads(r["messages"][-1]["content"])
        u = r["messages"][1]["content"]
        s1 = u.split("\nS2 [")[0]
        m = AG.search(s1)
        if not m or a.get("severity") in (None, "normal") or m.group(2) != a["severity"]:
            continue
        if flip == "under" and a["severity"] not in LOWER:
            continue
        to = "normal" if flip == "normal" else LOWER[a["severity"]]
        if to == "normal":
            bad = s1[:m.start()] + m.group(1) + "normal" + m.group(3) + "normal_conditions" + m.group(5) + \
                "  - Readings within the normal range [S1.E1]\n" + s1[m.end():]
        else:
            bad = s1[:m.start()] + m.group(1) + to + s1[m.start() + len(m.group(1)) + len(m.group(2)):]
        rows.append({"id": r["id"], "sys": r["messages"][0]["content"], "good": u, "bad": u.replace(s1, bad, 1), "gold": a})
    random.Random(seed).shuffle(rows)
    return rows[:n]


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--mode", choices=("profile", "eval"), required=True)
    ap.add_argument("--out", required=True)
    ap.add_argument("--tweaks", default="", help="eval: comma list of tweak json files ('none' = base)")
    ap.add_argument("--n-think-easy", type=int, default=120); ap.add_argument("--n-think-hard", type=int, default=80)
    ap.add_argument("--n-trust", type=int, default=200); ap.add_argument("--nll-rows", type=int, default=30)
    ap.add_argument("--flip", default="normal", choices=("normal", "under"))
    ap.add_argument("--skip-think", action="store_true")
    ap.add_argument("--ev-easy", type=int, default=80); ap.add_argument("--ev-hard", type=int, default=50); ap.add_argument("--ev-trust", type=int, default=120)
    a = ap.parse_args()
    tok, m, layers = WT.load()
    tools = json.load(open(WT.TOOLS, encoding="utf-8"))
    downs = [layers[L].mlp.down_proj for L in range(32)]
    inner, head = m.base_model.model.model, m.base_model.model.lm_head
    close_id = tok.convert_tokens_to_ids("</think>")
    nl_id = tok.encode("\n", add_special_tokens=False)[0]
    cap, tw, POS = {}, {}, {"p": -1}

    def hook(L):
        def h(mod, inp):
            x = inp[0]
            cap[L] = x[0, POS["p"]].detach().float()
            if L in tw:
                x = x.clone()
                x[..., tw[L][0]] *= tw[L][1]
                return (x,)
        return h
    for L in range(32):
        downs[L].register_forward_pre_hook(hook(L))

    def chat_ids(msgs):
        s = tok.apply_chat_template(msgs, tools=tools["chat"], tokenize=False, add_generation_prompt=True, enable_thinking=True)
        return tok(s, add_special_tokens=False, return_tensors="pt").input_ids.cuda()

    def inc_ids(sys_, user, prefix):
        s = tok.apply_chat_template([{"role": "system", "content": sys_}, {"role": "user", "content": user}], tools=tools["incident"],
                                    tokenize=False, add_generation_prompt=True, enable_thinking=False) + prefix
        return tok(s, add_special_tokens=False, return_tensors="pt").input_ids.cuda()

    def logits_last(ids):
        with torch.no_grad():
            return m(input_ids=ids, logits_to_keep=1).logits[0, -1].float()

    def p_close(ids):
        with torch.no_grad():
            o = m(input_ids=ids, use_cache=True, logits_to_keep=1)
            snap = {L: cap[L].clone() for L in range(32)}        # decision-token activations (before the newline follow-up step)
            pr = torch.softmax(o.logits[0, -1].float(), -1)
            pc, pn, p2 = float(pr[close_id]), float(pr[nl_id]), 0.0
            if pn > 0.02:
                o2 = m(input_ids=torch.tensor([[nl_id]], device="cuda:0"), past_key_values=o.past_key_values, use_cache=True, logits_to_keep=1)
                p2 = float(torch.softmax(o2.logits[0, -1].float(), -1)[close_id])
        cap.update(snap)
        return pc + pn * p2, int(pr.argmax())

    def sev_lp(row, which):
        """log P(gold title + severity + label | prompt + '{"title": "'); activations at the report's first decision token"""
        g = row["gold"]
        pre = inc_ids(row["sys"], row[which], '{"title": "')
        span = '%s", "severity": "%s", "label": "%s"' % (g["title"].replace('"', '\\"'), g["severity"], g["label"])
        sp = tok(span, add_special_tokens=False, return_tensors="pt").input_ids.cuda()
        ids = torch.cat([pre, sp], 1)
        POS["p"] = pre.shape[1] - 1
        with torch.no_grad():
            hs = inner(input_ids=ids).last_hidden_state[0]
            lg = head(hs[pre.shape[1] - 1:-1]).float()
        POS["p"] = -1
        lp = float(torch.log_softmax(lg, -1).gather(1, sp[0][:, None]).sum())
        return lp, {L: cap[L].clone() for L in range(32)}

    def think_pts(seed, ne, nh):
        p = WT.points(R4, ne, nh, seed, easy_turn2_only=False)
        return [x for x in p if x["after"] in ("tool", "user")]

    t0 = time.time()
    if a.mode == "profile":
        # ---- think contexts
        pts = [] if a.skip_think else think_pts(11, a.n_think_easy, a.n_think_hard)
        sums = {"T": torch.zeros(32, 9216, device="cuda:0"), "U": torch.zeros(32, 9216, device="cuda:0")}
        cnt = {"T": 0, "U": 0}
        think_start = []
        for k, p in enumerate(pts):
            ids = chat_ids(p["_msgs"])
            if ids.shape[1] > 12000:
                continue
            pc, top = p_close(ids)
            cls = "T" if (p["after"] == "tool" and p["gold_think"] is False) else ("U" if p["gold_think"] else None)
            if cls:
                sums[cls] += torch.stack([cap[L] for L in range(32)]); cnt[cls] += 1
            if p["gold_think"] and pc < 0.5:
                think_start.append(top)
            if k % 50 == 0:
                print("think %d/%d %.0fs" % (k, len(pts), time.time() - t0), flush=True)
        # ---- trust pairs
        tp = trust_pairs(R3INC, a.n_trust, 11, a.flip)
        dsum = torch.zeros(32, 9216, device="cuda:0"); rsum = torch.zeros(32, 9216, device="cuda:0"); gaps = []; sevc = {}
        for k, row in enumerate(tp):
            lg_, ag = sev_lp(row, "good")
            lb, ab = sev_lp(row, "bad")
            gaps.append(lg_ - lb)
            dsum += torch.stack([ab[L] - ag[L] for L in range(32)]); rsum += torch.stack([ag[L] for L in range(32)])
            sevc[row["gold"]["severity"]] = sevc.get(row["gold"]["severity"], 0) + 1
            if k % 50 == 0:
                print("trust %d/%d %.0fs" % (k, len(tp), time.time() - t0), flush=True)
        # ---- logit-lens directions (final norm gain g; tied unembedding)
        g = inner.norm.weight.float()
        WU = head.weight
        ts = [t for t, _ in sorted({t: think_start.count(t) for t in set(think_start)}.items(), key=lambda kv: -kv[1])[:10]] or \
            [tok.encode("The", add_special_tokens=False)[0]]
        d_think = g * (WU[close_id].float() - WU[ts].float().mean(0))
        sev_main = max(sevc, key=sevc.get)
        d_trust = g * (WU[tok.encode(sev_main, add_special_tokens=False)[0]].float() - WU[tok.encode("normal" if a.flip == "normal" else LOWER.get(sev_main, "normal"), add_special_tokens=False)[0]].float())
        import bitsandbytes.functional as BF
        torch.set_grad_enabled(False)
        LL = {"think": torch.zeros(32, 9216), "trust": torch.zeros(32, 9216)}
        for L in range(32):
            d = downs[L]
            W0 = BF.dequantize_4bit(d.base_layer.weight.data, d.base_layer.weight.quant_state).float()   # 2560 x 9216
            A_, B_ = d.lora_A["default"].weight.float(), d.lora_B["default"].weight.float()
            Weff = W0 + d.scaling["default"] * (B_ @ A_)
            LL["think"][L] = (d_think @ Weff).detach().cpu(); LL["trust"][L] = (d_trust @ Weff).detach().cpu()
            del W0, Weff
        mT, mU = (sums["T"] / max(1, cnt["T"])).cpu(), (sums["U"] / max(1, cnt["U"])).cpu()
        dW_, mR = (dsum / max(1, len(tp))).cpu(), (rsum / max(1, len(tp))).cpu()
        np.savez(a.out + "_profile.npz", mT=mT.numpy(), mU=mU.numpy(), d_wrong=dW_.numpy(), m_right=mR.numpy(),
                 ll_think=LL["think"].numpy(), ll_trust=LL["trust"].numpy())
        summ = {"n_T": cnt["T"], "n_U": cnt["U"], "think_start_tokens": [tok.decode([t]) for t in ts], "n_trust": len(tp),
                "trust_sev_counts": sevc, "trust_gap_mean": float(np.mean(gaps)), "trust_gap_median": float(np.median(gaps)),
                "trust_main_sev": sev_main}
        # tables: think = contribution after tool (want: strongly toward think) vs in user-think context
        cT, cU = mT * LL["think"], mU * LL["think"]
        idx = torch.argsort((cT - 0.5 * cU.clamp(max=0)).flatten())[:80]       # most negative = pushes think after tool, not needed
        with open(a.out + "_think.tsv", "w") as f:
            f.write("L\ti\tact_T\tact_U\tll_close\tcontrib_T\tcontrib_U\n")
            for q in idx.tolist():
                L, i = divmod(q, 9216)
                f.write("%d\t%d\t%.3f\t%.3f\t%.4f\t%.4f\t%.4f\n" % (L, i, mT[L, i], mU[L, i], LL["think"][L, i], cT[L, i], cU[L, i]))
        cD = dW_ * LL["trust"]                                                   # change of push caused by the wrong claim
        idx = torch.argsort(cD.flatten())[:80]
        with open(a.out + "_trust.tsv", "w") as f:
            f.write("L\ti\tact_right\tdelta_wrong\tll_sev\tcontrib_delta\n")
            for q in idx.tolist():
                L, i = divmod(q, 9216)
                f.write("%d\t%d\t%.3f\t%.3f\t%.4f\t%.4f\n" % (L, i, mR[L, i], dW_[L, i], LL["trust"][L, i], cD[L, i]))
        json.dump(summ, open(a.out + "_summary.json", "w"), indent=1)
        print(json.dumps(summ), flush=True)
        return

    # ---- eval
    pts = think_pts(12, a.ev_easy, a.ev_hard)
    tp = trust_pairs(R4, a.ev_trust, 12) + trust_pairs(R4, a.ev_trust // 2, 13, "under")
    calm = []                                                         # agent-right normal incidents: must stay normal
    for l in open(R4, encoding="utf-8"):
        r = json.loads(l)
        if r.get("tools") == "incident" and json.loads(r["messages"][-1]["content"]).get("severity") == "normal":
            calm.append({"id": r["id"], "sys": r["messages"][0]["content"], "good": r["messages"][1]["content"], "gold": json.loads(r["messages"][-1]["content"])})
    random.Random(14).shuffle(calm); calm = calm[:a.ev_trust // 2]
    nll_rows = [json.loads(l) for l in open(R4, encoding="utf-8") if l.strip()][-a.nll_rows:]

    def nll(r):
        tl = tools.get(r.get("tools") or "chat") or tools["chat"]
        full = tok.apply_chat_template(r["messages"], tools=tl, tokenize=False, enable_thinking=bool(r.get("think", r.get("hard"))))
        ids = tok(full, add_special_tokens=False, return_tensors="pt").input_ids.cuda()
        if ids.shape[1] > 9000:
            return None
        st = (ids[0] == tok.convert_tokens_to_ids("<|im_start|>")).nonzero().flatten().tolist()
        lab = torch.full_like(ids, -100)
        for j, s in enumerate(st):
            if tok.decode(ids[0, s + 1:s + 2]).startswith("assistant"):
                e = st[j + 1] if j + 1 < len(st) else ids.shape[1]
                lab[0, s + 3:e] = ids[0, s + 3:e]
        y = lab[0, 1:]; mk = y != -100
        with torch.no_grad():
            hs = inner(input_ids=ids).last_hidden_state[0, :-1]
            lg = head(hs[mk]).float()
        return float(torch.nn.functional.cross_entropy(lg, y[mk], reduction="sum")), int(mk.sum())

    summ = json.load(open(os.path.expanduser("~/we_work/n1_summary.json")))
    ts = [tok.encode(t, add_special_tokens=False)[0] for t in summ["think_start_tokens"] if t.strip()]   # newline = no-think path: excluded
    gN = inner.norm.weight.float(); WUe = head.weight
    DIRS = {"close": gN * (WUe[close_id].float() - WUe[ts].float().mean(0))}
    gp = os.path.expanduser("~/we_work/dir_close_grad.npy")          # exact d log-odds(close)/d residual (grad_dir.py), cos .98 across points
    if os.path.exists(gp):
        DIRS["grad"] = torch.tensor(np.load(gp), device="cuda:0", dtype=torch.float32)
    add = {}

    def ohook(L):
        def h(mod, inp, out):
            if L not in add:
                return out
            idx, M = add[L]
            return out + (inp[0][..., idx].float() @ M).to(out.dtype)
        return h
    for L in range(32):
        downs[L].register_forward_hook(ohook(L))
    res = json.load(open(a.out)) if os.path.exists(a.out) else {}
    for f in a.tweaks.split(","):
        tag = "base" if f == "none" else os.path.basename(f).replace(".json", "")
        if tag in res:
            continue
        tw.clear(); add.clear()
        if f != "none":
            by, ad = {}, {}
            for t in json.load(open(f)):
                if "add" in t:                                  # rewire: column i += coef * dir, so act_ref * coef * |dir|^2 = gain logits
                    d = DIRS[t.get("dir", "close")]
                    ad.setdefault(t["L"], ([], [])); ad[t["L"]][0].append(t["i"])
                    ad[t["L"]][1].append(d * (t["add"] / (t["ref"] * float(d @ d))))
                    continue
                by.setdefault(t["L"], ([], []))
                by[t["L"]][0].append(t["i"]); by[t["L"]][1].append(t["f"])
            for L, (ii, ff) in by.items():
                tw[L] = (torch.tensor(ii, device="cuda:0"), torch.tensor(ff, device="cuda:0", dtype=torch.bfloat16))
            for L, (ii, vv) in ad.items():
                add[L] = (torch.tensor(ii, device="cuda:0"), torch.stack(vv))
        th = []
        for p in pts:
            ids = chat_ids(p["_msgs"])
            if ids.shape[1] > 12000:
                continue
            th.append({"id": p["id"], "turn": p["turn"], "after": p["after"], "gold_think": p["gold_think"], "p_close": p_close(ids)[0]})
        tr = [{"id": r["id"], "good": sev_lp(r, "good")[0], "bad": sev_lp(r, "bad")[0]} for r in tp]
        cl = [{"id": r["id"], "lp": sev_lp(r, "good")[0]} for r in calm]
        nl = [x for x in (nll(r) for r in nll_rows) if x]
        res[tag] = {"think": th, "trust": tr, "calm": cl, "nll_per_tok": sum(x[0] for x in nl) / sum(x[1] for x in nl)}
        json.dump(res, open(a.out + ".part", "w")); os.replace(a.out + ".part", a.out)
        print("eval %s %.0fs" % (tag, time.time() - t0), flush=True)


if __name__ == "__main__":
    sys.exit(main())
