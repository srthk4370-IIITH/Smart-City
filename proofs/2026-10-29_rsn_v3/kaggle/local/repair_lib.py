"""rsn_v3 PLAN_V2 stages 3-4 (error-driven repair, DPO): data helpers used by repair_pool.sh and dpo.sh. CPU only; no model loads.
All rows are synthetic: the round-1 incident generator WITHOUT the real_agent kind (no real_pool rows) and the rsn_v3 chat
generator on the synthetic training store. Held-out sets (RWH, RWH-2, dev, chat dev) are never written into any output;
the gate results are read only as per-family / per-kind failure rates and label confusions (counts, no rows).

  gate-weights --tag T --gate-dir D --rwh2 F --out W.json     failure rates per incident family / chat kind + label confusions
  inc-pool --out F --seed S --n N [--weights W] [--exclude F..] fresh verified incident pool (generator rows with meta)
  chat-pool --out F --seed S --n N [--weights W]               fresh chat questions (train phrasings, dev questions dropped)
  inc-score --pool F --results R --out F                        score_v3 per row (+ fail reasons, gold/pred label)
  inc-rows --scored F --pool F --out F [--weights W]            failures -> gold rows (compact, verified, fixed) + hardest weak rows
  chat-failed --pool F --results R --out F                      failed chat records (teacher input)
  mix --repair F.. --replay-inc F --replay-chat F --out F       repair rows + equal-token replay of epoch-1 rows (synthetic only)
  pairs --scored F.. --pool F.. --out F [...]                   DPO pairs: verified-correct (chosen) vs the model's wrong output
  check --files F..                                             Kaggle-safety check: no real_agent rows, no held-out ids/prompts
"""
import argparse
import collections
import hashlib
import heapq
import json
import os
import random
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
KG = os.path.abspath(os.path.join(HERE, ".."))
V3 = os.path.abspath(os.path.join(KG, ".."))
R1 = os.path.abspath(os.path.join(V3, "..", "2026-10-25_reasoner_final"))
D1 = os.path.join(R1, "data")
FAIL_KEYS = ("parse", "schema", "label", "severity", "req", "check_recall", "check_prec", "inject", "forbidden", "nmd")
HEADER_TOK = {"incident": 1500, "chat": 2846, "none": 0}      # data/header_tokens.json (v4 chat 15 tools); incident approx.


def load(p):
    return [json.loads(l) for l in open(p, encoding="utf-8")] if p and os.path.exists(p) else []


def dump(rows, p):
    with open(p + ".part", "w", encoding="utf-8") as f:
        for r in rows:
            f.write(json.dumps(r, ensure_ascii=False) + "\n")
    os.replace(p + ".part", p)


def base_family(f):
    return (f or "").split(":")[0].split("+")[0]


def h(s):
    return hashlib.md5(s.encode("utf-8")).hexdigest()


def est_tokens(r):
    n = 0
    for m in r["messages"]:
        n += len(m.get("content") or "") + len(m.get("reasoning_content") or "")
        if m.get("tool_calls"):
            n += len(json.dumps(m["tool_calls"], ensure_ascii=False))
    return int(n / 3.3) + HEADER_TOK.get(r.get("tools", "incident"), 0)


def _score_mod():
    sys.path.insert(0, os.path.join(R1, "eval"))
    import score_v3 as S
    S.REPAIR = False
    return S


def fail_reasons(o):
    """strict per-row failure on the gate's report metrics (+ parse, injection, forbidden actions, needs_more_data)"""
    r = []
    if not o.get("parsed"):
        return ["parse"]
    if o.get("schema_err"):
        r.append("schema")
    for k in ("label", "severity", "req", "check_recall", "check_prec"):
        if o.get(k) is not None and o[k] < 1:
            r.append(k)
    if o.get("inject_followed"):
        r.append("inject")
    if o.get("forbidden"):
        r.append("forbidden")
    if o.get("nmd_ok") == 0:
        r.append("nmd")
    return r


def _label(S, rec):
    rep = S.parse((rec.get("final") or {}).get("content"))
    return (rep.get("label"), rep.get("severity")) if isinstance(rep, dict) else (None, None)


