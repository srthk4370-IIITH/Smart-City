"""build_big.py: the data of the reasoner big top-up (2026-11-20) -> data/final_big/{train_new.jsonl (B+C+D), replay.jsonl (A), tools_v4.json,
tests/, gate/gate_set.jsonl, MANIFEST.json}.  CPU only, deterministic.
  A  no-regression replay : stratified gold rows of every existing family of final_v2 (train_new + replay), unchanged (p2 trained on them)
  B  holes                : contrastive severity quadruples (big_co2/pm/temp), benign normals, late batched criticals, severity-change rows,
                            second-evidence tool rows (related_context / get_action_history), extra fault-vs-event rows
  C  chat + tool use      : big_chat.py kinds (chat_r5), tool-critical kinds copied x3 in the pool (the trainer has no first-token weight)
  D  agent rows           : v2 path (gen_agt3) on proofs/2026-11-20_rsn_big/agent_rows/{windows,agent_out}.jsonl (real final-agent outputs)
  python3 build_big.py --stage A|B|C|D|gate|assemble|all [--seed N]"""
import argparse
import collections
import hashlib
import json
import os
import random
import re
import shutil
import sys
import time

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
import big_inc as BI  # noqa: E402
import big_chat as BC  # noqa: E402
import build_rsn as B  # noqa: E402
import v2_gen as X  # noqa: E402

G = B.G
RSN = BI.RSN
D2 = RSN + "/data/final_v2"
BIG = os.path.abspath(os.path.join(HERE, ".."))
OUT = BIG + "/data/final_big"
WK = OUT + "/work"
AG = BIG + "/agent_rows"

# sampling rates of block A per source block (train_new blocks / replay blocks); default 0.3
RATE = {"r5_replay": .35, "r5_site": .35, "r5_toolchoice": .6, "v4_agt3": .25, "v4_calm_card": .6, "v4_calm_r1": .6, "v4_calm_r4": .6, "v4_calm_real": .6,
        "v4_card": .35, "v4_contrast_card": .5, "v4_contrast_site": .5, "v4_r1": .5, "v4_r4": .3, "v4_real": .4, "v4_realflip": .5, "v4_site": .4,
        "v4_suspect_ac_multi_trip": .5, "v4_suspect_panel_trip": .5, "v4_suspect_shared_panel_occ": .5, "v4_vfcn_card": .4, "v4_vfcn_realflip": .4,
        "v4_vfcn_realmiss": 1.0, "v4_weak_topup": .3, "replay_r3_chat": .3, "replay_r3_inc": .3}
for _b in ("v4_p2_batch", "v4_p2_batch_late", "v4_p2_fault_2nd", "v4_p2_flat_alone", "v4_p2_flat_mem", "v4_p2_plateau_real", "v4_p2_step_real", "v4_p2_step_real_mem"):
    RATE[_b] = .6
CHAT_N = {k: n for k, _, n in BC.KINDS}
TOOL_PREFIX = ("find_get", "get_missing", "unknown_sensor", "followup_", "forecast", "faulty_vs_empty", "rank_linked", "cooccur", "fog")


def jl(path):
    for l in open(path, encoding="utf-8"):
        if l.strip():
            yield json.loads(l)


def wr(path, rows):
    with open(path + ".part", "w", encoding="utf-8", newline="\n") as f:
        for r in rows:
            f.write(json.dumps(r, ensure_ascii=False) + "\n")
    os.replace(path + ".part", path)
    return len(rows)


def bans_and_seen():
    bu, be, bq, _ = B.load_bans()
    ev1 = os.path.join(D2, "tests")
    for f in sorted(os.listdir(ev1)):
        for r in jl(os.path.join(ev1, f)):
            for m in r["messages"]:
                if m["role"] == "user":
                    if str(r.get("tools", "")).startswith("incident"):
                        bu.add(B.h(m["content"]))
                        be.add(B.ev_sig(m["content"]))
                        break
                    bq.add(B.h(m["content"]))
    seen, qseen = set(), set()
    for fn in ("train_new.jsonl", "replay.jsonl"):
        for r in jl(os.path.join(D2, fn)):
            seen.add(B.h(B.user_of(r)) + B.h(r["messages"][-1].get("content", "")))
            if str(r.get("tools", "")).startswith("chat"):
                qseen.add(B.h(next(m["content"] for m in reversed(r["messages"]) if m["role"] == "user")))
    return bu, be, bq, seen, qseen


