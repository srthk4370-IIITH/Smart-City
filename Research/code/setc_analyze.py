"""setc_analyze.py: Set C board results -> results/setc_board.json + markdown table (stdout).
  forced-schema run (think off, split 3): board dir pulled to results/setc_board_raw/ (setc_board.sh outputs: <case>_a*.out, <case>_r.out, timing.jsonl, htpd.log)
  adaptive run (think adaptive, no split): results/board_drive/setc_adaptive.jsonl (board_drive.py)
usage: python setc_analyze.py"""
import json, os, re, statistics as S
HERE = os.path.dirname(os.path.abspath(__file__))
RAW = os.path.join(HERE, "results", "setc_board_raw")
MAN = json.load(open(os.path.join(HERE, "sets", "C", "MANIFEST.json"), encoding="utf-8"))
NS = (1, 2, 4, 8, 12)


def last(p):
    if not os.path.exists(p):
        return None
    ls = [l for l in open(p, encoding="utf-8", errors="replace").read().split("\n") if l.strip()]
    for l in reversed(ls):
        try:
            d = json.loads(l)
        except Exception:
            continue
        if d.get("kind") not in ("tok", "toks"):
            return d
    return None


def valid_report(t):
    try:
        o = json.loads(t)
    except Exception:
        m = re.search(r"\{.*\}", t or "", re.S)
        try:
            o = json.loads(m.group(0)) if m else None
        except Exception:
            o = None
    return isinstance(o, dict) and o.get("severity") in ("critical", "warning", "normal", "sensor_fault") and bool(o.get("label"))


def med(xs):
    xs = [x for x in xs if x is not None]
    return round(S.median(xs), 2) if xs else None


def forced_run():
    tim = {}
    for l in open(os.path.join(RAW, "timing.jsonl")):
        d = json.loads(l)
        if "wall_ms" in d:
            tim[d["tag"]] = d
    rows = []
    for c in MAN["cases"]:
        n = c["name"]; ag = []
        k = 0
        while os.path.exists(os.path.join(RAW, "%s_a%d.out" % (n, k))):
            a = last(os.path.join(RAW, "%s_a%d.out" % (n, k))); ag.append((a, tim.get("%s_a%d" % (n, k))))
            k += 1
        r = last(os.path.join(RAW, n + "_r.out"))
        if r is None:
            continue
        o = (r.get("outputs") or [{}])
        rs = r.get("reason") or {}
        rows.append(dict(name=n, N=c["N"], agent_calls=c["agent_calls"], agents_wall_s=sum((t or {}).get("wall_ms", 0) for a, t in ag) / 1000,
                         agents_prefill_s=sum((a or {}).get("prefill_ms", 0) for a, t in ag) / 1000, agents_swap_s=sum((a or {}).get("swap_ms", 0) for a, t in ag) / 1000,
                         reasoner_wall_s=tim[n + "_r"]["wall_ms"] / 1000, reasoner_total_s=(r.get("total_ms") or 0) / 1000, swap_in_s=(r.get("swap_ms") or 0) / 1000,
                         prefill_s=(r.get("prefill_ms") or 0) / 1000, ttft_s=(o[0].get("ttft_ms") or 0) / 1000, tokens=sum(x.get("tokens") or 0 for x in o),
                         stop=o[0].get("stop"), cache=rs.get("cache"), cached_tokens=rs.get("cached_tokens"), valid=valid_report(o[0].get("text") or ""),
                         error=r.get("error")))
    ov = last(os.path.join(RAW, "ovf_x0_r.out"))
    return rows, ov


def adaptive_run():
    p = os.path.join(HERE, "results", "board_drive", "setc_adaptive.jsonl")
    if not os.path.exists(p):
        return []
    N = {c["name"]: c["N"] for c in MAN["cases"]}
    rows = []
    for l in open(p, encoding="utf-8"):
        d = json.loads(l); st = d["reasoner"]["steps"]
        if d["id"] not in N:
            continue
        rows.append(dict(name=d["id"], N=N[d["id"]], agents_wall_s=d["agents_wall_s"], reasoner_wall_s=d["reasoner_wall_s"], calls=len(st), forced=d["reasoner"]["forced"],
                         think_chars=len(d["reasoner"]["think"] or ""), swap_in_s=((st[0]["reason"].get("swap_ms") or 0) / 1000), ttft_s=(st[0]["ttft_ms"] or 0) / 1000,
                         tokens=sum(s["tokens"] or 0 for s in st), valid=valid_report(d["reasoner"]["final"])))
    return rows


def table(rows, keys):
    out = {}
    for N in NS:
        rr = [r for r in rows if r["N"] == N]
        if rr:
            out[N] = dict(n=len(rr), **{k: med([r.get(k) for r in rr]) for k in keys}, valid=sum(r["valid"] for r in rr))
    return out


fr, ov = forced_run()
ar = adaptive_run()
res = dict(forced=table(fr, ["agent_calls", "agents_wall_s", "agents_prefill_s", "reasoner_wall_s", "swap_in_s", "prefill_s", "ttft_s", "tokens", "cached_tokens"]),
           adaptive=table(ar, ["agents_wall_s", "reasoner_wall_s", "swap_in_s", "ttft_s", "tokens", "calls", "think_chars"]),
           stops={N: sorted({r["stop"] for r in fr if r["N"] == N}) for N in NS},
           overflow=({k: v for k, v in ov.items() if k != "outputs"} | {"outputs": [{k: v for k, v in o.items() if k != "text"} for o in ov.get("outputs") or []]}) if ov else None,
           rows_forced=fr, rows_adaptive=ar)
json.dump(res, open(os.path.join(HERE, "results", "setc_board.json"), "w"), indent=1)
print(json.dumps({k: res[k] for k in ("forced", "adaptive", "stops", "overflow")}, indent=1))
