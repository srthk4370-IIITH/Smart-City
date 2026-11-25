"""prep_data.py [--seen 19200] [--selftest] : assemble the rsn_full training data (CPU only). Re-runnable; missing optional inputs are skipped.
  run:  ~/venvs/rsn/bin/python prep_data.py          (needs transformers + ~/models/qwen3.5-4b for token counts)
  in :  BIG/data/final_big/pool_train_new.jsonl + pool_replay.jsonl, lineage zip (Non-Synthetic/reasoner__*train* -> replay),
        D/data/{gen5_tools,real_rows,gen5_multidomain,gen5_domain}.jsonl (optional, produced by other agents)
  out:  D/data/{train_new,replay,dev,dev_inc,dev_chat}.jsonl, MANIFEST.json, PLAN.md, (+ gate/, tests/, tools_v4.json copies for check_big)
  steps: tag src_real -> dedupe -> exclude gate/test ids + user-text hashes -> trim rows > 6000 tokens -> audit (check_big.py) -> subsample -> dev."""
import collections
import copy
import glob
import hashlib
import json
import os
import random
import re
import shutil
import subprocess
import sys
import zipfile

QP = "/mnt/c/Users/hp/Desktop/qidk/proofs"
D = QP + "/2026-11-21_rsn_full"
BIG = QP + "/2026-11-20_rsn_big"
FB = BIG + "/data/final_big"
TESTS_V2 = QP + "/2026-11-13_v3_data/rsn/data/final_v2/tests"
ZIP = "/mnt/c/Users/hp/Desktop/SmartCity_Training_Datasets_2026-11-20.zip"
WORK = os.path.expanduser("~/rsn_full_work")
OUT = D + "/data"
MAXTOK = 6000
SEED = 20261121
SEEN = int(sys.argv[sys.argv.index("--seen") + 1]) if "--seen" in sys.argv else 19200
MIX_NEW = 0.65
NEWS = ["gen5_tools", "real_rows", "gen5_multidomain", "gen5_domain", "beh_v2"]
ID = re.compile(r"S\d+\.E\d+")
rnd = random.Random(SEED)
LOG = []


def log(*a):
    s = " ".join(str(x) for x in a)
    LOG.append(s)
    print(s, flush=True)


def jl(p):
    return [json.loads(l) for l in open(p, encoding="utf-8") if l.strip()]


def wr(p, rows):
    with open(p, "w", encoding="utf-8", newline="\n") as f:
        for r in rows:
            f.write(json.dumps(r, ensure_ascii=False) + "\n")


def hh(t):   # same normalisation as check_big.hh
    return hashlib.md5(re.sub(r"\s+", " ", re.sub(r"INC-\d+", "INC", t or "")).strip().lower().encode()).hexdigest()


def user_last(r):
    return next((m.get("content") or "" for m in reversed(r["messages"]) if m["role"] == "user"), "")


def chash(r):
    return hashlib.md5(json.dumps(r["messages"], ensure_ascii=False, sort_keys=True).encode()).hexdigest()


# ---------------------------------------------------------------- tokens
TOK = None
TOOLS_SRC = OUT + "/tools_v5.json" if os.path.exists(OUT + "/tools_v5.json") else FB + "/tools_v4.json"   # v5 = v4 + the new gen5 tools
TOOLS = json.load(open(TOOLS_SRC, encoding="utf-8"))


def ntok(r):
    global TOK
    if TOK is None:
        import getpass
        from transformers import AutoTokenizer
        TOK = AutoTokenizer.from_pretrained("/home/%s/models/qwen3.5-4b" % getpass.getuser())
    msgs = copy.deepcopy(r["messages"])
    for m in msgs:
        for tc in m.get("tool_calls") or []:
            if isinstance(tc["function"]["arguments"], str):
                tc["function"]["arguments"] = json.loads(tc["function"]["arguments"])
    txt = TOK.apply_chat_template(msgs, tools=TOOLS.get(r.get("tools")), tokenize=False, enable_thinking=bool(r.get("think", True)))
    return len(TOK(txt)["input_ids"])


OV = {}
N5 = {f["function"]["name"] for f in TOOLS["chat_r5"]}
N6 = {f["function"]["name"] for f in TOOLS.get("chat_r6", [])}


