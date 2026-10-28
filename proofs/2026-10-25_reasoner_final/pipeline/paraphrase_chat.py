"""Round 2 chat data: >= 5k diverse operator questions with verified gold from the same read-only tools.
1. Seeds: gen_chat.G kinds plus new kinds (per building, period comparison, top faulty sensor, last occurrence,
   did-the-fix-hold, two-turn follow-ups). Gold calls are executed on the training store; answers are templated
   from the results (numbers copied, never computed).
2. Paraphrase: a local model (base Qwen3.5-4B Q4 via llama-server, OpenAI API; no cloud) rewrites each seed
   question into K variants (register, word order, typos, Hinglish-light, terse/verbose).
3. Verify each variant: every literal slot (node ids, INC ids, dates, numbers) kept verbatim; metric and period
   meaning kept (synonym regexes); no new numbers/ids; not a near-duplicate (normalised text). Rejected -> dropped.
  python3 paraphrase_chat.py --url http://127.0.0.1:18097/v1/chat/completions --seeds 1800 --k 4 --out ../data/chat2_train.jsonl
  python3 paraphrase_chat.py --dry 20       # seeds + gold only, no model (CPU check)
Prints one summary line."""
import argparse
import json
import os
import random
import re
import sys
import urllib.request

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
import gen_chat as GC  # noqa: E402
from prompts import SYSTEM_CHAT, NET_OFF, NET_ON  # noqa: E402

METRIC_RX = {"co2": r"co2|carbon", "pm25": r"pm ?2\.?5|fine (dust|particle)|particulate", "pm10": r"pm ?10|coarse|dust",
             "level": r"tank|water level|level", "flow": r"flow", "tds": r"tds|dissolved", "ph": r"\bph\b|acid",
             "power_kw": r"power|load|electric|energy|kw", "pf": r"power factor|\bpf\b", "temp": r"temp|heat|hot",
             "rh": r"humid|\brh\b", "room_temp": r"room temp|temperature", "wind": r"wind"}
PRESET_RX = {"this_year": r"this year|2026|since jan|so far", "last_30d": r"30 days|past month|last month|recent month",
             "last_7d": r"7 days|week", "yesterday": r"yesterday", "this_month": r"this month", "last_month": r"last month|previous month",
             "today": r"today|so far today", "last_24h": r"24 ?h|last day|past day"}


class G2(GC.G):
    """extra kinds for round 2"""

    def by_building(self):
        R = self.R
        b = R.choice(["KH", "VN", "BK", "KN", "SB"])
        p = R.choice(["this_year", "last_30d", "last_month"])
        ph = R.choice(GC.PRESET_Q[p])
        q = R.choice(["How many incidents in %s building %s?", "%s block: incident count %s?", "Incidents at %s %s?"]) % (b, ph)
        c = [GC.call("count_incidents", {"time": {"preset": p}, "node": b})]
        return q, c, lambda r: "%s incidents in %s building %s." % (r[0]["count"], b, ph), {"literal": [b], "preset": p}

    def compare(self):
        R = self.R
        m = R.choice(["co2", "pm25", "level", "power_kw"])
        q = R.choice(["Were there more %s incidents this month than last month?", "Compare %s alerts this month vs last month."]) % GC.METRIC_Q[m][0]
        c = [GC.call("count_incidents", {"time": {"preset": "this_month"}, "metric": m}),
             GC.call("count_incidents", {"time": {"preset": "last_month"}, "metric": m})]

        def ans(r):
            a, b = r[0]["count"], r[1]["count"]
            w = "more" if a > b else ("fewer" if a < b else "the same number of")
            return "This month has %s %s incidents, last month had %s, so %s this month." % (a, GC.METRIC_Q[m][0], b, w)
        return q, c, ans, {"metric": m}

    def top_faulty(self):
        R = self.R
        q = R.choice(["Which sensor had the most faults this year?", "Worst sensor for faults in 2026?", "Which device keeps failing?"])
        c = [GC.call("sensor_faults", {"time": {"preset": "this_year"}, "basis": "ai"})]

        def ans(r):
            ss = r[0].get("sensors") or []
            if not ss:
                return "No sensor faults were flagged this year."
            top = max(ss, key=lambda s: s.get("incident_count", 0))
            return "%s %s had the most fault incidents this year (%s), first on %s." % (top["node"], top["metric"], top.get("incident_count"), top.get("first"))
        return q, c, ans, {}

    def last_occurrence(self):
        R = self.R
        m = R.choice(list(GC.METRIC_Q))
        q = R.choice(["When was the last %s incident?", "Last time %s was flagged?", "Most recent %s alert, when?"]) % GC.METRIC_Q[m][0]
        c = [GC.call("find_incidents", {"time": {"preset": "this_year"}, "metric": m, "limit": 1})]

        def ans(r):
            it = r[0].get("items") or []
            if not it:
                return "No %s incidents were recorded this year." % GC.METRIC_Q[m][0]
            return "The last one was [%s] at %s: %s." % (it[0]["id"], it[0]["time"], it[0]["title"])
        return q, c, ans, {"metric": m}


