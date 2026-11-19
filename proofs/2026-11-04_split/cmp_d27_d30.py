"""Side by side: deploy27 (4B on the NPU for chat) vs deploy30 (2B on the CPU) on the same 160 board questions.
Prints the latency summary and, for every question either run sent to the model, both answers for grading.
usage (WSL): python3 cmp_d27_d30.py > CMP_d27_d30.md"""
import json, statistics as st
D = "/mnt/c/Users/hp/Desktop/qidk/proofs/2026-11-01_chat/"
SETS = [("s1", "20_s1"), ("heldout", "21_heldout"), ("blind", "22_blind"), ("blind2", "23_blind2")]


def load(tag):
    try:
        return [json.loads(l) for l in open(D + "sweep%s.jsonl" % tag)]
    except FileNotFoundError:
        return []


print("# Chat sweep: deploy27 (4B, NPU) vs deploy30 (2B, CPU)\n")
print("| set | run | answers | errors/busy | router <1 s | median s | model answers | model mean s | model max s |")
print("|---|---|---|---|---|---|---|---|---|")
pairs = []
for name, t in SETS:
    a, b = load(t + "_d27"), load(t + "_d30")
    for run, rows in (("d27 4B", a), ("d30 2B", b)):
        if not rows:
            continue
        w = [r["wall_s"] for r in rows]
        bad = sum(1 for r in rows if r.get("error") or r.get("busy") or r.get("fail"))
        m = [r["wall_s"] for r in rows if r["wall_s"] > 2]
        print("| %s | %s | %d | %d | %d | %.1f | %d | %s | %s |" % (name, run, len(rows), bad, sum(1 for x in w if x < 1),
              st.median(w), len(m), "%.1f" % st.mean(m) if m else "-", "%.1f" % max(m) if m else "-"))
    for i, rb in enumerate(b):
        ra = a[i] if i < len(a) and a[i]["q"] == rb["q"] else None
        if rb["wall_s"] > 2 or (ra and ra["wall_s"] > 2):
            pairs.append((name, rb, ra))
print("\n## Questions that reached a model in either run\n")
for name, rb, ra in pairs:
    print("**[%s] %s**" % (name, rb["q"]))
    if ra:
        print("- 4B d27 (%.1f s): %s" % (ra["wall_s"], (ra.get("text") or ra.get("fail", ""))[:300].replace("\n", " ")))
    print("- 2B d30 (%.1f s, %s): %s\n" % (rb["wall_s"], rb.get("model") or "router", (rb.get("text") or rb.get("fail", ""))[:300].replace("\n", " ")))
