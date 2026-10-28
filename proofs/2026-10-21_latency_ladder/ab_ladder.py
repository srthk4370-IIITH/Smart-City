"""htpd-direct A/B for the v2 latency ladder (QIDK, htpd on 127.0.0.1:8091 through adb forward; start it with
proofs/2026-10-21_htpd_v7_ab/htpd_ab.sh or run_ladder.sh). Extends ../2026-10-21_htpd_v7_ab/ab_v2.py.

Why a new harness: ab_v2.py records rep 2 of the SAME prompts, so htpd's recent-output drafts already hold the exact
answers (B1 decodes at ~96 tok/s there, the app's early alerts at ~35 tok/s). That hides every decode-side lever
(drafting sources, rows per step, one batch vs 10 + 3). Here each workload runs a WARM set first and then the TARGET;
TARGET is recorded. N*/C13/CR/S* warm with DIFFERENT prompts of the same roles and window (prefix cache warm, recent
answers realistic, as in the app); B* keep ab_v2.py's same-prompt warm-up for continuity with earlier numbers.

Workloads
  B1 B4 B8 B13 M10     ab_v2.py workloads, warm = same prompts (optimistic; continuity only)
  N1 N4 N8 N13 NM10    same shapes, warm = disjoint prompts (seed-24 placement events)
  C13                  chaos-like: 13 x 4 h app prompts (3 AQ, 2 power, 3 water, 3 weather, 2 HVAC; parity fixtures,
                       agent prefill appended as the backend does), warm = other 4 h fixtures
  CR                   real chaos agent prompts from app_breakdown.py (chaos_prompts.jsonl: first incident = warm,
                       second = target); skipped if the file is missing
  S2                   2-domain synthesizer prompts from the app (refine_v7), warm = another synth prompt
  SC                   chaos synthesizer prompts (synth_prompts.jsonl from app_breakdown.py); skipped if missing
  COLD13               C13 with no warm-up; run it FIRST after an htpd start to measure the cold-start penalty
Agent workloads are split at --max-batch like the backend (10 -> 13 = 10 + 3; 14 for the one-batch arms).

  py -3 ab_ladder.py TAG [--only N1,N13,C13] [--max-batch 10] [--base TAG] [--stream] [--no-log]
Writes ab_<TAG>.json: per workload total/prefill/swap/first-progress, tokens, stops, texts, NSP temperature before,
and (unless --no-log) the htpd log lines of the TARGET run: prefix cache and "draft steps .. proposed .. accepted
[.. rows .. decode_ms]" per batch, so ms per decode step and rows per step can be computed.
"""
import argparse, json, re, socket, subprocess, time
from pathlib import Path

H = Path(__file__).resolve().parent
Q = Path(r"C:\Users\hp\Desktop\qidk")
ADB = str(Q / "Code/platform-tools/adb.exe")
P24 = Q / "proofs/2026-10-21_v2_confirm/placement_s24/prompts.jsonl"
FIX = Q / "Code/smart-city-edge-agent/app/backend/testdata/v2_prompt_fixtures.json"
AGENT_PREFILL = '{"pattern": "'
DEV_LOG = "/data/local/tmp/htpd_ab.log"


def adb(*args, timeout=30):
    try:
        r = subprocess.run([ADB, *args], capture_output=True, timeout=timeout, env={"MSYS_NO_PATHCONV": "1", **__import__("os").environ})
        return r.stdout.decode("utf-8", "replace")
    except Exception:
        return ""


def nsp_c():
    """Hottest NSP (NPU) junction in C, as the backend's thermal guard reads it (zones whose type starts with nsp),
    or None if no plausible value (run_ab.sh read 0 from one zone and therefore never cooled)."""
    out = adb("shell", "for z in /sys/class/thermal/thermal_zone*; do case $(cat $z/type 2>/dev/null) in nsp*) cat $z/temp;; esac; done")
    v = [int(t) for t in out.split() if t.isdigit() and 15000 < int(t) < 130000]
    return max(v) / 1000 if v else None


def log_size():
    s = adb("shell", f"wc -c < {DEV_LOG} 2>/dev/null").strip()
    return int(s) if s.isdigit() else None


