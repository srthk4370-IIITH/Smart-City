"""prep_rep.py (2026-11-25, owner: best non-report model = rsn_fix step 60; improve its reports only, then deploy).
Gate diff vs p2: report misses are over-escalation (critical where gold = warning: dry_run, acidic, heat_multihop, lpg card,
agent_miss; normal -> critical once). -> rep/data: 50 steps x 12 new + 4 replay.
new 600 = 450 unseen report rows with severity quotas (warning 200, normal 100, critical 90, sensor_fault 60; real-agent first)
        + 150 chat rows already learned (targeted_v1/v2 + chat families) to hold chat.
replay = final/data/replay.jsonl (older formats + v4)."""
import collections, json, os, random, shutil, sys

P = "/mnt/c/Users/hp/Desktop/qidk/proofs/2026-11-21_rsn_full"
OUT = P + "/rep/data"
rnd = random.Random(20261127)
os.makedirs(OUT, exist_ok=True)
sys.path.insert(0, P)
import prep_data as PD

jl = lambda p: [json.loads(l) for l in open(p, encoding="utf-8") if l.strip()]
used = set()
for f in ("final/data/train_new.jsonl", "topup/data/train_new.jsonl", "fix/data/train_new.jsonl"):
    used |= {r["id"].split("-x")[0] for r in jl(P + "/" + f)}
ev = {PD.hh(PD.user_last(r)) for f in ("data/dev_inc.jsonl", "data/dev_chat.jsonl", "gate_full/gate_set.jsonl") for r in jl(P + "/" + f)}

def gold(r):
    try:
        return json.loads(r["messages"][-1]["content"].split("</think>")[-1]).get("severity")
    except Exception:
        return None

by = collections.defaultdict(list)
for r in jl(P + "/data/train_new.jsonl"):
    if str(r.get("tools", "")).startswith("incident") and r["id"] not in used and PD.hh(PD.user_last(r)) not in ev:
        by[gold(r)].append(r)
rep = []
for sev, q in (("warning", 200), ("normal", 100), ("critical", 90), ("sensor_fault", 60)):
    rows = by.get(sev, [])
    rnd.shuffle(rows)
    rows.sort(key=lambda r: r.get("block") != "real_agt3")
    rep += [r for r in rows[:q * 2] if PD.ntok(r) <= 6600][:q]
chat = [r for r in jl(P + "/fix/data/train_new.jsonl") + jl(P + "/final/data/train_new.jsonl") if not str(r.get("tools", "")).startswith("incident")]
rnd.shuffle(chat)
new = rep + chat[:600 - len(rep)]
rnd.shuffle(new)
with open(OUT + "/train_new.jsonl", "w", encoding="utf-8", newline="\n") as f:
    f.writelines(json.dumps(r, ensure_ascii=False) + "\n" for r in new)
shutil.copy(P + "/final/data/replay.jsonl", OUT + "/replay.jsonl")
st = {"new": len(new), "report": len(rep), "sev": dict(collections.Counter(gold(r) for r in rep)), "chat_hold": len(new) - len(rep),
      "avail": {str(k): len(v) for k, v in by.items()}}
json.dump(st, open(OUT + "/STATS.json", "w"), indent=1)
print(st)
