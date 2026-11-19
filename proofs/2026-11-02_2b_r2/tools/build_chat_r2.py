"""r2 chat training rows + chat test set (stdlib python3 + the rsn_v3 chat pipeline; CPU).

train rows:
  * r1 rows: distill_laptop/chat3_distilled.jsonl (teacher answers verified in r1 + r1 reference/template rows), kept as is
  * new rows from data/chat_gen/chat3_train.jsonl (gen_chat_v3.py seed 404, train phrasings only): hard question -> gold calls
    + reference answer + the deterministic short plan think (select_distill.template_messages, verified); easy -> gold calls +
    reference answer with an EMPTY think (verified with verify_chat). Questions already in the r1 rows are skipped.
  * Hinglish / code-switched rewrite of the last question on --hinglish of the new rows (same gold; re-verified)
  * header: every row whose calls (all turns) use only the 9 tools of the app's current chat_header.txt is rendered with the
    9-tool header ("chat9") with probability --chat9 (else the 15-tool "chat" header). tools_r2.json = tools_v4 + chat9.
test records: data/chat_gen/chat3_dev.jsonl (held-out phrasings = blind style) minus any question in chat dev v3 (gate) or in
  training; --test-hinglish of them rewritten to Hinglish (flag "hinglish"); chat9-eligible ones flagged "chat9_ok".
  python3 build_chat_r2.py --out DIR
"""
import argparse
import collections
import json
import os
import random
import re
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
QIDK = os.path.abspath(os.path.join(HERE, "..", "..", ".."))
V3 = os.path.join(QIDK, "proofs", "2026-10-29_rsn_v3")
R2 = os.path.join(QIDK, "proofs", "2026-11-02_2b_r2")
sys.path.insert(0, os.path.join(V3, "pipeline"))
sys.path.insert(0, os.path.join(V3, "distill_laptop"))
import chatloop as CL  # noqa: E402
import verify_chat as VC  # noqa: E402
from tools_v3_impl import ToolsV3  # noqa: E402
import select_distill as SD  # noqa: E402

APP_HEADER = os.path.join(QIDK, "Code", "smart-city-edge-agent", "app", "backend", "chat_header.txt")

# ---------------------------------------------------------------- Hinglish (code-switched) rewrite of a question
HI = [(r"\bhow many\b", ["kitne", "kitne saare"]), (r"\bhow much\b", ["kitna"]), (r"\bwhat is\b|\bwhat's\b", ["kya hai", "kya hai"]),
      (r"\bwhat was\b", ["kya tha"]), (r"\bwhich\b", ["kaunsa", "kaun sa"]), (r"\bwhy\b", ["kyun", "kyon"]),
      (r"\bshow me\b", ["dikhao", "dikha do"]), (r"\btell me\b", ["batao", "bata do"]), (r"\btoday\b", ["aaj"]),
      (r"\byesterday\b", ["kal"]), (r"\bthis week\b", ["is hafte", "iss week"]), (r"\bthis month\b", ["is mahine"]),
      (r"\blast month\b", ["pichle mahine"]), (r"\bright now\b|\bat the moment\b", ["abhi"]), (r"\bnow\b", ["abhi"]),
      (r"\bin the last 7 days\b|\bover the past week\b", ["pichle 7 din mein", "last 7 din mein"]),
      (r"\bin the last 24 hours\b", ["pichle 24 ghante mein"]), (r"\bthis year\b", ["is saal"]),
      (r"\btoday's\b", ["aaj ka"]), (r"\byesterday's\b", ["kal ka"]), (r"\band\b", ["aur"]), (r"\bthere\b", [""]),
      (r"\bin ([A-Z]{2}(?: building| block)?)\b", [r"\1 mein"]), (r"\bfor ([A-Z]{2}(?: building| block)?)\b", [r"\1 ke liye"]),
      (r"\bany\b", ["koi"]), (r"\bplease\b|\bpls\b", ["please", "plz"]), (r"^(?:is|are|does|do|did|has|have) ", ["kya "])]
PRE = ["bhai ", "yaar ", "acha ", "sun ", "ek baat batao, ", "", "", ""]
SUF = [" batao", " bata do", " jaldi", " yaar", " na", "?", "", ""]
PROTECT = re.compile(r"\b(?:INC-\d+|[A-Z]{2,}(?:-[A-Z0-9]+)+)\b")


