"""Chat r5 eval of the rsn_ft gate (llama-server raw /completion, greedy; chatloop.run_samples + verify_chat.verify, the
chat_r3_eval.py loop) with the r5 header (tools_v4.json "chat_r5", 25 tools) and the record's own r5 system.
  --mode site : test_campus_chat (site-tool chat on the IIITH tree). Executor = gen_chat_v4.SiteTools (Python twin of
                chat_site.go) on core.sitegraph.campus_site() with the status / incident overlay rebuilt from the gold tool
                results; a call equal to a gold call (node resolved to its id, defaults filled) returns the stored gold
                result verbatim, so the gold world is reproduced exactly where the gold looked. Verify: gold calls (or an
                equivalent call with the same result), grounding, <= 650 chars, refusal on site:refuse, think rules
                (easy = no reasoning in any turn, also after the tool result), plus key facts: every [INC-] id and node id of
                the gold answer that came from a tool result must be in the answer.
  --mode fog  : test_fog (r3/r4 chat test records in the r5 header): executor = tools_r3_impl.ToolsR3(fog, last_sync) as
                chat_r3_eval --mode r3test, with the 4 site tools answered by SiteTools on the IIITH tree (no overlay).
--think 1 = adaptive (prompt opens <think>, budget 128), 0 = empty think block. Resumable (skips ids in --out).
  ~/venvs/rsn/bin/python chat_v4_eval.py --port P --mode site --records test_campus_chat.jsonl --tools tools_v4.json --think 1 --out O"""
import argparse
import copy
import json
import os
import re
import sys
import time

HERE = os.path.dirname(os.path.abspath(__file__))
QIDK = os.path.abspath(os.path.join(HERE, "..", "..", "..", ".."))
H4 = os.path.join(QIDK, "proofs", "2026-11-06_4b_local")
RSN = os.path.join(QIDK, "proofs", "2026-11-13_v3_data", "rsn")
for p in (os.path.join(H4, "post"), RSN, os.path.join(QIDK, "proofs", "2026-11-13_v3_data", "core")):
    if p not in sys.path:
        sys.path.insert(0, p)
import chat_r3_eval as CE  # noqa: E402  (puts chatloop / verify_chat / tools_r3 on sys.path)
import chatloop as CL  # noqa: E402
import verify_chat as VC  # noqa: E402

SITE_NAMES = ("get_site_tree", "nodes_under", "linked_equipment", "site_status")
SITE_DEFAULTS = {"get_site_tree": {"depth": 1}, "linked_equipment": {"direction": "both"}}
_CAMPUS = []


def campus():
    if not _CAMPUS:
        import sitegraph as SG
        _CAMPUS.append(SG.campus_site())
    return _CAMPUS[0]


def gold_pairs(rec):
    """[(name, args, result)] of the gold transcript (tool results matched by tool_call_id)"""
    calls, res = {}, {}
    for m in rec["messages"]:
        for tc in m.get("tool_calls") or []:
            a = tc["function"]["arguments"]
            calls[tc["id"]] = (tc["function"]["name"], json.loads(a) if isinstance(a, str) else a)
        if m["role"] == "tool":
            try:
                res[m.get("tool_call_id")] = json.loads(m["content"])
            except Exception:
                pass
    return [(n, a, res[i]) for i, (n, a) in calls.items() if i in res]


def overlay_from(pairs):
    """sensor status + open incidents visible in the gold tool results"""
    st, inc = {}, {}

    def walk(o):
        if isinstance(o, dict):
            if o.get("kind") == "sensor" and o.get("status") not in (None, "normal") and o.get("id"):
                st[o["id"]] = o["status"]
            for x in o.get("open_incidents") or []:
                if isinstance(x, dict) and x.get("sensor"):
                    inc[x["sensor"]] = {"id": x["id"], "severity": x["severity"], "title": x.get("title", "")}
                    st.setdefault(x["sensor"], x["severity"])
            for v in o.values():
                walk(v)
        elif isinstance(o, list):
            for v in o:
                walk(v)
    for _, _, r in pairs:
        walk(r)
    return st, inc


class SiteExec:
    def __init__(self, rec):
        import gen_chat_v4 as GC
        pairs = gold_pairs(rec)
        st, inc = overlay_from(pairs)
        self.T = GC.SiteTools(campus(), st, inc)
        self.gold = {self.key(n, a): r for n, a, r in pairs}
        self.qid = 0

    def key(self, name, args):
        a = dict(SITE_DEFAULTS.get(name, {}), **(args or {}))
        if "node" in a and isinstance(a["node"], str):
            a["node"] = self.T.find(a["node"]) or a["node"].strip().lower()
        return name + json.dumps(a, sort_keys=True)

    def run(self, name, args):
        k = self.key(name, args)
        if k in self.gold:
            return copy.deepcopy(self.gold[k])
        if name not in SITE_NAMES:
            return {"error": "tool %s has no data for this site question" % name, "source": "device"}
        try:
            return self.T.call(name, dict(args or {}))
        except Exception as e:
            return {"error": "bad arguments: %s" % str(e)[:80], "source": "device"}


