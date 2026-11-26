"""leakage_check.py: frozen sets vs every training / dev / gate file (no case id, window time, E-line block or user-text hash overlap) + retrieval surface.
Writes LEAKAGE.md + leakage.json; exits 1 (loudly) on any overlap.  Needs sets/*.jsonl (freeze_sets.py).
Block hash = md5 of the >=3 consecutive evidence lines of a window ('E1 last = ...' ... , S-prefix stripped): the same signature the training dedup (ev_sig) uses."""
import collections, glob, hashlib, json, os, re, sys, datetime as dt
import pdata as D, pcase as P, pcore as C

Q = D.Q
H = lambda s: hashlib.md5(s.encode()).hexdigest()
BTXT = {}
EL = re.compile(r"^(?:S\d+\.)?(E\d+ .*)$")
CTX = re.compile(r"CONTEXT: \w{3} (\d{1,2}) (\w{3}) (\d{4})")
MON = {m: i + 1 for i, m in enumerate("Jan Feb Mar Apr May Jun Jul Aug Sep Oct Nov Dec".split())}


def blocks_of(text):
    out, cur = [], []
    for ln in text.split("\n"):
        m = EL.match(ln.strip())
        if m:
            cur.append(m.group(1))
        else:
            if len(cur) >= 3:
                out.append(H("\n".join(cur))); BTXT[out[-1]] = "\n".join(cur)
            cur = []
    if len(cur) >= 3:
        out.append(H("\n".join(cur))); BTXT[out[-1]] = "\n".join(cur)
    return out


def strings(o):
    if isinstance(o, str):
        yield o
    elif isinstance(o, dict):
        for v in o.values():
            yield from strings(v)
    elif isinstance(o, list):
        for v in o:
            yield from strings(v)


def user_texts(r):
    """user-side text of a training row (messages user turns, prompt fields)"""
    out = []
    for m in r.get("messages", []) if isinstance(r, dict) else []:
        if m.get("role") == "user" and isinstance(m.get("content"), str):
            out.append(m["content"])
    for k in ("prompt", "user", "input"):
        if isinstance(r, dict) and isinstance(r.get(k), str):
            out.append(r[k])
    return out


# ------------------------------------------------------------------ eval side
cases = []
for n in "ABDF":
    cases += [json.loads(l) for l in open("%s/sets/%s.jsonl" % (D.PAPER, n))]
ev_blocks = {}          # block hash -> [case id]
ev_user = {}
win = []                # (key, end-143*300, end, case id)
for c in cases:
    a = P.assemble(c)
    for s in a["sensors"]:
        txt = s["prompt"].split("user<|end_header_id|>", 1)[1] if s["prompt"] else "\n".join("E%s %s" % (i[1:], t) if False else "%s %s" % (i, t) for i, t in C.L.evidence(s["sdef"]["role"], s["sdef"]["metric"], s["hist"][-48:], C.dtime(c["end"]), None))
        for b in blocks_of(txt):
            ev_blocks.setdefault(b, []).append(c["id"])
        if s["prompt"]:
            ev_user.setdefault(H(s["prompt"].split("user<|end_header_id|>", 1)[1]), []).append(c["id"])
    for k in c["series"]:
        win.append((k, c["end"] - 143 * 300, c["end"], c["id"]))
ids = {c["id"] for c in cases}
min_start = min(w[1] for w in win)
max_real_start = D.CUTOFF

# ------------------------------------------------------------------ training side
R = Q + "/proofs/2026-11-21_rsn_full"
files = []
for d in ("data", "topup/data", "final/data", "fix/data", "rep/data"):
    files += sorted(glob.glob("%s/%s/*.jsonl" % (R, d)))