def hinglish(R, q):
    """code-switched rewrite: 2-4 phrase swaps (in table order, so multi-word phrases win), optional filler prefix/suffix;
    ids and numbers untouched"""
    ids = PROTECT.findall(q)
    t = PROTECT.sub("\0", q)
    cands = [k for k, (p, _) in enumerate(HI) if re.search(p, t, 0 if "[A-Z]" in p else re.I)]
    if not cands:
        return None
    pick = sorted(R.sample(cands, min(len(cands), R.randint(1, 4))))
    n = 0
    for k in pick:
        p, alts = HI[k]
        t2 = re.sub(p, R.choice(alts), t, count=1, flags=0 if "[A-Z]" in p else re.I)
        if t2 != t:
            t, n = t2, n + 1
    if n < 1:
        return None
    t = re.sub(r"\s{2,}", " ", t).strip().rstrip("?.!")
    low = t[:1].lower() + t[1:] if t[:2].isalpha() and not t[:2].isupper() else t
    pre, suf = R.choice(PRE), R.choice(SUF)
    if n == 1 and not pre.strip() and suf.strip() in ("", "?"):
        suf = R.choice([" batao", " bata do", " yaar", " na"])
    t = (pre + low if t and t[0] != "\0" else t) + suf
    for i in ids:
        t = t.replace("\0", i, 1)
    return t


def last_user_idx(msgs):
    return max(i for i, m in enumerate(msgs) if m["role"] == "user")


def with_question(rec, q):
    r = json.loads(json.dumps(rec))
    r["messages"][last_user_idx(r["messages"])]["content"] = q
    return r


def call_names(msgs):
    return {tc["function"]["name"] for m in msgs for tc in (m.get("tool_calls") or [])}


def norm(s):
    return re.sub(r"\s+", " ", re.sub(r"[^a-z0-9 ]", " ", s.lower())).strip()


def qkey(msgs):
    """the whole user side of a session (history + question), normalised"""
    return " || ".join(norm(m["content"]) for m in msgs if m["role"] == "user")


def app9():
    h = open(APP_HEADER, encoding="utf-8").read()
    return [json.loads(l) for l in re.findall(r"^\{.*\}$", h, re.M)]


