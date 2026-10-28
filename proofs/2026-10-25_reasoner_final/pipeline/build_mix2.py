"""Round-2 mix: incidents 50 / chat2 35 / replay 15 (by examples), from verified (.ok) files -> data/train_mix2.jsonl.
Size: ~3,400 examples (about 0.5 epoch of round 1's 6.9k)."""
import json, os, random, sys
D = os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "data")
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from build_mix import fix  # noqa: E402
R = random.Random(52)
load = lambda n: [json.loads(l) for l in open(os.path.join(D, n), encoding="utf-8")] if os.path.exists(os.path.join(D, n)) else []
inc, chat, rep = load("incidents_train.ok.jsonl"), load("chat2_train.ok.jsonl"), load("replay_train.ok.jsonl")
border = load("incidents_border.ok.jsonl")          # owner priority: severity consistency near thresholds
inc = [r for r in inc if not r["family"].startswith("chatter")]   # its "always warning" gold disagrees with the backend last-value rule
N = 3400
take = lambda xs, k: R.sample(xs, min(k, len(xs)))
rows = take(border, 450) + take(inc, int(N * .50) - min(450, len(border))) + take(chat, int(N * .35)) + take(rep, int(N * .15))
rows = [fix(r) if r.get("tools") != "none" else {"id": r["id"], "family": r["family"], "tools": "none", "messages": r["messages"]} for r in rows]
R.shuffle(rows)
with open(os.path.join(D, "train_mix2.jsonl"), "w", encoding="utf-8") as f:
    for r in rows:
        f.write(json.dumps(r, ensure_ascii=False) + "\n")
print("mix2 total %d (incidents %d, chat2 %d of %d, replay %d of %d)" % (len(rows), min(len(inc), int(N * .5)), min(len(chat), int(N * .35)), len(chat), min(len(rep), int(N * .15)), len(rep)))