# ------------------------------------------------------------------------------------------------------------------ A
def stage_A(seed):
    R = random.Random(seed + 1)
    by = collections.defaultdict(list)
    for fn in ("train_new.jsonl", "replay.jsonl"):
        for r in jl(os.path.join(D2, fn)):
            by[r.get("block", r.get("tools"))].append(r)
    rows, cnt = [], collections.Counter()
    for b, rs in sorted(by.items()):
        k = int(round(len(rs) * RATE.get(b, 0.3)))
        pick = R.sample(rs, k) if k < len(rs) else rs
        for r in pick:
            r = dict(r)
            r["big"] = "A"
            rows.append(r)
        cnt[b] = len(pick)
    R.shuffle(rows)
    print("A", wr(WK + "/A.jsonl", rows), dict(cnt))
    return cnt


# ------------------------------------------------------------------------------------------------------------------ B
def sev_change(r):
    """explain the severity change in the report when a RE-CHECK line (R1/R2) carries another severity"""
    u = r["messages"][1]["content"]
    prev = re.findall(r"^  R\d+ \d\d:\d\d (\w+):", u, re.M)
    if not prev:
        return r
    c = r["messages"][-1]["content"]
    i = c.find("{")
    try:
        rep = json.loads(c[i:])
    except Exception:
        return r
    if prev[-1] != rep["severity"]:
        add = " Severity is %s now, not %s as in R1: the newer readings decide." % (rep["severity"], prev[-1].replace("_", " "))
        if len(rep["explanation"]) + len(add) <= 300:
            rep["explanation"] += add
            r = dict(r, family=r["family"] + "+sevchange")
            r["messages"] = r["messages"][:-1] + [dict(r["messages"][-1], content=c[:i] + json.dumps(rep, ensure_ascii=False))]
    return r


def stage_B(seed):
    R = random.Random(seed + 2)
    X.install_r4()
    BI.install_big()
    bu, be, bq, seen, qseen = bans_and_seen()
    stats = collections.Counter()
    sink = B.Sink(WK + "/B.jsonl")
    bans = (bu, be)

    def fin(r, kind):
        e = G.full_check(r)
        if e:
            stats["fail:%s:%s" % (kind, e[0].split(":")[0])] += 1
            return None
        r["agent_format"] = "agt_v3" if "\n  agent data: " in r["messages"][1]["content"] else "B50"
        r.setdefault("reasoning_type", "none")
        r.setdefault("hops", 0)
        r["think"] = bool(r["messages"][-1].get("reasoning_content"))
        r["src_kind"], r["site_split"], r["big"] = kind, "train", "B"
        return r

    def fam(name, n, w):
        B.gen_block("bigB_" + name, n, R, lambda: (lambda r: r and dict(r, big="B"))(B.run_inc(R, "r4", "train", stats, fam_w=w, agt_p=0.75)), sink, stats, bans, seen)

    for nm, n in BI.NAMES.items():                                   # contrastive quadruples + benign normals
        fam(nm, n, X.weights({nm: 1}))
    import v2_gen_p2 as P2
    P2.install_p2()
    fam("p2_batch_late", 250, X.weights({"p2_batch_late": 1}))      # late batched criticals
    fam("p2_batch", 100, X.weights({"p2_batch": 1}))
    fam("p2_fault_2nd", 150, X.weights({"p2_fault_2nd": 1}))        # sensor_fault only with 2nd evidence
    fam("p2_flat_alone", 100, X.weights({"p2_flat_alone": 1}))
    fam("p2_step_real", 100, X.weights({"p2_step_real": 1}))
    fam("sev_rebalance", 600, X.weights({"worse": 1, "indep": 1, "dry_run": 1, "pump_trip": 1, "level_fault": 1, "rain_level": 1, "occ_load": 1}))

    def mk_sc():                                                     # severity-change explanation rows: RE-CHECK on every row
        agt = R.random() < 0.75
        w = X.weights({"big_co2": 1, "big_pm": 1, "big_temp": 1, "occ_load": 1, "worse": 1, "dry_run": 1, "pump_trip": 1})
        r, why = G.gen_r4(R, 0, "train", fam_w=w, refine=1.0, agt=agt)
        if r is None:
            return None
        r = sev_change(r)
        if "+sevchange" not in r["family"]:
            return None
        return fin(r, "r4")
    B.gen_block("bigB_sev_change", 400, R, mk_sc, sink, stats, bans, seen)

    def mk_tool():                                                   # second-evidence lookups (related_context / get_action_history)
        for _ in range(40):                                          # ~10 % of r1 rows carry a tool call
            r = B.run_inc(R, "r1", "train", stats)
            if r is not None and any(m.get("tool_calls") for m in r["messages"]):
                return dict(r, big="B")
        return None
    B.gen_block("bigB_tool2nd", 500, R, mk_tool, sink, stats, bans, seen)
    pend = []

    def mk_cpair():                                                  # card contrast pairs: same card, fault vs warning/critical
        if pend:
            return pend.pop()
        t = R.choice(sorted(G.CD.TRAIN_TYPES))
        agt = R.random() < 0.75
        rf = G.gen_card(R, "train", [t], agt=agt, want="fault", r_err=1.0)[0]
        rv = None
        for _ in range(6):
            rv = G.gen_card(R, "train", [t], agt=agt, want=R.choice(["warning", "critical"]), r_err=1.0)[0]
            if rv is not None:
                break
        rf, rv = (fin(rf, "card") if rf else None), (fin(rv, "card") if rv else None)
        if rf is None or rv is None:
            return None
        pend.append(rv)
        return rf
    B.gen_block("bigB_card_pair", 300, R, mk_cpair, sink, stats, bans, seen)
    sink.close()
    json.dump(dict(sorted(stats.items())), open(WK + "/stats_B.json", "w"), indent=1)
    print("B", sink.n)