def audit_r6(r):
    """check_big only audits chat_r5: same schema rules (tool name, arg names, enums, required) for chat_r6 rows."""
    sch = {f["function"]["name"]: f["function"]["parameters"] for f in TOOLS["chat_r6"]}
    bad = []
    for m in r["messages"]:
        for tc in m.get("tool_calls") or []:
            n, a = tc["function"]["name"], tc["function"]["arguments"]
            a = json.loads(a) if isinstance(a, str) else a
            if n not in sch:
                bad.append("unknown tool " + n)
                continue
            for k, v in a.items():
                if k not in sch[n]["properties"]:
                    bad.append("arg %s.%s" % (n, k))
                elif "enum" in sch[n]["properties"][k] and v not in sch[n]["properties"][k]["enum"]:
                    bad.append("enum %s.%s=%s" % (n, k, v))
            bad += ["required %s.%s" % (n, q) for q in sch[n].get("required", []) if q not in a]
    if not (r["messages"][-1].get("content") or "").strip():
        bad.append("empty final")
    return bad


def overhead(tools_key):
    """constant tokens the tools schema adds to every row of that kind (chat_r5 ~4.5k): the 6000 budget is counted on the row's own content (full - overhead);
    the trainer's hard max-len (7424, full template) is enforced as well."""
    if tools_key not in OV:
        ntok({"messages": [{"role": "system", "content": "x"}, {"role": "user", "content": "y"}], "tools": None, "think": True})
        m = [{"role": "system", "content": "x"}, {"role": "user", "content": "y"}]
        a = len(TOK(TOK.apply_chat_template(m, tools=TOOLS.get(tools_key), tokenize=False, enable_thinking=True))["input_ids"])
        b = len(TOK(TOK.apply_chat_template(m, tools=None, tokenize=False, enable_thinking=True))["input_ids"])
        OV[tools_key] = a - b
    return OV[tools_key]


MAXLEN = 7424


def too_long(r, full):
    return full - overhead(r.get("tools")) > MAXTOK or full > MAXLEN


def chars(r):
    return sum(len(m.get("content") or "") + len(m.get("reasoning_content") or "") + len(json.dumps(m.get("tool_calls", ""))) for m in r["messages"])


# ---------------------------------------------------------------- tagging
def is_real(r):
    if r.get("src_lineage"):
        return True
    # real = real campus window (window_src real / src_kind real, real_flip) or a real-derived block; "agt3_real:syn" = synthetic window with the real agent head, NOT real
    sk, blk, kd = str(r.get("src_kind", "")), str(r.get("block", "")), str(r.get("kind", ""))
    return (sk in ("real", "real_flip") or r.get("window_src") == "real" or "real" in blk or "agt3-real" in kd or "real_flip" in kd or "realflip" in kd)


def infer_tools(r):
    if r.get("tools") in TOOLS:
        return r["tools"]
    s = r["messages"][0].get("content") or ""
    return "incident_v4" if "cross-domain reasoner" in s else "chat_r5" if "operator assistant" in s else None


def is_report(r):
    return str(r.get("tools", "")).startswith("incident")


# ---------------------------------------------------------------- trim
def asst_text(msgs, i):
    out = []
    for m in msgs[i + 1:]:
        if m["role"] == "assistant":
            out.append((m.get("content") or "") + " " + (m.get("reasoning_content") or "") + " " + json.dumps(m.get("tool_calls") or ""))
    return " ".join(out)


NUM = re.compile(r"(?<![\w.])\d+(?:\.\d+)?(?![\w])")


def item_cited(item, atext, nums):
    it = item if isinstance(item, str) else json.dumps(item, ensure_ascii=False)
    if isinstance(item, dict):
        for k in ("id", "node", "name", "sensor", "ref"):
            if item.get(k) and str(item[k]) in atext:
                return True
    elif isinstance(item, str) and item in atext:
        return True
    for n in NUM.findall(it):
        if (len(n) >= 3 or "." in n) and not re.fullmatch(r"20\d\d", n) and n in nums:
            return True
    return False


def dump_like(orig, obj):
    for kw in ({"ensure_ascii": False}, {"ensure_ascii": False, "separators": (",", ":")}, {"ensure_ascii": True}, {"ensure_ascii": False, "indent": 1}):
        try:
            if json.dumps(json.loads(orig), **kw) == orig:
                return json.dumps(obj, **kw)
        except Exception:
            return None
    return json.dumps(obj, ensure_ascii=False)


