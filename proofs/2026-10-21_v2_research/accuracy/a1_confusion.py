"""Failure analysis of the v2 placement study (device, Q4_0 on htpd). Read-only on proofs/2026-10-20_v2_post.
py -3 a1_confusion.py  -> writes confusion_*.md / a1_*.json next to this script."""
import json, re, sys
from collections import Counter, defaultdict
from pathlib import Path

HERE = Path(__file__).resolve().parent
SRC = HERE.parents[1] / "2026-10-20_v2_post" / "device" / "placement_v2"
V1 = HERE.parents[1] / "2026-10-16_placement_study"


def cut_at_action(text):
    depth, in_str, esc, kstart = 0, False, False, None
    i = 0
    while i < len(text):
        ch = text[i]
        if in_str:
            if esc: esc = False
            elif ch == "\\": esc = True
            elif ch == '"':
                in_str = False
                if kstart is not None:
                    key = text[kstart:i]; j = i + 1
                    while j < len(text) and text[j] in " \t\n": j += 1
                    if depth == 1 and key == "action" and (j >= len(text) or text[j] == ":"):
                        head = text[:kstart - 1].rstrip()
                        if head.endswith(","): head = head[:-1]
                        return head + "}"
                    kstart = None
        else:
            if ch == '"': in_str = True; kstart = i + 1
            elif ch in "{[": depth += 1; kstart = None
            elif ch in "}]":
                depth -= 1; kstart = None
                if depth == 0: return text[:i + 1]
            elif ch not in " \t\n": kstart = None
        i += 1
    return text


def parse(text):
    s = text.find("{")
    if s < 0: return None
    try:
        p = json.loads(cut_at_action(text[s:]))
        return p if isinstance(p, dict) else None
    except Exception:
        return None


def norm(v): return str(v).strip().lower().replace(" ", "_").replace("-", "_")


NUM = r"([-+]?\d+(?:\.\d+)?)"


def evid(prompt):
    u = prompt[prompt.index("user<|end_header_id|>"):]
    e = {}
    m = re.search(r"E4 trend = " + NUM + r".*?\(r2 " + NUM + r"\)", u); e["slope"], e["r2"] = (float(m[1]), float(m[2])) if m else (None, None)
    m = re.search(r"E7 halves " + NUM + r" -> " + NUM + r", curvature " + NUM + r"/h, oscillation crossings (\d+)", u)
    if m: e["h1"], e["h2"], e["curv"], e["cross"] = float(m[1]), float(m[2]), float(m[3]), int(m[4])
    m = re.search(r"E8 noise " + NUM + r", longest flat run (\d+) pts, plateau at max (\d+)", u)
    if m: e["noise"], e["flat"], e["plateau"] = float(m[1]), int(m[2]), int(m[3])
    m = re.search(r"E5 largest 5-min change = " + NUM, u); e["maxjump"] = float(m[1]) if m else None
    m = re.search(r"E2 max = " + NUM, u); e["max"] = float(m[1]) if m else None
    m = re.search(r"E3 min = " + NUM, u); e["min"] = float(m[1]) if m else None
    m = re.search(r"E1 last = " + NUM, u); e["last"] = float(m[1]) if m else None
    m = re.search(r"E9 (.*)", u); e["e9"] = m[1] if m else ""
    m = re.search(r"E10 (.*)", u); e["e10"] = m[1] if m else ""
    m = re.search(r"SERIES \(([^)]*)\): (.*)", u); e["series_kind"] = m[1] if m else None
    e["series_len"] = len(m[2].split()) if m else None
    e["prompt_chars"] = len(prompt)
    return e