def seeds(g, n, R):
    kinds = [k for k, w in GC.KINDS] + ["by_building", "compare", "top_faulty", "last_occurrence"]
    out, tries = [], 0
    while len(out) < n and tries < n * 6:
        tries += 1
        k = R.choice(kinds)
        it = getattr(g, k)()
        if not it:
            continue
        q, calls, ansf = it[:3]
        slots = it[3] if len(it) > 3 else {}
        res = g.run(calls)
        if any(isinstance(x, dict) and "error" in x for x in res):
            continue
        a = ansf(res)
        if not a:
            continue
        lit = set(re.findall(r"\b(?:[A-Z]{2,}-[A-Z0-9-]+|INC-\d+|\d{4}-\d\d-\d\d)\b", q)) | set(slots.get("literal", []))
        out.append({"kind": k, "q": q, "calls": calls, "res": res, "a": a, "literal": sorted(lit),
                    "metric": slots.get("metric") or next((m for m in GC.METRIC_Q if any(w.lower() in q.lower() for w in GC.METRIC_Q[m])), None),
                    "preset": next((c["args"].get("time", {}).get("preset") for c in calls if isinstance(c["args"].get("time"), dict)), None)})
    return out


PARA = ("Rewrite the operator question below in {k} different ways a campus facilities operator might type it: vary wording, "
        "length, politeness, word order; some terse, one with a small typo, one in simple Indian English. Keep the exact "
        "meaning, every sensor id, incident id, building code, date and number verbatim; do not add new facts. "
        "Reply with a JSON list of {k} strings only.\nQuestion: {q}")


def gpu_cool():
    """owner heat guard: wait at GPU >= 75 C until <= 65 C"""
    import subprocess, time
    def t():
        try:
            return int(subprocess.check_output(["nvidia-smi", "--query-gpu=temperature.gpu", "--format=csv,noheader,nounits"]).decode().strip())
        except Exception:
            return 0
    if t() >= int(os.environ.get("HEAT_HI", 75)):
        while t() > int(os.environ.get("HEAT_LO", 65)):
            time.sleep(10)


def ask(url, q, k):
    gpu_cool()
    body = {"messages": [{"role": "user", "content": PARA.format(k=k, q=q)}], "temperature": 0.9, "top_p": 0.95, "max_tokens": 400,
            "chat_template_kwargs": {"enable_thinking": False}}
    req = urllib.request.Request(url, data=json.dumps(body).encode(), headers={"Content-Type": "application/json"})
    with urllib.request.urlopen(req, timeout=300) as r:
        t = json.loads(r.read())["choices"][0]["message"]["content"]
    a, b = t.find("["), t.rfind("]")
    try:
        return [x for x in json.loads(t[a:b + 1]) if isinstance(x, str)]
    except Exception:
        return []


def norm(s):
    return re.sub(r"[^a-z0-9 ]", "", s.lower()).strip()