def trim_tool_msgs(r, keep_head):
    msgs, n_cut = r["messages"], 0
    for i, m in enumerate(msgs):
        if m["role"] != "tool" or not isinstance(m.get("content"), str) or len(m["content"]) < 1500:
            continue
        try:
            obj = json.loads(m["content"])
        except Exception:
            continue
        if not isinstance(obj, dict):
            continue
        at = asst_text(msgs, i)
        nums = set(NUM.findall(at))
        best = max(((k, v) for k, v in obj.items() if isinstance(v, list) and len(v) > 4), key=lambda kv: len(json.dumps(kv[1])), default=None)
        if not best:
            continue
        k, lst = best
        keep = [x for j, x in enumerate(lst) if j < keep_head or item_cited(x, at, nums)]
        cut = len(lst) - len(keep)
        if cut <= 0:
            continue
        obj[k] = keep + ["... (%d more items)" % cut]
        new = dump_like(m["content"], obj)
        if new is None:
            continue
        m["content"] = new
        n_cut += cut
    return n_cut


def trim_incident(r):
    msgs, n_cut = r["messages"], 0
    ui = next((i for i, m in enumerate(msgs) if m["role"] == "user"), None)
    if ui is None:
        return 0
    cited = set(ID.findall(asst_text(msgs, ui)))
    out, sensor = [], None
    for l in msgs[ui]["content"].split("\n"):
        m = re.match(r"^(S\d+) \[", l)
        if m:
            sensor = m.group(1)
        e = re.match(r"^\s+(S\d+\.E\d+)\b", l)
        if e and sensor and sensor != "S1" and e.group(1).split(".")[0] == sensor and e.group(1) not in cited:
            n_cut += 1
            continue
        out.append(l)
    msgs[ui]["content"] = "\n".join(out)
    return n_cut


def trim_row(r):
    """returns (new_row, tokens) or (None, tokens) when it cannot be brought under MAXTOK. assistant turns / tool calls / system untouched."""
    t0 = ntok(r)
    if not too_long(r, t0):
        return r, t0, 0
    for stage in ("tool2", "tool0", "inc"):
        x = copy.deepcopy(r)
        c = 0
        if stage == "tool2":
            c = trim_tool_msgs(x, 2)
        elif stage == "tool0":
            c = trim_tool_msgs(x, 0)
        if stage == "inc" or (stage == "tool0" and is_report(x)):
            c += trim_incident(x)
        if c:
            t = ntok(x)
            if not too_long(x, t):
                x["trimmed"] = {"from_tokens": t0, "to_tokens": t, "cut": c}
                return x, t, c
        r = x if c else r
    return None, t0, 0


def untouched_ok(a, b):
    """assistant turns, tool calls, system prompt identical; every cited id still present."""
    if len(a["messages"]) != len(b["messages"]):
        return False
    for x, y in zip(a["messages"], b["messages"]):
        if x["role"] != y["role"]:
            return False
        if x["role"] in ("assistant", "system") and x != y:
            return False
    return True


# ---------------------------------------------------------------- selection helpers
def bal(rows, n, key):
    """equal quota per key, leftovers redistributed (every family stays represented)."""
    if n >= len(rows):
        return list(rows)
    by = collections.defaultdict(list)
    for r in rows:
        by[key(r)].append(r)
    for v in by.values():
        rnd.shuffle(v)
    out, left = [], n
    keys = sorted(by, key=lambda k: len(by[k]))
    for i, k in enumerate(keys):
        q = left // (len(keys) - i)
        take = by[k][:q]
        out += take
        left -= len(take)
    return out


def fam(r):
    return r.get("block") or str(r.get("family", "")).split(":")[0] or r.get("tools")