def log_since(off):
    if off is None:
        return ""
    return adb("shell", f"tail -c +{off + 1} {DEV_LOG}", timeout=60)


def workloads():
    w = {}
    p24 = [json.loads(l) for l in open(P24, encoding="utf-8")]
    ev = [p for p in p24 if not p["truth"].get("clean")]

    def pick(d, ns, k, skip=0):
        out, seen = [], set()
        for p in ev:
            if p["d"] == d and p["n"] in ns and p["id"] not in seen:
                seen.add(p["id"])
                if len(seen) > skip:
                    out.append(p["prompt"])
            if len(out) == k:
                break
        return out
    for k in (1, 4, 8, 13):
        tgt = pick(8, (48,), k)
        w[f"B{k}"] = ("agents", tgt, tgt)
        w[f"N{k}"] = ("agents", pick(8, (48,), k, skip=13), tgt)
    m10 = pick(36, (96,), 5) + pick(36, (144,), 5)
    w["M10"] = ("agents", m10, m10)
    w["NM10"] = ("agents", pick(36, (96,), 5, skip=5) + pick(36, (144,), 5, skip=5), m10)

    fx = json.load(open(FIX, encoding="utf-8"))["fixtures"]
    by = {}
    for f in fx:
        if f["n"] == 48:
            by.setdefault(f["role"], []).append(f["prompt"] + AGENT_PREFILL)
    mix = {"air_quality": 3, "power": 2, "water": 3, "weather": 3, "hvac": 2}
    tgt = [p for r, k in mix.items() for p in by[r][:k]]
    warm = [p for r, k in mix.items() for p in by[r][k:k + max(1, k)]]
    w["C13"] = ("agents", warm, tgt)
    w["COLD13"] = ("agents", [], tgt)

    cp = H / "chaos_prompts.jsonl"
    if cp.exists():
        incs = [json.loads(l) for l in open(cp, encoding="utf-8")]
        if len(incs) >= 2:
            w["CR"] = ("agents", incs[0]["prompts"], incs[1]["prompts"])
    syn = []
    for f in sorted(Q.glob("proofs/2026-10-21_v2_app/refine_v7/INC-*_early.json")):
        fin = json.load(open(f, encoding="utf-8")).get("final") or {}
        if fin.get("prompt") and fin.get("latency_ms"):
            syn.append(fin["prompt"])
    if len(syn) >= 2:
        w["S2"] = ("synth", syn[1:2], syn[0:1])
    sp = H / "synth_prompts.jsonl"
    if sp.exists():
        ss = [json.loads(l)["prompt"] for l in open(sp, encoding="utf-8")]
        if len(ss) >= 2:
            w["SC"] = ("synth", ss[0:1], ss[1:2])
    return w


def call(req, stream):
    s = socket.create_connection(("127.0.0.1", 8091), timeout=600)
    t0 = time.time()
    if stream:
        req = dict(req, stream=True)
    s.sendall((json.dumps(req) + "\n").encode())
    buf, first = b"", None
    while True:
        d = s.recv(1 << 20)
        if not d:
            break
        buf += d
        while b"\n" in buf:
            line, buf = buf.split(b"\n", 1)
            o = json.loads(line)
            if o.get("kind") in ("tok", "toks"):
                if first is None:
                    first = time.time() - t0
                continue
            s.close()
            if o.get("error"):
                raise RuntimeError(o["error"])
            o["_wall_s"], o["_first_s"] = time.time() - t0, first
            return o
    raise RuntimeError("connection closed without a result")


def run(kind, prompts, max_batch, stream):
    parts = []
    if kind == "synth":
        for p in prompts:
            parts.append(call({"kind": "synth", "prompt": p}, stream))
    else:
        for c in range(0, len(prompts), max_batch):
            parts.append(call({"kind": "agents", "prompts": prompts[c:c + max_batch]}, stream))
    return parts


