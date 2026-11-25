"""prep_topup.py (2026-11-24, v2: owner "add 200 more steps, reports too, need both good"): data for the 400-step top-up from rsn_full
step 640 -> topup/data/{train_new,replay}.jsonl. Trainer mix 0.75 -> 12 new + 4 replay rows per step; new rows = 4800:
  chat 2800 = targeted_v1 (gate-failure causes) x2 + 1000 unseen chat rows (round-robin over chat families)
  report 2000 = unseen report rows spread over blocks: gen5_multi (multi-domain) 600, gen5_dom (domain) 500, bigD_agt3 400,
                bigB_p2_step_real all (131), real_agt3 rest  -> domain + multi-domain + real-agent reasoning
replay (4/step): data/replay.jsonl (mostly reports). Report share ~54 %, chat ~46 %. "unseen" = not in rsn_full schedule steps < 640;
rows > 6600 tokens skipped. Run: ~/venvs/rsn/bin/python build/prep_topup.py"""
import collections, copy, json, os, random, shutil, sys
import torch

P = "/mnt/c/Users/hp/Desktop/qidk/proofs/2026-11-21_rsn_full"
R = os.path.expanduser("~/smartcity_runs/rsn_full")
OUT = P + "/topup/data"
N_CHAT_UNSEEN, TGT_REPEAT = 1000, 2
REP_Q = [("gen5_multi", 600), ("gen5_dom", 500), ("bigD_agt3", 400), ("bigB_p2_step_real", 131), ("real_agt3", 369)]
rnd = random.Random(20261124)
os.makedirs(OUT, exist_ok=True)
sys.path.insert(0, P)
import prep_data as PD                 # same tokenizer + template as the trainer's length check

ok = {r["id"] for r in torch.load(R + "/new_3e013a2c90cd_seg_tok.pt", weights_only=False) if len(r["ids"]) <= 6656}
G = json.load(open(R + "/schedule.json"))["groups"]
seen = {i[2:] for g in G[:640] for i in g if i.startswith("N:")}
rows = [json.loads(l) for l in open(P + "/data/train_new.jsonl")]
is_rep = lambda r: str(r.get("tools", "")).startswith("incident")
unseen = [r for r in rows if r["id"] in ok and r["id"] not in seen]

tgt0 = [json.loads(l) for l in open(P + "/data/targeted_v1.jsonl")]
tgt0 = [r for r in tgt0 if PD.ntok(r) <= 6600]
tgt = []
for k in range(TGT_REPEAT):
    for r in tgt0:
        c = copy.deepcopy(r)
        c.setdefault("block", "targeted_v1")
        if k:
            c["id"] = "%s-x%d" % (r["id"], k + 1)
            c["dup_of"] = r["id"]
        tgt.append(c)

def fam(r):
    f = str(r.get("family") or r["id"]).split(":")
    return "%s|%s" % (r.get("block"), ":".join(f[:2]) if f[0] in ("site", "r5tool", "r5replay") else f[0].rsplit("-", 1)[0])

by = collections.defaultdict(list)
for r in unseen:
    if not is_rep(r):
        by[fam(r)].append(r)
for v in by.values():
    rnd.shuffle(v)
chat = []
while len(chat) < N_CHAT_UNSEEN and any(by.values()):
    for k in sorted(by):
        if by[k] and len(chat) < N_CHAT_UNSEEN:
            chat.append(by[k].pop())
rep = []
for blk, q in REP_Q:
    pool = [r for r in unseen if is_rep(r) and r.get("block") == blk]
    rnd.shuffle(pool)
    rep += pool[:q]
new = tgt + chat + rep
rnd.shuffle(new)
with open(OUT + "/train_new.jsonl", "w", encoding="utf-8", newline="\n") as f:
    f.writelines(json.dumps(r, ensure_ascii=False) + "\n" for r in new)
shutil.copy(P + "/data/replay.jsonl", OUT + "/replay.jsonl")
st = {"new_rows": len(new), "targeted_rows": len(tgt), "targeted_unique": len(tgt0), "chat_unseen": len(chat),
      "chat_families": len({fam(r) for r in chat}), "report_rows": len(rep),
      "report_blocks": dict(collections.Counter(r.get("block") for r in rep)), "replay_rows": sum(1 for _ in open(OUT + "/replay.jsonl"))}
json.dump(st, open(OUT + "/STATS.json", "w"), indent=1)
print(st)