def selftest():
    items = [{"id": "INC-%04d" % i, "time": "2026-08-01", "title": "x" * 80, "n": 100 + i} for i in range(300)]
    r = {"tools": "chat_r5", "think": True, "id": "t", "messages": [
        {"role": "system", "content": "s"}, {"role": "user", "content": "q"},
        {"role": "assistant", "content": "", "tool_calls": [{"id": "c", "type": "function", "function": {"name": "x", "arguments": {}}}]},
        {"role": "tool", "tool_call_id": "c", "content": json.dumps({"total": 300, "items": items}, ensure_ascii=False)},
        {"role": "assistant", "content": "Newest is INC-0007 with 123 readings."}]}
    x = copy.deepcopy(r)
    c = trim_tool_msgs(x, 2)
    body = json.loads(x["messages"][3]["content"])
    assert c == 300 - 4 and untouched_ok(r, x), (c, len(body["items"]))
    kept = [i["id"] for i in body["items"][:-1]]
    assert "INC-0007" in kept and "INC-0023" in kept and body["items"][-1] == "... (%d more items)" % c and body["total"] == 300, kept
    u = "CONTEXT\nS1 [FLAGGED]: a\n  S1.E1 last 1\n  S1.E2 max 2\nS2 [FLAGGED]: b\n  S2.E1 last 3\n  S2.E2 max 4\n  S2.E3 min 5\nLINKS: x"
    r2 = {"messages": [{"role": "system", "content": "s"}, {"role": "user", "content": u}, {"role": "assistant", "content": '{"chain": "S2.E2 up"}'}]}
    y = copy.deepcopy(r2)
    assert trim_incident(y) == 2 and "S2.E2" in y["messages"][1]["content"] and "S1.E2" in y["messages"][1]["content"] and "S2.E1" not in y["messages"][1]["content"] and untouched_ok(r2, y)
    print("selftest ok")