def build_row(rec, ex, source_tag):
    """verified training messages for one record: hard -> template plan think, easy -> empty think"""
    if rec.get("hard"):
        tm = SD.template_messages(rec, ex)
        if tm is not None:
            return tm, "template"
    ref = CL.gold_messages(rec)[len(CL.prompt_messages(rec)):]
    ex.qid = 0
    v = VC.verify(rec, ref, executor=ex)
    if v["pass"] or (rec.get("hard") and [x.split(":")[0] for x in v["reasons"]] == []):
        return ref, "reference"
    return None, ",".join(x.split(":")[0] for x in v["reasons"])


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--out", required=True)
    ap.add_argument("--records", default=os.path.join(R2, "data", "chat_gen", "chat3_train.jsonl"))
    ap.add_argument("--test-records", default=os.path.join(R2, "data", "chat_gen", "chat3_dev.jsonl"))
    ap.add_argument("--r1-rows", default=os.path.join(V3, "distill_laptop", "chat3_distilled.jsonl"))
    ap.add_argument("--gate-dev", default=os.path.join(V3, "data", "chat3_dev.jsonl"))
    ap.add_argument("--hinglish", type=float, default=0.2)
    ap.add_argument("--chat9", type=float, default=0.35)
    ap.add_argument("--test-hinglish", type=float, default=0.25)
    ap.add_argument("--seed", type=int, default=909)
    a = ap.parse_args()
    os.makedirs(a.out, exist_ok=True)
    R = random.Random(a.seed)
    nine = app9()
    nine_names = {f["function"]["name"] for f in nine}
    tools = json.load(open(os.path.join(V3, "pipeline", "tools_v4.json")))
    v4_first9 = [t for t in tools["chat"] if t["function"]["name"] in nine_names]
    assert [json.dumps(x, sort_keys=True) for x in v4_first9] == [json.dumps(x, sort_keys=True) for x in nine], "app header != tools_v4 subset"
    tools["chat9"] = nine
    json.dump(tools, open(os.path.join(a.out, "tools_r2.json"), "w"), ensure_ascii=False)

    ex = ToolsV3()
    st = collections.Counter()
    gate = [json.loads(l) for l in open(a.gate_dev, encoding="utf-8")]
    gate_q = {qkey(CL.prompt_messages(r)) for r in gate}
    gate_last = {norm(CL.prompt_messages(r)[-1]["content"]) for r in gate}
    rows, seen = [], set()
    # r1 rows (verified in r1); header choice applies to them too
    for l in open(a.r1_rows, encoding="utf-8"):
        r = json.loads(l)
        lu = last_user_idx(r["messages"])
        k = qkey(r["messages"][:lu + 1])
        if k in gate_q:
            st["r1_drop_gate_overlap"] += 1
            continue
        seen.add(k)
        if call_names(r["messages"]) <= nine_names and R.random() < a.chat9:
            r = dict(r, tools="chat9")
        r["r2_src"] = "r1_" + r.get("source", "?")
        rows.append(r)
        st["r1_rows"] += 1
    # new rows
    for l in open(a.records, encoding="utf-8"):
        rec = json.loads(l)
        k = qkey(CL.prompt_messages(rec))
        if k in seen or k in gate_q or norm(CL.prompt_messages(rec)[-1]["content"]) in gate_last:
            st["new_drop_dup"] += 1
            continue
        hing = False
        if R.random() < a.hinglish:
            q = CL.prompt_messages(rec)[-1]["content"]
            h = hinglish(R, q)
            if h:
                rec, hing = with_question(rec, h), True
        new, why = build_row(rec, ex, "new")
        if new is None and hing:              # the rewrite broke something: fall back to the English question
            st["hinglish_verify_fail"] += 1
            continue
        if new is None:
            st["new_verify_fail:" + why] += 1
            continue
        seen.add(qkey(CL.prompt_messages(rec)))
        msgs = CL.prompt_messages(rec) + new
        tset = "chat9" if (call_names(msgs) <= nine_names and R.random() < a.chat9) else "chat"
        rows.append({"id": rec["id"] + ("-h" if hing else "-n"), "family": "chat3:" + rec["kind"] + ("+hinglish" if hing else ""),
                     "tools": tset, "think": True, "hard": bool(rec.get("hard")), "source": why, "r2_src": "new_" + why,
                     "messages": msgs})
        st["new_rows"] += 1
        st["new_hinglish"] += hing
    R.shuffle(rows)
    with open(os.path.join(a.out, "chat_train.jsonl"), "w", encoding="utf-8", newline="\n") as f:
        for r in rows:
            f.write(json.dumps(r, ensure_ascii=False) + "\n")
    # test
    tr_last = {norm(r["messages"][last_user_idx(r["messages"])]["content"]) for r in rows}
    test = []
    TR = random.Random(a.seed + 1)
    for l in open(a.test_records, encoding="utf-8"):
        rec = json.loads(l)
        k = qkey(CL.prompt_messages(rec))
        lastq = norm(CL.prompt_messages(rec)[-1]["content"])
        if k in gate_q or lastq in gate_last or lastq in tr_last:
            st["test_drop_overlap"] += 1
            continue
        rec["hinglish"] = False
        if TR.random() < a.test_hinglish:
            h = hinglish(TR, CL.prompt_messages(rec)[-1]["content"])
            if h:
                rec2 = with_question(rec, h)
                ref = CL.gold_messages(rec2)[len(CL.prompt_messages(rec2)):]
                ex.qid = 0
                if VC.verify(rec2, ref, executor=ex)["pass"] or rec2.get("must_refuse"):
                    rec, rec["hinglish"] = rec2, True
        rec["chat9_ok"] = {c["name"] for c in rec["gold_calls"]} <= nine_names and call_names(rec["messages"]) <= nine_names
        rec["id"] = rec["id"].replace("chat3-dev", "chat-test-r2")
        test.append(rec)
    with open(os.path.join(a.out, "chat_test.jsonl"), "w", encoding="utf-8", newline="\n") as f:
        for r in test:
            f.write(json.dumps(r, ensure_ascii=False) + "\n")
    comp = collections.Counter()
    for r in rows:
        comp["tools:" + r["tools"]] += 1
        comp["hard" if r["hard"] else "easy"] += 1
        comp["src:" + r["r2_src"]] += 1
        comp["turns:%d" % sum(1 for m in r["messages"] if m["role"] == "user")] += 1
    tcomp = collections.Counter()
    for r in test:
        tcomp["hinglish"] += r["hinglish"]
        tcomp["chat9_ok"] += r["chat9_ok"]
        tcomp["hard"] += bool(r["hard"])
        tcomp["kinds"] = len({x["kind"] for x in test})
    man = {"rows": len(rows), "test": len(test), "stats": dict(st), "train_composition": dict(sorted(comp.items())),
           "test_composition": dict(tcomp), "kinds_train": dict(collections.Counter(r["family"].split("+")[0] for r in rows).most_common()),
           "seed": a.seed, "hinglish_frac": a.hinglish, "chat9_frac": a.chat9}
    json.dump(man, open(os.path.join(a.out, "chat_manifest.json"), "w"), indent=1)
    print("chat r2: train %d rows, test %d; %s" % (len(rows), len(test), dict(st)))


if __name__ == "__main__":
    main()