def _gold_label(row):
    if "gold" in row:
        g = row["gold"]
        return max(g["labels"], key=g["labels"].get), max(g["severities"], key=g["severities"].get)
    rep = json.loads(row["messages"][-1]["content"])
    return rep.get("label"), rep.get("severity")


# ------------------------------------------------------------------------------------------------ gate weights
def cmd_gate_weights(a):
    S = _score_mod()
    res_dir = os.path.join(R1, "eval", "results", a.tag)
    suites = {"rwh": os.path.join(D1, "incidents_rwh.ok.jsonl"), "dev": os.path.join(D1, "incidents_dev.ok.jsonl")}
    if a.rwh2:
        suites["rwh2"] = a.rwh2
    fam = collections.defaultdict(lambda: [0, 0])
    conf = collections.Counter()
    sevc = collections.Counter()
    why = collections.Counter()
    n_items = 0
    for suite, gp in suites.items():
        rows = {r["id"]: r for r in load(gp) if "id" in r}
        for rec in load(os.path.join(res_dir, suite + ".jsonl")):
            row = rows.get(rec["id"])
            if row is None or "error" in (rec.get("final") or {}):
                continue
            n_items += 1
            fr = fail_reasons(S.score_incident(row, rec))
            f = base_family(row.get("family"))
            fam[f][0] += 1
            fam[f][1] += int(bool(fr))
            why.update(fr)
            gl, gs = _gold_label(row)
            pl, ps = _label(S, rec)
            if "label" in fr or "parse" in fr:
                conf["%s->%s" % (gl, pl)] += 1
            if "severity" in fr:
                sevc["%s->%s" % (gs, ps)] += 1
    kinds = collections.defaultdict(lambda: [0, 0])
    cp = os.path.join(a.gate_dir, "chatdev3_v3.jsonl") if a.gate_dir else ""
    for r in load(cp):
        kinds[r["kind"]][0] += 1
        kinds[r["kind"]][1] += int(not r["pass"])
    out = {"tag": a.tag, "items": n_items, "fail_reasons": dict(why.most_common()),
           "family_fail": {k: {"n": v[0], "fail": v[1], "rate": round(v[1] / max(1, v[0]), 3)} for k, v in sorted(fam.items())},
           "kind_fail": {k: {"n": v[0], "fail": v[1], "rate": round(v[1] / max(1, v[0]), 3)} for k, v in sorted(kinds.items())},
           "label_confusions": dict(conf.most_common()), "severity_confusions": dict(sevc.most_common()),
           "note": "counts from the gate's held-out suites; no held-out row is copied anywhere"}
    json.dump(out, open(a.out, "w"), indent=1)
    print("gate weights: %d items, %d families, %d chat kinds, label confusions %s" % (n_items, len(fam), len(kinds),
                                                                                    dict(conf.most_common(4))))


def family_weights(w, weak):
    """pool weight per generator family: x(1 + 3 * smoothed gate failure rate) for families seen in the gate, x2 for weak families"""
    sys.path.insert(0, os.path.join(R1, "pipeline"))
    import families as F
    ff = (w or {}).get("family_fail", {})
    m = mean_rate(ff)
    return {k: (1.0 + 3.0 * srate(ff.get(k), m)) * (2.0 if k in weak else 1.0) for k in F.FAMILIES}


def mean_rate(d):
    return sum(v["fail"] for v in d.values()) / max(1, sum(v["n"] for v in d.values()))


def srate(v, mean):
    """failure rate shrunk toward the overall rate (2 pseudo-items): a family / kind with 3 gate items is not over-weighted"""
    v = v or {"n": 0, "fail": 0}
    return (v["fail"] + 2.0 * mean) / (v["n"] + 2.0)


def weak_set(w):
    sys.path.insert(0, KG)
    import gen_incidents_v3 as GI
    ws = set(GI.WEAK)
    for k, v in ((w or {}).get("family_fail") or {}).items():
        if v["n"] >= 2 and v["rate"] >= 0.25:
            ws.add(k)
    return ws


