"""Build reasoner requests (lab_ab format) from the app's story incidents (final.prompt), so the 4B and 2B can be compared on the
exact prompts the live app built. Request schema/split/max_new copied from the RWH bench request q10 (same app build)."""
import glob, json, os
O = "/mnt/c/Users/hp/Desktop/qidk/proofs/2026-11-02_2b_board/app"
base = json.load(open("/mnt/c/Users/hp/Desktop/qidk/proofs/2026-10-27_reasoner_fast/bench/rreq_split/q10.json"))
idx = []
for k, f in enumerate(sorted(glob.glob(O + "/raw/*_INC-*.json"))):
    i = json.load(open(f)); p = (i.get("final") or {}).get("prompt") or ""
    if "<|im_start|>user\n" not in p: continue
    r = dict(base); r["prompt"] = p; r["prefix"] = p[:p.find("<|im_start|>user\n") + len("<|im_start|>user\n")]; r["id"] = "story:" + i["id"]
    n = 100 + len(idx); open(f"{O}/rreq/q{n}.json", "w").write(json.dumps(r) + chr(10))
    idx.append((n, os.path.basename(f), p[-60:].replace("\n", "|")))
for x in idx: print(x)