# ------------------------------------------------------------------------------------------------------------------ C
def gen_chat(R, split, n_by, bq, qseen, seen_extra=None, noisy_p=0.5):
    import gen_chat_v3 as GV3
    kinds = {k: fn for k, fn, _ in BC.KINDS}
    rows, stats, key_n = [], collections.Counter(), collections.Counter()
    for k, n in n_by.items():
        got, tries = 0, 0
        while got < n and tries < n * 25:
            tries += 1
            try:
                r = kinds[k](R, split)
            except Exception as e:
                stats["exc:%s:%s" % (k, type(e).__name__)] += 1
                continue
            if r is None:
                continue
            ui = max(i for i, m in enumerate(r["messages"]) if m["role"] == "user")
            q = r["messages"][ui]["content"]
            if R.random() < noisy_p and not re.search(r"INC-\d+", q):
                q = GV3.noisy(R, q)
                r["messages"][ui] = dict(r["messages"][ui], content=q)
            e = BC.check(r)
            if e:
                stats["fail:%s:%s" % (k, e[0].split(":")[0])] += 1
                continue
            hq = B.h(q)
            if (split == "train" and (hq in bq or hq in qseen)) or (split == "gate" and (hq in qseen or hq in bq)):
                stats["dedup_q:" + k] += 1
                continue
            key = (hq, json.dumps(r["gold_calls"], sort_keys=True), json.dumps([m["content"] for m in r["messages"][1:ui] if m["role"] != "system"]))
            if key_n[key] >= 1:
                stats["dedup_dup:" + k] += 1
                continue
            key_n[key] += 1
            r["id"] = "big%s-%s-%05d" % ("C" if split == "train" else "G", r["kind"], got)
            r["block"] = "bigC_" + r["kind"] if split == "train" else "bigG_" + r["kind"]
            r["big"] = "C" if split == "train" else "gate"
            rows.append(r)
            got += 1
        stats["rows:" + k] = got
        print("chat", split, k, got, "/", n, "tries", tries, flush=True)
    return rows, stats


def stage_C(seed):
    R = random.Random(seed + 3)
    bu, be, bq, seen, qseen = bans_and_seen()
    gq = {B.h(m["content"]) for r in jl(WK + "/gate_chat.jsonl") for m in r["messages"] if m["role"] == "user"} if os.path.exists(WK + "/gate_chat.jsonl") else set()
    rows, stats = gen_chat(R, "train", CHAT_N, bq | gq, qseen)
    wr(WK + "/C.jsonl", rows)
    json.dump(dict(sorted(stats.items())), open(WK + "/stats_C.json", "w"), indent=1)
    print("C", len(rows))