# ------------------------------------------------------------------------------------------------ pools
def held_prompts(extra):
    """user messages of every held-out incident set + any --exclude file (epoch-1 rows): never in a pool"""
    s = set()
    for p in [os.path.join(D1, n) for n in ("incidents_dev.ok.jsonl", "incidents_rwh.ok.jsonl", "incidents_dev.jsonl",
                                            "incidents_rwh.jsonl")] + list(extra or []):
        if not p or not os.path.exists(p):
            continue
        with open(p, encoding="utf-8") as f:
            for l in f:
                m = json.loads(l)["messages"]
                if len(m) > 1:
                    s.add(h(m[1]["content"]))
    return s


def cmd_inc_pool(a):
    sys.path.insert(0, os.path.join(R1, "pipeline"))
    import gen_incidents as G
    import verify as V
    assert a.seed not in (7, 31, 4242), "seed %d is used by round 1 / epoch 1 / RWH-2" % a.seed
    w = json.load(open(a.weights)) if a.weights else None
    fw = family_weights(w, weak_set(w))
    kinds = sorted(fw)                              # no "real" kind: no real_pool rows (synthetic only, Kaggle-safe)
    wts = [fw[k] for k in kinds]
    held = held_prompts(a.exclude)
    R = random.Random(a.seed)
    out, seen, bad, leak, tries = [], set(), collections.Counter(), 0, 0
    while len(out) < a.n and tries < a.n * 20:
        tries += 1
        ex = G.make(R, R.choices(kinds, wts)[0], "train", [])
        e = V.check_incident(ex)
        if e:
            bad[e[0].split(":")[0]] += 1
            continue
        u = h(ex["messages"][1]["content"])
        if u in held:
            leak += 1
            continue
        if u in seen:
            continue
        seen.add(u)
        ex["id"] = "rp%d-%05d" % (a.seed, len(out))
        out.append(ex)
    dump(out, a.out)
    c = collections.Counter(base_family(r["family"]) for r in out)
    rep = {"rows": len(out), "seed": a.seed, "tries": tries, "verify_fail": dict(bad), "dropped_heldout_or_epoch1": leak,
           "families": dict(c.most_common()), "weights": {k: round(v, 2) for k, v in fw.items()}, "real_agent_rows": 0}
    json.dump(rep, open(a.out + ".report.json", "w"), indent=1)
    print("incident pool: %d rows (seed %d, %d tries, %d held-out/epoch-1 prompts dropped)" % (len(out), a.seed, tries, leak))


def cmd_chat_pool(a):
    sys.path.insert(0, os.path.join(V3, "pipeline"))
    import gen_chat_v3 as GC
    from tools_v3_impl import ToolsV3
    assert a.seed not in (303, 1303), "seed %d is the chat3 train/dev seed" % a.seed
    w = json.load(open(a.weights)) if a.weights else {}
    kf = w.get("kind_fail") or {}
    m = mean_rate(kf)
    GC.KINDS = [(k, wt * (1.0 + 3.0 * srate(kf.get(k), m))) for k, wt in GC.KINDS]
    ban = set()
    for p in (os.path.join(V3, "data", "chat3_dev.jsonl"),):
        for r in load(p):
            ban.add(GC.norm(next(m["content"] for m in reversed(r["messages"]) if m["role"] == "user")))
    recs = GC.make_split(ToolsV3(), "train", a.n, a.seed, ban=ban)
    for i, r in enumerate(recs):
        r["id"] = "rpc%d-%05d" % (a.seed, i)
        r["split"] = "repair"
    dump(recs, a.out)
    c = collections.Counter(r["kind"] for r in recs)
    json.dump({"rows": len(recs), "seed": a.seed, "kinds": dict(c.most_common()), "hard": sum(r["hard"] for r in recs)},
              open(a.out + ".report.json", "w"), indent=1)
    print("chat pool: %d records, %d kinds, hard %d (seed %d)" % (len(recs), len(c), sum(r["hard"] for r in recs), a.seed))


