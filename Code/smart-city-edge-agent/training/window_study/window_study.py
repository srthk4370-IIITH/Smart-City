"""Window-length study: does the agent see more (and flag better) with a 2 h, 4 h, 8 h or 12 h window?

The fine-tuned agents only ever saw 48-point (4 h x 5 min) windows. This study feeds the SAME model the
same cases at 24 / 48 / 96 / 144 points (5-min samples; the series line keeps its 10-min means, so a longer
window is a longer prompt) and scores each length against known ground truth. Every window ENDS at the
same moment (the evaluation instant), so a short window simply sees less history.

Cases (continuous roles; base = a REAL calm 12 h window from the test split, Nov-Dec):
  clean          the real window untouched                          truth: stable / normal (false-alarm probe)
  classic_<p>    one training pattern injected in the last 4 h      truth: generator labels (as in training)
  step_old       step change 2.5-8 h before the end                 truth: step_increase|step_decrease
  drift_long     slow drift over the last 6-12 h                    truth: gradual_increase|gradual_decrease
  subthr_spikes  3-5 small spikes (below the training spike size     truth: "recurrent anomaly" - any flag
                 and below warning limits) spread over 2-12 h, the   counts as detection; pattern reported
                 last one in the final 30 min
Plus a variety probe: random REAL test-split windows (all 5 roles incl. occupancy, no injection), where
there is no truth and we count how many distinct (pattern, status, cause) outcomes each length surfaces.

  python window_study.py build  --out DIR      # laptop: cases.jsonl (+ prompts per length), dataset hash
  python window_study.py run    --out DIR      # htpd on the QIDK (adb forward tcp:8091), samples.jsonl
  python window_study.py analyze --out DIR     # summary.json, tables.md, plots (SVG)
"""
import argparse
import hashlib
import json
import math
import random
import socket
import sys
import time
from collections import Counter, defaultdict
from datetime import datetime, timedelta
from pathlib import Path

HERE = Path(__file__).resolve().parent
TRAIN = HERE.parent
sys.path.insert(0, str(TRAIN))
sys.path.insert(0, str(TRAIN / "export"))
import features as F  # noqa: E402
import generate_dataset as G  # noqa: E402

LENGTHS = (24, 48, 96, 144)
FULL = max(LENGTHS)
PREFILL = '{"pattern": "'
CONT_ROLES = ("air_quality", "water", "power", "weather")


# ------------------------------------------------------------------ prompt for any length
def _hours(n):
    h = n * F.STEP_MIN / 60
    return f"{h:g}"


