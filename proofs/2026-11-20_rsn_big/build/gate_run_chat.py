"""gate_run_chat.py --port P --tag T --resdir D --file gate_set.jsonl --tools tools_v4.json [--limit N]: runs the chat_en + tool_chain slices of the
big-run gate through llama-server with the app's think mode (adaptive, as run_ft.py) and LIVE tools: calls equal to a gold call get the gold
result, every other call is executed by the Python twins (big_chat.exec_tool). Output D/T/<slice>.jsonl, resumable."""
import argparse, copy, json, os, sys, time
ap = argparse.ArgumentParser()
ap.add_argument("--port", type=int, required=True); ap.add_argument("--tag", required=True); ap.add_argument("--resdir", required=True)
ap.add_argument("--file", required=True); ap.add_argument("--tools", required=True); ap.add_argument("--limit", type=int, default=0)
A = ap.parse_args()
P = "/mnt/c/Users/hp/Desktop/qidk/proofs/"
sys.path.insert(0, P + "2026-11-20_rsn_big/build"); sys.path.insert(0, P + "2026-11-13_v3_train/rsn_ft/post")
sys.argv = ["run_ft.py", "--think", "1", "--tag", A.tag, "--port", str(A.port), "--resdir", A.resdir, "v4", "--name", "x", "--file", "/dev/null", "--tools", A.tools]
import run_ft as F  # noqa: E402  (patches RB.Client.chat: adaptive think, reasoning split)
import big_chat as BC  # noqa: E402


class LiveExec:
    def __init__(self, row):
        self.gold = {}
        pend = {}
        for m in row["messages"]:
            for tc in m.get("tool_calls") or []:
                pend[tc["id"]] = (tc["function"]["name"], json.dumps(tc["function"]["arguments"], sort_keys=True))
            if m["role"] == "tool":
                self.gold[pend[m["tool_call_id"]]] = json.loads(m["content"])
        BC.world()["ex"].qid = 0

    def run(self, name, args):
        k = (name, json.dumps(args, sort_keys=True))
        if k in self.gold:
            return copy.deepcopy(self.gold[k])
        return BC.exec_tool(name, args)


tools = json.load(open(A.tools))
cli = F.RB.Client(A.port, 1500)
rows = [json.loads(l) for l in open(A.file, encoding="utf-8") if l.strip()]
rows = [r for r in rows if r.get("slice") in ("chat_en", "tool_chain")]
if A.limit:
    rows = rows[:A.limit]
out = os.path.join(A.resdir, A.tag); os.makedirs(out, exist_ok=True)
done = {}
for sl in ("chat_en", "tool_chain"):
    p = os.path.join(out, sl + ".jsonl")
    done[sl] = {json.loads(l)["id"] for l in open(p)} if os.path.exists(p) else set()
n = 0
for r in rows:
    if r["id"] in done[r["slice"]]:
        continue
    F.RV.gpu_cool(); del F.THINKS[:]
    lu = max(i for i, m in enumerate(r["messages"]) if m["role"] == "user")
    t0 = time.time()
    res = F.RB.run_loop(cli, LiveExec(r), r["messages"][0]["content"], [dict(m) for m in r["messages"][1:lu + 1]], tools[r.get("tools") or "chat_r5"], max_tokens=1500)
    rec = {"id": r["id"], "slice": r["slice"], "kind": r.get("kind"), "wall_s": round(time.time() - t0, 2), "calls": res["calls"], "final": res["final"], "think": "\n".join(F.THINKS)}
    with open(os.path.join(out, r["slice"] + ".jsonl"), "a") as f:
        f.write(json.dumps(rec) + "\n")
    n += 1
print("%s chat gate: %d rows" % (A.tag, n))
