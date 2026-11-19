"""Build rsn fine-tune dataset v2 = APPROVED v1 (data/final, unchanged rows) + v2 additions -> data/final_v2/.
  python3 build_v2.py [--seed 11115]     (needs data/final_v2/work/{windows,agent_out}.jsonl from v2_stage1.sh)
Additions (v2_gen.py): agt_v3 real outputs (v4_agt3), weak reasoning types (v4_weak_*), suspect parent (v4_suspect),
cross-floor flow + negative controls (v4_xfloor), fault vs real event contrasts (v4_contrast_*), chat tool choice
(r5_toolchoice: co_occurring_incidents / fog_search_history r4 rows in the r5 header), more r3-format replay (replay ~1 pass
at --mix 0.75). Same gen-time verification (full_check / check_chat) and dedup as v1, plus bans on every v1 test/dev row and
on all v1 train/replay rows. CPU only, deterministic."""
import argparse
import collections
import json
import os
import random
import re
import shutil
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
import build_rsn as B  # noqa: E402
import v2_gen as X  # noqa: E402
import fmt_v4 as FM  # noqa: E402
G = B.G
V1 = os.path.join(HERE, "data", "final")
OUT = os.environ.get("V2_OUT") or os.path.join(HERE, "data", "final_v2")
WORK = os.path.join(OUT, "work")
TOOLCHOICE = {"co_occurring_incidents", "fog_search_history"}


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--seed", type=int, default=11115)
    ap.add_argument("--scale", type=float, default=1.0)
    ap.add_argument("--replay-total", type=int, default=4000 if os.environ.get("P2_FAMILIES") != "1" else 4600)
    a = ap.parse_args()
    S = lambda n: max(1, int(round(n * a.scale)))  # noqa: E731
    X.install_r4()
    stats = collections.Counter()
    bu, be, bq, pool_ban = B.load_bans()
    # bans: every v1 test/dev row
    for f in sorted(os.listdir(os.path.join(V1, "tests"))):
        for l in open(os.path.join(V1, "tests", f), encoding="utf-8"):
            r = json.loads(l)
            for m in r["messages"]:
                if m["role"] == "user":
                    if r.get("tools", "").startswith("incident"):
                        bu.add(B.h(m["content"]))
                        be.add(B.ev_sig(m["content"]))
                    else:
                        bq.add(B.h(m["content"]))
                    if r.get("tools", "").startswith("incident"):
                        break
    seen = set()
    v1ids = set()
    for fn in ("train_new.jsonl", "replay.jsonl"):
        for l in open(os.path.join(V1, fn), encoding="utf-8"):
            r = json.loads(l)
            seen.add(B.h(B.user_of(r)) + B.h(r["messages"][-1].get("content", "")))
            if fn == "replay.jsonl":
                v1ids.add(r.get("id"))
    stats["bans_prompts"], stats["bans_evsig"], stats["bans_questions"], stats["v1_rows_seen"] = len(bu), len(be), len(bq), len(seen)
    os.makedirs(os.path.join(OUT, "tests"), exist_ok=True)
    tmp = os.path.join(WORK, "train_add.jsonl")
    sink = B.Sink(tmp)
    R = random.Random(a.seed)
    bans = (bu, be)

    def fin(r, kind):
        if r is None:
            return None
        e = G.full_check(r)
        if e:
            for x in sorted(set(z.split(":")[0] for z in e)):
                stats["fail:%s:%s" % (kind, x)] += 1
            return None
        r["agent_format"] = "agt_v3" if "\n  agent data: " in r["messages"][1]["content"] else "B50"
        r.setdefault("reasoning_type", "none")
        r.setdefault("hops", 0)
        r["think"] = bool(r["messages"][-1].get("reasoning_content"))
        r["src_kind"], r["site_split"], r["v2_add"] = kind, "train", "2026-11-15"
        return r

    def until(fn, cond, cap=200):
        def f():
            for _ in range(cap):
                r = fn()
                if r is not None and cond(r):
                    return r
            stats["cap_hit"] += 1
            return None
        return f

    # ---------------------------------------------------------------- 1. agt_v3 real outputs
    wins = {json.loads(l)["wid"]: json.loads(l) for l in open(os.path.join(WORK, "windows.jsonl"), encoding="utf-8")}
    outs = {}
    for l in open(os.path.join(WORK, "agent_out.jsonl"), encoding="utf-8"):
        o = json.loads(l)
        outs[o["id"]] = o["text"]
    stats["agt_windows"], stats["agt_outputs"] = len(wins), len(outs)
    plan = []
    for wid in sorted(outs):
        w = wins[wid]
        o = X.parse_agent(outs[wid])
        if o is None:
            stats["agt_unparsable"] += 1
            continue
        wrong = o["status"] != w["gold"]["status"]
        stats["agt_%s:%s" % (w["src"], "wrong" if wrong else "right")] += 1
        if wrong:
            stats["agt_err:%s->%s" % (w["gold"]["status"], o["status"])] += 1
        plan += [wid] * (2 if wrong else 1)
    R.shuffle(plan)
    it = iter(plan)

    def mk_agt():
        wid = next(it, None)
        if wid is None:
            return None
        r, why = X.gen_agt3(R, wins[wid], outs[wid])
        if r is None:
            stats["drop:agt3:" + str(why)] += 1
            return None
        r["window_id"] = wid
        return fin(r, "agt3")
    B.gen_block("v4_agt3", len(plan), R, mk_agt, sink, stats, bans, seen)

    # ---------------------------------------------------------------- 2. weak reasoning types + suspect parent
    weak = [("v4_weak_multihop2", {"heat_feeder2": 1}, "multihop", 2, 150), ("v4_weak_multihop3", {"heat_multihop": 1, "pf_chain": 1}, "multihop", 3, 150),
            ("v4_weak_multihop4", {"pf_chain4": 1}, "multihop", 4, 150), ("v4_weak_chain_max", {"occ_load": 1}, "chain_max", None, 250),
            ("v4_weak_transitive", {"heat_trans": 1}, "transitive", None, 250), ("v4_weak_three_way", {"heat_three": 1, "occ_load": 1}, "three_way", None, 250),
            ("v4_weak_pair_who", {"pm_ingress": 1, "pump_trip": 1, "leak": 1, "level_fault": 1}, "pair_who", None, 300)]
    for name, fw, rt, hops, n in weak:
        w = X.weights(fw)
        B.gen_block(name, S(n), R, until(lambda w=w: B.run_inc(R, "r4", "train", stats, fam_w=w, agt_p=0.75),
                                         lambda r, rt=rt, hops=hops: r["reasoning_type"] == rt and (hops is None or r["hops"] == hops)),
                    sink, stats, bans, seen)
    for kind in ("panel_trip", "shared_panel_occ", "ac_multi_trip"):
        B.gen_block("v4_suspect_" + kind, S(100), R,
                    lambda kind=kind: fin(G.gen_site_fam(R, "train", kind, agt=R.random() < 0.75)[0], "site"), sink, stats, bans, seen)

    # ---------------------------------------------------------------- 3. cross-floor flow
    for kind, n in (("water", 150), ("heat", 130), ("smoke", 130), ("neg_water", 90), ("neg_heat", 80), ("neg_smoke", 70)):
        def mk_x(kind=kind):
            r, why = X.gen_xfloor(R, "train", kind, agt=R.random() < 0.75)
            if r is None:
                stats["drop:xfloor:%s:%s" % (kind, why)] += 1
                return None
            return fin(r, "xfloor")
        B.gen_block("v4_xfloor_" + kind, S(n), R, mk_x, sink, stats, bans, seen)

    # ---------------------------------------------------------------- 4a. fault vs real event contrasts
    cw = X.weights({"pm_fault": 1, "pm_ingress": 1, "wx_fault": 1, "wx_fault_co2": 1, "heat_trans": 1, "level_fault": 1, "leak": 1,
                    "occ_fault": 1, "occ_load": 1})
    B.gen_block("v4_contrast_site", S(300), R, lambda: B.run_inc(R, "r4", "train", stats, fam_w=cw), sink, stats, bans, seen)
    pend = []

    def mk_cpair():
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
        rf, rv = fin(rf, "card"), fin(rv, "card")
        if rf is None or rv is None:
            stats["drop:contrast_card_pair"] += 1
            return None
        pid = "cpair-%06d" % R.randrange(10 ** 6)
        rf["pair_id"] = rv["pair_id"] = pid
        pend.append(rv)
        return rf
    B.gen_block("v4_contrast_card", S(200), R, mk_cpair, sink, stats, bans, seen)

    # ---------------------------------------------------------------- top-up to >= 12,100 train_new rows (cheap weak-type incidents)
    n_tc = S(300)
    need = int(round(12100 * a.scale)) - (6133 if a.scale == 1.0 else 0) - sink.n - n_tc
    if need > 0:
        tw = X.weights({"pm_ingress": 1, "pump_trip": 1, "leak": 1, "level_fault": 1, "heat_three": 1, "heat_trans": 1, "heat_feeder2": 1, "pf_chain4": 1})
        B.gen_block("v4_weak_topup", need, R, lambda: B.run_inc(R, "r4", "train", stats, fam_w=tw), sink, stats, bans, seen)

    # ---------------------------------------------------------------- 4a2. reasoner part 2 families (owner plan 2026-11-18; env P2_FAMILIES=1)
    if os.environ.get("P2_FAMILIES") == "1":
        import v2_gen_p2 as P2
        P2.install_p2()
        for nm, n in P2.P2_NAMES.items():
            wp = X.weights({nm: 1})
            B.gen_block("v4_p2_" + nm[3:], S(n), R, until(lambda wp=wp: B.run_inc(R, "r4", "train", stats, fam_w=wp, agt_p=0.75), lambda r: True),
                        sink, stats, bans, seen)

    # ---------------------------------------------------------------- 4b. chat tool choice (r4 rows, r5 header)
    tc = []
    for l in open(B.R4 + "train_new.jsonl", encoding="utf-8"):
        if '"tools": "chat"' not in l or not any(t in l for t in TOOLCHOICE):
            continue
        r = json.loads(l)
        names = {c["function"]["name"] for m in r["messages"] if m["role"] == "assistant" for c in (m.get("tool_calls") or [])}
        if names & TOOLCHOICE:
            tc.append(r)
    stats["toolchoice_pool"] = len(tc)
    Rt = random.Random(a.seed + 5)
    Rt.shuffle(tc)
    itc = iter(tc)

    def mk_tc():
        for r in itc:
            r = dict(r)
            r["messages"] = [dict(r["messages"][0], content=FM.chat_system_r5(r["messages"][0]["content"]))] + r["messages"][1:]
            r["tools"] = "chat_r5"
            r["family"] = "r5tool:" + r["family"]
            if any(B.h(m["content"]) in bq for m in r["messages"] if m["role"] == "user"):
                stats["dedup_test:r5_toolchoice_q"] += 1
                continue
            e = G.V.check_chat(dict(r, tools="chat"))
            if e:
                stats["fail:r5tool:" + e[0].split(":")[0]] += 1
                continue
            r["v2_add"] = "2026-11-15"
            return r
        return None
    B.gen_block("r5_toolchoice", n_tc, R, mk_tc, sink, stats, (bq, set()), seen)
    sink.close()

    # ---------------------------------------------------------------- assemble train_new (v1 rows unchanged + additions)
    with open(os.path.join(OUT, "train_new.jsonl.part"), "w", encoding="utf-8", newline="\n") as f:
        with open(os.path.join(V1, "train_new.jsonl"), encoding="utf-8") as g:
            shutil.copyfileobj(g, f)
        for l in open(tmp, encoding="utf-8"):
            r = json.loads(l)
            r["v2_add"] = "2026-11-15"
            f.write(json.dumps(r, ensure_ascii=False) + "\n")
            stats["v2_train_rows"] += 1
    os.replace(os.path.join(OUT, "train_new.jsonl.part"), os.path.join(OUT, "train_new.jsonl"))

    # ---------------------------------------------------------------- replay: v1 rows + more r3 rows (same rules as v1)
    excl = {(json.loads(l)["file"], json.loads(l)["id"]) for l in open(B.AUD + "exclusions.jsonl")}
    add_n = max(0, a.replay_total - len(v1ids))
    v1rep_n = sum(1 for _ in open(os.path.join(V1, "replay.jsonl"), encoding="utf-8"))
    n_inc = int(round(add_n * 1200 / 1900))
    rep_tmp = os.path.join(WORK, "replay_add.jsonl")
    sk = B.Sink(rep_tmp)
    Rr = random.Random(a.seed + 7)
    for fname, key, n in (("incidents_train.jsonl", "inc", n_inc), ("chat_train_r3.jsonl", "chat", add_n - n_inc)):
        fams = collections.defaultdict(list)
        k = 0
        for l in open(B.R3 + fname, encoding="utf-8"):
            k += 1
            m = re.search(r'"id": "([^"]+)"', l)
            fm = re.search(r'"family": "([^"]+)"', l)
            rid, fam = (m.group(1) if m else ""), (fm.group(1).split("+")[0] if fm else "?")
            if ("r3_train", rid) in excl or rid in v1ids:
                continue
            lst = fams[fam]
            if len(lst) < 400:
                lst.append(l)
            else:
                j = Rr.randrange(k)
                if j < 400:
                    lst[j] = l
        per = max(1, (n * 2) // max(1, len(fams)))
        pool_l = []
        for fam in sorted(fams):
            Rr.shuffle(fams[fam])
            pool_l += fams[fam][:per]
        Rr.shuffle(pool_l)
        got = 0
        for l in pool_l:
            if got >= n:
                break
            r = json.loads(l)
            u = B.user_of(r)
            hu = B.h(u) + B.h(r["messages"][-1].get("content", ""))
            qs = [B.h(m["content"]) for m in r["messages"] if m["role"] == "user"] if key == "chat" else [B.h(u)]
            if any(q in (bu if key == "inc" else bq) for q in qs) or (key == "inc" and B.ev_sig(u) in be and "S1.E1" in u) or hu in seen:
                stats["replay_add_dedup"] += 1
                continue
            e = G.V.check_incident(r) if r["tools"] == "incident" else G.V.check_chat(r)
            if e:
                stats["replay_add_verify_drop"] += 1
                continue
            seen.add(hu)
            r["block"] = "replay_r3_" + key
            r["v2_add"] = "2026-11-15"
            sk.add(r)
            got += 1
        stats["rows:replay_add_" + key] = got
    sk.close()
    with open(os.path.join(OUT, "replay.jsonl.part"), "w", encoding="utf-8", newline="\n") as f:
        for src in (os.path.join(V1, "replay.jsonl"), rep_tmp):
            with open(src, encoding="utf-8") as g:
                shutil.copyfileobj(g, f)
    os.replace(os.path.join(OUT, "replay.jsonl.part"), os.path.join(OUT, "replay.jsonl"))
    stats["replay_v1_rows"] = v1rep_n
    # tests + tools: identical copies of v1 (held-out sets unchanged)
    for f in sorted(os.listdir(os.path.join(V1, "tests"))):
        shutil.copyfile(os.path.join(V1, "tests", f), os.path.join(OUT, "tests", f))
    shutil.copyfile(os.path.join(V1, "tools_v4.json"), os.path.join(OUT, "tools_v4.json"))
    if os.environ.get("P2_FAMILIES") == "1":   # held-out rows of the new families for the part-2 gate (dev site split, not in train)
        import v2_gen_p2 as P2
        Rd = random.Random(a.seed + 99)
        nd_, tries = 0, 0
        with open(os.path.join(OUT, "tests", "dev_p2.jsonl"), "w", encoding="utf-8", newline="\n") as f:
            for nm, n in P2.P2_NAMES.items():
                wp, got = X.weights({nm: 1}), 0
                while got < max(2, int(round(S(n) * 0.08))) and tries < 4000:
                    tries += 1
                    r = B.run_inc(Rd, "r4", "dev", stats, fam_w=wp, agt_p=0.75)
                    if r is None or B.h(B.user_of(r)) in bu or B.ev_sig(B.user_of(r)) in be:
                        continue
                    r["id"], r["p2_family"] = "p2dev-%04d" % nd_, nm
                    f.write(json.dumps(r, ensure_ascii=False) + "\n")
                    nd_ += 1
                    got += 1
        stats["dev_p2_rows"] = nd_
    json.dump(dict(sorted(stats.items())), open(os.path.join(OUT, "build_stats_v2.json"), "w", newline="\n"), indent=1)
    print(json.dumps(dict(sorted(stats.items())))[:4000])


if __name__ == "__main__":
    main()
