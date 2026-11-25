"""prep_fix.py (2026-11-25): short fix top-up from rsn_final step 127 -> fix/data/{train_new,replay}.jsonl (60 steps x 12 new + 4 replay).
Real weaknesses at final steps 50/100 (gen_rows.jsonl): reports confuse sensor_fault vs a real event in both directions
(real-agent pollution event called sensor_fault; r2-format sensor_fault called normal). Chat eval misses were mostly harness
(unknown site tool / incident not on the device), but chains-with-final-answer + cite-ids rows (targeted_v2) still help.
new 720 = 360 report rows (unseen, gold label sensor_fault vs real events vs normal, balanced, real-agent first) + 360 targeted_v2 chat.
replay = final/data/replay.jsonl (older formats + v4)."""
import collections, json, os, random, shutil, sys

P = "/mnt/c/Users/hp/Desktop/qidk/proofs/2026-11-21_rsn_full"
OUT = P + "/fix/data"
rnd = random.Random(20261126)
os.makedirs(OUT, exist_ok=True)
sys.path.insert(0, P)
import prep_data as PD

jl = lambda p: [json.loads(l) for l in open(p, encoding="utf-8") if l.strip()]
used = set()
for f in ("final/data/train_new.jsonl", "topup/data/train_new.jsonl"):
    used |= {r["id"].split("-x")[0] for r in jl(P + "/" + f)}
ev = {PD.hh(PD.user_last(r)) for f in ("data/dev_inc.jsonl", "data/dev_chat.jsonl", "gate_full/gate_set.jsonl") for r in jl(P + "/" + f)}

def gold_label(r):
    try:
        return json.loads(r["messages"][-1]["content"].split("</think>")[-1]).get("label")
    except Exception:
        return None

by = collections.defaultdict(list)
for r in jl(P + "/data/train_new.jsonl"):
    if not str(r.get("tools", "")).startswith("incident") or r["id"] in used or PD.hh(PD.user_last(r)) in ev:
        continue
    g = gold_label(r)
    k = "sensor_fault" if g == "sensor_fault" else "normal" if g in ("normal_operation", "normal") else "event" if g else None
    if k:
        by[(k, r.get("block") == "real_agt3")].append(r)
for v in by.values():
    rnd.shuffle(v)
rep = []
for k in ("sensor_fault", "event", "normal"):
    q = {"sensor_fault": 140, "event": 140, "normal": 80}[k]
    rows = by[(k, True)] + by[(k, False)]
    rep += [r for r in rows if PD.ntok(r) <= 6600][:q]
chat = [r for r in jl(P + "/data/targeted_v2.jsonl") if PD.ntok(r) <= 6600]
rnd.shuffle(chat)
new = rep + chat[:720 - len(rep)]
rnd.shuffle(new)
with open(OUT + "/train_new.jsonl", "w", encoding="utf-8", newline="\n") as f:
    f.writelines(json.dumps(r, ensure_ascii=False) + "\n" for r in new)
shutil.copy(P + "/final/data/replay.jsonl", OUT + "/replay.jsonl")
st = {"new": len(new), "report": len(rep), "report_kinds": {k: sum(1 for r in rep if (gold_label(r) == "sensor_fault") == (k == "sensor_fault")) for k in ("sensor_fault", "other")},
      "chat_v2": len(new) - len(rep), "avail": {"%s|%s" % k: len(v) for k, v in by.items()}}
json.dump(st, open(OUT + "/STATS.json", "w"), indent=1)
print(st)