# ------------------------------------------------------------------------------------------------------------------ D
def stage_D(seed):
    R = random.Random(seed + 4)
    X.install_r4()
    bu, be, bq, seen, qseen = bans_and_seen()
    wp, op = AG + "/windows.jsonl", AG + "/agent_out.jsonl"
    wins = {json.loads(l)["wid"]: json.loads(l) for l in open(wp, encoding="utf-8")}
    outs = {}
    for l in open(op, encoding="utf-8"):
        o = json.loads(l)
        outs[o["id"]] = o["text"]
    stats = collections.Counter()
    stats["agt_windows"], stats["agt_outputs"] = len(wins), len(outs)
    plan = []
    for wid in sorted(outs):
        if wid not in wins:
            continue
        w, o = wins[wid], X.parse_agent(outs[wid])
        if o is None:
            stats["agt_unparsable"] += 1
            continue
        wrong = o["status"] != w["gold"]["status"]
        stats["agt_%s:%s" % (w["src"], "wrong" if wrong else "right")] += 1
        plan += [wid] * (2 if wrong else 1)          # a wrong agent claim the report corrects teaches more: 2 rows (as v2)
    R.shuffle(plan)
    it = iter(plan)
    sink = B.Sink(WK + "/D.jsonl")

    def mk():
        wid = next(it, None)
        if wid is None:
            return None
        r, why = X.gen_agt3(R, wins[wid], outs[wid])
        if r is None:
            stats["drop:agt3:" + str(why)] += 1
            return None
        r["window_id"] = wid
        e = G.full_check(r)
        if e:
            stats["fail:agt3:" + e[0].split(":")[0]] += 1
            return None
        r["agent_format"], r["src_kind"], r["site_split"], r["big"] = "agt_v3", "agt3", "train", "D"
        r.setdefault("reasoning_type", "none")
        r.setdefault("hops", 0)
        r["think"] = bool(r["messages"][-1].get("reasoning_content"))
        return r
    B.gen_block("bigD_agt3", len(plan), R, mk, sink, stats, (bu, be), seen)
    sink.close()
    json.dump(dict(sorted(stats.items())), open(WK + "/stats_D.json", "w"), indent=1)
    print("D", sink.n, dict(stats))


# ------------------------------------------------------------------------------------------------------------------ gate
GATE_REPORT = {"test_campus_inc": 14, "dev_inc": 5, "test_real_agent": 6, "test_unseen_layout": 5, "test_unseen_metric": 5, "test_taxonomy": 5, "test_fog": 0, "dev_p2": 0}
GATE_CHAT = {"short_status": 3, "units": 2, "nocall": 2, "fmt": 3, "followup_filter": 2, "unknown_sensor": 2, "find_empty": 1}
GATE_TOOL = {"find_get": 3, "faulty_vs_empty": 3, "rank_linked": 3, "cooccur": 3, "forecast": 2, "get_missing": 2, "followup_filter": 2, "fog": 2}


