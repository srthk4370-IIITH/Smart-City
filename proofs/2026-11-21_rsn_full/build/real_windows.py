"""real_windows.py: REAL pre-cutoff windows (sft_v2 train/dev real-baseline families + real_pool) -> agent_rows/windows_real.jsonl
(agt_v3 prompt rebuilt with core/evidence.py, gold passes label-audit judge on the exact E-lines; no overlap with test suites / earlier agent rows)."""
import sys, os, re, json, glob, hashlib, random, collections, datetime as dt
Q = "/mnt/c/Users/hp/Desktop/qidk"; RSN = Q + "/proofs/2026-11-13_v3_data/rsn"; D = Q + "/proofs/2026-11-21_rsn_full"
sys.path.insert(0, RSN); import v2_windows as W
CD, EV, GA, AU = W.CD, W.EV, W.GA, W.AU
H = lambda s: hashlib.md5(s.encode()).hexdigest()
# ---- cutoff
mx = 0
for f in glob.glob(Q + "/Code/smart-city-edge-agent/data/series/*/*.csv"):
    last = None
    for l in open(f): last = l
    try: mx = max(mx, int(float(last.split(",")[0])))
    except Exception: pass
CUT = mx - 21 * 86400
ist = lambda e: dt.datetime.fromtimestamp(e, dt.timezone(dt.timedelta(hours=5, minutes=30))).strftime("%Y-%m-%d %H:%M IST")
open(D + "/CUTOFF.md", "w").write("# Cutoff\nCampus replay data range ends %s (epoch %d). Paper held-out test = last 3 weeks.\n**CUTOFF = epoch %d = %s.** Every row built here has all windows ending strictly before it (real windows: end_epoch < cutoff, checked per row; injected scenes dated 2025-01..2025-12-10; sft_v2 train/dev pool ends %s).\nBoard incidents (old_inc.jsonl): sim clock is shifted +1 year to campus data, only 428 non-injected incidents exist, and their reports are the old board schema with no verified gold -> not used.\n" % (ist(mx), mx, CUT, ist(CUT), "2025-08"))
print("cutoff", CUT, ist(CUT))
# ---- bans (tests + earlier agent windows)
bad = set(); AG = Q + "/proofs/2026-11-20_rsn_big/agent_rows"
def eh(t):
    L = re.findall(r"^E\d+ .*$", t, re.M); return H("\n".join(L)) if len(L) >= 3 else None
for fn in (RSN + "/data/final_v2/work/windows.jsonl", AG + "/windows.jsonl", AG + "/raw_windows.jsonl"):
    for l in open(fn):
        x = json.loads(l); bad.add(eh(x["prompt"]))
for f in glob.glob(RSN + "/data/final_v2/tests/*.jsonl") + glob.glob(Q + "/proofs/2026-11-20_rsn_big/data/final_big/tests/*.jsonl"):
    for l in open(f, encoding="utf-8"):
        for m in re.finditer(r"(?:E\d+ [^\n\"]*\n){3,}", l.replace("\n", "\n")):
            bad.add(H("\n".join(re.findall(r"^E\d+ .*$", m.group(0), re.M))))
bad.discard(None)
REAL = {("stable", "stable"), ("real_routine", None), ("real_longrange", None), ("zero_idle", None), ("occupancy", "real")}
isreal = lambda x: (x["family"], None) in REAL or (x["family"], x["sub"]) in REAL
rows = []
sd = Q + "/Code/smart-city-edge-agent/data/sft_v2/"
for fn in ("train", "dev", "test"):
    for l in open(sd + fn + ".jsonl", encoding="utf-8"):
        x = json.loads(l)
        if isreal(x) and x["end_epoch"] < CUT and x["role"] != "hvac" and x["n"] % 2 == 0 and x["hist"]:
            rows.append(x)
print("candidates", len(rows), collections.Counter(x["family"] for x in rows))
R = random.Random(2111); R.shuffle(rows)
out, st, seen = [], collections.Counter(), set()
for x in rows:
    m = re.search(r"^NODE: (\S+) \(([^)]*)\)", x["prompt"].split("user<|end_header_id|>", 1)[1], re.M)
    loc = m.group(2) if m else x["node"]
    head = [ln for ln in re.findall(r"^(?:LIMITS|TANK):.*$", x["prompt"], re.M)]
    try:
        cid = CD.metric_to_card(x["role"], x["metric"], x["node"], loc)
        card = json.loads(json.dumps(CD.existing_cards()[cid]))
        if cid == "tank_level":
            tl = GA.NODE_LIMITS.get(x["node"]); card["tank"] = {k: tl[k] for k in ("high", "overflow", "fill_min")} if tl else None
        prompt, _, _, _ = EV.agent_prompt(card, x["node"], loc, x["hist"][-144:], x["n"], x["end_epoch"])
    except Exception as ex:
        st["exc:" + type(ex).__name__] += 1; continue
    ev = W.elines(prompt); e = eh(prompt)
    if e in bad or e in seen: st["dup_or_banned"] += 1; continue
    g = {k: x.get(k) for k in ("pattern", "status", "likely_cause", "fault_kind", "event_active", "onset")}
    hd = [h for h in head if h.startswith(("LIMITS:", "TANK:"))] or W.lim_head(card)
    s, why = W.supported(x["role"], x["metric"], g, hd, ev, x["n"], x["end_epoch"])
    if s != "y": st["unsupported"] += 1; continue
    seen.add(e)
    out.append({"wid": "full-%05d" % len(out), "src": "real", "src_real": True, "card_id": cid, "role": x["role"], "metric": x["metric"], "node": x["node"], "loc": loc, "n": x["n"],
                "end_epoch": x["end_epoch"], "prompt": prompt, "head": ["NODE: %s (%s)" % (x["node"], loc), ("METRIC: %s [%s]" % (x["metric"], W.UNIT.get(x["metric"], ""))).replace(" [] ", " ")] + hd,
                "ev": ev, "gold": g, "audit_why": why, "family_agt": x["family"] + ":" + str(x["sub"])})
    st["ok:" + g["status"]] += 1
occ=[o for o in out if o["role"]=="occupancy"]; R.shuffle(occ); out=[o for o in out if o["role"]!="occupancy"]+occ[:900]
nn = [o for o in out if o["gold"]["status"] != "normal"]; no = [o for o in out if o["gold"]["status"] == "normal"]
R.shuffle(no); sel = nn + no[:max(0, 4200 - len(nn))]; R.shuffle(sel)
for i, o in enumerate(sel): o["wid"] = "full-%05d" % i
os.makedirs(D + "/agent_rows", exist_ok=True)
open(D + "/agent_rows/windows_real.jsonl", "w", newline="\n").write("".join(json.dumps(o, ensure_ascii=False) + "\n" for o in sel))
print(len(sel), dict(st), collections.Counter(o["gold"]["status"] for o in sel), collections.Counter(o["role"] for o in sel), max(o["end_epoch"] for o in sel) < CUT)