def main():
    cases = {c["id"]: c for c in map(json.loads, open(SRC / "cases.jsonl", encoding="utf-8"))}
    prompts = {(p["id"], p["d"], p["n"]): p for p in map(json.loads, open(SRC / "prompts.jsonl", encoding="utf-8"))}
    rows = []
    for r in map(json.loads, open(SRC / "samples.jsonl", encoding="utf-8")):
        p = prompts[(r["id"], r["d"], r["n"])]
        a = parse(r["text"])
        c = cases[r["id"]]
        rows.append({"id": r["id"], "d": r["d"], "n": r["n"], "role": c["role"], "metric": c["metric"], "node": c["node"],
                     "truth": p["truth"]["pattern"], "clean": p["truth"]["clean"],
                     "pred": norm(a.get("pattern", "")) if a else "INVALID",
                     "status": norm(a.get("status", "")) if a else "INVALID",
                     "conf": a.get("confidence") if a else None, "tokens": r["tokens"],
                     "seen": "unseen" if c["node"] in UNSEEN else "seen", **evid(p["prompt"])})
    json.dump(rows, open(HERE / "a1_rows.json", "w"), indent=0)
    out = []
    pats = ["spike", "dip", "step_increase", "step_decrease", "gradual_increase", "gradual_decrease",
            "exponential_increase", "oscillation", "flatline", "erratic"]
    for (d, n) in [(8, 48), (36, 48), (36, 96), (36, 144), (24, 48), (18, 48)]:
        sel = [r for r in rows if r["d"] == d and r["n"] == n and not r["clean"]]
        cm = defaultdict(Counter)
        for r in sel: cm[r["truth"]][r["pred"]] += 1
        acc = sum(r["truth"] == r["pred"] for r in sel) / len(sel)
        out.append(f"\n## d={d} ({d*5} min since onset), window n={n}: pattern accuracy {acc:.3f} (n={len(sel)})\n")
        out.append("| truth | n | acc | predicted (count) |\n|---|---|---|---|")
        for t in pats:
            c = cm[t]; k = sum(c.values())
            if not k: continue
            out.append(f"| {t} | {k} | {c[t]/k:.0%} | " + ", ".join(f"{p} {v}" for p, v in c.most_common() if p != t) + " |")
        # role split
        rs = defaultdict(list)
        for r in sel: rs[r["role"]].append(r["truth"] == r["pred"])
        out.append("\nby role: " + ", ".join(f"{k} {sum(v)/len(v):.0%} (n={len(v)})" for k, v in sorted(rs.items())))
        ps = defaultdict(list)
        for r in sel: ps[(r["role"], r["truth"])].append(r["truth"] == r["pred"])
        out.append("\nrole x pattern (wrong/total): " + "; ".join(f"{k[0][:5]}/{k[1]} {len(v)-sum(v)}/{len(v)}" for k, v in sorted(ps.items()) if len(v) - sum(v) > 0))
    # clean windows
    for n in (48, 96, 144):
        sel = [r for r in rows if r["n"] == n and r["clean"]]
        out.append(f"\nclean n={n}: called " + str(Counter(r["pred"] for r in sel).most_common()) +
                   f"; status!=normal {sum(r['status']!='normal' for r in sel)}/{len(sel)} by role " +
                   str({ro: f"{sum(r['status']!='normal' for r in sel if r['role']==ro)}/{sum(1 for r in sel if r['role']==ro)}" for ro in ('air_quality','water','power')}))
    # d=24 -> d=36 flips at n=48
    key = {(r["id"], r["d"], r["n"]): r for r in rows}
    flips = Counter()
    for r in rows:
        if r["d"] == 36 and r["n"] == 48 and not r["clean"]:
            o = key[(r["id"], 24, 48)]
            flips[(o["truth"] == o["pred"], r["truth"] == r["pred"], r["truth"])] += 1
    out.append("\n## n=48 paired d=24 -> d=36 (right->wrong / wrong->right per pattern)")
    for t in pats:
        out.append(f"{t}: R->W {flips[(True, False, t)]}, W->R {flips[(False, True, t)]}")
    # best-of-ladder: is any window length right?
    out.append("\n## d=36: accuracy by window n and oracle over n")
    sel = defaultdict(dict)
    for r in rows:
        if r["d"] == 36 and not r["clean"]: sel[r["id"]][r["n"]] = r
    orc = sum(any(v[n]["truth"] == v[n]["pred"] for n in v) for v in sel.values())
    maj = 0
    for v in sel.values():
        c = Counter(v[n]["pred"] for n in v).most_common()
        top = c[0][0] if c[0][1] >= 2 else v[48]["pred"]
        maj += top == v[48]["truth"]
    out.append(f"oracle(any of 48/96/144) {orc}/{len(sel)} = {orc/len(sel):.3f}; majority vote 3 lengths (tie->48) {maj}/{len(sel)} = {maj/len(sel):.3f}")
    # reweight to v1 pattern mix
    v1t = Counter(); v1ok = Counter()
    v1prompts = {(p["id"], p["n"]): p["truth"]["pattern"] for p in map(json.loads, open(V1 / "prompts.jsonl", encoding="utf-8"))}
    v1rows = [json.loads(l) for l in open(V1 / "samples.jsonl", encoding="utf-8")]
    v1cm = defaultdict(Counter); v1rule = Counter()
    for r in v1rows:
        if r["n"] != 36: continue
        t = v1prompts[(r["id"], 36)]; a = parse(r["text"]); pr = norm(a.get("pattern", "")) if a else "INVALID"
        v1t[t] += 1; v1ok[t] += pr == t; v1cm[t][pr] += 1; v1rule[t] += r.get("rule") == t
    v1role = Counter(); v1roleok = Counter()
    v1cases = {c["id"]: c for c in map(json.loads, open(V1 / "cases.jsonl", encoding="utf-8"))}
    for r in v1rows:
        if r["n"] != 36: continue
        t = v1prompts[(r["id"], 36)]; a = parse(r["text"]); pr = norm(a.get("pattern", "")) if a else "INVALID"
        ro = v1cases[r["id"]]["role"]; v1role[ro] += 1; v1roleok[ro] += pr == t
    v2t = Counter(); v2ok = Counter()
    for r in rows:
        if r["d"] == 36 and r["n"] == 48 and not r["clean"]:
            v2t[r["truth"]] += 1; v2ok[r["truth"]] += r["truth"] == r["pred"]
    a_v2_on_v1mix = sum(v1t[t] * v2ok[t] / v2t[t] for t in v1t) / sum(v1t.values())
    a_v1_on_v2mix = sum(v2t[t] * v1ok[t] / v1t[t] for t in v2t) / sum(v2t.values())
    out.append("\n## Apples-to-apples at 3 h (d=36, 4 h window)")
    out.append(f"v1: {sum(v1ok.values())}/{sum(v1t.values())} = {sum(v1ok.values())/sum(v1t.values()):.3f}; v2: {sum(v2ok.values())}/{sum(v2t.values())} = {sum(v2ok.values())/sum(v2t.values()):.3f}")
    out.append(f"v2 per-pattern acc reweighted to v1 mix: {a_v2_on_v1mix:.3f}; v1 reweighted to v2 mix: {a_v1_on_v2mix:.3f}")
    out.append("v1 by role at d=36: " + ", ".join(f"{k} {v1roleok[k]}/{v1role[k]}" for k in v1role))
    out.append("| pattern | v1 n | v1 acc | v1 rules acc | v2 n | v2 acc |\n|---|---|---|---|---|---|")
    for t in pats:
        out.append(f"| {t} | {v1t[t]} | {v1ok[t]/max(1,v1t[t]):.0%} | {v1rule[t]/max(1,v1t[t]):.0%} | {v2t[t]} | {v2ok[t]/max(1,v2t[t]):.0%} |")
    out.append("\nv1 d=36 confusions: " + "; ".join(f"{t}: " + ", ".join(f"{p} {v}" for p, v in v1cm[t].most_common() if p != t) for t in pats if v1cm[t][t] < v1t[t]))
    # base-window overlap between v1 and v2 cases
    k1 = {(c["node"], c["metric"], c["end_epoch"]) for c in v1cases.values()}
    k2 = {(c["node"], c["metric"], c["end_epoch"]) for c in cases.values() if c["pattern"] != "clean"}
    out.append(f"\nshared base windows v1/v2 events: {len(k1 & k2)} of {len(k2)}")
    (HERE / "confusion_v2_placement.md").write_text("# v2 placement study: confusion analysis (device Q4_0)\n" + "\n".join(out), encoding="utf-8")
    print("\n".join(out))


UNSEEN = set()
if __name__ == "__main__":
    main()