DR = re.compile(r"draft steps (\d+) proposed (\d+) accepted (\d+)(?: rows (\d+) decode_ms (\d+))?")
PC = re.compile(r"prefix cache: (\d+) hit, (\d+) saved, (\d+) member restores, (\d+) skipped, (\d+) ms")


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("tag")
    ap.add_argument("--only")
    ap.add_argument("--base")
    ap.add_argument("--stream", action="store_true")
    ap.add_argument("--max-batch", type=int, default=10, help="split like the backend: 10 for 10x1280, 14 for the one-batch layout")
    ap.add_argument("--no-log", action="store_true", help="do not read the htpd log over adb")
    a = ap.parse_args()
    W = workloads()
    keys = a.only.split(",") if a.only else [k for k in W if not k.startswith("B") and k not in ("M10",)]
    res = {}
    for k in keys:
        if k not in W:
            print(f"{a.tag} {k}: not available (missing input file?)")
            continue
        kind, warm, tgt = W[k]
        c0 = nsp_c()
        if warm:
            run(kind, warm, a.max_batch, a.stream)
        off = None if a.no_log else log_size()
        t0 = time.time()
        parts = run(kind, tgt, a.max_batch, a.stream)
        wall = time.time() - t0
        lg = "" if a.no_log else log_since(off)
        outs = [o for q in parts for o in q["outputs"]]
        x = res[k] = {
            "kind": kind, "n": len(tgt), "batches": len(parts), "nsp_c_before": c0,
            "total_ms": round(sum(q.get("total_ms", 0) for q in parts), 1),
            "prefill_ms": round(sum(q.get("prefill_ms", 0) for q in parts), 1),
            "swap_ms": round(sum(q.get("swap_ms", 0) for q in parts), 1),
            "per_batch_ms": [round(q.get("total_ms", 0)) for q in parts],
            "wall_s": round(wall, 2), "first_progress_s": parts[0]["_first_s"] and round(parts[0]["_first_s"], 2),
            "texts": [o["text"] for o in outs], "stops": [o.get("stop") for o in outs], "tokens": [o.get("tokens") for o in outs],
            "ttft_ms": [o.get("ttft_ms") for o in outs], "ms": [o.get("ms") for o in outs],
            "draft": [dict(zip(("steps", "proposed", "accepted", "rows", "decode_ms"), [int(v) if v else None for v in m.groups()])) for m in DR.finditer(lg)],
            "prefix_cache": [dict(zip(("hit", "saved", "restores", "skipped", "ms"), map(int, m.groups()))) for m in PC.finditer(lg)],
        }
        if len(x["draft"]) == len(parts):  # v7 logs no decode_ms: decode = batch total - batch prefill
            for d, q in zip(x["draft"], parts):
                if d.get("decode_ms") is None:
                    d["decode_ms"] = round(q.get("total_ms", 0) - q.get("prefill_ms", 0))
        for d in x["draft"]:
            if d["steps"]:
                d["accept_per_step"] = round(d["accepted"] / d["steps"], 2)
                if d.get("rows"):
                    d["rows_per_step"] = round(d["rows"] / d["steps"], 1)
                if d.get("decode_ms"):
                    d["ms_per_step"] = round(d["decode_ms"] / d["steps"], 1)
        st = {s: x["stops"].count(s) for s in set(x["stops"])}
        print(f"{a.tag} {k}: n={x['n']} in {x['batches']} batch(es) total {x['total_ms']/1e3:.2f}s prefill {x['prefill_ms']/1e3:.2f}s "
              f"swap {x['swap_ms']:.0f}ms per-batch {x['per_batch_ms']} nsp {c0} stops {st} "
              f"steps {[d['steps'] for d in x['draft']]} ms/step {[d.get('ms_per_step') for d in x['draft']]}", flush=True)
    out = H / f"ab_{a.tag}.json"
    json.dump(res, open(out, "w"), indent=1)
    if a.base and (H / f"ab_{a.base}.json").exists():
        b = json.load(open(H / f"ab_{a.base}.json"))
        tot = same = 0
        for k in res:
            if k in b:
                tot += len(res[k]["texts"])
                same += sum(x == y for x, y in zip(res[k]["texts"], b[k]["texts"]))
        print(f"{a.tag}: identical texts vs {a.base}: {same}/{tot} (HTP run-to-run floor ~21-24/25 = 84-96%)")


if __name__ == "__main__":
    main()