class FogExecs(CE.Execs):
    def of(self, rec):
        e = super().of(rec)
        import gen_chat_v4 as GC
        site = GC.SiteTools(campus(), {}, {})
        inner = e.run

        def run(name, args):
            if name in SITE_NAMES:
                try:
                    return site.call(name, dict(args or {}))
                except Exception as ex:
                    return {"error": "bad arguments: %s" % str(ex)[:80], "source": "device"}
            return inner(name, args)
        e.run = run
        return e


IDS = re.compile(r"\bINC-\d+\b")


def site_facts(rec, final):
    """[INC-] ids and node ids of the gold answer that come from a gold tool result must be in the answer"""
    gold = rec["messages"][-1]["content"]
    src = " ".join(json.dumps(r) for _, _, r in gold_pairs(rec))
    miss = [i for i in set(IDS.findall(gold)) if i in src and i not in final]
    for nid in set(re.findall(r"\b[A-Z]{2,}[A-Z0-9-]*\d[A-Z0-9-]*\b", gold)):
        if nid in src and nid not in final and not nid.startswith("INC-"):
            miss.append(nid)
    return sorted(miss)


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--port", type=int, required=True)
    ap.add_argument("--mode", choices=("site", "fog"), required=True)
    ap.add_argument("--records", required=True)
    ap.add_argument("--tools", required=True)
    ap.add_argument("--think", type=int, required=True)
    ap.add_argument("--out", required=True)
    ap.add_argument("--tokenizer", default=os.path.expanduser("~/models/qwen3.5-4b"))
    ap.add_argument("--think-budget", type=int, default=128)
    ap.add_argument("--limit", type=int, default=0)
    a = ap.parse_args()
    VC.DEFAULTS.update(CE.R3_DEFAULTS)
    VC.DEFAULTS.update(SITE_DEFAULTS)
    from transformers import AutoTokenizer
    tok = AutoTokenizer.from_pretrained(a.tokenizer)
    tools = json.load(open(a.tools, encoding="utf-8"))["chat_r5"]
    recs = [json.loads(l) for l in open(a.records, encoding="utf-8") if l.strip()]
    if a.limit:
        recs = recs[:a.limit]
    done = set()
    if os.path.exists(a.out):
        done = {json.loads(l)["id"] for l in open(a.out, encoding="utf-8") if l.strip()}
    fx = FogExecs() if a.mode == "fog" else None
    mk = (lambda rec: fx.of(rec)) if fx else (lambda rec: SiteExec(rec))
    be = CL.LlamaServerBackend(a.port, think_budget=a.think_budget)
    n = 0
    for rec in recs:
        if rec["id"] in done:
            continue
        if a.mode == "site":
            rec = dict(rec, must_refuse=rec.get("family") == "site:refuse", kind=rec.get("family", "site:?").split(":")[-1],
                       gold_calls=[dict(g, required=sorted(g["args"])) for g in rec.get("gold_calls") or []])
        s = CL.Sample(rec, 0, a.think)
        t0, k0 = time.time(), be.tokens
        CL.run_samples(be, tok, tools, [s], lambda r=rec: mk(r), VC.parse_turn)
        ver = mk(rec)
        ver.qid = 0
        v = VC.verify(rec, CL.candidate(s), executor=ver)
        reasons = list(v["reasons"])
        if a.mode == "site" and v["final"]:
            reasons += ["missing_fact:" + x for x in site_facts(rec, v["final"])]
        o = {"id": rec["id"], "kind": rec.get("kind"), "hard": bool(rec.get("hard")), "must_refuse": bool(rec.get("must_refuse")),
             "fog": rec.get("fog"), "group": rec.get("group"), "hinglish": bool(rec.get("hinglish")), "mode": a.mode, "think": a.think,
             "reasoning_type": rec.get("reasoning_type", "none"), "hops": rec.get("hops", 0),
             "pass": not reasons, "reasons": reasons, "warnings": v["warnings"], "think_tokens": v["think_tokens"], "status": s.status,
             "forced": s.forced, "wall_s": round(time.time() - t0, 2), "gen_tokens": be.tokens - k0, "final": v["final"], "new": s.new}
        with open(a.out, "a", encoding="utf-8") as f:
            f.write(json.dumps(o, ensure_ascii=False) + "\n")
        n += 1
        if n % 25 == 0:
            print("chat_v4 %s %d done" % (a.mode, n), flush=True)
    print("chat_v4 %s: %d new items -> %s" % (a.mode, n, a.out))


if __name__ == "__main__":
    main()