# ------------------------------------------------------------------------------------------------ scoring / repair rows
def cmd_inc_score(a):
    S = _score_mod()
    rows = {r["id"]: r for r in load(a.pool)}
    out, err = [], 0
    for rec in load(a.results):
        row = rows.get(rec["id"])
        if row is None:
            continue
        if "error" in (rec.get("final") or {}):
            err += 1
            continue
        o = S.score_incident(row, rec)
        gl, gs = _gold_label(row)
        pl, ps = _label(S, rec)
        out.append({"id": rec["id"], "family": row["family"], "fail": fail_reasons(o), "gold_label": gl, "pred_label": pl,
                    "gold_sev": gs, "pred_sev": ps, "conf": o.get("conf"),
                    "score": {k: o.get(k) for k in ("parsed", "label", "severity", "req", "check_recall", "check_prec", "schema_err")}})
    dump(out, a.out)
    nf = sum(1 for r in out if r["fail"])
    print("scored %d pool rows (%d server errors skipped): %d failures (%.1f%%) %s" % (
        len(out), err, nf, 100.0 * nf / max(1, len(out)), dict(collections.Counter(x for r in out for x in r["fail"]).most_common(6))))


def train_row(row, source):
    """gold row in the epoch-1 training form: compact gold text (kept only if it still verifies) + build_mix.fix"""
    sys.path.insert(0, os.path.join(R1, "pipeline"))
    sys.path.insert(0, KG)
    import verify as V
    from build_mix import fix
    import gen_incidents_v3 as GI
    r = json.loads(json.dumps(row))
    orig = r["messages"][-1]["content"]
    new = json.dumps(GI.compact_report(json.loads(orig)), ensure_ascii=False)
    if new != orig:
        r2 = dict(r, messages=r["messages"][:-1] + [dict(r["messages"][-1], content=new)])
        if not V.check_incident(r2):
            r = r2
    out = fix(r)
    out["source"] = source
    out["think"] = False
    return out


def cmd_inc_rows(a):
    pool = {r["id"]: r for r in load(a.pool)}
    sc = load(a.scored)
    w = json.load(open(a.weights)) if a.weights else None
    weak = weak_set(w)
    fails = [s for s in sc if s["fail"]]
    ok_weak = [s for s in sc if not s["fail"] and base_family(s["family"]) in weak]
    # hardest passing rows of the weak families: +tool / +inject variants first, then the lowest stated confidence
    ok_weak.sort(key=lambda s: (not ("+tool:" in s["family"] or "+inject" in s["family"]),
                                s["conf"] if isinstance(s["conf"], (int, float)) else 1.0, s["id"]))
    extra = ok_weak[:int(round(a.hard_frac * len(fails)))]
    rows = [train_row(pool[s["id"]], "repair_fail") for s in fails] + [train_row(pool[s["id"]], "repair_hard") for s in extra]
    dump(rows, a.out)
    print("incident repair rows: %d failures + %d hardest weak-family rows -> %s" % (len(fails), len(extra), a.out))


def cmd_chat_failed(a):
    recs = {r["id"]: r for r in load(a.pool)}
    res = load(a.results)
    bad = [recs[r["id"]] for r in res if not r["pass"] and r["id"] in recs]
    dump(bad, a.out)
    print("chat pool: %d answered, %d failed verification -> %s (%s)" % (len(res), len(bad), a.out,
          dict(collections.Counter(x.split(":")[0] for r in res if not r["pass"] for x in r["reasons"]).most_common(6))))


# ------------------------------------------------------------------------------------------------ mix
def _replay_sample(paths, exclude_ids, k, seed):
    """uniform sample (k smallest random keys) over all epoch-1 rows, streaming, synthetic only (no real_agent rows)"""
    R = random.Random(seed)
    heap = []
    skipped = 0
    for p in paths:
        if not p or not os.path.exists(p):
            continue
        with open(p, encoding="utf-8") as f:
            for l in f:
                r = json.loads(l)
                if r["id"] in exclude_ids:
                    continue
                if (r.get("family") or "").startswith("real_agent"):
                    skipped += 1
                    continue
                key = R.random()
                if len(heap) < k:
                    heapq.heappush(heap, (-key, l))
                elif -heap[0][0] > key:
                    heapq.heapreplace(heap, (-key, l))
    return [json.loads(l) for _, l in sorted(heap, key=lambda x: -x[0])], skipped


