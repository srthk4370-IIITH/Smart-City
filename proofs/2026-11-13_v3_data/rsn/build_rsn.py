"""Build the rsn v3 fine-tune data (v4 incident format + chat r5 + r3-format replay) and the held-out tests.

  python3 build_rsn.py --out data/final [--scale 1.0] [--seed 11113]
Deterministic (fixed seeds). CPU only, stdlib. Every row is verified (incidents: round-1 verify.check_incident + think rules
+ v4 checks; chat: verify.check_chat + site-tool schema + think rules); failures are dropped and counted in the manifest.
Dedup: exact normalised prompt / question vs all test + dev sets (r3, r4, rwh, rwh2, round-1 dev, test_r2, dev60, chat tests)
and real pool windows used by any test suite are banned from training."""
import argparse
import collections
import hashlib
import json
import os
import random
import re
import sys
import time

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
import gen_inc_v4 as G  # noqa: E402
import gen_chat_v4 as C  # noqa: E402
import fmt_v4 as FM  # noqa: E402

Q = G.QIDK + "/proofs/"
R3 = Q + "2026-11-06_4b_local/data/final/"
R4 = Q + "2026-11-12_topup_r4/data/final/"
AUD = Q + "2026-11-13_label_audit/"
TEST_FILES_INC = [R3 + "incidents_test_r2.jsonl", R3 + "incidents_dev60.jsonl", R3 + "dev_r3.jsonl", R4 + "test_inc_r4.jsonl",
                  R4 + "dev_gen_inc.jsonl", Q + "2026-10-25_reasoner_final/data/incidents_rwh.jsonl",
                  Q + "2026-10-29_rsn_v3/kaggle/build/r1/heldout/incidents_rwh2.jsonl", Q + "2026-10-25_reasoner_final/data/incidents_dev.jsonl"]
TEST_FILES_CHAT = [R3 + "chat_test_r2.jsonl", R3 + "chat_test_r3.jsonl", R4 + "test_chat_r4.jsonl", R4 + "dev_gen_chat.jsonl"]

# train counts at scale 1.0 (owner pack: APPROVAL.md)
COUNTS = {"inc:r4": 1500, "inc:site": 450, "inc:r1": 700, "inc:real": 450, "inc:real_flip": 250, "inc:card": 500,
          "chat:site": 700, "chat:r5_replay": 900, "replay:inc_r3": 1200, "replay:chat_r3": 700}
TESTS = {"test_campus_inc": 300, "test_campus_chat": 200, "test_unseen_metric": 200, "test_unseen_layout": 300,
         "test_taxonomy": 640, "test_real_flip": 100, "test_fog": 450, "dev_inc": 200, "dev_chat": 100}


def norm(t):
    return re.sub(r"\s+", " ", re.sub(r"INC-\d+", "INC", t or "")).strip().lower()


def h(t):
    return hashlib.md5(norm(t).encode()).hexdigest()


def user_of(r):
    return next((m["content"] for m in r["messages"] if m["role"] == "user"), "")


def ev_sig(u):
    """evidence block signature: the S#.E# lines (values) of the prompt"""
    return hashlib.md5("\n".join(sorted(re.findall(r"S\d+\.E\d+ (.*)", u))).encode()).hexdigest()


def load_bans():
    bu, be, bq = set(), set(), set()
    for f in TEST_FILES_INC:
        if os.path.exists(f):
            for l in open(f, encoding="utf-8"):
                u = user_of(json.loads(l))
                bu.add(h(u))
                be.add(ev_sig(u))
    for f in TEST_FILES_CHAT:
        if os.path.exists(f):
            for l in open(f, encoding="utf-8"):
                r = json.loads(l)
                for m in r["messages"]:
                    if m["role"] == "user":
                        bq.add(h(m["content"]))
    pool_ban = set()
    for l in open(AUD + "audit.jsonl"):
        a = json.loads(l)
        if a["file"] not in ("r3_train", "r1_train", "r4_replay") and a["pool_id"]:
            pool_ban.add(a["pool_id"])
    return bu, be, bq, pool_ban


class Sink:
    def __init__(self, path):
        self.f = open(path + ".part", "w", encoding="utf-8", newline="\n")
        self.path, self.n = path, 0

    def add(self, r):
        r.pop("_ov", None)
        self.f.write(json.dumps(r, ensure_ascii=False) + "\n")
        self.n += 1

    def close(self):
        self.f.close()
        os.replace(self.path + ".part", self.path)