# ================================================================ main
def main():
    os.makedirs(OUT, exist_ok=True)
    gate = jl(FB + "/gate/gate_set.jsonl")
    ban_ids = {g["id"] for g in gate}
    ban_h = {hh(user_last(g)) for g in gate}
    nt = 0
    for d in (TESTS_V2, FB + "/tests"):
        for f in sorted(glob.glob(d + "/*.jsonl")):
            for r in jl(f):
                ban_ids.add(r["id"])
                ban_h.add(hh(user_last(r)))
                nt += 1
    log("ban sets: gate %d rows, tests %d rows -> %d ids, %d user-text hashes" % (len(gate), nt, len(ban_ids), len(ban_h)))

    # ---- load
    cand, skipped = [], collections.Counter()

    def add(rows, src, kind):   # kind: 'new' or 'replay'
        for r in rows:
            if r.get("dup_of"):          # intentional x2/x3 copies of the old pool: re-weighted here instead
                skipped["dup_of_copy:" + src] += 1
                continue
            t = infer_tools(r)
            if t is None:
                skipped["no_tools:" + src] += 1
                continue
            if t == "chat_r5" and "chat_r6" in TOOLS:     # rows that call a tool only the v5 menu has (data_health, forecast_crossing...) must be rendered with chat_r6
                used = {tc["function"]["name"] for m in r["messages"] for tc in m.get("tool_calls") or []}
                if used - N5 and used <= N6:
                    t = "chat_r6"
                    skipped["retag_chat_r6:" + src] += 1
            r["tools"] = t
            r.setdefault("think", True)
            r["src_file"], r["_kind"] = src, kind
            cand.append(r)
    add(jl(FB + "/pool_train_new.jsonl"), "pool_train_new", "new")
    add(jl(FB + "/pool_replay.jsonl"), "pool_replay", "replay")
    # lineage (real-derived, Non-Synthetic) -> replay
    lin = WORK + "/Non-Synthetic"
    if not glob.glob(lin + "/reasoner__*train*"):
        os.makedirs(WORK, exist_ok=True)
        with zipfile.ZipFile(ZIP) as z:        # read-only on the zip
            for n in z.namelist():
                if n.startswith("Non-Synthetic/reasoner__") and "__train" in n:
                    z.extract(n, WORK)
    for f in sorted(glob.glob(lin + "/reasoner__*train*.jsonl")):
        rows = jl(f)
        for r in rows:
            r["src_lineage"] = True
        add(rows, "lineage:" + os.path.basename(f).split("__2026")[0], "replay")
    present = {}
    for n in NEWS:
        p = OUT + "/" + n + ".jsonl"
        if os.path.exists(p) and os.path.getsize(p):
            rows = jl(p)
            for r in rows:
                r.setdefault("block", n)
            present[n] = len(rows)
            add(rows, n, "gen5")
        else:
            present[n] = 0
    log("loaded", len(cand), "rows; optional new files:", present, "; skipped", dict(skipped))

    # ---- tag + dedupe + exclude
    seen_id, seen_c, rows = {}, {}, []
    stat = collections.Counter()
    for r in cand:
        r["src_real"] = bool(r["src_real"]) if "src_real" in r else bool(is_real(r))   # new-agent files may carry their own tag
        c = chash(r)
        if c in seen_c:
            if r["src_real"]:
                seen_c[c]["src_real"] = True       # same content seen as real elsewhere: keep first copy, keep the tag
            if r.get("src_lineage"):
                seen_c[c]["src_lineage"] = True
            if r.get("block") == "beh_v2":         # behaviour block (2026-11-22): the pool copy must still go into train_new
                seen_c[c]["_kind"], seen_c[c]["block"] = "gen5", "beh_v2"
                seen_c[c].setdefault("gold_calls", r.get("gold_calls", []))
            stat["dup_content"] += 1
            continue
        if r["id"] in seen_id:
            r["id"] = r["id"] + "-" + r["src_file"].split(":")[-1][:12]
            if r["id"] in seen_id:
                stat["dup_id"] += 1
                continue
        if r["id"] in ban_ids:
            stat["excluded_id"] += 1
            continue
        if hh(user_last(r)) in ban_h:
            stat["excluded_userhash"] += 1
            continue
        seen_id[r["id"]] = 1
        seen_c[c] = r
        rows.append(r)
    log("after dedupe/exclude:", len(rows), dict(stat))

    # ---- trim rows > MAXTOK
    ctr = collections.Counter()
    out_rows = []
    long_chars = 0     # measure every row (chars are a poor token proxy: tools schema overhead)
    for i, r in enumerate(rows):
        if chars(r) < long_chars:      # cheap pre-filter: far below 6000 tokens
            out_rows.append(r)
            continue
        x, t, c = trim_row(r)
        ctr["measured"] += 1
        if x is None:
            ctr["dropped_untrimmable"] += 1
            ctr["drop:%s:%s" % (r["src_file"].split(":")[0], r.get("block"))] += 1
            continue
        if x is not r:
            if not untouched_ok(r, x):
                ctr["trim_violation_dropped"] += 1
                continue
            ctr["trimmed"] += 1
        out_rows.append(x)
    rows = out_rows
    log("trim:", dict(ctr), "-> rows", len(rows))

    # ---- verify trimmed rows with check_big (written to a scratch dir below, after selection); build selection first
    new_pool = [r for r in rows if r["_kind"] in ("new", "gen5")]
    rep_pool = [r for r in rows if r["_kind"] == "replay"]
    gen5 = [r for r in new_pool if r["_kind"] == "gen5"]
    base_new = [r for r in new_pool if r["_kind"] == "new"]
    real_new = [r for r in base_new if r["src_real"]]
    syn_new = [r for r in base_new if not r["src_real"]]
    # replay: real-derived/lineage rows ALL kept; rest stratified up to 35% of the seen rows
    NEWS_N, REPS_N = round(SEEN * MIX_NEW), SEEN - round(SEEN * MIX_NEW)

    def x2(r):                       # real-agent report rows go in twice (id-suffixed copy, same convention as the old pool)
        c = copy.deepcopy(r)
        c["id"] += "-x2"
        c["dup_of"] = r["id"]
        return c
    fixed = []
    for r in real_new + gen5:
        fixed.append(r)
        if r["src_real"] and is_report(r):
            fixed.append(x2(r))
    left = max(0, NEWS_N - len(fixed))
    rep_s = [r for r in syn_new if is_report(r)]
    chat_s = [r for r in syn_new if not is_report(r)]
    wR, wC = 2 * len(rep_s), len(chat_s)          # report rows count double in the share
    qR = round(left * wR / max(wR + wC, 1))
    filler = bal(rep_s, qR, fam) + bal(chat_s, left - qR if len(chat_s) >= left - qR else len(chat_s), fam)
    train_new = fixed + filler
    rnd.shuffle(train_new)
    rep_real = [r for r in rep_pool if r["src_real"]]
    rep_syn = [r for r in rep_pool if not r["src_real"]]
    replay = rep_real + bal(rep_syn, max(0, REPS_N - len(rep_real)), fam)
    rnd.shuffle(replay)
    for r in train_new + replay:
        r.pop("_kind", None)

    # ---- dev: from existing tests, not in the gate set
    dev, slices = [], {}
    gate_ids = {g["id"] for g in gate}
    gate_h = {hh(user_last(g)) for g in gate}
    train_h = {hh(user_last(r)) for r in train_new + replay}
    train_ids = {r["id"] for r in train_new + replay}

    def pick(files, n, pred, name):
        pool = []
        for f in files:
            p = f if f.startswith("/") else None
            for d in (FB + "/tests", TESTS_V2):
                if os.path.exists(d + "/" + f):
                    p = d + "/" + f
            if p and os.path.exists(p):
                pool += [dict(r, dev_src=os.path.basename(p)) for r in jl(p)]
        pool = [r for r in pool if r["id"] not in gate_ids and hh(user_last(r)) not in gate_h and hh(user_last(r)) not in train_h
                and r["id"] not in train_ids and pred(r)]
        got = bal(pool, n, lambda r: (r.get("dev_src"), str(r.get("family", "")).split(":")[0].split("+")[0]))
        for r in got:
            r["dev_slice"] = name
        slices[name] = len(got)
        return got
    calls = lambda r: any(m.get("tool_calls") for m in r["messages"])
    dev_rep = pick(["dev_inc.jsonl", "dev_p2.jsonl", "test_campus_inc.jsonl", "test_taxonomy.jsonl"], 120, lambda r: True, "report")
    dev_real = pick(["test_real_agent.jsonl", "dev_inc.jsonl"], 100, lambda r: "real_agent" in str(r.get("family", "")) or r.get("src_kind") == "real", "real_agent")
    seen_dev = {r["id"] for r in dev_rep}
    dev_real = [r for r in dev_real if r["id"] not in seen_dev]
    dev_chat = pick(["dev_chat.jsonl", "test_campus_chat.jsonl", "test_fog.jsonl"], 70, lambda r: not calls(r), "chat")
    dev_tool = pick(["dev_chat.jsonl", "test_campus_chat.jsonl", "test_fog.jsonl"], 50, calls, "tool")
    dev = dev_rep + dev_real + dev_chat + dev_tool
    wr(OUT + "/dev.jsonl", dev)
    wr(OUT + "/dev_inc.jsonl", dev_rep + dev_real)
    wr(OUT + "/dev_chat.jsonl", dev_chat + dev_tool)
    wr(OUT + "/train_new.jsonl", train_new)
    wr(OUT + "/replay.jsonl", replay)

    # ---- audit with check_big.py (verify + audit of the new rows; also gate/test overlap)
    for src, dst in ((FB + "/gate", OUT + "/gate"), (FB + "/tests", OUT + "/tests")):
        shutil.copytree(src, dst, dirs_exist_ok=True)
    shutil.copy(TOOLS_SRC, OUT + "/tools_v4.json")   # check_big reads tools_v4.json: same content as the schema used for tokens/audit
    p = subprocess.run(["python3", BIG + "/build/check_big.py", OUT], capture_output=True, text=True, cwd=BIG + "/build")
    chk = (p.stdout + p.stderr).strip().splitlines()[-6:]
    log("check_big rc=%d: %s" % (p.returncode, " | ".join(chk)))

    r6 = [r for r in train_new + replay if r.get("tools") == "chat_r6"]
    r6_bad = [(r["id"], audit_r6(r)) for r in r6]
    r6_bad = [x for x in r6_bad if x[1]]
    log("chat_r6 rows %d, schema-audit bad %d %s" % (len(r6), len(r6_bad), r6_bad[:3]))

    # ---- stats
    def tok_stats(rs, k=900):
        s = rnd.sample(rs, min(k, len(rs)))
        ns = [ntok(r) for r in s]
        return {"rows": len(rs), "sample": len(ns), "mean_tokens": round(sum(ns) / max(len(ns), 1)), "max_tokens": max(ns or [0]),
                "over_%d_in_sample" % MAXTOK: sum(1 for n in ns if n > MAXTOK), "over_maxlen_7424": sum(1 for n in ns if n > MAXLEN)}
    man = {"seen_target": SEEN, "mix_new": MIX_NEW, "optional_inputs": present, "skipped_load": dict(skipped), "dedupe_exclude": dict(stat),
           "trim": dict(ctr), "trim_max_tokens": MAXTOK, "check_big_rc": p.returncode, "check_big_tail": chk, "dev_slices": slices, "chat_r6_rows": len(r6), "chat_r6_bad": len(r6_bad), "tools_schema": TOOLS_SRC}
    for name, rs in (("train_new", train_new), ("replay", replay)):
        c = collections.Counter()
        real = sum(1 for r in rs if r["src_real"])
        for r in rs:
            c[(("R:" if r["src_real"] else "S:") + str(r.get("src_file", "")).split(":")[0] + ":" + str(fam(r)))] += 1
        man[name] = {"rows": len(rs), "real": real, "synthetic": len(rs) - real, "by_source": dict(collections.Counter(str(r.get("src_file")).split(":")[0] for r in rs)),
                     "by_block": dict(sorted(c.items())), "tokens": tok_stats(rs)}
    man["dev"] = {"rows": len(dev), "tokens": tok_stats(dev, 300)}
    json.dump(man, open(OUT + "/MANIFEST.json", "w", encoding="utf-8", newline="\n"), indent=1)
    tn, rp = man["train_new"], man["replay"]
    ntok_new = tn["tokens"]["mean_tokens"]
    plan = ["# rsn_full data plan (prep_data.py, rerun when new data lands)", "",
            "- target seen: %d rows = %d steps x 16 (mix %.2f new / %.2f replay -> %d new, %d replay)" % (SEEN, SEEN // 16, MIX_NEW, 1 - MIX_NEW, NEWS_N, REPS_N),
            "- train_new: %d rows (%d real, %d synthetic); mean tokens %d, max %d | replay: %d rows (%d real, %d synthetic); mean %d, max %d" % (
                tn["rows"], tn["real"], tn["synthetic"], ntok_new, tn["tokens"]["max_tokens"], rp["rows"], rp["real"], rp["synthetic"], rp["tokens"]["mean_tokens"], rp["tokens"]["max_tokens"]),
            "- composition train_new: ALL real rows (real-agent report rows also as -x2 copies), ALL gen5/new-agent rows (%s), filler from pool_train_new (report rows weighted x2 vs chat/tool, equal quota per family)" % present,
            "- replay: ALL real-derived rows (pool_replay real + lineage Non-Synthetic reasoner train files) + stratified rest of pool_replay up to 35 percent of seen (family-equal quotas, leftovers redistributed)",
            "- tag src_real: src_kind real/real_flip, window_src real (agt3_real:syn = synthetic window, not real), block contains 'real', lineage; dedupe: exact messages hash + id (old x2/x3 pool copies dropped)",
            "- excluded: ids and normalised last-user-text hashes of gate_set + all test/dev sets; excluded counts %s" % dict(stat),
            "- trim > %d tokens of row content (Qwen3.5-4B template; the constant tools-schema prefix, ~4.5k for chat_r5, is not counted, but the trainer max-len 7424 on the full template is enforced): tool results cut only list items not cited by later assistant turns (id or quoted number), + '... (N more items)'; incident prompts drop uncited evidence lines of non-S1 sensors; assistant/tool calls/system untouched. Result %s" % (MAXTOK, dict(ctr)),
            "- audit: check_big.py rc=%d (see data/CHECK.md); dev: %s rows %s from existing tests minus gate set (dev.jsonl; dev_inc.jsonl = report+real_agent, dev_chat.jsonl = chat+tool, the two names run_full.sh expects)" % (p.returncode, len(dev), slices),
            "- run: GO file needed in %s; epochs 1 (rows seen above). Missing optional inputs now: %s" % (D, [k for k, v in present.items() if not v])]
    open(OUT + "/../PLAN.md", "w", encoding="utf-8", newline="\n").write("\n".join(plan) + "\n")
    open(OUT + "/PLAN.md", "w", encoding="utf-8", newline="\n").write("\n".join(plan) + "\n")
    log("done: train_new %d (real %d) replay %d (real %d) dev %d" % (tn["rows"], tn["real"], rp["rows"], rp["real"], len(dev)))


if __name__ == "__main__":
    if "--selftest" in sys.argv:
        selftest()
    else:
        selftest()
        main()
