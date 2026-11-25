"""prep_final.py (2026-11-25, owner: "make this the last training, everything best it can be"): data for the final run
(final/data/{train_new,replay}.jsonl), started from the rsn_topup checkpoint (~step 105: chat 11/24 -> 13/24, older-format
r3 slices dipped). Trainer mix 0.75 = 12 new + 4 replay rows per step, ~130 steps.
new (1560 rows = 130 x 12): rows of topup/data/train_new.jsonl NOT yet seen by the topup schedule, 50 % chat (targeted + chat
     families) / 50 % report (multi-domain, domain, real-agent ...), balanced round-robin by family.
replay (pool 3000, 4/step): the older formats the r3 eval slice checks, which dipped at topup step 100:
     1000 r2-format incident reports (2026-11-02_2b_r2 incidents_train.jsonl, tools "incident")
     800 r3-format chat (2026-11-06_4b_local chat_train_r3.jsonl, tools "chat", fog-aware)
     1200 v4 reports + chat from data/replay.jsonl (keeps the r4 formats in replay too)
Exclusions: ids + normalised last-user-text hashes of every eval/gate/test file (gen_inc_r2, gen_chat_r3, dev_*, gate, tests).
Rows > 6600 tokens dropped. Run: ~/venvs/rsn/bin/python build/prep_final.py"""
import collections, glob, json, os, random, sys

P = "/mnt/c/Users/hp/Desktop/qidk/proofs/2026-11-21_rsn_full"
Q = "/mnt/c/Users/hp/Desktop/qidk/proofs"
TR = os.path.expanduser("~/smartcity_runs/rsn_topup")
OUT = P + "/final/data"
N_STEPS, K_NEW = 130, 12
rnd = random.Random(20261125)
os.makedirs(OUT, exist_ok=True)
sys.path.insert(0, P)
import prep_data as PD

jl = lambda p: [json.loads(l) for l in open(p, encoding="utf-8") if l.strip()]
is_rep = lambda r: str(r.get("tools", "")).startswith("incident")

# ---- exclusion sets (all eval / gate / test rows)
ban_id, ban_h = set(), set()
ev = [Q + "/2026-11-02_2b_r2/data/final/gen_inc_r2.jsonl", Q + "/2026-11-06_4b_local/data/final/gen_chat_r3.jsonl",
      Q + "/2026-11-02_2b_r2/data/final/incidents_test_r2.jsonl", Q + "/2026-11-02_2b_r2/data/final/incidents_dev60.jsonl",
      Q + "/2026-11-06_4b_local/data/final/chat_test_r3.jsonl", Q + "/2026-11-06_4b_local/data/final/dev_r3.jsonl",
      P + "/data/dev.jsonl", P + "/data/dev_inc.jsonl", P + "/data/dev_chat.jsonl", P + "/gate_full/gate_set.jsonl"]
ev += glob.glob(P + "/data/gate/*.jsonl") + glob.glob(P + "/data/tests/*.jsonl") + glob.glob(Q + "/2026-11-13_v3_data/rsn/data/final_v2/tests/*.jsonl")
for f in ev:
    if os.path.exists(f):
        for r in jl(f):
            ban_id.add(r.get("id"))
            ban_h.add(PD.hh(PD.user_last(r)))
clean = lambda r: r.get("id") not in ban_id and PD.hh(PD.user_last(r)) not in ban_h

# ---- new rows: unseen part of the topup data
S = json.load(open(TR + "/status.json"))["step"]
G = json.load(open(TR + "/schedule.json"))["groups"]
seen = {i[2:] for g in G[:S] for i in g if i.startswith("N:")}
pool = [r for r in jl(P + "/topup/data/train_new.jsonl") if r["id"] not in seen and r.get("id", "").split("-x")[0] not in
        {s.split("-x")[0] for s in seen} and clean(r)]

def fam(r):
    f = str(r.get("family") or r["id"]).split(":")
    return "%s|%s" % (r.get("block"), ":".join(f[:2]) if f[0] in ("site", "r5tool", "r5replay") else f[0].rsplit("-", 1)[0])

def rr(rows, n):
    by = collections.defaultdict(list)
    for r in rows:
        by[fam(r)].append(r)
    for v in by.values():
        rnd.shuffle(v)
    out = []
    while len(out) < n and any(by.values()):
        for k in sorted(by):
            if by[k] and len(out) < n:
                out.append(by[k].pop())
    return out

n_new = N_STEPS * K_NEW
new = rr([r for r in pool if not is_rep(r)], n_new // 2) + rr([r for r in pool if is_rep(r)], n_new - n_new // 2)
rnd.shuffle(new)

# ---- replay: older formats + v4 replay
def take(path, n, tools, filt=lambda r: True):
    rows = [r for r in jl(path) if clean(r) and filt(r)]
    rnd.shuffle(rows)
    out = []
    for r in rows:
        if len(out) >= n:
            break
        r["tools"] = r.get("tools") or tools
        r.setdefault("think", tools == "chat" and r.get("think", True))
        if PD.ntok(r) <= 6600:
            r["block"] = r.get("block") or ("r2_inc" if tools == "incident" else "r3_chat")
            out.append(r)
    return out
r2 = take(Q + "/2026-11-02_2b_r2/data/final/incidents_train.jsonl", 1000, "incident", lambda r: r.get("tools", "incident") == "incident")
r3 = take(Q + "/2026-11-06_4b_local/data/final/chat_train_r3.jsonl", 800, "chat", lambda r: r.get("tools") == "chat")
v4 = [r for r in jl(P + "/data/replay.jsonl") if clean(r)]
rnd.shuffle(v4)
rep = r2 + r3 + v4[:1200]
rnd.shuffle(rep)

for name, rows in (("train_new", new), ("replay", rep)):
    with open(OUT + "/%s.jsonl" % name, "w", encoding="utf-8", newline="\n") as f:
        f.writelines(json.dumps(r, ensure_ascii=False) + "\n" for r in rows)
st = {"topup_step": S, "new": len(new), "new_chat": sum(1 for r in new if not is_rep(r)), "new_report": sum(1 for r in new if is_rep(r)),
      "new_blocks": dict(collections.Counter(r.get("block") for r in new)), "replay": len(rep), "replay_r2_inc": len(r2),
      "replay_r3_chat": len(r3), "replay_v4": min(1200, len(v4)), "banned_ids": len(ban_id)}
json.dump(st, open(OUT + "/STATS.json", "w"), indent=1)
print(st)