def chat_systems():
    """r3 chat system variants (device time, fog state) from the r4 train chat rows"""
    out = collections.defaultdict(list)
    for l in open(R4 + "train_new.jsonl", encoding="utf-8"):
        if '"tools": "chat"' not in l:
            continue
        r = json.loads(l)
        s = r["messages"][0]["content"]
        if len(out[r.get("fog")]) < 40 and s not in out[r.get("fog")]:
            out[r.get("fog")].append(s)
        if all(len(v) >= 40 for v in out.values()) and len(out) >= 3:
            break
    return out


def r5_system(sys3, site=None):
    s = FM.chat_system_r5(sys3)
    if site is not None and not str(site.get("site_id", "")).startswith("iiith"):
        camp = next(n["name"] for n in site["nodes"] if n["kind"] == "campus")
        s = s.replace("(IIIT Hyderabad)", "(%s)" % camp)
    return s


def run_inc(R, kind, split, stats, real_pool=None, agt_p=0.75, types=None, fam_w=None):
    agt = R.random() < agt_p
    if kind == "r4":
        r, why = G.gen_r4(R, 0, split, fam_w=fam_w, agt=agt)
    elif kind == "site":
        r, why = G.gen_site_fam(R, split, R.choice(["panel_trip", "shared_panel_occ", "ac_multi_trip"]), agt=agt)
    elif kind == "r1":
        r, why = G.gen_r1(R, split, R.choice(sorted(G.GI.F.FAMILIES)), agt=agt)
    elif kind in ("real", "real_flip"):
        r, why = G.gen_real(R, split, R.choice(real_pool), flip=(kind == "real_flip"))
    elif kind == "card":
        r, why = G.gen_card(R, split, types, agt=agt)
    if r is None:
        stats["drop:%s:%s" % (kind, why)] += 1
        return None
    e = G.full_check(r)
    if e:
        for x in sorted(set(z.split(":")[0] for z in e)):
            stats["fail:%s:%s" % (kind, x)] += 1
        return None
    r["agent_format"] = "agt_v3" if "\n  agent data: " in r["messages"][1]["content"] else "B50"
    if "reasoning_type" not in r:
        r["reasoning_type"], r["hops"] = "none", 0
    r["think"] = bool(r["messages"][-1].get("reasoning_content"))
    r["src_kind"] = kind
    r["site_split"] = split
    return r


def balanced_r4(R, rows_by_type, n_per):
    have = collections.Counter({t: len(v) for t, v in rows_by_type.items()})
    tgt = min(M_RT, key=lambda t: have[t])
    return [f[2] * (6.0 if G.M.RT_OF[f[0]] == tgt else 1.0) for f in G.M.FAMS]


M_RT = G.M.RTYPES


