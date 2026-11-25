"""beh_v2.py (2026-11-22): behaviour block for the rsn_full retrain. The 1st run early-stopped (chat 10/12 -> 6/12) because the new chat
data had no site/refuse/unknown rows and no r5 fog-style chat; these come from the p2 training set (final_v2/train_new.jsonl, chat rows):
ALL site:* rows + a family-balanced sample of r5replay/r5tool rows up to TOTAL. Gate/test/dev exclusion and dedupe happen in prep_data.py."""
import json, random, collections
SRC = "/mnt/c/Users/hp/Desktop/qidk/proofs/2026-11-13_v3_data/rsn/data/final_v2/train_new.jsonl"
OUT = "/mnt/c/Users/hp/Desktop/qidk/proofs/2026-11-21_rsn_full/data/beh_v2.jsonl"
TOTAL = 1500
rnd = random.Random(20261122)
site, other = [], collections.defaultdict(list)
for l in open(SRC, encoding="utf-8"):
    d = json.loads(l)
    if not str(d.get("tools", "")).startswith("chat") or d.get("dup_of"):
        continue
    f = str(d.get("family", ""))
    (site.append(d) if f.startswith("site") else other[":".join(f.split(":")[:3])].append(d))
rest, keys = TOTAL - len(site), sorted(other, key=lambda k: len(other[k]))
pick = []
for i, k in enumerate(keys):
    rnd.shuffle(other[k]); q = (rest - len(pick)) // (len(keys) - i); pick += other[k][:q]
rows = site + pick
for r in rows:
    r["block"] = "beh_v2"
    if "gold_calls" not in r:   # check_big.audit_chat needs it: the row's own tool calls
        r["gold_calls"] = [{"name": tc["function"]["name"], "arguments": tc["function"]["arguments"]} for m in r["messages"] for tc in m.get("tool_calls") or []]
rnd.shuffle(rows)
with open(OUT, "w", encoding="utf-8", newline="\n") as f:
    f.writelines(json.dumps(r, ensure_ascii=False) + "\n" for r in rows)
print("beh_v2: site %d + r5 %d = %d" % (len(site), len(pick), len(rows)))

# 2026-11-22: drop rows that fail check_big (verify + audit), so the block passes the same 5% audit as every other block
import sys
sys.path.insert(0, "/mnt/c/Users/hp/Desktop/qidk/proofs/2026-11-20_rsn_big/build")
import os
os.chdir("/mnt/c/Users/hp/Desktop/qidk/proofs/2026-11-20_rsn_big/build")
sys.argv[1:] = ["/mnt/c/Users/hp/Desktop/qidk/proofs/2026-11-21_rsn_full/data"]   # check_big reads its data dir from argv at import
import types
CB = types.ModuleType("check_big")
CB.__file__ = os.path.abspath("check_big.py")
src = open("check_big.py").read().rsplit("\nmain()", 1)[0]   # module without its trailing main() call
exec(compile(src, "check_big.py", "exec"), CB.__dict__)
ok = [r for r in rows if not (CB.BC.check(r) + CB.audit_chat(r))]
with open(OUT, "w", encoding="utf-8", newline="\n") as f:
    f.writelines(json.dumps(r, ensure_ascii=False) + "\n" for r in ok)
print("beh_v2 after check_big: %d kept, %d dropped" % (len(ok), len(rows) - len(ok)))