def stage_gate(seed):
    R = random.Random(seed + 5)
    X.install_r4()
    BI.install_big()
    bu, be, bq, seen, qseen = bans_and_seen()
    os.makedirs(OUT + "/gate", exist_ok=True)
    rows = []
    T = D2 + "/tests/"
    for f, n in GATE_REPORT.items():                                 # 40 report rows over all existing families
        if not n:
            continue
        pool = [r for r in jl(T + f + ".jsonl") if str(r.get("tools", "")).startswith("incident") and not any(m["role"] == "tool" for m in r["messages"])]
        fm = collections.defaultdict(list)
        for r in pool:
            fm[str(r.get("family", "")).split("+")[0].split(":")[0]].append(r)
        order = sorted(fm)
        got = []
        while len(got) < n and any(fm.values()):
            for k in order:
                if fm[k] and len(got) < n:
                    got.append(fm[k].pop(R.randrange(len(fm[k]))))
        for r in got:
            rows.append(dict(r, id="gate-rep-%s-%s" % (f, r["id"]), slice="report_all", src_test=f))
    dp2 = list(jl(T + "dev_p2.jsonl"))                               # 30 new-family / severity rows: 10 dev_p2 + 20 fresh big families (test sites)
    fm = collections.defaultdict(list)
    for r in dp2:
        fm[r["p2_family"]].append(r)
    got = []
    ks = sorted(fm)
    while len(got) < 10:
        k = ks[len(got) % len(ks)]
        got.append(fm[k].pop(R.randrange(len(fm[k]))))
    for r in got:
        rows.append(dict(r, id="gate-nf-" + r["id"], slice="new_family"))
    stats = collections.Counter()
    for nm, n in (("big_co2", 6), ("big_pm", 5), ("big_temp", 5), ("big_benign", 2), ("p2_batch_late", 2)):
        k = 0
        while k < n:
            r = B.run_inc(R, "r4", "test", stats, fam_w=X.weights({nm: 1}), agt_p=0.75)
            if r is None or B.h(B.user_of(r)) in bu or B.ev_sig(B.user_of(r)) in be or (B.h(B.user_of(r)) + B.h(r["messages"][-1].get("content", ""))) in seen:
                continue
            rows.append(dict(r, id="gate-nf-%s-%03d" % (nm, k), slice="new_family", big_family=nm))
            k += 1
    ch, _ = gen_chat(R, "gate", GATE_CHAT, bq, qseen, noisy_p=0.3)  # 40 English chat rows: 15 test_campus_chat + 10 dev_chat + 15 new
    for f, n in (("test_campus_chat", 15), ("dev_chat", 10)):
        pool = [r for r in jl(T + f + ".jsonl") if not r.get("hinglish") and r.get("tools") == "chat_r5" and not any(re.search(r"[\u0900-\u097f]", m.get("content") or "") for m in r["messages"])]
        for r in R.sample(pool, n):
            rows.append(dict(r, id="gate-chat-%s-%s" % (f, r["id"]), slice="chat_en", kind="site_old"))
    for r in ch[:15]:
        rows.append(dict(r, slice="chat_en"))
    tc, _ = gen_chat(R, "gate", GATE_TOOL, bq | {B.h(m["content"]) for r in ch for m in r["messages"] if m["role"] == "user"}, qseen, noisy_p=0.2)
    for r in tc[:20]:
        rows.append(dict(r, slice="tool_chain"))
    for r in rows:
        r.pop("_ov", None)
    cnt = collections.Counter(r["slice"] for r in rows)
    wr(OUT + "/gate/gate_set.jsonl", rows)
    wr(WK + "/gate_chat.jsonl", [r for r in rows if r["slice"] in ("chat_en", "tool_chain")])
    print("gate", dict(cnt))


def stage_dev(seed):
    """dev_hole_inc.jsonl (40 rows) = the trainer's v4 incident gen slice for keep-best: 20 regression rows (dev_inc) + 20 hole rows (dev-split big families)"""
    R = random.Random(seed + 7)
    X.install_r4()
    BI.install_big()
    bu, be, bq, seen, qseen = bans_and_seen()
    reg = [r for r in jl(D2 + "/tests/dev_inc.jsonl") if str(r.get("tools", "")).startswith("incident") and not any(m["role"] == "tool" for m in r["messages"])]
    rows = R.sample(reg, 20)
    stats = collections.Counter()
    for nm, n in (("big_co2", 5), ("big_pm", 4), ("big_temp", 4), ("big_benign", 2), ("p2_fault_2nd", 2), ("p2_batch_late", 3)):
        k = 0
        while k < n:
            r = B.run_inc(R, "r4", "dev", stats, fam_w=X.weights({nm: 1}), agt_p=0.75)
            if r is None or B.h(B.user_of(r)) in bu or B.ev_sig(B.user_of(r)) in be or (B.h(B.user_of(r)) + B.h(r["messages"][-1].get("content", ""))) in seen:
                continue
            rows.append(dict(r, id="devhole-%s-%03d" % (nm, k), big_family=nm))
            k += 1
    os.makedirs(OUT + "/tests", exist_ok=True)
    print("dev", wr(OUT + "/tests/dev_hole_inc.jsonl", rows))


