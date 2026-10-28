"""A/B table from ab_board.sh outputs: per config and request, total/prefill/decode ms, tokens, stop, JSON validity, and
identity vs the reference config (byte-identical text, or same severity/label/checklist actions)."""
import glob, json, os, re, sys
D = sys.argv[1]; ref = sys.argv[2]
PR = [json.loads(l) for l in open(os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "bench", "prompts.jsonl"), encoding="utf-8")]
def load(p):
    try:
        for ln in open(p, encoding="utf-8"):
            if ln.strip():
                o = json.loads(ln)
                if o.get("kind") not in ("toks", "tok"): return o
    except Exception as e:
        return {"error": str(e)}
    return {}
def fields(t):
    try: j = json.loads(t)
    except Exception:
        try: j = json.loads(t + "}")   # stray-bracket check: the backend's one-bracket repair
        except Exception: return None
    return (j.get("severity"), j.get("label"), tuple(c.get("action") for c in j.get("checklist", [])), j.get("title"))
res = {}
for p in sorted(glob.glob(os.path.join(D, "*_q*_*.json"))):
    m = re.match(r"(.+)_q(\d+)_(\d+)\.json", os.path.basename(p)); name, q, k = m.group(1), int(m.group(2)), int(m.group(3))
    res.setdefault(name, {})[(q, k)] = load(p)
rows = []
for name, d in res.items():
    tot = []
    for (q, k), o in sorted(d.items()):
        if k == 0: continue  # warm-up (swap + prefix state)
        out = (o.get("outputs") or [{}])[0]; t = out.get("text", "")
        r = res.get(ref, {}).get((q, k), {}); rt = ((r.get("outputs") or [{}])[0]).get("text")
        f, rf = fields(t), fields(rt or "")
        same = "bytes" if rt == t else ("fields" if f and rf and f[:3] == rf[:3] else "DIFF")
        g = fields(PR[q]["gold"]) if PR[q]["id"].startswith("rwh:") else None
        gs = "-" if not g or not f else ("=" if f[:2] == g[:2] and f[2][:1] == g[2][:1] else f"{f[0]}/{f[1]}/{f[2][:1]} vs {g[0]}/{g[1]}/{g[2][:1]}")
        rows.append(f"| {name} | q{q} | {o.get('total_ms', 0)/1000:.1f} | {o.get('prefill_ms', 0)/1000:.1f} | {(out.get('ms', 0) - o.get('prefill_ms', 0))/1000:.1f} | {out.get('tokens')} | {out.get('forced')} | {out.get('stop')} | {'ok' if f else 'BAD'} | {same} | {gs} |")
        tot.append(o.get("total_ms", 0) / 1000)
    if tot: rows.append(f"| **{name}** | mean | **{sum(tot)/len(tot):.1f}** | | | | | | | | |")
    a0, a1 = load(os.path.join(D, f"{name}_agents0.json")), load(os.path.join(D, f"{name}_agents1.json"))
    ra = load(os.path.join(D, f"{ref}_agents0.json"))
    ta = lambda o: [x.get("text") for x in o.get("outputs", [])]
    rows.append(f"| {name} | agents | before==after {ta(a0)==ta(a1)}, ==ref {ta(a0)==ta(ra)} | reload {a1.get('reload_ms', a1.get('swap_ms', '-'))} | | | | | | |")
print("| config | req | total s | prefill s | decode s | tokens | forced | stop | json | vs " + ref + " | sev/label/action1 vs gold (RWH) |")
print("|---|---|---|---|---|---|---|---|---|---|---|")
print("\n".join(rows))
