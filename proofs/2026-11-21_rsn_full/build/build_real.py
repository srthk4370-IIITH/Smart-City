"""build_real.py: real pre-cutoff windows + deployed-agent outputs -> reasoner report rows via the verified v2 path (X.gen_agt3 + full_check). src_real=true."""
import sys, json, random, collections
sys.path.insert(0, "/mnt/c/Users/hp/Desktop/qidk/proofs/2026-11-20_rsn_big/build")
import build_big as BB, v2_gen as X
B, G = BB.B, BB.G
D = "/mnt/c/Users/hp/Desktop/qidk/proofs/2026-11-21_rsn_full"
R = random.Random(52113); X.install_r4()
bu, be, bq, seen, qseen = BB.bans_and_seen()
wins = {json.loads(l)["wid"]: json.loads(l) for l in open(D + "/agent_rows/windows_real.jsonl")}
outs = {}
for l in open(D + "/agent_rows/agent_out_real.jsonl"):
    o = json.loads(l); outs[o["id"]] = o["text"]
st = collections.Counter(); plan = []
for wid in sorted(outs):
    if wid not in wins: continue
    o = X.parse_agent(outs[wid])
    if o is None: st["agt_unparsable"] += 1; continue
    wrong = o["status"] != wins[wid]["gold"]["status"]
    st["agt:" + ("wrong" if wrong else "right")] += 1
    plan += [wid] * (2 if wrong else 1)
R.shuffle(plan); it = iter(plan); sink = B.Sink(D + "/data/real_rows.jsonl")
def mk():
    wid = next(it, None)
    if wid is None: return None
    r, why = X.gen_agt3(R, wins[wid], outs[wid])
    if r is None: st["drop:agt3:" + str(why)] += 1; return None
    r["window_id"] = wid
    e = G.full_check(r)
    if e: st["fail:agt3:" + e[0].split(":")[0]] += 1; return None
    w = wins[wid]
    r.update(agent_format="agt_v3", src_kind="agt3_real", site_split="train", src_real=True, real_end_epoch=w["end_epoch"], gold_status=w["gold"]["status"], real_family=w["family_agt"], gen5="real", block="real_agt3")
    r.setdefault("reasoning_type", "none"); r.setdefault("hops", 0); r["think"] = bool(r["messages"][-1].get("reasoning_content"))
    return r
B.gen_block("real_agt3", len(plan), R, mk, sink, st, (bu, be), seen); sink.close()
print(sink.n, dict(st))