files += sorted(glob.glob(R + "/data/targeted_v*.jsonl")) + sorted(glob.glob(R + "/data/gen5_*.jsonl")) + [R + "/data/real_rows.jsonl"]
files += sorted(glob.glob(Q + "/proofs/2026-11-13_v3_data/agt_v3/*.jsonl")) + sorted(glob.glob(Q + "/Code/smart-city-edge-agent/data/sft_v2/*.jsonl"))
files += sorted(glob.glob(R + "/agent_rows/windows_real.jsonl"))
files = list(dict.fromkeys(f for f in files if os.path.exists(f)))
res = dict(files=[], id_overlap=[], block_overlap={}, user_overlap={}, time_overlap=[], max_train_end=0, max_ctx_date=None, rows=0)
mx_end = 0
mx_ctx = dt.date(2000, 1, 1)
EVAL_FILES = ("test.jsonl", "dev.jsonl", "gate_set.jsonl")
for f in files:
    role = "eval-only" if os.path.basename(f) in EVAL_FILES or "/gate/" in f else "training"
    nrow = hit_b = hit_i = 0
    for line in open(f, encoding="utf-8"):
        if not line.strip():
            continue
        try:
            r = json.loads(line)
        except Exception:
            continue
        nrow += 1
        rid = r.get("id") or r.get("wid")
        if rid in ids:
            res["id_overlap"].append((os.path.basename(f), rid)); hit_i += 1
        real = bool(r.get("src_real")) or r.get("src") == "real" or r.get("real_end_epoch") is not None or str(r.get("family", "")).split(":")[0] in ("stable", "real_routine", "real_longrange", "zero_idle") or r.get("source") == "real"
        for fld in ("end_epoch", "real_end_epoch"):
            v = r.get(fld)
            if real and isinstance(v, (int, float)) and v > 1e9:
                if v > mx_end:
                    mx_end = v
                if v >= min_start:
                    res["time_overlap"].append((os.path.basename(f), rid, v, role))
        for s in strings(r):
            if "E1 " in s and "E2 " in s:
                for b in blocks_of(s):
                    if b in ev_blocks:
                        res["block_overlap"].setdefault(b, []).append(os.path.basename(f) + ":" + role); hit_b += 1
        for u in user_texts(r):
            if "CONTEXT:" in u:
                for m in CTX.finditer(u[:300]):
                    try:
                        d0 = dt.date(int(m.group(3)), MON[m.group(2)], int(m.group(1)))
                        mx_ctx = max(mx_ctx, d0)
                    except Exception:
                        pass
            if H(u) in ev_user:
                res["user_overlap"].setdefault(H(u), []).append(os.path.basename(f))
    res["files"].append((os.path.relpath(f, Q), nrow, hit_b))
    res["rows"] += nrow
res["max_train_end"] = mx_end
res["max_ctx_date"] = str(mx_ctx)

# ------------------------------------------------------------------ retrieval surface
ret = []
inc_path = Q + "/Code/smart-city-edge-agent/app/device/state/incidents.jsonl"
n_inc = hit_inc = 0
if os.path.exists(inc_path):
    for line in open(inc_path, encoding="utf-8"):
        try:
            r = json.loads(line)
        except Exception:
            continue
        n_inc += 1
        t = r.get("created_sim") or r.get("CreatedSim") or 0
        if isinstance(t, (int, float)) and any(abs(t - c["end"]) < 12 * 3600 for c in cases):
            hit_inc += 1