def agent_prompt_n(role, node, location, metric, xs, end_epoch):
    """features.agent_prompt generalised to len(xs) points. Identical text at 48 points (asserted)."""
    n = len(xs)
    old = F.WINDOW
    F.WINDOW = n  # idx_time / rule_pattern read the module global
    try:
        m = F.METRICS[(role, metric)]
        dec, unit = m["dec"], m["unit"]
        end = datetime.fromtimestamp(end_epoch, F.IST)
        start = end - timedelta(minutes=F.STEP_MIN * (n - 1))
        lines = [f"NODE: {node} ({location})", f"METRIC: {metric} [{unit or 'ratio'}]"]
        if m["warn"] is not None:
            rel = "below" if m["dir"] == "low" else "above"
            lines.append(f"LIMITS: warning {rel} {m['warn']}, critical {rel} {m['crit']}")
        lines.append(f"WINDOW: {start:%a %d %b %H:%M} -> {end:%H:%M} IST, {n} x 5 min")
        if role == "occupancy":
            st = F.occ_stats(xs)
            lines.append("STATES (1=occupied): " + "".join(str(int(v)) for v in xs))
        else:
            st = F.compute_stats(xs, dec)
            lines.append("SERIES (10-min means): " + " ".join(F.fmt(v, dec) for v in F.downsample(xs, n // 2)))
        lines.append("EVIDENCE:")
        ev = F.evidence_items(role, metric, st, end_epoch, dec, unit)
        for eid, _, text in ev:
            if eid == "E6" and role != "occupancy":
                text = text.replace("mean 4h", f"mean {_hours(n)}h")
            lines.append(f"{eid} {text}")
        user = "\n".join(lines)
        rules = F.SYSTEM_RULES.replace("a 4-hour window", f"a {_hours(n)}-hour window")
        system = F.SYSTEM_PROMPTS[role] + rules + " " + F.output_schema_hint(role)
        rule = F.rule_pattern(role, metric, xs, end_epoch)
        return F.llama3_prompt(system, user), rule
    finally:
        F.WINDOW = old


# ------------------------------------------------------------------ data
def windows_full(series, stride):
    old = F.WINDOW
    F.WINDOW = FULL
    try:
        yield from G.windows(series, stride, min_have=FULL - 6)
    finally:
        F.WINDOW = old


def clamp(y, m):
    return [min(m["hi"], max(m["lo"], v)) for v in y]


def label(role, node, metric, xs, end, pattern, A, s0, base_mean, rng):
    """Ground-truth (pattern, status, cause) exactly as the training generator would label xs."""
    old = F.WINDOW
    F.WINDOW = len(xs)
    try:
        ex = G.make_example(role, node, metric, xs, end, pattern, A, s0, base_mean, rng, "test")
    finally:
        F.WINDOW = old
    return {"pattern": ex["pattern"], "status": ex["status"], "likely_cause": ex["likely_cause"]}


def build(a):
    rng = random.Random(a.seed)
    out = Path(a.out)
    out.mkdir(parents=True, exist_ok=True)
    print("loading series ...", flush=True)
    series = G.load_series()
    calm, real = defaultdict(list), defaultdict(list)
    for (role, node, metric), s in series.items():
        for end, xs in windows_full(s, stride=12):
            if G.split_of(end) != a.split:
                continue
            if role == "occupancy":
                real[role].append((node, metric, end, [1.0 if v >= 0.5 else 0.0 for v in xs]))
                continue
            real[role].append((node, metric, end, xs))
            if not G.is_zero_flat(xs) and G.is_calm(role, metric, xs[-48:]):
                s0, st = G.scale_of(role, metric, xs)
                # whole 12 h calm too (else "clean" would contain real events)
                if st["range"] <= 10 * s0 and abs(st["slope_per_h"]) * 12 <= 4 * s0:
                    calm[role].append((node, metric, end, xs))
    pool_stats = {"calm_12h_windows": {r: len(v) for r, v in calm.items()},
                  "real_12h_windows": {r: len(v) for r, v in real.items()}}
    print(json.dumps(pool_stats), flush=True)

    cases = []

    def add(family, role, node, metric, end, y, truth, extra=None):
        c = {"id": f"C{len(cases):04d}", "family": family, "role": role, "node": node, "metric": metric,
             "end_epoch": end, "xs": [round(v, 6) for v in y], "truth": truth}
        if extra:
            c.update(extra)
        cases.append(c)

    for role in CONT_ROLES:
        pool = calm[role]
        if not pool:
            print(f"WARNING: no calm 12 h windows for {role}")
            continue
        # clean
        for node, metric, end, base in rng.sample(pool, min(a.clean, len(pool))):
            s0, st = G.scale_of(role, metric, base[-48:])
            add("clean", role, node, metric, end, base, label(role, node, metric, base[-48:], end, "stable", 0, s0, st["mean"], rng))
        # classic training patterns in the last 4 h
        for p in F.CONT_PATTERNS:
            if p == "stable":
                continue
            made = tries = 0
            while made < a.classic and tries < a.classic * 40:
                tries += 1
                node, metric, end, base = rng.choice(pool)
                m = F.METRICS[(role, metric)]
                tail = base[-48:]
                s0, bst = G.scale_of(role, metric, tail)
                y48, A = G.inject(p, tail, s0, rng, m["lo"], m["hi"])
                if not G.verify(p, tail, y48, s0, m["dec"]):
                    continue
                add(f"classic_{p}", role, node, metric, end, base[:-48] + y48,
                    label(role, node, metric, y48, end, p, A, s0, bst["mean"], rng))
                made += 1
        # step 2.5-8 h before the end
        for _ in range(a.long):
            node, metric, end, base = rng.choice(pool)
            m = F.METRICS[(role, metric)]
            s0, bst = G.scale_of(role, metric, base)
            k = rng.randint(30, 100)
            sgn = rng.choice((1, -1))
            A = s0 * rng.uniform(4, 10)
            y = clamp([v + (sgn * A if i >= FULL - k else 0) for i, v in enumerate(base)], m)
            p = "step_increase" if sgn > 0 else "step_decrease"
            add("step_old", role, node, metric, end, y, label(role, node, metric, y, end, p, A, s0, bst["mean"], rng),
                {"step_age_pts": k})
        # slow drift over the last 6-12 h
        for _ in range(a.long):
            node, metric, end, base = rng.choice(pool)
            m = F.METRICS[(role, metric)]
            s0, bst = G.scale_of(role, metric, base)
            L = rng.randint(72, FULL)
            sgn = rng.choice((1, -1))
            A = s0 * rng.uniform(4, 8)
            y = clamp([v + (sgn * A * (i - (FULL - L)) / (L - 1) if i >= FULL - L else 0) for i, v in enumerate(base)], m)
            p = "gradual_increase" if sgn > 0 else "gradual_decrease"
            add("drift_long", role, node, metric, end, y, label(role, node, metric, y, end, p, A, s0, bst["mean"], rng),
                {"drift_len_pts": L})
        # recurring small spikes, each one below the training spike size and below the warning limit
        made = tries = 0
        while made < a.subthr and tries < a.subthr * 40:
            tries += 1
            node, metric, end, base = rng.choice(pool)
            m = F.METRICS[(role, metric)]
            s0, _ = G.scale_of(role, metric, base[-48:])
            k = rng.randint(3, 5)
            T = rng.randint(24, FULL - 2)
            pos = sorted({FULL - 1 - rng.randint(0, 5)} | {FULL - 1 - rng.randint(6, T) for _ in range(k - 1)})
            y = list(base)
            for p_ in pos:
                y[p_] += s0 * rng.uniform(2.0, 3.5)
            if m["warn"] is not None and m["dir"] == "high" and max(y) >= m["warn"]:
                continue
            y = clamp(y, m)
            add("subthr_spikes", role, node, metric, end, y,
                {"pattern": "recurrent_small_spikes", "status": "normal", "likely_cause": None},
                {"spike_idx": pos, "spread_pts": FULL - 1 - pos[0]})
            made += 1
    # variety probe: random real windows, no truth
    for role in F.ROLES:
        pool = real[role]
        for node, metric, end, xs in rng.sample(pool, min(a.real, len(pool))):
            add("real", role, node, metric, end, xs, None)

    with open(out / "cases.jsonl", "w", encoding="utf-8") as fh:
        for c in cases:
            fh.write(json.dumps(c) + "\n")
    n_tok = defaultdict(list)
    if a.no_prompts:
        print(f"{len(cases)} cases written (no prompts)")
        return
    # every prompt per length (exactly what the NPU receives)
    tok = None
    try:
        from tokenizers import Tokenizer
        tok = Tokenizer.from_file(str(a.tokenizer))
    except Exception as e:  # noqa: BLE001
        print("tokenizer unavailable:", e)
    with open(out / "prompts.jsonl", "w", encoding="utf-8") as fh:
        for c in cases:
            loc = G.describe(c["node"])
            for n in LENGTHS:
                xs = c["xs"][-n:]
                pr, rule = agent_prompt_n(c["role"], c["node"], loc, c["metric"], xs, c["end_epoch"])
                if n == 48:
                    ref, _, _ = F.agent_prompt(c["role"], c["node"], loc, c["metric"], xs, c["end_epoch"])
                    assert pr == ref, "48-point prompt must equal the training prompt"
                t = len(tok.encode(pr, add_special_tokens=False).ids) if tok else None
                n_tok[n].append(t)
                fh.write(json.dumps({"id": c["id"], "n": n, "prompt": pr, "rule": rule, "prompt_tokens": t}) + "\n")
    fams = Counter(c["family"] for c in cases)
    h = hashlib.sha256((out / "cases.jsonl").read_bytes()).hexdigest()[:16]
    manifest = {"created": datetime.now().isoformat(timespec="seconds"), "seed": a.seed, "lengths": LENGTHS,
                "cases": len(cases), "families": fams, "pool": pool_stats, "cases_sha256_16": h,
                "prompt_tokens": {n: {"mean": round(sum(v) / len(v), 1), "max": max(v)} for n, v in n_tok.items() if v and v[0]},
                "args": vars(a) | {"tokenizer": str(a.tokenizer)}}
    (out / "manifest.json").write_text(json.dumps(manifest, indent=1, default=str))
    print(json.dumps(manifest, indent=1, default=str))


# ------------------------------------------------------------------ run on htpd
def call(req, port):
    s = socket.create_connection(("127.0.0.1", port), timeout=900)
    s.sendall((json.dumps(req) + "\n").encode())
    buf = b""
    while not buf.endswith(b"\n"):
        d = s.recv(1 << 20)
        if not d:
            break
        buf += d
    s.close()
    return json.loads(buf.decode("utf-8", errors="replace"))  # a token can split a UTF-8 char


def run(a):
    out = Path(a.out)
    prompts = [json.loads(l) for l in open(out / "prompts.jsonl", encoding="utf-8")]
    done = set()
    sp = out / "samples.jsonl"
    if sp.exists():
        done = {(r["id"], r["n"]) for r in map(json.loads, open(sp, encoding="utf-8"))}
    todo = [p for p in prompts if (p["id"], p["n"]) not in done]
    # one length per batch keeps the per-batch latency attributable to that length
    by_n = defaultdict(list)
    for p in todo:
        by_n[p["n"]].append(p)
    # interleave lengths so board heat drifts equally over all of them
    batches = []
    for n, ps in by_n.items():
        for i in range(0, len(ps), a.batch):
            batches.append(ps[i:i + a.batch])
    random.Random(1).shuffle(batches)
    print(f"{len(todo)} prompts left in {len(batches)} batches", flush=True)
    import subprocess
    adb = str(TRAIN.parents[1] / "platform-tools" / "adb.exe")

    def board_c():
        r = subprocess.run([adb, "shell", "cat /sys/class/thermal/thermal_zone*/temp"], capture_output=True, text=True)
        v = [int(x) for x in r.stdout.split() if x.lstrip("-").isdigit()]
        return max(v) // 1000 if v else -1

    with open(sp, "a", encoding="utf-8") as fh:
        for bi, b in enumerate(batches):
            # thermal pacing: the 900-window run once stalled at 91 C; keep every batch below ~85 C
            c = board_c()
            if c >= a.hot:
                print(f"board {c} C, cooling to {a.cool} C ...", flush=True)
                while board_c() > a.cool:
                    time.sleep(10)
            t0 = time.time()
            r = call({"kind": "agents", "prompts": [p["prompt"] + PREFILL for p in b]}, a.port)
            dt = time.time() - t0
            for p, o in zip(b, r["outputs"]):
                fh.write(json.dumps({"id": p["id"], "n": p["n"], "text": PREFILL + o["text"], "stop": o["stop"],
                                     "tokens": o["tokens"], "batch": bi, "batch_size": len(b), "batch_s": round(dt, 2),
                                     "prefill_ms": r.get("prefill_ms"), "prompt_tokens": p["prompt_tokens"],
                                     "rule": p["rule"], "board_c_before": c}) + "\n")
            fh.flush()
            print(f"[{bi + 1}/{len(batches)}] n={b[0]['n']} x{len(b)} {dt:.1f}s", flush=True)


# ------------------------------------------------------------------ analysis
def parse(text):
    from validate_tuned_on_device import first_json
    p = first_json(text)
    if not isinstance(p, dict):
        return None
    norm = lambda v: str(v).strip().lower().replace(" ", "_").replace("-", "_")
    return {k: norm(p.get(k, "")) for k in ("pattern", "status", "likely_cause", "action")}


QUIET = {"stable", "vacant", "occupied"}


def flagged(pred):
    return pred is not None and (pred["status"] != "normal" or pred["pattern"] not in QUIET)


def wilson(k, n, z=1.96):
    if n == 0:
        return (0.0, 0.0)
    p = k / n
    d = 1 + z * z / n
    c = (p + z * z / (2 * n)) / d
    h = z * math.sqrt(p * (1 - p) / n + z * z / (4 * n * n)) / d
    return (round(max(0, c - h), 3), round(min(1, c + h), 3))


def rate(xs):
    k, n = sum(1 for x in xs if x), len(xs)
    return {"rate": round(k / n, 3) if n else None, "k": k, "n": n, "ci95": wilson(k, n)}


def analyze(a):
    out = Path(a.out)
    cases = {c["id"]: c for c in map(json.loads, open(out / "cases.jsonl", encoding="utf-8"))}
    rows = [json.loads(l) for l in open(out / "samples.jsonl", encoding="utf-8")]
    for r in rows:
        c = cases[r["id"]]
        r["family"], r["role"], r["truth"] = c["family"], c["role"], c["truth"]
        r["pred"] = parse(r["text"])
        r["flag"] = flagged(r["pred"])
        rp = r.get("rule")
        r["rule_flag"] = rp is not None and rp not in QUIET
    # "clean" bases are real windows that pass the training generator's calm test, but real data still
    # holds real dips/spikes (and some sit above a limit: truth status warning). A false alarm is therefore
    # only counted where the truth is normal, and a STRICT subset keeps windows where the rule classifier
    # sees nothing at ANY length (rule-visible history excluded; biased toward what rules can see).
    rules_by_case = defaultdict(dict)
    for r in rows:
        rules_by_case[r["id"]][r["n"]] = r.get("rule")
    strict = {cid for cid, c in cases.items() if c["family"] == "clean" and c["truth"]["status"] == "normal"
              and len(rules_by_case[cid]) == len(LENGTHS) and all(v in QUIET for v in rules_by_case[cid].values())}
    for r in rows:
        if r["family"] == "clean" and r["truth"]["status"] != "normal":
            r["family"] = "clean_above_limit"
        elif r["id"] in strict:
            r["family"] = "clean_strict"
    S = {"n_samples": len(rows), "lengths": {}, "strict_clean_cases": len(strict)}
    fam_names = sorted({r["family"] for r in rows if r["family"] != "real"},
                       key=lambda f: (not f.startswith("clean"), not f.startswith("classic"), f))
    for n in LENGTHS:
        R = [r for r in rows if r["n"] == n]
        lab = [r for r in R if r["family"] not in ("real",)]
        ev = [r for r in lab if not r["family"].startswith("clean")]
        acc = [r for r in lab if r["family"] not in ("subthr_spikes",)]
        d = {
            "json_valid": rate([r["pred"] is not None for r in R]),
            "detection_all_events": rate([r["flag"] for r in ev]),
            "false_alarm_clean": rate([r["flag"] for r in lab if r["family"] in ("clean", "clean_strict")]),
            "false_alarm_clean_strict": rate([r["flag"] for r in lab if r["family"] == "clean_strict"]),
            "pattern_acc": rate([r["pred"] is not None and r["pred"]["pattern"] == r["truth"]["pattern"] for r in acc]),
            "status_acc": rate([r["pred"] is not None and r["pred"]["status"] == r["truth"]["status"] for r in acc]),
            "cause_acc": rate([r["pred"] is not None and r["pred"]["likely_cause"] == r["truth"]["likely_cause"] for r in acc]),
            "rules_detection_all_events": rate([r["rule_flag"] for r in ev]),
            "rules_false_alarm_clean": rate([r["rule_flag"] for r in lab if r["family"] in ("clean", "clean_strict")]),
            "per_family": {},
            "latency": {},
        }
        for f in fam_names:
            F_ = [r for r in lab if r["family"] == f]
            if not F_:
                continue
            e = {"flag": rate([r["flag"] for r in F_]), "rules_flag": rate([r["rule_flag"] for r in F_])}
            if f != "subthr_spikes":
                e["pattern"] = rate([r["pred"] is not None and r["pred"]["pattern"] == r["truth"]["pattern"] for r in F_])
                e["status"] = rate([r["pred"] is not None and r["pred"]["status"] == r["truth"]["status"] for r in F_])
            e["called"] = Counter(r["pred"]["pattern"] if r["pred"] else "INVALID" for r in F_).most_common(5)
            d["per_family"][f] = e
        real = [r for r in R if r["family"] == "real" and r["pred"]]
        d["variety_real"] = {
            "n": len(real),
            "flagged": rate([r["flag"] for r in real]),
            "distinct_patterns": len({r["pred"]["pattern"] for r in real}),
            "distinct_pattern_status_cause": len({(r["pred"]["pattern"], r["pred"]["status"], r["pred"]["likely_cause"]) for r in real}),
            "distinct_flagged_outcomes": len({(r["pred"]["pattern"], r["pred"]["status"], r["pred"]["likely_cause"]) for r in real if r["flag"]}),
            "patterns": Counter(r["pred"]["pattern"] for r in real).most_common(),
        }
        bs = {}
        for r in R:
            bs[r["batch"]] = (r["batch_s"], r["batch_size"], r["prefill_ms"])
        per_call = [s / k for s, k, _ in bs.values()]
        pt = [r["prompt_tokens"] for r in R if r["prompt_tokens"]]
        d["latency"] = {"batches": len(bs), "mean_s_per_call_in_batch": round(sum(per_call) / len(per_call), 3) if per_call else None,
                        "mean_batch_s": round(sum(s for s, _, _ in bs.values()) / len(bs), 2) if bs else None,
                        "mean_prefill_s": round(sum((p or 0) for _, _, p in bs.values()) / len(bs) / 1000, 2) if bs else None,
                        "mean_prompt_tokens": round(sum(pt) / len(pt), 1) if pt else None,
                        "mean_output_tokens": round(sum(r["tokens"] for r in R) / len(R), 1) if R else None}
        S["lengths"][str(n)] = d
    (out / "summary.json").write_text(json.dumps(S, indent=1))
    write_tables(S, fam_names, out)
    plots(S, fam_names, out)
    print((out / "tables.md").read_text(encoding="utf-8"))


def pct(e):
    return "-" if e is None or e["rate"] is None else f"{100 * e['rate']:.0f}% ({e['k']}/{e['n']})"


def write_tables(S, fams, out):
    L = [str(n) for n in LENGTHS]
    hdr = "| | " + " | ".join(f"{n} pts ({int(n) * 5 / 60:g} h)" for n in L) + " |\n|---|" + "---|" * len(L) + "\n"
    t = ["# Window-length study - results\n", "## Headline (AI agents, QIDK NPU via htpd)\n", hdr]
    for k, name in [("detection_all_events", "detection, all injected events"), ("false_alarm_clean", "false alarms, clean windows (truth normal)"),
                    ("false_alarm_clean_strict", "false alarms, strict clean (rules quiet at every length)"),
                    ("pattern_acc", "pattern accuracy (labelled families)"), ("status_acc", "status accuracy"),
                    ("cause_acc", "cause accuracy"), ("json_valid", "valid JSON"),
                    ("rules_detection_all_events", "rules (Mode 1) detection"), ("rules_false_alarm_clean", "rules (Mode 1) false alarms")]:
        t.append(f"| {name} | " + " | ".join(pct(S["lengths"][n][k]) for n in L) + " |\n")
    t.append("\n## Detection (any flag) per family\n")
    t.append(hdr)
    for f in fams:
        t.append(f"| {f} | " + " | ".join(pct(S["lengths"][n]["per_family"].get(f, {}).get("flag")) for n in L) + " |\n")
    t.append("\n## Pattern accuracy per family\n")
    t.append(hdr)
    for f in fams:
        if f == "subthr_spikes":
            continue
        t.append(f"| {f} | " + " | ".join(pct(S["lengths"][n]["per_family"].get(f, {}).get("pattern")) for n in L) + " |\n")
    t.append("\n## What the agent called the sub-threshold recurring spikes\n")
    for n in L:
        e = S["lengths"][n]["per_family"].get("subthr_spikes")
        if e:
            t.append(f"- {n} pts: {e['called']}\n")
    t.append("\n## Variety on real (uninjected) test windows\n")
    t.append(hdr)
    for k, name in [("flagged", "share flagged")]:
        t.append(f"| {name} | " + " | ".join(pct(S["lengths"][n]["variety_real"][k]) for n in L) + " |\n")
    for k, name in [("distinct_patterns", "distinct patterns"), ("distinct_pattern_status_cause", "distinct (pattern, status, cause)"),
                    ("distinct_flagged_outcomes", "distinct flagged outcomes")]:
        t.append(f"| {name} | " + " | ".join(str(S["lengths"][n]["variety_real"][k]) for n in L) + " |\n")
    t.append("\n## Cost\n")
    t.append(hdr)
    for k, name in [("mean_prompt_tokens", "prompt tokens (mean)"), ("mean_output_tokens", "output tokens (mean)"),
                    ("mean_batch_s", "batch time, s"), ("mean_prefill_s", "batch prefill, s"),
                    ("mean_s_per_call_in_batch", "s per agent inside a batch")]:
        t.append(f"| {name} | " + " | ".join(str(S["lengths"][n]["latency"][k]) for n in L) + " |\n")
    (out / "tables.md").write_text("".join(t), encoding="utf-8")


def plots(S, fams, out):
    try:
        import matplotlib
        matplotlib.use("Agg")
        import matplotlib.pyplot as plt
    except Exception as e:  # noqa: BLE001
        print("no matplotlib:", e)
        return
    L = [str(n) for n in LENGTHS]
    hrs = [int(n) * 5 / 60 for n in L]

    def series(get):
        v, lo, hi = [], [], []
        for n in L:
            e = get(S["lengths"][n])
            r = e["rate"] if e and e["rate"] is not None else float("nan")
            v.append(r)
            lo.append(r - e["ci95"][0] if e else 0)
            hi.append(e["ci95"][1] - r if e else 0)
        return v, [lo, hi]

    fig, ax = plt.subplots(figsize=(7, 4.2))
    for k, name in [("detection_all_events", "detection (events)"), ("false_alarm_clean", "false alarms (clean)"),
                    ("false_alarm_clean_strict", "false alarms (strict clean)"),
                    ("pattern_acc", "pattern accuracy"), ("status_acc", "status accuracy")]:
        v, err = series(lambda d: d[k])
        ax.errorbar(hrs, v, yerr=err, marker="o", capsize=3, label=name)
    ax.set_xticks(hrs, [f"{h:g} h\n({n} pts)" for h, n in zip(hrs, L)])
    ax.set_ylim(0, 1.02)
    ax.set_ylabel("rate (95% Wilson CI)")
    ax.set_title("Agent window length vs detection and accuracy (QIDK NPU)")
    ax.grid(alpha=.3)
    ax.legend(fontsize=8)
    fig.tight_layout()
    fig.savefig(out / "headline.svg")
    plt.close(fig)

    fig, ax = plt.subplots(figsize=(8, 4.6))
    for f in fams:
        v, err = series(lambda d: d["per_family"].get(f, {}).get("flag"))
        ax.plot(hrs, v, marker="o", label=f)
    ax.set_xticks(hrs, [f"{h:g} h" for h in hrs])
    ax.set_ylim(0, 1.02)
    ax.set_ylabel("share flagged")
    ax.set_title("Flag rate per case family (clean = false alarms)")
    ax.grid(alpha=.3)
    ax.legend(fontsize=7, ncol=2)
    fig.tight_layout()
    fig.savefig(out / "per_family_flag.svg")
    plt.close(fig)

    fig, ax1 = plt.subplots(figsize=(6.5, 4))
    ax1.bar([h - .35 for h in hrs], [S["lengths"][n]["variety_real"]["distinct_pattern_status_cause"] for n in L], width=.7, label="distinct outcomes")
    ax1.set_ylabel("distinct (pattern, status, cause)")
    ax2 = ax1.twinx()
    ax2.plot(hrs, [S["lengths"][n]["latency"]["mean_batch_s"] for n in L], "o-", color="C3", label="batch time (s)")
    ax2.set_ylabel("batch time, s")
    ax1.set_xticks(hrs, [f"{h:g} h" for h in hrs])
    ax1.set_title("Variety on real windows vs cost")
    fig.tight_layout()
    fig.savefig(out / "variety_cost.svg")
    plt.close(fig)


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("cmd", choices=["build", "run", "analyze"])
    ap.add_argument("--out", required=True)
    ap.add_argument("--seed", type=int, default=7)
    ap.add_argument("--clean", type=int, default=12, help="clean windows per role")
    ap.add_argument("--classic", type=int, default=2, help="cases per training pattern per role")
    ap.add_argument("--long", type=int, default=8, help="step_old and drift_long cases per role")
    ap.add_argument("--subthr", type=int, default=10, help="sub-threshold spike cases per role")
    ap.add_argument("--real", type=int, default=24, help="real windows per role (variety probe)")
    ap.add_argument("--split", default="test", choices=["train", "dev", "test"], help="months to draw windows from")
    ap.add_argument("--no-prompts", action="store_true", help="cases only (detector tuning needs no NPU prompts)")
    ap.add_argument("--batch", type=int, default=8)
    ap.add_argument("--port", type=int, default=8091)
    ap.add_argument("--hot", type=int, default=85, help="pause before a batch at this board temperature (C)")
    ap.add_argument("--cool", type=int, default=72, help="resume below this temperature (C)")
    ap.add_argument("--tokenizer", default=str(TRAIN.parent / "models" / "genie_bundle" /
                                               "llama_v3_2_3b_instruct-genie-w4a16-qualcomm_snapdragon_8gen3" / "tokenizer.json"))
    a = ap.parse_args()
    {"build": build, "run": run, "analyze": analyze}[a.cmd](a)


if __name__ == "__main__":
    main()