def cmd_mix(a):
    rep = []
    for p in a.repair:
        rep += load(p)
    ids = collections.Counter(r["id"] for r in rep)
    assert all(v == 1 for v in ids.values()), "duplicate repair ids"
    R = random.Random(a.seed)
    # budget: repair + replay ~= --budget-tokens; failures are kept before hardest/extra rows
    pri = {"repair_fail": 0, "distill": 0, "distill_long": 0, "template": 0, "reference": 0, "repair_hard": 1}
    R.shuffle(rep)
    rep.sort(key=lambda r: pri.get(r.get("source"), 0))
    cap = a.budget_tokens / (1.0 + a.ratio)
    keep, t_rep = [], 0
    for r in rep:
        t = est_tokens(r)
        if t_rep + t > cap and keep:
            continue
        keep.append(r)
        t_rep += t
    need = a.ratio * t_rep
    cand, skipped = _replay_sample([a.replay_inc, a.replay_chat], set(ids), max(64, int(3 * a.ratio * len(keep)) + 64), a.seed)
    replay, t_rpl = [], 0
    for r in cand:
        if t_rpl >= need:
            break
        r = dict(r, source="replay_e1")
        if r.get("tools") == "chat":
            r["think"] = True
        elif "think" not in r:
            r["think"] = False
        replay.append(r)
        t_rpl += est_tokens(r)
    out = keep + replay
    R.shuffle(out)
    dump(out, a.out)
    src = collections.Counter(r.get("source") for r in out)
    kinds = collections.Counter(r.get("tools") for r in out)
    rp = {"rows": len(out), "repair_rows": len(keep), "repair_rows_dropped_by_budget": len(rep) - len(keep), "replay_rows": len(replay),
          "est_tokens_repair": t_rep, "est_tokens_replay": t_rpl, "est_tokens_total": t_rep + t_rpl, "ratio": a.ratio,
          "budget_tokens": a.budget_tokens, "sources": dict(src), "tools": dict(kinds), "real_agent_rows_skipped_in_replay": skipped,
          "real_agent_rows": sum(1 for r in out if (r.get("family") or "").startswith("real_agent")),
          "md5": hashlib.md5(open(a.out, "rb").read()).hexdigest()}
    json.dump(rp, open(a.out + ".report.json", "w"), indent=1)
    print("repair mix: %d rows (repair %d, replay %d), est tokens %.1fM (repair %.1fM, replay %.1fM) %s" % (
        len(out), len(keep), len(replay), (t_rep + t_rpl) / 1e6, t_rep / 1e6, t_rpl / 1e6, dict(src)))


# ------------------------------------------------------------------------------------------------ DPO pairs
def _rejected_incident(chosen, rec):
    """the model's own trajectory on the same prompt (system + user of the training row): calls (one per turn, as the
    gold rows) with their tool results, then its final text"""
    msgs = json.loads(json.dumps(chosen["messages"][:2]))
    for i, c in enumerate(rec.get("calls") or []):
        args = c["args"] if isinstance(c["args"], dict) else {"_raw": str(c["args"])}
        msgs.append({"role": "assistant", "content": "", "tool_calls": [{"id": "call_%d" % (i + 1), "type": "function",
                                                                           "function": {"name": c["name"], "arguments": args}}]})
        msgs.append({"role": "tool", "tool_call_id": "call_%d" % (i + 1), "content": json.dumps(c["result"], ensure_ascii=False)})
    msgs.append({"role": "assistant", "content": (rec.get("final") or {}).get("content") or ""})
    return msgs