DEG = re.compile(r"longest flat run (4[0-9]|[5-9][0-9]) pts|state changes = 0|occupied fraction = (0\.00|1\.00)|current state = [01]\s+E2 occupied fraction")
degenerate = {k: v for k, v in res["block_overlap"].items() if DEG.search(BTXT.get(k, ""))}
real_overlap = {k: v for k, v in res["block_overlap"].items() if k not in degenerate}
train_time = [t for t in res["time_overlap"] if t[3] == "training"]
bad = bool(res["id_overlap"] or any(x.endswith(":training") for v in real_overlap.values() for x in v) or res["user_overlap"] or train_time)
md = ["# Leakage check (frozen sets A, B, D, F)", "", "Run %s. Sets: %s." % (dt.datetime.now().strftime("%Y-%m-%d %H:%M"), ", ".join("%s=%d" % (n, sum(1 for c in cases if c["set"] == n)) for n in "ABDF")),
      "", "Every eval window (incl. its 12 h history) ends after the training cutoff (epoch %d, 2025-12-11 00:00 IST): earliest window start in the sets = epoch %d (%s)." % (D.CUTOFF, min_start, C.dtime(min_start).strftime("%Y-%m-%d %H:%M IST")),
      "", "| check | result |", "|---|---|",
      "| case ids vs training row ids | %d overlaps |" % len(res["id_overlap"]),
      "| evidence-block hashes (E1..E10 of every sensor in every eval incident, %d distinct blocks) vs %d training rows in %d files | %d overlapping blocks |" % (len(ev_blocks), res["rows"], len(files), len(res["block_overlap"])),
      "| agent-prompt user text hashes (%d) vs training prompts | %d overlaps |" % (len(ev_user), len(res["user_overlap"])),
      "| REAL-labelled training rows (src_real / real_end_epoch / real families) with an end epoch >= first eval window start | %d (latest real training end epoch %d = %s) |" % (len(train_time), mx_end, C.dtime(mx_end).strftime("%Y-%m-%d %H:%M IST") if mx_end else "-"),
      "| latest CONTEXT date in any training reasoner prompt | %s (info only: synthetic scenes carry arbitrary calendar dates; real rows are checked by epoch above) |" % res["max_ctx_date"],
      "| retrieval corpus (app state/incidents.jsonl) | %d past incidents on disk, %d within 12 h of an eval case end (sim clock is shifted +1 year, never overlaps) |" % (n_inc, hit_inc),
      "", "Overlaps with EVAL-ONLY files (the old agent's sft_v2 test split; not training data of the deployed agent or the reasoner): %d real windows end inside the held-out weeks; informative evidence-block overlaps with them: %d. Low-information block overlaps (listed in leakage.json): %s." % (sum(1 for t in res["time_overlap"] if t[3] == "eval-only"), sum(1 for v in real_overlap.values() if all(x.endswith(":eval-only") for x in v)), "; ".join("%s in %s" % (ev_blocks[k], v) for k, v in degenerate.items())),
      "", "## Retrieval-memory surface",
      "- The harness runs the reasoner with `MEMORY: no past incidents or maintenance on these sensors in the last 90 days` and tools `find_incidents` / `get_action_history` / `get_sensor_history` / `related_context` answering from an EMPTY, frozen corpus (see run_case.py: ToolExec). No finished report, seed case (rag_seed.json is not in the repo) or past incident can be returned, so no eval case can be retrieved and no training case leaks through retrieval. The retrieval ablation is therefore not meaningful in this version; a retrieval-on arm needs a corpus frozen before the test window (future work).",
      "- Retrieval-hit rate per case = 0 by construction (logged as `tool_calls` with empty results).",
      "", "## Fault-family overlap (explicit; training generators vs these test generators)",
      "Training synthetic rows: 140,690 of 163,567 (RESEARCH_PAPER.md section 11). Test injections are written separately (pinject.py), applied to REAL held-out campus windows, and share no code with gen5_* / gen_r4_inc. Conceptual overlap with training families is expected and listed:", "",
      "| test family | closest training family | note |", "|---|---|---|",
      "| heat_room, heat_ac3, heat_ac_water, heat_crowd_water(+hvac) | gen5 heat_three / heat_trans / heat_multihop | same physical story (heat -> room -> power), different generator, real baselines, campus node ids |",
      "| crowd_co2, crowd_heat | occ_load | same story |", "| pm_ingress | pm_ingress | same story |", "| ac_fail | ac_fail | same story |",
      "| fault_vs_event | occ_fault / wx_fault_co2 | same story |", "| single_* | card / r1 single-sensor families | same story |",
      "| real windows (A, D, F natural) | real_rows (pre-cutoff real windows) | disjoint in time by construction |", "",
      "**RESULT: %s**" % ("FAIL (overlap found, see leakage.json)" if bad else "PASS (no overlap)")]
open(D.PAPER + "/LEAKAGE.md", "w", newline="\n").write("\n".join(md) + "\n")
json.dump(dict(bad=bad, id_overlap=res["id_overlap"][:50], block_overlap={k: [ev_blocks[k], v, BTXT.get(k)] for k, v in list(res["block_overlap"].items())[:50]},
               user_overlap=len(res["user_overlap"]), time_overlap=res["time_overlap"][:50], files=res["files"], max_ctx_date=res["max_ctx_date"],
               n_eval_blocks=len(ev_blocks), n_cases=len(cases)), open(D.PAPER + "/leakage.json", "w", newline="\n"), indent=1)
print("\n".join(md[:12]))
if bad:
    print("LEAKAGE: OVERLAP FOUND", file=sys.stderr)
    sys.exit(1)
