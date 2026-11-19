"""drop r3 replay rows that fail round-1 verify (num grounding / tool error) -> replay.jsonl rewritten; counts to build_stats_replay_filter.json"""
import json, os, sys
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import gen_inc_v4 as G
D = sys.argv[1]
p = os.path.join(D, "replay.jsonl")
keep, drop = [], 0
for l in open(p, encoding="utf-8"):
    r = json.loads(l)
    e = G.V.check_incident(r) if r["tools"] == "incident" else G.V.check_chat(r)
    if e:
        drop += 1
    else:
        keep.append(l)
open(p + ".part", "w", encoding="utf-8", newline="\n").writelines(keep)
os.replace(p + ".part", p)
json.dump({"replay_dropped_verify": drop, "replay_kept": len(keep)}, open(os.path.join(D, "build_stats_replay_filter.json"), "w"))
print(drop, len(keep))