def cmd_pairs(a):
    sys.path.insert(0, KG)
    import chatloop as CL
    w = json.load(open(a.weights)) if a.weights else {}
    confused = set(w.get("label_confusions") or {})
    pairs = []
    # incidents: (scored, pool, results) triples
    assert len(a.scored) == len(a.pool) == len(a.results), "--scored/--pool/--results must pair up"
    for sp, pp, rp in zip(a.scored, a.pool, a.results):
        pool = {r["id"]: r for r in load(pp)}
        res = {r["id"]: r for r in load(rp)}
        for s in load(sp):
            if not s["fail"] or s["id"] not in res or s["id"] not in pool:
                continue
            fr = set(s["fail"])
            if not fr & {"label", "severity", "parse", "schema", "req", "inject", "forbidden", "nmd"}:
                continue                     # check_recall/prec-only misses: SFT repair rows, not preference pairs
            ch = train_row(pool[s["id"]], "dpo_chosen")
            rj = _rejected_incident(ch, res[s["id"]])
            if rj[-1]["content"].strip() == ch["messages"][-1]["content"].strip():
                continue
            key = "%s->%s" % (s["gold_label"], s["pred_label"])
            pri = 0 if key in confused else (1 if fr & {"label", "severity"} else 2)
            pairs.append((pri, {"id": "dpo-" + s["id"], "tools": "incident", "think": False, "family": s["family"], "kind": "incident",
                                "confusion": key, "fail": sorted(fr), "on_policy": sp == a.scored[0],
                                "chosen": ch["messages"], "rejected": rj}))
    n_inc = len(pairs)
    # chat: failed answers of the pool vs the verified rows of the teacher step (select_distill output)
    chosen = collections.defaultdict(list)
    for p in a.chat_chosen or []:
        for r in load(p):
            chosen[r.get("question_id") or r["id"].rsplit("-", 1)[0]].append(r)
    pref = {"distill": 0, "distill_long": 1, "template": 2, "reference": 3}
    for cp, cr in zip(a.chat_pool or [], a.chat_results or []):
        recs = {r["id"]: r for r in load(cp)}
        for r in load(cr):
            if r["pass"] or r["id"] not in recs or not chosen.get(r["id"]):
                continue
            new = r.get("new") or []
            if not any(m["role"] == "assistant" for m in new):
                continue
            c = sorted(chosen[r["id"]], key=lambda x: (pref.get(x.get("source"), 4), x["id"]))[0]
            rj = CL.prompt_messages(recs[r["id"]]) + new
            pairs.append((1, {"id": "dpo-" + r["id"], "tools": "chat", "think": True, "family": "chat3:" + r["kind"], "kind": "chat",
                              "confusion": "chat:" + ",".join(sorted({x.split(":")[0] for x in r["reasons"]})), "fail": r["reasons"],
                              "on_policy": cp == a.chat_pool[0], "chosen": c["messages"], "rejected": rj}))
    R = random.Random(a.seed)
    R.shuffle(pairs)
    inc = sorted([p for p in pairs if p[1]["kind"] == "incident"], key=lambda p: (p[0], not p[1]["on_policy"]))
    cht = sorted([p for p in pairs if p[1]["kind"] == "chat"], key=lambda p: not p[1]["on_policy"])
    fr = a.chat_max_frac
    n_chat = min(len(cht), int(a.max * fr), int(len(inc) * fr / max(1e-9, 1 - fr)))      # chat <= frac of the pairs
    pick = [p for _, p in inc[:a.max - n_chat]] + [p for _, p in cht[:n_chat]]
    R.shuffle(pick)
    dump(pick, a.out)
    rp = {"pairs": len(pick), "incident_candidates": n_inc, "chat_candidates": len(pairs) - n_inc,
          "incident": sum(p["kind"] == "incident" for p in pick), "chat": sum(p["kind"] == "chat" for p in pick),
          "on_policy": sum(p["on_policy"] for p in pick), "gate_confusions": sorted(confused),
          "confusions": dict(collections.Counter(p["confusion"] for p in pick).most_common(20)),
          "real_agent_rows": sum(1 for p in pick if (p["family"] or "").startswith("real_agent"))}
    json.dump(rp, open(a.out + ".report.json", "w"), indent=1)
    print("dpo pairs: %d (incident %d of %d candidates, chat %d of %d); top confusions %s" % (
        len(pick), rp["incident"], n_inc, rp["chat"], len(pairs) - n_inc, dict(list(rp["confusions"].items())[:5])))


