"""setc_adaptive.py: Set C variant for profile reasoner_think=adaptive (reasoner_v3.go: prompt ends inside an open think block
"<|im_start|>assistant\n<think>\n", Force off => no schema, no split decoding; max_new 700). Agents requests unchanged.
Reads sets/C/req, writes sets/C_adaptive/req (+ ORDER)."""
import glob, json, os, shutil
S, D = "sets/C/req", "sets/C_adaptive/req"
os.makedirs(D, exist_ok=True)
OPEN = "<|im_start|>assistant\n<think>\n\n</think>\n\n"; AOPEN = "<|im_start|>assistant\n<think>\n"
for f in glob.glob(S + "/*"):
    n = os.path.basename(f)
    if n.endswith("_r.json"):
        r = json.load(open(f, encoding="utf-8"))
        assert r["prompt"].endswith(OPEN)
        r["prompt"] = r["prompt"][:-len(OPEN)] + AOPEN
        for k in ("schema", "split", "split_after"): r.pop(k, None)
        r["max_new"] = 700
        open(D + "/" + n, "w", encoding="utf-8", newline="\n").write(json.dumps(r) + "\n")
    else:
        shutil.copy(f, D + "/" + n)
print(len(os.listdir(D)))
