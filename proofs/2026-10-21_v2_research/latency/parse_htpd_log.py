"""Turn a pulled htpd.log into per-batch decode-step numbers (no device access from this script).

The main session pulls the log:  adb pull /data/local/tmp/smart_city_edge/state/htpd.log  <dir>/
htpd prints, per agents batch (app/htpd/htpd.cpp):
  htpd: prefix cache: H hit, S saved, C member restores, K skipped, X ms, cache N
  htpd: draft steps T proposed P accepted A
The backend trace (logcat / backend log) prints per batch:
  Prefetch(htpd): n agents in one batch, W ms (prefill F ms)
Pair them in order to get ms per decode step = (W - F) / T, and the acceptance rate A / P.
Usage: python parse_htpd_log.py htpd.log [backend.log]
"""
import re, sys, statistics as st, json

pc = re.compile(r"prefix cache: (\d+) hit, (\d+) saved, (\d+) member restores, (\d+) skipped, (\d+) ms")
dr = re.compile(r"draft steps (\d+) proposed (\d+) accepted (\d+)")
pf = re.compile(r"Prefetch\(htpd\): (\d+) agents in one batch, (\d+) ms \(prefill (\d+) ms\)")

def main(path, backend=None):
    pcs, drs = [], []
    for line in open(path, errors="replace"):
        m = pc.search(line)
        if m:
            pcs.append(dict(hit=int(m[1]), saved=int(m[2]), restores=int(m[3]), skipped=int(m[4]), ms=int(m[5])))
        m = dr.search(line)
        if m:
            drs.append(dict(steps=int(m[1]), proposed=int(m[2]), accepted=int(m[3])))
    out = dict(batches=len(drs))
    if pcs:
        out["prefix_cache_ms_median"] = st.median(p["ms"] for p in pcs)
        out["prefix_cache_ms_per_restore"] = round(sum(p["ms"] for p in pcs) / max(1, sum(p["restores"] + p["hit"] for p in pcs)), 1)
    if drs:
        out["steps_median"] = st.median(d["steps"] for d in drs)
        out["accept_rate"] = round(sum(d["accepted"] for d in drs) / max(1, sum(d["proposed"] for d in drs)), 3)
    if backend:
        bs = [dict(n=int(m[1]), wall=int(m[2]), prefill=int(m[3])) for m in (pf.search(l) for l in open(backend, errors="replace")) if m]
        pairs = list(zip(bs[-len(drs):], drs[-len(bs):])) if bs and drs else []
        rows = [dict(n=b["n"], ms_per_step=round((b["wall"] - b["prefill"]) / d["steps"], 1), steps=d["steps"]) for b, d in pairs if d["steps"]]
        by_n = {}
        for r in rows:
            by_n.setdefault(r["n"], []).append(r["ms_per_step"])
        out["ms_per_step_by_streams"] = {n: dict(batches=len(v), median=st.median(v)) for n, v in sorted(by_n.items())}
    print(json.dumps(out, indent=1))

if __name__ == "__main__":
    main(*sys.argv[1:3])