def gen_block(name, n, R, maker, sink, stats, bans, seen):
    bu, be = bans
    got, tries = 0, 0
    t0 = time.time()
    while got < n and tries < n * 6:
        tries += 1
        try:
            r = maker()
        except Exception as ex:  # a generator bug must not stop the build; counted
            stats["exc:%s:%s" % (name, type(ex).__name__)] += 1
            continue
        if r is None:
            continue
        u = user_of(r)
        hu = h(u) + h(r["messages"][-1].get("content", ""))
        if h(u) in bu or (r.get("tools", "").startswith("incident") and ev_sig(u) in be and "S1.E1" in u):
            stats["dedup_test:%s" % name] += 1
            continue
        if hu in seen:
            stats["dedup_dup:%s" % name] += 1
            continue
        seen.add(hu)
        r["id"] = "%s-%05d" % (name, got)
        r["block"] = name
        sink.add(r)
        got += 1
    stats["rows:%s" % name] = got
    stats["tries:%s" % name] = tries
    print("%s %d/%d in %.0f s" % (name, got, n, time.time() - t0), flush=True)
    return got


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--out", default=os.path.join(HERE, "data", "final"))
    ap.add_argument("--scale", type=float, default=1.0)
    ap.add_argument("--tscale", type=float, default=1.0)
    ap.add_argument("--seed", type=int, default=11113)
    ap.add_argument("--only", default="")
    a = ap.parse_args()
    os.makedirs(a.out, exist_ok=True)
    stats = collections.Counter()
    bu, be, bq, pool_ban = load_bans()
    print("bans: prompts %d evsig %d questions %d pool windows %d" % (len(bu), len(be), len(bq), len(pool_ban)), flush=True)
    aud = G._audit_ok()
    pool = [json.loads(l) for l in open(Q + "2026-10-25_reasoner_final/data/real_pool.jsonl")]
    ptrain = [p for p in pool if p["split"] == "train" and aud[p["id"]]["supported"] == "y" and p["id"] not in pool_ban]
    pheld = [p for p in pool if p["split"] == "heldout" and aud[p["id"]]["supported"] == "y"]
    pwrong = [p for p in ptrain if (p.get("pred") or {}).get("status") and p["pred"]["status"] != p["gold"]["status"]]
    stats["pool_train_supported"], stats["pool_train_agent_wrong"], stats["pool_heldout_supported"] = len(ptrain), len(pwrong), len(pheld)
    real_train = pwrong * 3 + ptrain          # oversample real agent mistakes (>= 1/2 of the family)
    suite_ids = set()
    for l in open(AUD + "audit.jsonl"):
        x = json.loads(l)
        if x["file"] in ("rwh", "rwh2", "dev", "test_r2") and x["supported"] == "y" and x["pool_id"]:
            suite_ids.add(x["pool_id"])
    psuite = [p for p in pool if p["id"] in suite_ids]
    systems = chat_systems()
    tools_r3 = json.load(open(R3 + "tools_r3.json", encoding="utf-8"))
    json.dump(FM.tools_v4(tools_r3), open(os.path.join(a.out, "tools_v4.json"), "w", encoding="utf-8"), ensure_ascii=False, indent=0)
    seen = set()
    S = lambda k: max(1, int(round(COUNTS[k] * a.scale)))  # noqa: E731
    T = lambda k: max(1, int(round(TESTS[k] * a.tscale)))  # noqa: E731
    only = set(a.only.split(",")) if a.only else None

    def want(x):
        return only is None or x in only

    # ------------------------------------------------------------------ train: new v4 incidents + r5 chat
    if want("train"):
        sink = Sink(os.path.join(a.out, "train_new.jsonl"))
        R = random.Random(a.seed)
        rt = collections.defaultdict(list)

        def mk_r4():
            r = run_inc(R, "r4", "train", stats, fam_w=balanced_r4(R, rt, 0))
            if r:
                rt[r["reasoning_type"]].append(1)
            return r
        gen_block("v4_r4", S("inc:r4"), R, mk_r4, sink, stats, (bu, be), seen)
        gen_block("v4_site", S("inc:site"), R, lambda: run_inc(R, "site", "train", stats), sink, stats, (bu, be), seen)
        gen_block("v4_r1", S("inc:r1"), R, lambda: run_inc(R, "r1", "train", stats), sink, stats, (bu, be), seen)
        gen_block("v4_real", S("inc:real"), R, lambda: run_inc(R, "real", "train", stats, real_pool=real_train), sink, stats, (bu, be), seen)
        gen_block("v4_realflip", S("inc:real_flip"), R, lambda: run_inc(R, "real_flip", "train", stats, real_pool=ptrain), sink, stats, (bu, be), seen)
        gen_block("v4_card", S("inc:card"), R, lambda: run_inc(R, "card", "train", stats, types=G.CD.TRAIN_TYPES), sink, stats, (bu, be), seen)
        # chat: site tools (25 % two-turn sessions)
        sites = {}

        def mk_site_chat(split="train", campus=False):
            site = G.SG.campus_site() if campus else G.SG.gen_site(R.randrange(6000 if split == "train" else 300), split)
            fog = R.choices(["online", "offline", "timeout"], [45, 45, 10])[0]
            sysm = r5_system(R.choice(systems[fog]), site)
            kinds = list(C.EN)
            w = [1.4 if k in ("hard_hot", "ac_flagged", "bld_status") else 1.0 for k in kinds]
            k = R.choices(kinds, w)[0]
            r, why = C.make_row(R, site, sysm, k)
            if r and R.random() < 0.25:
                k2 = R.choices(kinds, w)[0]
                r2, why2 = C.make_row(R, site, sysm, k2, ov=r["_ov"], prev=r["messages"][1:])
                if r2:
                    r = r2
            if r is None:
                stats["drop:chat_site:" + why] += 1
                return None
            r["fog"] = fog
            e = C.check_row(r)
            if e:
                for x in sorted(set(z.split(":")[0] for z in e)):
                    stats["fail:chat_site:%s" % x] += 1
                return None
            if h(r["messages"][-2 if r["messages"][-2]["role"] == "user" else 1]["content"]) in bq:
                return None
            r.pop("gold_calls", None)
            return r
        gen_block("r5_site", S("chat:site"), R, mk_site_chat, sink, stats, (bq, set()), seen)
        # chat: r4 chat rows re-rendered with the r5 header (taxonomy x-kinds, fog states, easy)
        rep = collections.defaultdict(list)
        for l in open(R4 + "train_new.jsonl", encoding="utf-8"):
            if '"tools": "chat"' not in l:
                continue
            r = json.loads(l)
            g = "x" if r.get("group") == "x" else ("fog" if "fog" in r["family"] else ("easy" if not r.get("hard") else "other"))
            rep[g].append(r)
        want_g = {"x": 0.39, "fog": 0.39, "easy": 0.22}
        Rr = random.Random(a.seed + 5)
        pick = []
        for g, fr in want_g.items():
            Rr.shuffle(rep[g])
            pick += rep[g][:int(round(S("chat:r5_replay") * fr))]
        rep.clear()

        def it_r5():
            for r in pick:
                r = dict(r)
                r["messages"] = [dict(r["messages"][0], content=FM.chat_system_r5(r["messages"][0]["content"]))] + r["messages"][1:]
                r["tools"] = "chat_r5"
                r["family"] = "r5replay:" + r["family"]
                e = G.V.check_chat(dict(r, tools="chat"))
                if e:
                    stats["fail:r5replay:" + e[0].split(":")[0]] += 1
                    continue
                yield r
        itr = it_r5()
        gen_block("r5_replay", len(pick), R, lambda: next(itr, None), sink, stats, (bq, set()), seen)
        sink.close()
        stats["train_new_rows"] = sink.n

    # ------------------------------------------------------------------ replay (r3 format, unchanged rows)
    if want("replay"):
        excl = {(json.loads(l)["file"], json.loads(l)["id"]) for l in open(AUD + "exclusions.jsonl")}
        sink = Sink(os.path.join(a.out, "replay.jsonl"))
        Rr = random.Random(a.seed + 7)
        for fname, key, n in (("incidents_train.jsonl", "inc", S("replay:inc_r3")), ("chat_train_r3.jsonl", "chat", S("replay:chat_r3"))):
            fams = collections.defaultdict(list)
            k = 0
            for l in open(R3 + fname, encoding="utf-8"):
                k += 1
                m = re.search(r'"id": "([^"]+)"', l)
                fm = re.search(r'"family": "([^"]+)"', l)
                rid, fam = (m.group(1) if m else ""), (fm.group(1).split("+")[0] if fm else "?")
                if ("r3_train", rid) in excl:
                    stats["replay_excluded_audit"] += 1
                    continue
                lst = fams[fam]
                # reservoir per family (cap 400 offsets per family keeps RAM small)
                if len(lst) < 400:
                    lst.append(l)
                else:
                    j = Rr.randrange(k)
                    if j < 400:
                        lst[j] = l
            per = max(1, n // max(1, len(fams)))
            pool_l = []
            for fam in sorted(fams):
                Rr.shuffle(fams[fam])
                pool_l += fams[fam][:per]
            rest = [x for fam in sorted(fams) for x in fams[fam][per:]]
            Rr.shuffle(rest)
            pool_l += rest[:max(0, n - len(pool_l))]
            got = 0
            for l in pool_l[:n]:
                r = json.loads(l)
                u = user_of(r)
                if h(u) in (bu if key == "inc" else bq):
                    stats["replay_dedup_test"] += 1
                    continue
                r["block"] = "replay_r3_" + key
                sink.add(r)
                got += 1
            stats["rows:replay_r3_" + key] = got
            stats["replay_families_" + key] = len(fams)
            print("replay", key, got, "families", len(fams), flush=True)
        sink.close()

    # ------------------------------------------------------------------ held-out tests + dev
    if want("tests"):
        td = os.path.join(a.out, "tests")
        os.makedirs(td, exist_ok=True)
        tseen = set()
        R = random.Random(a.seed + 100)

        def blk(name, n, maker, split_bans=(bu, be)):
            sk = Sink(os.path.join(td, name + ".jsonl"))
            gen_block(name, n, R, maker, sk, stats, split_bans, tseen | seen)
            sk.close()
        rtc = collections.defaultdict(list)

        def mk_tax(split):
            def f():
                r = run_inc(R, "r4", split, stats, fam_w=balanced_r4(R, rtc, 0))
                if r:
                    rtc[r["reasoning_type"]].append(1)
                return r
            return f
        blk("test_campus_inc", T("test_campus_inc"), lambda: (lambda k: run_inc(R, k, "campus", stats, real_pool=pheld, types=G.CD.TRAIN_TYPES))(
            R.choice(["r4", "r4", "r4", "site", "r1"])))
        blk("test_campus_chat", T("test_campus_chat"), lambda: mk_site_chat_t(R, systems, stats, bq, campus=True), (bq, set()))
        blk("test_unseen_metric", T("test_unseen_metric"), lambda: run_inc(R, "card", "test", stats, types=G.CD.TEST_TYPES))
        blk("test_unseen_layout", T("test_unseen_layout"), lambda: run_inc(R, R.choice(["r4", "r4", "site"]), "test", stats))
        rtc.clear()
        blk("test_taxonomy", T("test_taxonomy"), mk_tax("test"))
        sk = Sink(os.path.join(td, "test_real_agent.jsonl"))
        it = iter(psuite)
        gen_block("test_real_agent", len(psuite), R, lambda: (lambda p: None if p is None else run_inc(R, "real", "test", stats, real_pool=[p]))(next(it, None)),
                  sk, stats, (set(), set()), set())
        it2 = iter(R.sample(pheld, len(pheld)))
        gen_block("test_real_agent_flip", T("test_real_flip"), R, lambda: (lambda p: None if p is None else run_inc(R, "real_flip", "test", stats, real_pool=[p]))(next(it2, None)),
                  sk, stats, (set(), set()), set())
        sk.close()
        # test_fog: r4 + r3 chat test records re-rendered for r5 (gen records: prompt + gold_calls + gold_facts)
        sk = Sink(os.path.join(td, "test_fog.jsonl"))
        byfog = collections.defaultdict(list)
        for f in (R4 + "test_chat_r4.jsonl", R3 + "chat_test_r3.jsonl"):
            for l in open(f, encoding="utf-8"):
                r = json.loads(l)
                if r.get("fog") in ("online", "offline", "timeout"):
                    byfog[r["fog"]].append(r)
        want_f = {"online": 180, "offline": 180, "timeout": 90}
        for fog, n in want_f.items():
            Rr = random.Random(a.seed + 9)
            Rr.shuffle(byfog[fog])
            for r in byfog[fog][:int(round(n * a.tscale))]:
                r = dict(r)
                r["messages"] = [dict(r["messages"][0], content=FM.chat_system_r5(r["messages"][0]["content"]))] + r["messages"][1:]
                r["tools"] = "chat_r5"
                if "tool_names" in r:
                    r["tool_names"] = list(r["tool_names"]) + [t["function"]["name"] for t in FM.SITE_TOOLS]
                sk.add(r)
            stats["rows:test_fog:" + fog] = min(len(byfog[fog]), int(round(n * a.tscale)))
        sk.close()
        blk("dev_inc", T("dev_inc"), lambda: run_inc(R, R.choice(["r4", "r4", "site", "r1", "real", "card"]), "dev", stats,
                                                      real_pool=ptrain[:200], types=G.CD.TRAIN_TYPES))
        blk("dev_chat", T("dev_chat"), lambda: mk_site_chat_t(R, systems, stats, bq, split="dev"), (bq, set()))
    json.dump(dict(sorted(stats.items())), open(os.path.join(a.out, "build_stats%s.json" % ("_" + a.only.replace(",", "_") if a.only else "")), "w"), indent=1)
    print(json.dumps(dict(sorted(stats.items())))[:3000])


def mk_site_chat_t(R, systems, stats, bq, split="test", campus=False):
    site = G.SG.campus_site() if campus else G.SG.gen_site(R.randrange(300 if split == "dev" else 400), split)
    fog = R.choices(["online", "offline", "timeout"], [45, 45, 10])[0]
    sysm = r5_system(R.choice(systems[fog]), site)
    k = R.choice(list(C.EN))
    r, why = C.make_row(R, site, sysm, k)
    if r is None:
        stats["drop:chat_site_t:" + why] += 1
        return None
    r["fog"] = fog
    if C.check_row(r):
        stats["fail:chat_site_t"] += 1
        return None
    return r


if __name__ == "__main__":
    main()