def valid(seed, v, seen):
    if not (8 <= len(v) <= 220) or norm(v) in seen:
        return False
    if any(l not in v for l in seed["literal"]):
        return False
    if re.findall(r"\b(?:INC-\d+|[A-Z]{2,}-[A-Z0-9-]+)\b", v) and set(re.findall(r"\b(?:INC-\d+|[A-Z]{2,}-[A-Z0-9-]+)\b", v)) - set(seed["literal"]):
        return False
    qn = set(re.findall(r"\d+(?:\.\d+)?", seed["q"]))
    if set(re.findall(r"\d+(?:\.\d+)?", v)) - qn - {"2", "5", "10"}:      # PM2.5 / PM10 digits allowed
        return False
    if seed["metric"] and seed["metric"] in METRIC_RX and not re.search(METRIC_RX[seed["metric"]], v, re.I):
        return False
    if seed["preset"] and seed["preset"] in PRESET_RX and not re.search(PRESET_RX[seed["preset"]], v, re.I):
        return False
    return True


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--url", default="http://127.0.0.1:18097/v1/chat/completions")
    ap.add_argument("--seeds", type=int, default=1800)
    ap.add_argument("--k", type=int, default=4)
    ap.add_argument("--dry", type=int, default=0)
    ap.add_argument("--out", default=os.path.join(HERE, "..", "data", "chat2_train.jsonl"))
    ap.add_argument("--seed", type=int, default=31)
    ap.add_argument("--cap", type=int, default=0, help="stop once this many distinct questions are kept")
    a = ap.parse_args()
    from tools_impl import Executor, openai_tools, CHAT_TOOLS
    ex = Executor(path=GC.STORE)
    R = random.Random(a.seed)
    g = G2(R, ex)
    sd = seeds(g, a.dry or a.seeds, R)
    tnames = [t["function"]["name"] for t in openai_tools(CHAT_TOOLS)]
    rows, seen, kept, tried = [], set(), 0, 0
    got = {}
    if not a.dry:
        from concurrent.futures import ThreadPoolExecutor

        def job(i):
            try:
                return i, ask(a.url, sd[i]["q"], a.k)
            except Exception as e:
                print("paraphrase error:", str(e)[:80], file=sys.stderr)
                return i, []
        with ThreadPoolExecutor(8) as pool:
            for i, vs in pool.map(job, range(len(sd))):
                got[i] = vs
    for i, s in enumerate(sd):
        if a.cap and len(seen) >= a.cap:
            break
        variants = [s["q"]]
        for v in got.get(i, []):
            tried += 1
            if valid(s, v, seen):
                variants.append(v)
                kept += 1
        for v in variants:
            seen.add(norm(v))
            net = NET_ON if R.random() < 0.3 and s["kind"] not in ("offline_docs", "old_data") else NET_OFF
            msgs = [{"role": "system", "content": SYSTEM_CHAT.format(now="2026-10-22 12:00", dow="Thursday", net=net)}, {"role": "user", "content": v}]
            for j, (cl, r) in enumerate(zip(s["calls"], s["res"])):
                msgs.append({"role": "assistant", "content": "", "tool_calls": [{"id": "call_%d" % (j + 1), "type": "function",
                             "function": {"name": cl["name"], "arguments": cl["args"]}}]})
                msgs.append({"role": "tool", "tool_call_id": "call_%d" % (j + 1), "content": json.dumps(r)})
            msgs.append({"role": "assistant", "content": s["a"]})
            rows.append({"id": "chat2-%05d" % len(rows), "family": "chat2:" + s["kind"], "tools": "chat", "tool_names": tnames, "messages": msgs})
    with open(a.out, "w", encoding="utf-8") as f:
        for r in rows:
            f.write(json.dumps(r, ensure_ascii=False) + "\n")
    print("chat2 seeds=%d rows=%d paraphrases kept %d/%d distinct_q=%d" % (len(sd), len(rows), kept, tried, len(seen)))


if __name__ == "__main__":
    main()
