"""A/B of htpd builds/flags on real v2 prompts (QIDK, htpd on 127.0.0.1:8091 via adb forward).
Workloads (fixed, deterministic):
  B1/B4/B8/B13  seed-24 placement event prompts at 4 h (d=8, n=48), the first k distinct cases across roles
  M10           10 refinement prompts, 8 h and 12 h (d=36, n=96/144)
  RUN1..3       batches of 8 same-length prompts that held the 2026-10-20 runaways (n=96 Q0008.., n=48 Q0146.., n=144 Q0233..)
Each workload runs twice; rep 2 is recorded (rep 1 warms the prefix cache). With --stream the request asks for
progress lines and the time to the first one is recorded.
  py -3 ab_v2.py TAG [--stream] [--base TAG] [--only B13,M10]
"""
import argparse, json, socket, time
from pathlib import Path
H = Path(__file__).resolve().parent
P24 = Path(r"C:\Users\hp\Desktop\qidk\proofs\2026-10-21_v2_confirm\placement_s24\prompts.jsonl")
P23 = Path(r"C:\Users\hp\Desktop\qidk\proofs\2026-10-20_v2_post\device\placement_v2\prompts.jsonl")

def workloads():
    p24 = [json.loads(l) for l in open(P24, encoding="utf-8")]
    ev = [p for p in p24 if not p["truth"].get("clean")]
    def pick(d, ns, k):
        out, seen = [], set()
        for p in ev:
            if p["d"] == d and p["n"] in ns and p["id"] not in seen:
                out.append(p["prompt"]); seen.add(p["id"])
            if len(out) == k:
                break
        return out
    w = {f"B{k}": pick(8, (48,), k) for k in (1, 4, 8, 13)}
    w["M10"] = pick(36, (96,), 5) + pick(36, (144,), 5)
    p23 = [json.loads(l) for l in open(P23, encoding="utf-8")]
    for tag, (qid, d, n) in {"RUN1": ("Q0008", 0, 96), "RUN2": ("Q0146", 4, 48), "RUN3": ("Q0233", 12, 144)}.items():
        same = [p for p in p23 if p["n"] == n]
        i = next(k for k, p in enumerate(same) if p["id"] == qid and p["d"] == d)
        st = (i // 8) * 8
        w[tag] = [p["prompt"] for p in same[st:st + 8]]
    return w

def call(req, stream):
    s = socket.create_connection(("127.0.0.1", 8091), timeout=600)
    t0 = time.time(); s.sendall((json.dumps(req) + "\n").encode())
    buf, first, lines = b"", None, 0
    while True:
        d = s.recv(1 << 20)
        if not d:
            break
        buf += d
        while b"\n" in buf:
            line, buf = buf.split(b"\n", 1)
            o = json.loads(line)
            if o.get("kind") in ("tok", "toks"):
                lines += 1
                if first is None:
                    first = time.time() - t0
                continue
            s.close()
            o["_wall_s"] = time.time() - t0; o["_first_s"] = first; o["_prog_lines"] = lines
            return o
    raise RuntimeError("connection closed without a result")

def main():
    ap = argparse.ArgumentParser(); ap.add_argument("tag"); ap.add_argument("--stream", action="store_true")
    ap.add_argument("--base"); ap.add_argument("--only")
    ap.add_argument("--max-batch", type=int, default=10, help="split bigger workloads like the backend (10 + 3)")
    a = ap.parse_args()
    W = workloads(); keys = a.only.split(",") if a.only else list(W)
    res = {}
    for k in keys:
        for rep in range(2):
            parts, t0 = [], time.time()
            for c in range(0, len(W[k]), a.max_batch):
                req = {"kind": "agents", "prompts": W[k][c:c + a.max_batch]}
                if a.stream:
                    req["stream"] = True
                parts.append(call(req, a.stream))
        r = {"outputs": [o for q in parts for o in q["outputs"]], "total_ms": sum(q.get("total_ms", 0) for q in parts),
             "prefill_ms": sum(q.get("prefill_ms", 0) for q in parts), "steps": [q.get("steps") for q in parts],
             "_wall_s": time.time() - t0, "_first_s": parts[0]["_first_s"], "_prog_lines": sum(q["_prog_lines"] for q in parts),
             "batches": len(parts)}
        outs = r["outputs"]
        res[k] = {"n": len(W[k]), "total_ms": r.get("total_ms"), "prefill_ms": r.get("prefill_ms"), "wall_s": round(r["_wall_s"], 2),
                  "first_progress_s": r["_first_s"] and round(r["_first_s"], 2), "progress_lines": r["_prog_lines"],
                  "texts": [o["text"] for o in outs], "stops": [o.get("stop") for o in outs],
                  "tokens": [o.get("tokens") for o in outs], "forced": [o.get("forced") for o in outs], "steps": r.get("steps"), "batches": r["batches"]}
        x = res[k]
        print(f"{a.tag} {k}: n={x['n']} total {x['total_ms']/1e3:.2f}s prefill {(x['prefill_ms'] or 0)/1e3:.2f}s "
              f"first-progress {x['first_progress_s']} stops {dict((s, x['stops'].count(s)) for s in set(x['stops']))}", flush=True)
    json.dump(res, open(H / f"ab_{a.tag}.json", "w"), indent=1)
    if a.base and (H / f"ab_{a.base}.json").exists():
        b = json.load(open(H / f"ab_{a.base}.json"))
        tot = same = 0
        for k in res:
            if k in b and not k.startswith("RUN"):
                tot += len(res[k]["texts"]); same += sum(x == y for x, y in zip(res[k]["texts"], b[k]["texts"]))
        print(f"{a.tag}: identical texts vs {a.base} (non-runaway workloads): {same}/{tot}")

if __name__ == "__main__":
    main()