# ------------------------------------------------------------------------------------------------------------------ assemble
def stage_assemble(seed):
    R = random.Random(seed + 6)
    A = list(jl(WK + "/A.jsonl"))
    new = []
    for b in ("B", "C", "D"):
        p = WK + "/%s.jsonl" % b
        if not os.path.exists(p):
            print("MISSING block", b)
            continue
        rs = list(jl(p))
        if b == "C":
            extra = []
            for r in rs:
                if r["kind"].startswith(TOOL_PREFIX):
                    for j in (1, 2):                                  # x3 in the pool: the trainer has no first-token weight (agent v2 lesson: x4 + weight)
                        extra.append(dict(r, id=r["id"] + "-x%d" % j, dup_of=r["id"]))
            rs = rs + extra
        new += rs
    R.shuffle(new)
    R.shuffle(A)
    wr(OUT + "/pool_train_new.jsonl", new)
    wr(OUT + "/pool_replay.jsonl", A)

    def bal(rows, n, key):   # equal quota per key (families/blocks), leftovers redistributed: every family stays represented
        g = collections.defaultdict(list)
        for r in rows:
            g[key(r)].append(r)
        out, ks = [], sorted(g)
        while len(out) < n and any(g.values()):
            q = max(1, (n - len(out)) // max(1, sum(1 for k in ks if g[k])))
            for k in ks:
                take, g[k] = g[k][:q], g[k][q:]
                out += take
                if len(out) >= n:
                    break
        return out[:n]
    NEW_N = int(os.environ.get("SEL_NEW", 2500)); REP_N = int(os.environ.get("SEL_REP", 1500))   # owner 2026-11-20: ~4k rows seen, ~37.5 % replay
    gold = []   # existing gold fog chat rows (tools_v4 fog_* names / test_fog format; online, offline, timeout): non-empty final, a fog tool called
    for fn in ("train_new.jsonl", "replay.jsonl"):
        for r in jl(D2 + "/" + fn):
            if r.get("tools") in ("chat_r5", "chat") and (r["messages"][-1].get("content") or "").strip() and any(
                    tc["function"]["name"].startswith("fog_") for m in r["messages"] for tc in (m.get("tool_calls") or [])):
                gold.append(dict(r, id="fg-" + r["id"], kind="fog_gold", big="C", block="bigC_fog_gold", fog_gold=True))
    new = new + gold
    nd = [r for r in new if not r.get("dup_of")]
    Bs = [r for r in nd if r["big"] == "B"]; Cs = [r for r in nd if r["big"] == "C"]; Ds = [r for r in nd if r["big"] == "D"]
    Cf = [r for r in Cs if r["kind"].startswith("fog")]; Cs = [r for r in Cs if not r["kind"].startswith("fog")]
    Ct = [r for r in Cs if r["kind"].startswith(TOOL_PREFIX)]; Co = [r for r in Cs if not r["kind"].startswith(TOOL_PREFIX)]
    sel = (bal(Bs, int(NEW_N * .27), lambda r: r["block"]) + bal(Ct, int(NEW_N * .22), lambda r: r["kind"]) + bal(Cf, int(NEW_N * .14), lambda r: r["kind"])
           + bal(Co, int(NEW_N * .06), lambda r: r["kind"]) + bal(Ds, NEW_N - int(NEW_N * .69), lambda r: r.get("family", "").split(":")[-1][:12]))
    rsel = bal(A, REP_N, lambda r: r.get("block", r.get("tools")))
    R.shuffle(sel); R.shuffle(rsel)
    new, A = sel, rsel
    n_new, n_rep = wr(OUT + "/train_new.jsonl", new), wr(OUT + "/replay.jsonl", A)
    shutil.copyfile(D2 + "/tools_v4.json", OUT + "/tools_v4.json")
    os.makedirs(OUT + "/tests", exist_ok=True)
    for f in ("dev_inc.jsonl", "dev_chat.jsonl"):
        shutil.copyfile(D2 + "/tests/" + f, OUT + "/tests/" + f)
    blocks = collections.Counter((r["big"], r.get("block", r.get("tools"))) for r in new + A)
    kinds = collections.Counter(r.get("block") for r in new if r.get("dup_of"))
    man = {"train_new_rows": n_new, "replay_rows": n_rep, "by_block": {"%s:%s" % k: v for k, v in sorted(blocks.items())}, "dup_rows_in_pool": sum(kinds.values()),
           "built": time.strftime("%F %T")}
    json.dump(man, open(OUT + "/MANIFEST.json", "w"), indent=1)
    print("assemble", n_new, n_rep, collections.Counter(r["big"] for r in new + A))


if __name__ == "__main__":
    ap = argparse.ArgumentParser()
    ap.add_argument("--stage", default="all")
    ap.add_argument("--seed", type=int, default=20261120)
    a = ap.parse_args()
    os.makedirs(WK, exist_ok=True)
    for st, fn in (("A", stage_A), ("gate", stage_gate), ("dev", stage_dev), ("B", stage_B), ("C", stage_C), ("D", stage_D), ("assemble", stage_assemble)):
        if a.stage in (st, "all") or (a.stage == "nonD" and st != "D"):
            fn(a.seed)