# ------------------------------------------------------------------------------------------------ Kaggle safety
def cmd_check(a):
    held = held_prompts([a.rwh2] if a.rwh2 else [])
    held_ids = set()
    for p in (os.path.join(V3, "data", "chat3_dev.jsonl"),):
        held_ids |= {r["id"] for r in load(p)}
    bad = collections.Counter()
    n = 0
    for p in a.files:
        for r in load(p):
            n += 1
            if (r.get("family") or "").startswith("real_agent"):
                bad["real_agent"] += 1
            for msgs in (r.get("messages"), r.get("chosen"), r.get("rejected")):
                if msgs and r.get("tools") == "incident" and len(msgs) > 1 and h(msgs[1]["content"]) in held:
                    bad["heldout_prompt"] += 1
            if r["id"].split("-")[0] in ("rwh2",) or r["id"] in held_ids or r["id"].rsplit("-", 1)[0] in held_ids:
                bad["heldout_id"] += 1
    ok = not bad
    print("check %d rows in %d files: %s" % (n, len(a.files), "OK (synthetic only, no held-out rows)" if ok else "FAIL %s" % dict(bad)))
    sys.exit(0 if ok else 1)


def main():
    ap = argparse.ArgumentParser()
    sp = ap.add_subparsers(dest="cmd", required=True)
    p = sp.add_parser("gate-weights")
    p.add_argument("--tag", required=True)
    p.add_argument("--gate-dir", default="")
    p.add_argument("--rwh2", default="")
    p.add_argument("--out", required=True)
    p = sp.add_parser("inc-pool")
    p.add_argument("--out", required=True)
    p.add_argument("--seed", type=int, required=True)
    p.add_argument("--n", type=int, default=3000)
    p.add_argument("--weights", default="")
    p.add_argument("--exclude", nargs="*", default=[])
    p = sp.add_parser("chat-pool")
    p.add_argument("--out", required=True)
    p.add_argument("--seed", type=int, required=True)
    p.add_argument("--n", type=int, default=2000)
    p.add_argument("--weights", default="")
    p = sp.add_parser("inc-score")
    p.add_argument("--pool", required=True)
    p.add_argument("--results", required=True)
    p.add_argument("--out", required=True)
    p = sp.add_parser("inc-rows")
    p.add_argument("--scored", required=True)
    p.add_argument("--pool", required=True)
    p.add_argument("--out", required=True)
    p.add_argument("--weights", default="")
    p.add_argument("--hard-frac", type=float, default=0.25, help="hardest passing weak-family rows, as a share of the failures")
    p = sp.add_parser("chat-failed")
    p.add_argument("--pool", required=True)
    p.add_argument("--results", required=True)
    p.add_argument("--out", required=True)
    p = sp.add_parser("mix")
    p.add_argument("--repair", nargs="+", required=True)
    p.add_argument("--replay-inc", required=True)
    p.add_argument("--replay-chat", default="")
    p.add_argument("--ratio", type=float, default=1.0, help="replay tokens per repair token (PLAN_V2: 1:1)")
    p.add_argument("--budget-tokens", type=float, default=15e6)
    p.add_argument("--seed", type=int, default=515)
    p.add_argument("--out", required=True)
    p = sp.add_parser("pairs")
    p.add_argument("--scored", nargs="*", default=[], help="first = on-policy (current candidate), later = older runs")
    p.add_argument("--pool", nargs="*", default=[])
    p.add_argument("--results", nargs="*", default=[])
    p.add_argument("--chat-pool", nargs="*", default=[])
    p.add_argument("--chat-results", nargs="*", default=[])
    p.add_argument("--chat-chosen", nargs="*", default=[])
    p.add_argument("--weights", default="")
    p.add_argument("--max", type=int, default=2000)
    p.add_argument("--chat-max-frac", type=float, default=0.3)
    p.add_argument("--seed", type=int, default=616)
    p.add_argument("--out", required=True)
    p = sp.add_parser("check")
    p.add_argument("--files", nargs="+", required=True)
    p.add_argument("--rwh2", default="")
    a = ap.parse_args()
    globals()["cmd_" + a.cmd.replace("-", "_")](a)


if __name__ == "__main__":
    main()
