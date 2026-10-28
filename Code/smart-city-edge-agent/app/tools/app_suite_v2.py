"""Through-the-app test suite for the v2 agent (dynamic windows, early -> 1.5 h -> 3 h refinement, batched htpd).

Everything goes through the running app's HTTP API (the same surface as the dashboard sliders), plus adb only
for the robustness phase (killing the backend / htpd) and to restore the port forward. Every phase writes raw
JSON evidence into --out and the run ends with summary.json + summary.txt + manifest.json (collect-proofs rule).

  adb forward tcp:8000 tcp:8000
  py -3 app_suite_v2.py --out ../../../../proofs/2026-10-22_suite_v2                     # all phases
  py -3 app_suite_v2.py --out DIR --phases scenarios,chain                              # a) only
  py -3 app_suite_v2.py --out DIR --phases multi,chaos --chaos-rounds 3                 # b)
  py -3 app_suite_v2.py --out DIR --phases faults --fault-trials 12                     # c)
  py -3 app_suite_v2.py --out DIR --phases soak --soak-min 20                           # d)
  py -3 app_suite_v2.py --out DIR --phases stream                                       # e)
  py -3 app_suite_v2.py --out DIR --phases robust                                       # f)
  py -3 app_suite_v2.py --out DIR --quick                                               # short pass of everything
  py -3 app_suite_v2.py --out DIR --summarize-only                                      # rebuild summary from DIR

Phases (comma list for --phases; "all" = every one, in this order):
  scenarios  a) every scenario alone, after a reset, followed early -> 1.5 h -> 3 h
  chain      a) the scenarios back to back WITHOUT reset (refinement chain on a busy board)
  multi      b) 2-4 scenarios injected together across roles: batching, per-sensor windows, latency vs N
  chaos      b) every sensor driven abnormal at once: the 10-13-agent worst case vs the v1 baseline (14.7 s)
  faults     c) random sensor faults through /api/ingest (stuck/noise/dropout/saturation/quantised)
  soak       d) calm board, plausible random values for N minutes: count false alarms
  stream     e) SSE /api/events during an incident: time to first token per agent, gaps between tokens
  robust     f) backend restart mid-incident, htpd kill mid-batch: recovery, final states, queue drains

Resumable: each finished unit (one scenario, one trial, ...) is written to units/<key>.json and skipped on the
next run with the same --out (use --fresh to redo). Ctrl-C loses only the unit in progress.
Thermal pacing: before each unit /api/status device temperatures are read; above --max-temp (80 C) or with the
thermal guard tripped the suite waits until the board is below --resume-temp (70 C).

Checks are "hard" (count as FAIL) or "soft" (reported as WARN: model-quality or latency observations that
are evidence, not regressions). Window rules (hard): every agent window is a trained length (24..144, step 6),
early = 48, refined >= the family floor of features_v2.go WindowN, and covers the previous stage's onset + 12
readings (capped at 144). The exact WindowN value is recomputed from the snapshots and compared (soft, because
the backend's previous-finding fallback is approximated from the snapshot).

Offline smoke (no device): run the host build in mock mode and point the suite at it:
  wsl: ./edge-agent-host --mock --dir APPDIR --addr 0.0.0.0:18000      (APPDIR has data/ web/ state/ agent_version=v2)
  py -3 app_suite_v2.py --base http://127.0.0.1:18000 --no-adb --quick --out DIR \
        --restart-cmd "wsl.exe -e pkill -x edge-agent-host" --htpd-kill-cmd ""
"""
from __future__ import annotations

import argparse
import json
import os
import random
import re
import statistics
import subprocess
import sys
import threading
import time
import urllib.request
from datetime import datetime, timedelta, timezone
from pathlib import Path

import stress_app as S

IST = timezone(timedelta(hours=5, minutes=30))
STEP_S = 300  # one reading = 5 minutes of sensor time
DONE = ("done", "done_with_errors")
V1_CHAOS_BASELINE_MS = 14700.0
ALL_PHASES = ["scenarios", "chain", "multi", "chaos", "faults", "soak", "stream", "robust"]
NO_AGENT_METRICS = ("occ", "ac_units_on", "ac_on")

# features_v2.go window policy (keep in sync with WindowN / windowFamily)
LADDER_ALERT, WIN_SHORT, WIN_MID, WIN_LONG, WIN_BASELINE, STEP_N, MAX_N = 48, 48, 96, 144, 12, 6, 144
FAMILY = {"flatline": "flat", "spike": "transient", "dip": "transient", "erratic": "noisy", "oscillation": "noisy",
          "stable": "stable", "gradual_increase": "trend", "gradual_decrease": "trend", "exponential_increase": "trend",
          "step_increase": "step", "step_decrease": "step", "throttling": "step"}

A = None  # parsed args
OUT: Path = None
LOG = None
rng = random.Random(20261022)
_print_lock = threading.Lock()


# ------------------------------------------------------------------ output / bookkeeping
def say(*a):
    msg = " ".join(str(x) for x in a)
    with _print_lock:
        print(msg, flush=True)
        if LOG:
            LOG.write(msg + "\n")
            LOG.flush()


def wjson(path: Path, obj):
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(path.suffix + ".tmp")
    tmp.write_text(json.dumps(obj, indent=1, default=str), encoding="utf-8")
    os.replace(tmp, path)


class Unit:
    """One resumable piece of work. Collects its checks; saved to units/<key>.json when finished."""

    def __init__(self, phase, key):
        self.phase, self.key, self.checks, self.data = phase, key, [], {}
        self.t0 = time.time()

    def check(self, name, ok, evidence="", hard=True):
        ok = bool(ok)
        ev = str(evidence) if evidence is not None else ""
        if ok and ev and not ev.startswith("info:"):
            ev = "info: " + ev
        self.checks.append({"check": name, "ok": ok, "hard": hard, "evidence": ev[:2000]})
        tag = "PASS" if ok else ("FAIL" if hard else "WARN")
        say(f"  [{tag}] {name}" + (f"  - {ev[:240]}" if not ok and ev else ""))
        return ok

    def path(self):
        return OUT / "units" / (re.sub(r"[^A-Za-z0-9_.-]+", "_", self.key) + ".json")

    def save(self):
        wjson(self.path(), {"phase": self.phase, "key": self.key, "seconds": round(time.time() - self.t0, 1),
                            "checks": self.checks, "data": self.data})


def unit_done(key):
    if A.fresh:
        return False
    p = OUT / "units" / (re.sub(r"[^A-Za-z0-9_.-]+", "_", key) + ".json")
    return p.exists()


# ------------------------------------------------------------------ device / backend plumbing
def adb_cmd(*args, timeout=30):
    if A.no_adb:
        return ""
    try:
        return subprocess.run([S.ADB, *args], capture_output=True, text=True, timeout=timeout).stdout.strip()
    except Exception as e:
        return f"adb error: {e}"


def run_cmd(cmd, timeout=60):
    if not cmd:
        return {"cmd": cmd, "skipped": True}
    try:
        p = subprocess.run(cmd, shell=True, capture_output=True, text=True, timeout=timeout)
        return {"cmd": cmd, "rc": p.returncode, "out": (p.stdout + p.stderr).strip()[:500]}
    except Exception as e:
        return {"cmd": cmd, "error": str(e)}


def local_wait_backend(limit):
    t0 = time.time()
    while time.time() - t0 < limit:
        if S._req("/api/status", None, None, 5)[0] == 200:
            return True
        time.sleep(3)
    return False


def status():
    code, st = S.req("/api/status", timeout=20)
    return st if code == 200 and isinstance(st, dict) else {}


def temps(st):
    dv = (st or {}).get("device") or {}
    vals = [dv.get(k) for k in ("npu_c", "skin_c", "cpu_c", "thermal_max_c")]
    vals = [float(v) for v in vals if isinstance(v, (int, float)) and v > 0]
    return (max(vals) if vals else None), bool(dv.get("thermal_guard"))


def thermal_pace(tag=""):
    """Wait while the board is hot: above --max-temp or thermal guard tripped -> wait for --resume-temp."""
    t, guard = temps(status())
    if (t is None or t <= A.max_temp) and not guard:
        return t
    say(f"  [thermal] {tag}: {t} C guard={guard} - pausing until <= {A.resume_temp} C")
    t0 = time.time()
    while time.time() - t0 < A.thermal_wait_max:
        time.sleep(20)
        t, guard = temps(status())
        if t is not None and t <= A.resume_temp and not guard:
            break
    say(f"  [thermal] resumed after {time.time() - t0:.0f}s at {t} C")
    with open(OUT / "thermal_pauses.jsonl", "a", encoding="utf-8") as f:
        f.write(json.dumps({"tag": tag, "waited_s": round(time.time() - t0), "temp_c": t, "wall": time.time()}) + "\n")
    return t


def npu_idle(timeout=240):
    t0 = time.time()
    while time.time() - t0 < timeout:
        npu = status().get("npu") or {}
        if not npu.get("busy") and not npu.get("queue"):
            return True, round(time.time() - t0, 1)
        time.sleep(2)
    return False, timeout


def wait_no_running(timeout=240):
    t0 = time.time()
    stuck = running_incidents()
    while stuck and time.time() - t0 < timeout:
        time.sleep(3)
        stuck = running_incidents()
    return stuck, round(time.time() - t0, 1)


def running_incidents():
    _, items = S.req("/api/incidents?limit=60", timeout=20)
    return [i["id"] for i in (items if isinstance(items, list) else []) if i.get("state") == "running"]


def fresh_board(clock="10:00", warmup=None):
    """Reset (clear injections, restart history, defaults, 1 s polls), Mode 3, wait for history to build."""
    S.reset(clock)
    S.req("/api/sensors", {"noise_scale": 1})
    S.req("/api/mode", {"mode": 3})
    w = A.warmup if warmup is None else warmup
    if w:
        time.sleep(w)


def incident(iid):
    code, d = S.req(f"/api/incidents/{iid}", timeout=20)
    return d if code == 200 and isinstance(d, dict) else None


# ------------------------------------------------------------------ incident extraction
RX_BATCH = re.compile(r"running all (\d+) NPU agents")
RX_ORCH = re.compile(r"Orchestrator: (\d+) sensor\(s\) to NPU agents")


def timeline_stats(msgs):
    return {
        "batched_n": [int(m.group(1)) for m in (RX_BATCH.search(x) for x in msgs) if m],
        "orchestrated_n": [int(m.group(1)) for m in (RX_ORCH.search(x) for x in msgs) if m],
        "solo_reruns": sum("re-running alone" in x for x in msgs),
        "solo_still_invalid": sum("solo re-run also invalid" in x for x in msgs),
        "npu_unavailable_reruns": sum("re-running (NPU was unavailable)" in x for x in msgs),
        "npu_still_unavailable": sum("NPU still unavailable" in x for x in msgs),
        "cached": sum("cached" in x for x in msgs),
        "synth_rejected": sum("rejected by policy" in x for x in msgs),
        "npu_retries": sum("NPU retr" in x for x in msgs),
    }


def extract(inc, prev_timeline_len=0):
    """Compact per-stage record: what the operator saw plus every number needed for latency/window checks."""
    agents = inc.get("agents") or []
    by_ref = {}
    for a in agents:
        by_ref.setdefault(a.get("ref"), a)
        if a.get("prompt"):
            by_ref[a.get("ref")] = a  # prefer the NPU call over a context entry
    sens = []
    for s in inc.get("sensors") or []:
        if s.get("context"):
            continue
        a = by_ref.get(s.get("ref")) or {}
        p = a.get("parsed") or {}
        rf = s.get("rule_finding") or {}
        sens.append({"ref": s.get("ref"), "node": s.get("node"), "metric": s.get("metric"), "role": s.get("role"),
                     "win_n_raw": s.get("win_n"), "win_n": s.get("win_n") or LADDER_ALERT, "window_end": s.get("window_end"),
                     "rule_pattern": rf.get("pattern"), "rule_status": rf.get("status"),
                     "pattern": p.get("pattern"), "status": p.get("status"), "onset": p.get("onset"),
                     "fault_kind": p.get("fault_kind"), "confidence": p.get("confidence"),
                     "llm": bool(a.get("prompt")), "model": a.get("model"), "valid": a.get("valid"),
                     "errors": a.get("errors"), "repairs": a.get("repairs"),
                     "latency_ms": a.get("latency_ms"), "ttft_ms": a.get("ttft_ms"), "gen_tokens": a.get("gen_tokens"),
                     "tokens_per_s": a.get("tokens_per_s"), "early_stopped": a.get("early_stopped"),
                     "long_range": [x.get("text") for x in s.get("long_range") or []]})
    f = inc.get("final") or {}
    fp = f.get("parsed") or {}
    tl = [t.get("msg", "") for t in inc.get("timeline") or []]
    revs = inc.get("revisions") or []
    stage = inc.get("refine_stage") or "early"
    rev = next((r for r in reversed(revs) if r.get("stage") == stage), {})
    return {"id": inc.get("id"), "stage": stage, "state": inc.get("state"), "severity": inc.get("severity"),
            "severity_final": inc.get("severity_final"), "title": inc.get("title"), "rule_title": inc.get("rule_title"),
            "refine_note": inc.get("refine_note"), "next_refine_sim": inc.get("next_refine_sim"),
            "created_sim": inc.get("created_sim"), "total_ms": inc.get("total_ms"), "stage_ms": rev.get("ms"),
            "npu_calls": inc.get("npu_calls"), "stage_npu_calls": rev.get("npu_calls"), "revisions": len(revs),
            "revision_list": [{"stage": r.get("stage"), "sim_end": r.get("sim_end"), "ms": r.get("ms"),
                               "severity": r.get("severity"), "title": r.get("title"),
                               "sensors": [{k: x.get(k) for k in ("ref", "metric", "pattern", "status", "kept", "no_data")}
                                           for x in r.get("sensors") or []]} for r in revs],
            "n_llm_agents": sum(1 for a in agents if a.get("prompt")), "n_flagged": len(sens),
            "n_context": sum(1 for s in inc.get("sensors") or [] if s.get("context")),
            "sensors": sens,
            "final": {"model": f.get("model"), "valid": f.get("valid"), "errors": f.get("errors"),
                      "latency_ms": f.get("latency_ms"), "ttft_ms": f.get("ttft_ms"), "gen_tokens": f.get("gen_tokens"),
                      "tokens_per_s": f.get("tokens_per_s"), "label": fp.get("label"), "severity": fp.get("severity"),
                      "domains": fp.get("affected_domains")},
            "timeline_all": timeline_stats(tl), "timeline_new": timeline_stats(tl[prev_timeline_len:]),
            "timeline_len": len(tl), "timeline_tail": tl[prev_timeline_len:][-40:]}


def follow(ids, tag, until="3h", timeout=None, discover=None):
    """Poll incidents until each reaches `until` (or has nothing more to refine / failed / times out).
    Saves every stage's full JSON as raw/<tag>/<id>_<stage>.json (the check_windows.py layout).
    `discover`: callable returning more incident ids (late joiners), polled for the first 20 s.
    Returns {id: {"stages": {stage: extract}, "final_state": str, "timed_out": bool}}."""
    timeout = timeout or A.stage_timeout * 3
    raw = OUT / "raw" / tag
    raw.mkdir(parents=True, exist_ok=True)
    res = {i: {"stages": {}, "order": [], "final_state": None, "timed_out": False, "_key": None, "_tl": 0, "_end": False}
           for i in ids}
    t0 = time.time()
    while time.time() - t0 < timeout:
        if discover and time.time() - t0 < 20:
            for i in discover():
                res.setdefault(i, {"stages": {}, "order": [], "final_state": None, "timed_out": False,
                                   "_key": None, "_tl": 0, "_end": False})
        if all(r["_end"] for r in res.values()):
            break
        for iid, r in res.items():
            if r["_end"]:
                continue
            inc = incident(iid)
            if not inc:
                continue
            st, stg = inc.get("state"), inc.get("refine_stage") or "early"
            r["final_state"] = st
            if st in DONE or st == "failed":
                key = (stg, len(inc.get("revisions") or []), st)
                if key != r["_key"]:
                    r["_key"] = key
                    wjson(raw / f"{iid}_{stg}.json", inc)
                    ex = extract(inc, r["_tl"])
                    ex["t_since_follow_s"] = round(time.time() - t0, 1)
                    r["_tl"] = ex["timeline_len"]
                    r["stages"][stg] = ex
                    r["order"].append(stg)
                    sv = ", ".join(f"{s['metric']}:{s['pattern']}/{s['status']} n={s['win_n']}" for s in ex["sensors"])
                    say(f"    {ex['t_since_follow_s']:6.1f}s {iid} {stg:4} {st} sev={ex['severity']} "
                        f"agents={ex['n_llm_agents']} ms={ex['stage_ms'] or ex['total_ms']} | {sv} | {ex['title']!r}")
                note = inc.get("refine_note") or ""
                if st == "failed" or stg == until or not inc.get("next_refine_sim") or note.startswith("Not refined"):
                    r["_end"] = True
        time.sleep(2)
    for r in res.values():
        r["timed_out"] = not r["_end"]
        for k in ("_key", "_tl", "_end"):
            r.pop(k, None)
    return res


def new_incidents(before, wait=150, settle=8):
    """Wait for the first new incident, then `settle` s for others raised by the same event."""
    iid, dt = S.wait_new_incident(before, wait)
    if not iid:
        return [], dt
    time.sleep(settle)
    return [i for i in S.incident_ids() if i not in before], dt


# ------------------------------------------------------------------ window policy (port of check_windows.py)
def family(pattern, role):
    if pattern in FAMILY:
        return FAMILY[pattern]
    if role in ("occupancy", "hvac"):
        return "other"
    return "invalid"


def window_n(stage, early_pattern, role, status, age):
    if stage in ("early", "", None):
        return LADDER_ALERT
    fam = family(early_pattern, role)
    if fam == "stable" and status in ("warning", "critical"):
        # features_v2.go: "stable" yet warning/critical = the early call did not see the shape: unrecognised (8 h)
        fam = "invalid"
    n = WIN_SHORT
    if status == "sensor_fault":
        n = WIN_LONG if fam in ("flat", "noisy") else WIN_MID
    elif fam == "flat":
        n = WIN_LONG
    elif fam in ("transient", "invalid"):
        n = WIN_MID
    elif fam == "step" and stage == "3h":
        n = WIN_MID
    elif fam == "noisy" and stage == "3h":
        n = WIN_LONG
    floor = n
    if age is not None and age >= 0:
        need = age + WIN_BASELINE
        need += (STEP_N - need % STEP_N) % STEP_N
        n = max(n, min(need, MAX_N))
    return n, floor


def hhmm(t):
    return datetime.fromtimestamp(t, IST).strftime("%H:%M")


def onset_age(onset, end, n=MAX_N):
    """readings from HH:MM onset to `end` (1 = the last reading), searching back n readings (features_v2 onsetAge)."""
    if not onset or not end:
        return None
    for k in range(n):
        if hhmm(end - k * STEP_S) == onset:
            return k + 1
    return None


def window_rows(iid, stages_ex):
    """Validate every flagged sensor's window at each stage. stages_ex: {stage: extract()}."""
    rows = []
    early = {s["ref"]: s for s in (stages_ex.get("early") or {}).get("sensors", [])}
    # refine.go takes the early pattern from the "early" revision when there is one (it can be a 12 h
    # override such as "level_shift (12 h view)", which windowFamily maps to "invalid" -> 8 h)
    early_rev = {}
    for ex in stages_ex.values():
        for r in ex.get("revision_list") or []:
            if r.get("stage") == "early":
                early_rev = {x["ref"]: x.get("pattern") for x in r.get("sensors") or []}
    prev_stage = None
    for stage in ("early", "1.5h", "3h"):
        ex = stages_ex.get(stage)
        if not ex:
            continue
        prev = stages_ex.get(prev_stage) if prev_stage else None
        prev_by = {s["ref"]: s for s in (prev or {}).get("sensors", [])}
        prev_end = max([s.get("window_end") or 0 for s in (prev or {}).get("sensors", [])] + [ex.get("created_sim") or 0])
        for s in ex["sensors"]:
            n, end = s["win_n"], s.get("window_end") or 0
            trained = 24 <= n <= MAX_N and n % STEP_N == 0
            e = early.get(s["ref"], {})
            early_pat = e.get("pattern") if e.get("valid") else (e.get("pattern") or e.get("rule_pattern"))
            if early_rev.get(s["ref"]):
                early_pat = early_rev[s["ref"]]
            fam = family(early_pat, s["role"])
            if stage == "early":
                exp, floor, covered, cover_age = LADDER_ALERT, LADDER_ALERT, True, None
            else:
                was = prev_by.get(s["ref"], {})
                was_status = was.get("status") if was.get("valid") else was.get("rule_status")
                was_onset = was.get("onset") if was.get("valid") else None
                status = was_status if was_status == "sensor_fault" else s.get("rule_status")
                a = onset_age(was_onset, prev_end) if was_onset else None
                if a is not None:
                    age = a + int((end - prev_end) / STEP_S)
                else:
                    age = int((end - (ex.get("created_sim") or end)) / STEP_S) + WIN_BASELINE
                exp, floor = window_n(stage, early_pat, s["role"], status, age)
                cover_age = onset_age(was_onset, end) if was_onset else None
                covered = cover_age is None or n >= min(cover_age + WIN_BASELINE, MAX_N)
            rows.append({"incident": iid, "stage": stage, "ref": s["ref"], "metric": s["metric"], "role": s["role"],
                         "win_n": n, "hours": round(n / 12, 1), "early_pattern": early_pat, "early_family": fam,
                         "pattern": s.get("pattern"), "status": s.get("status"), "prev_onset_age": cover_age,
                         "expected_n": exp, "family_floor": floor, "trained": trained, "covers_onset": covered,
                         "floor_ok": n >= floor, "exact": n == exp,
                         "ok": trained and covered and n >= floor})
        prev_stage = stage
    return rows


def check_windows(u, iid, stages_ex, label=""):
    rows = window_rows(iid, stages_ex)
    u.data.setdefault("window_rows", []).extend(rows)
    bad = [r for r in rows if not r["ok"]]
    inexact = [r for r in rows if r["ok"] and not r["exact"]]
    u.check(f"{label}{iid}: {len(rows)} sensor-stage windows trained, >= family floor, cover onset + 1 h",
            rows and not bad, json.dumps(bad)[:600] if bad else f"{len(rows)} rows")
    if rows:
        u.check(f"{label}{iid}: window equals recomputed WindowN", not inexact,
                json.dumps([(r['stage'], r['metric'], r['win_n'], r['expected_n']) for r in inexact]) if inexact else "",
                hard=False)
    return rows


def check_incident_basics(u, iid, fr, label="", want_stages=("early", "1.5h", "3h")):
    stages = fr["stages"]
    u.check(f"{label}{iid}: no timeout following the incident", not fr["timed_out"], f"reached {fr['order']}")
    u.check(f"{label}{iid}: final state done/done_with_errors", fr["final_state"] in DONE, fr["final_state"])
    if fr["final_state"] in DONE:
        u.check(f"{label}{iid}: final state is 'done' (no errors)", fr["final_state"] == "done", fr["final_state"], hard=False)
    reached = [s for s in want_stages if s in stages]
    last = stages.get(fr["order"][-1]) if fr["order"] else {}
    note = (last or {}).get("refine_note") or ""
    u.check(f"{label}{iid}: refined through {want_stages[-1]}", reached == list(want_stages),
            f"stages {fr['order']} note={note!r}", hard=not note)
    for stg in reached:
        ex = stages[stg]
        u.check(f"{label}{iid} {stg}: severity decided by reasoner", ex.get("severity_final"), ex.get("severity"), hard=False)
        u.check(f"{label}{iid} {stg}: title present", bool(ex.get("title")), ex.get("title"))
        bad = [(s["metric"], s["errors"]) for s in ex["sensors"] if s["llm"] and not s["valid"]]
        u.check(f"{label}{iid} {stg}: every NPU agent passed policy", not bad, json.dumps(bad)[:300], hard=False)
    return reached


# ------------------------------------------------------------------ stats
def pct(xs, q):
    xs = sorted(x for x in xs if isinstance(x, (int, float)))
    if not xs:
        return None
    k = (len(xs) - 1) * q
    lo, hi = int(k), min(int(k) + 1, len(xs) - 1)
    return xs[lo] + (xs[hi] - xs[lo]) * (k - lo)


def dist(xs):
    xs = [x for x in xs if isinstance(x, (int, float))]
    if not xs:
        return {"n": 0}
    return {"n": len(xs), "min": round(min(xs), 1), "median": round(statistics.median(xs), 1),
            "p90": round(pct(xs, 0.9), 1), "max": round(max(xs), 1), "mean": round(statistics.fmean(xs), 1)}


# ------------------------------------------------------------------ a) scenarios one by one, and the refine chain
def scenario_list():
    _, scs = S.req("/api/scenarios")
    ids = [s["id"] for s in scs] if isinstance(scs, list) else []
    if A.scenarios:
        ids = [x for x in A.scenarios.split(",") if x]
    return ids


def phase_scenarios():
    say("\n== a) scenarios one by one (reset before each), followed early -> 1.5 h -> 3 h ==")
    for sc in scenario_list():
        key = f"scenarios/{sc}"
        if unit_done(key):
            say(f"  (done earlier) {sc}")
            continue
        thermal_pace(sc)
        u = Unit("scenarios", key)
        fresh_board("23:00" if sc == "off_hours_presence" else "10:00")
        before = set(S.incident_ids())
        t0 = time.time()
        code, _ = S.req("/api/inject", {"scenario": sc})
        say(f"\n -- {sc}: injected (HTTP {code})")
        if not u.check(f"{sc}: injectable", code == 200, f"HTTP {code}"):
            u.save(); continue
        ids, dt = new_incidents(before, A.incident_wait)
        u.data.update({"scenario": sc, "incidents": ids, "t_to_incident_s": round(time.time() - t0 - (8 if ids else 0), 1)})
        if not u.check(f"{sc}: incident raised", ids, f"{ids} after {dt:.0f}s" if ids else f"none in {A.incident_wait}s"):
            u.save(); continue
        fr = follow(ids, f"scenarios_{sc}")
        u.data["follow"] = fr
        for iid, r in fr.items():
            check_incident_basics(u, iid, r, f"{sc} ")
            check_windows(u, iid, r["stages"], f"{sc} ")
        idle, waited = npu_idle(120)
        u.check(f"{sc}: NPU idle afterwards", idle, f"waited {waited}s")
        u.save()


def phase_chain():
    key = "chain/" + "+".join(scenario_list())
    say("\n== a) refine chain: scenarios back to back WITHOUT reset ==")
    if unit_done(key):
        say("  (done earlier)")
        return
    thermal_pace("chain")
    u = Unit("chain", key)
    fresh_board()
    u.data["steps"] = []
    for sc in scenario_list():
        thermal_pace(f"chain {sc}")
        before = set(S.incident_ids())
        t0 = time.time()
        code, _ = S.req("/api/inject", {"scenario": sc})
        say(f"\n -- chain {sc}: injected (HTTP {code})")
        ids, dt = new_incidents(before, A.incident_wait)
        step = {"scenario": sc, "incidents": ids, "t_to_incident_s": round(dt, 1)}
        u.data["steps"].append(step)
        # on a busy board the gate may correctly fold a sensor into nothing new (already reported): soft
        if not u.check(f"chain {sc}: incident raised", ids, f"{ids}" if ids else "none", hard=False):
            continue
        fr = follow(ids, f"chain_{sc}")
        step["follow"] = fr
        step["t_total_s"] = round(time.time() - t0, 1)
        for iid, r in fr.items():
            check_incident_basics(u, iid, r, f"chain {sc} ")
            check_windows(u, iid, r["stages"], f"chain {sc} ")
    stuck, w1 = wait_no_running()
    idle, waited = npu_idle(240)
    u.check("chain: no incident left running, NPU queue drained", not stuck and idle, f"running={stuck} waited={w1}+{waited}s")
    u.save()


# ------------------------------------------------------------------ b) multi-sensor incidents and chaos
DEFAULT_SETS = [
    "ventilation_failure+power_throttling",
    "ventilation_failure+tank_leak",
    "ventilation_failure+power_throttling+tank_leak",
    "stuck_sensor+heat_buildup+pump_cycling",
    "ventilation_failure+power_throttling+tank_leak+pm_spike",
]


def batching_checks(u, label, ex):
    n = ex["n_llm_agents"]
    tl = ex["timeline_new"] if ex["stage"] != "early" else ex["timeline_all"]
    if n >= 2 and (ex["stage"] == "early" or tl["orchestrated_n"]):
        # one model load / one htpd batch for every agent (htpd splits above its stream count, 10 for v2).
        # Refinements run on a quiet working copy whose orchestrator lines are not in the timeline, so
        # they are only judged when the timeline carries them.
        u.check(f"{label}: {n} NPU agents announced as one batch", n in tl["batched_n"] or sum(tl["batched_n"]) >= n,
                f"batched_n={tl['batched_n']} orchestrated={tl['orchestrated_n']}", hard=ex["stage"] == "early")
    u.check(f"{label}: solo re-runs of invalid batched answers <= 3", tl["solo_reruns"] <= 3, f"{tl['solo_reruns']}")


def phase_multi():
    say("\n== b) multi-sensor incidents: several scenarios at once ==")
    sets = A.multi_sets.split(",") if A.multi_sets else DEFAULT_SETS
    for st in sets:
        scs = [x for x in st.split("+") if x]
        key = f"multi/{st}"
        if unit_done(key):
            say(f"  (done earlier) {st}")
            continue
        thermal_pace(st)
        u = Unit("multi", key)
        fresh_board()
        before = set(S.incident_ids())
        codes = [S.req("/api/inject", {"scenario": sc})[0] for sc in scs]
        say(f"\n -- multi {st}: injected {codes}")
        u.check(f"{st}: all injectable", all(c == 200 for c in codes), str(codes))
        ids, dt = new_incidents(before, A.incident_wait, settle=15)
        u.data.update({"set": scs, "incidents": ids})
        if not u.check(f"{st}: incident(s) raised", ids, str(ids)):
            u.save(); continue
        fr = follow(ids, f"multi_{st}", discover=lambda: [i for i in S.incident_ids() if i not in before])
        u.data["follow"] = fr
        roles_hit = set()
        for iid, r in fr.items():
            check_incident_basics(u, iid, r, f"{st} ")
            rows = check_windows(u, iid, r["stages"], f"{st} ")
            for stg, ex in r["stages"].items():
                batching_checks(u, f"{st} {iid} {stg}", ex)
                roles_hit |= {s["role"] for s in ex["sensors"]}
            # per-sensor windows at the refine stages: sensors of different early families should differ
            for stg in ("1.5h", "3h"):
                rs = [x for x in rows if x["stage"] == stg]
                fams = {x["early_family"] for x in rs}
                if len(rs) >= 2 and len(fams) >= 2:
                    u.data.setdefault("per_sensor_windows", []).append(
                        {"incident": iid, "stage": stg, "windows": [(x["metric"], x["early_family"], x["win_n"]) for x in rs]})
        n_max = max((ex["n_llm_agents"] for r in fr.values() for ex in r["stages"].values()), default=0)
        u.data["max_agents_in_one_incident"] = n_max
        u.check(f"{st}: {len(scs)} scenarios -> one incident with >= 2 NPU agents", n_max >= 2,
                f"max agents in one incident {n_max}, incidents {len(ids)}", hard=False)
        stuck, waited = wait_no_running()
        u.check(f"{st}: no incident left running", not stuck, f"{stuck} after {waited}s")
        u.save()


def chaos_targets():
    targets = {}
    for s in S.sensors():
        if s["metric"] == "occ":
            targets[s["node"], s["metric"]] = 1
        elif s["metric"] in ("ac_units_on", "ac_on"):
            targets[s["node"], s["metric"]] = 0
        else:
            hi = rng.random() < 0.75
            frac = rng.uniform(0.6, 0.95)
            v = s["default"] + (s["max"] - s["default"]) * frac if hi else s["default"] - (s["default"] - s["min"]) * frac
            targets[s["node"], s["metric"]] = round(v, 2)
    return targets


def phase_chaos():
    say(f"\n== b) chaos: every sensor abnormal at once, {A.chaos_rounds} round(s) - worst-case latency vs v1 14.7 s ==")
    for r in range(A.chaos_rounds):
        key = f"chaos/round{r + 1}"
        if unit_done(key):
            say(f"  (done earlier) {key}")
            continue
        thermal_pace(key)
        u = Unit("chaos", key)
        fresh_board()
        before = set(S.incident_ids())
        targets = chaos_targets()
        u.data["targets"] = {f"{n}|{m}": v for (n, m), v in targets.items()}
        stop = threading.Event()

        def drive():  # hold every value like a real event, until the analysis is over
            while not stop.is_set():
                vals = [{"node": n, "metric": m, "value": v} for (n, m), v in targets.items()]
                S.req("/api/sensors", {"values": vals}, timeout=20)
                stop.wait(1)

        th = threading.Thread(target=drive, daemon=True)
        th.start()
        try:
            ids, dt = new_incidents(before, A.incident_wait, settle=10)
            u.data["incidents"] = ids
            if not u.check(f"{key}: incident raised", ids, str(ids)):
                continue
            fr = follow(ids, f"chaos_r{r + 1}", discover=lambda: [i for i in S.incident_ids() if i not in before])
            u.data["follow"] = fr
            main = max(fr.items(), key=lambda kv: (kv[1]["stages"].get("early") or {}).get("n_llm_agents") or 0)
            iid, mr = main
            ex = mr["stages"].get("early")
            if not u.check(f"{key}: main incident {iid} finished its early analysis", ex, mr["final_state"]):
                continue
            n, ms = ex["n_llm_agents"], ex["stage_ms"] or ex["total_ms"] or 0
            u.data["main"] = {"incident": iid, "n_agents": n, "early_ms": ms,
                              "stage_ms": {k: v.get("stage_ms") or v.get("total_ms") for k, v in mr["stages"].items()}}
            say(f"  chaos main {iid}: {n} NPU agents, early analysis {ms / 1000:.1f}s (v1 baseline 14.7 s)")
            u.check(f"{key}: >= 10 NPU agents in the main incident", n >= 10, f"{n} agents", hard=False)
            u.check(f"{key}: early analysis {ms / 1000:.1f}s within v1 baseline 14.7 s ({n} agents)",
                    ms and ms <= V1_CHAOS_BASELINE_MS, f"{ms:.0f} ms", hard=False)
            batching_checks(u, f"{key} {iid} early", ex)
            check_incident_basics(u, iid, mr, f"{key} ")
            check_windows(u, iid, mr["stages"], f"{key} ")
            u.check(f"{key}: cross-domain report names >= 2 domains", len(ex["final"].get("domains") or []) >= 2,
                    str(ex["final"].get("domains")), hard=False)
        finally:
            stop.set()
            th.join(5)
            S.reset()
            st = status()
            t, guard = temps(st)
            u.data["temp_after_c"] = t
            u.check(f"{key}: thermal guard not tripped", not guard, f"{t} C")
            u.save()


# ------------------------------------------------------------------ c) random sensor faults through /api/ingest
FAULT_KINDS = ["stuck", "noise", "dropout", "saturation", "quantised"]


def fault_driver(s, kind, stop):
    """Drives one sensor with a fault. Note the simulator adds the sensor's own jitter to whatever value is
    held and clamps to [min, max], so a noise-free stuck value is only possible at a rail: 'stuck' holds the
    LOW rail, 'saturation' the HIGH rail (both read exactly flat). A mid-range stuck sensor is covered by the
    stuck_sensor scenario in phase a."""
    lo, hi, d = s["min"], s["max"], s["default"]
    span, noise = hi - lo, max(s.get("noise") or 0, (hi - lo) * 0.002)
    q = max(noise * 20, span * 0.05)
    level = d
    k = 0
    while not stop.is_set():
        if kind == "stuck":
            v = lo - 6 * noise - 1
        elif kind == "saturation":
            v = hi + 6 * noise + 1
        elif kind == "noise":
            v = d + rng.uniform(-0.3, 0.3) * span
        elif kind == "dropout":
            v = lo if rng.random() < 0.4 else d
        else:  # quantised: coarse steps of q around a slow walk
            level += rng.uniform(-noise, noise)
            v = round(level / q) * q
        S.req("/api/ingest", {"node": s["node"], "metric": s["metric"], "value": round(v, 3)}, timeout=15, _retry=False)
        k += 1
        stop.wait(0.5)


def phase_faults():
    say(f"\n== c) random sensor faults via /api/ingest: {A.fault_trials} trial(s) ==")
    pool = [s for s in S.sensors() if s["metric"] not in NO_AGENT_METRICS and s.get("role") != "hvac"]
    frng = random.Random(A.seed + 7)
    plan = [(frng.choice(pool), FAULT_KINDS[i % len(FAULT_KINDS)] if i < len(FAULT_KINDS) else frng.choice(FAULT_KINDS))
            for i in range(A.fault_trials)]
    for t, (s, kind) in enumerate(plan):
        key = f"faults/{t + 1:02d}_{kind}_{s['node']}_{s['metric']}"
        if unit_done(key):
            say(f"  (done earlier) {key}")
            continue
        thermal_pace(key)
        u = Unit("faults", key)
        u.data.update({"kind": kind, "sensor": s})
        fresh_board()
        before = set(S.incident_ids())
        stop = threading.Event()
        th = threading.Thread(target=fault_driver, args=(s, kind, stop), daemon=True)
        say(f"\n -- fault {kind} on {s['metric']}@{s['node']} ({s['role']})")
        th.start()
        try:
            ids, dt = new_incidents(before, A.fault_wait, settle=5)
            u.data["incidents"] = ids
            mine = []
            for iid in ids:
                inc = incident(iid) or {}
                if any(x.get("node") == s["node"] and x.get("metric") == s["metric"] and not x.get("context")
                       for x in inc.get("sensors") or []):
                    mine.append(iid)
            # stuck at a zero rail is a plausible 'off' reading, not necessarily a fault: soft for every kind
            if not u.check(f"{kind} {s['metric']}@{s['node']}: incident raised for the faulty sensor", mine,
                           f"{mine} (all new: {ids})", hard=False):
                continue
            fr = follow(mine, f"faults_{t + 1:02d}_{kind}")
            u.data["follow"] = fr
            for iid, r in fr.items():
                check_incident_basics(u, iid, r, f"{kind} ")
                check_windows(u, iid, r["stages"], f"{kind} ")
                early = (r["stages"].get("early") or {}).get("sensors", [])
                me = next((x for x in early if x["node"] == s["node"] and x["metric"] == s["metric"]), None)
                if not me:
                    continue
                fam = family(me["pattern"] if me["valid"] else me["rule_pattern"], s["role"])
                u.data.setdefault("early", []).append({"incident": iid, **{k: me[k] for k in
                                                       ("pattern", "status", "fault_kind", "rule_pattern", "rule_status", "valid")},
                                                       "family": fam})
                if fam in ("flat", "noisy"):
                    # expectation from the brief: flat/noisy faults are sensor faults, analysed on 12 h windows
                    zero_rail = kind == "stuck" and abs(s["min"]) < 1e-6
                    u.check(f"{kind} {iid}: early {fam} family -> status sensor_fault",
                            me["status"] == "sensor_fault" or me["rule_status"] == "sensor_fault",
                            f"agent {me['pattern']}/{me['status']} fault_kind={me['fault_kind']} rule {me['rule_pattern']}/{me['rule_status']}",
                            hard=not zero_rail)
                    for stg in ("1.5h", "3h"):
                        ex = r["stages"].get(stg)
                        if not ex:
                            continue
                        w = next((x for x in ex["sensors"] if x["node"] == s["node"] and x["metric"] == s["metric"]), None)
                        if w and (fam == "flat" or w.get("status") == "sensor_fault" or me["status"] == "sensor_fault"
                                  or stg == "3h"):
                            u.check(f"{kind} {iid} {stg}: 12 h window for a {fam} fault", w["win_n"] == WIN_LONG,
                                    f"win_n={w['win_n']}")
                else:
                    u.check(f"{kind} {iid}: early family {fam} (not flat/noisy: no 12 h expectation)", True,
                            f"agent {me['pattern']}/{me['status']}", hard=False)
        finally:
            stop.set()
            th.join(5)
            u.save()


# ------------------------------------------------------------------ d) calm-board false alarm soak
def phase_soak():
    key = f"soak/{A.soak_min}min"
    say(f"\n== d) calm board for {A.soak_min} min: plausible random values, expect NO incidents ==")
    if unit_done(key):
        say("  (done earlier)")
        return
    thermal_pace("soak")
    u = Unit("soak", key)
    fresh_board()
    before = set(S.incident_ids())
    ss = [s for s in S.sensors()]
    srng = random.Random(A.seed + 11)
    walk = {(s["node"], s["metric"]): s["default"] for s in ss}
    t0, sent, samples = time.time(), 0, []
    while time.time() - t0 < A.soak_min * 60:
        for s in srng.sample(ss, min(6, len(ss))):
            if s["metric"] in NO_AGENT_METRICS:
                continue  # occupancy / AC state: leave at the default (a change is an event, not noise)
            k = (s["node"], s["metric"])
            span = max((s.get("noise") or 0) * 2, (s["max"] - s["min"]) * 0.002)
            # mean-reverting walk within ~ the sensor's own jitter
            walk[k] = walk[k] + srng.uniform(-span, span) * 0.5 - (walk[k] - s["default"]) * 0.2
            S.req("/api/ingest", {"node": s["node"], "metric": s["metric"], "value": round(walk[k], 3)}, timeout=15)
            sent += 1
        if int(time.time() - t0) % 60 < 1:
            samples.append({"t": round(time.time() - t0), "new": [i for i in S.incident_ids() if i not in before]})
        time.sleep(1)
    new = [i for i in S.incident_ids() if i not in before]
    u.data.update({"ingests": sent, "readings_per_sensor": int(A.soak_min * 60), "new_incidents": new, "samples": samples,
                   "incidents": [extract(incident(i) or {}) for i in new]})
    for i in new:
        inc = incident(i)
        if inc:
            wjson(OUT / "raw" / "soak" / f"{i}.json", inc)
    u.check(f"soak: no false alarms in {A.soak_min} min ({sent} plausible readings)", not new, f"spurious: {new}")
    u.save()


# ------------------------------------------------------------------ e) SSE streaming
class SSE:
    def __init__(self):
        self.events, self.stop, self.err = [], threading.Event(), None
        self.th = threading.Thread(target=self.run, daemon=True)

    def run(self):
        try:
            r = urllib.request.urlopen(S.B + "/api/events", timeout=40)
            ev, data = None, []
            while not self.stop.is_set():
                line = r.readline()
                if not line:
                    break
                line = line.decode("utf-8", "replace").rstrip("\r\n")
                if line.startswith("event:"):
                    ev = line[6:].strip()
                elif line.startswith("data:"):
                    data.append(line[5:].strip())
                elif line == "":
                    if ev and ev not in ("live", "tick", "ingest"):
                        try:
                            d = json.loads("\n".join(data))
                        except Exception:
                            d = "\n".join(data)
                        self.events.append({"t": time.time(), "event": ev, "data": d})
                    ev, data = None, []
        except Exception as e:
            self.err = str(e)

    def start(self):
        self.th.start()
        time.sleep(1)
        return self


def stream_stats(events, t_ref):
    toks = {}
    inc_first = {}
    for e in events:
        d = e["data"] if isinstance(e["data"], dict) else {}
        if e["event"] == "incident" and d.get("id"):
            inc_first.setdefault(d["id"], e["t"])
        if e["event"] == "token":
            toks.setdefault((d.get("incident"), d.get("ref")), []).append((e["t"], len(d.get("text") or "")))
    out = []
    for (iid, ref), ts in sorted(toks.items(), key=lambda kv: kv[1][0][0]):
        t0 = inc_first.get(iid, t_ref)
        gaps = [round((b[0] - a[0]) * 1000) for a, b in zip(ts, ts[1:])]
        out.append({"incident": iid, "ref": ref, "token_events": len(ts), "chars": sum(c for _, c in ts),
                    "first_token_s_from_incident": round(ts[0][0] - t0, 2), "first_token_s_from_inject": round(ts[0][0] - t_ref, 2),
                    "stream_s": round(ts[-1][0] - ts[0][0], 2),
                    "gap_ms": dist(gaps), "max_gap_ms": max(gaps) if gaps else None})
    return out


def phase_stream():
    say("\n== e) streaming: SSE token events per agent while an incident runs ==")
    for st in (A.stream_sets.split(",") if A.stream_sets else ["crowded_room", "ventilation_failure+power_throttling+tank_leak"]):
        key = f"stream/{st}"
        if unit_done(key):
            say(f"  (done earlier) {key}")
            continue
        thermal_pace(key)
        u = Unit("stream", key)
        fresh_board()
        sse = SSE().start()
        before = set(S.incident_ids())
        t_inj = time.time()
        for sc in st.split("+"):
            S.req("/api/inject", {"scenario": sc})
        ids, dt = new_incidents(before, A.incident_wait, settle=10)
        if not u.check(f"{st}: incident raised", ids, str(ids)):
            sse.stop.set(); u.save(); continue
        # the token stream belongs to the early analysis (refinements are quiet), so wait for it only
        incs = {i: S.wait_done(i, A.stage_timeout) for i in ids}
        time.sleep(2)
        sse.stop.set()
        ev = list(sse.events)
        with open(OUT / "raw" / f"sse_{re.sub(r'[^A-Za-z0-9_]+', '_', st)}.jsonl", "w", encoding="utf-8") as f:
            for e in ev:
                f.write(json.dumps(e) + "\n")
        stats = stream_stats(ev, t_inj)
        u.data.update({"incidents": ids, "sse_error": sse.err, "events": len(ev), "per_agent": stats})
        u.check(f"{st}: SSE connected and delivered incident events", any(e["event"] == "incident" for e in ev),
                f"{len(ev)} events err={sse.err}")
        for iid, inc in incs.items():
            if not inc:
                u.check(f"{st} {iid}: early analysis finished", False, "timeout")
                continue
            wjson(OUT / "raw" / f"stream_{iid}.json", inc)
            refs = [a["ref"] for a in inc.get("agents") or [] if a.get("prompt")]
            got = {s["ref"] for s in stats if s["incident"] == iid}
            missing = [r for r in refs if r not in got]
            u.check(f"{st} {iid}: every NPU agent streamed tokens ({len(refs)} agents)", not missing, f"missing {missing}")
            final = [s for s in stats if s["incident"] == iid and s["ref"] == "final"]
            if (inc.get("final") or {}).get("prompt"):
                u.check(f"{st} {iid}: synthesizer streamed tokens", final, "", hard=False)
            for s in stats:
                if s["incident"] == iid:
                    a = next((x for x in inc.get("agents") or [] if x.get("ref") == s["ref"]), {})
                    s["agent_ttft_ms"], s["agent_latency_ms"] = a.get("ttft_ms"), a.get("latency_ms")
                    say(f"    {iid} {s['ref']:5} first token {s['first_token_s_from_incident']:6.2f}s after incident, "
                        f"{s['token_events']} events, max gap {s['max_gap_ms']} ms (agent ttft {s['agent_ttft_ms']})")
        u.save()


# ------------------------------------------------------------------ f) robustness
def wait_running_with_agents(before, timeout):
    """First new incident, returned once it is running and its agents have started (timeline)."""
    t0 = time.time()
    iid = None
    while time.time() - t0 < timeout:
        if not iid:
            new = [i for i in S.incident_ids() if i not in before]
            iid = new[0] if new else None
        if iid:
            inc = incident(iid) or {}
            tl = " ".join(t.get("msg", "") for t in inc.get("timeline") or [])
            if inc.get("state") == "running" and ("Orchestrator" in tl or "agent" in tl):
                return iid, inc
            if inc.get("state") in DONE:
                return iid, inc
        time.sleep(0.5)
    return iid, None


def after_recovery_checks(u, label):
    ok_up = S.wait_backend(240)
    u.check(f"{label}: backend reachable again", ok_up, "")
    S.req("/api/mode", {"mode": 3})
    idle, waited = npu_idle(240)
    u.check(f"{label}: NPU queue drained (not busy, queue 0)", idle, f"waited {waited}s")
    stuck, waited = wait_no_running()
    u.check(f"{label}: no incident stuck in 'running'", not stuck, f"{stuck} after {waited}s")
    # the system still works: a fresh incident end to end
    fresh_board(warmup=min(A.warmup, 20))
    before = set(S.incident_ids())
    S.req("/api/inject", {"scenario": "ventilation_failure"})
    iid, _ = S.wait_new_incident(before, A.incident_wait)
    inc = S.wait_done(iid, A.stage_timeout) if iid else None
    u.check(f"{label}: a new incident afterwards completes", inc and inc.get("state") in DONE,
            f"{iid} {(inc or {}).get('state')}")
    if inc:
        wjson(OUT / "raw" / "robust" / f"{label.replace(' ', '_')}_after_{iid}.json", inc)


def phase_robust():
    say("\n== f) robustness: backend restart mid-incident, htpd kill mid-batch ==")
    restart_cmd = A.restart_cmd if A.restart_cmd is not None else f'"{S.ADB}" shell pkill -x edge-agent'
    htpd_cmd = A.htpd_kill_cmd if A.htpd_kill_cmd is not None else f'"{S.ADB}" shell pkill -x htpd'
    trials = [("backend_restart", restart_cmd, k) for k in range(A.robust_trials)] + \
             [("htpd_kill", htpd_cmd, k) for k in range(A.robust_trials)]
    for kind, cmd, k in trials:
        key = f"robust/{kind}_{k + 1}"
        if unit_done(key):
            say(f"  (done earlier) {key}")
            continue
        if not cmd:
            say(f"  {key}: no command configured - skipped")
            continue
        thermal_pace(key)
        u = Unit("robust", key)
        fresh_board()
        before = set(S.incident_ids())
        for sc in ("ventilation_failure", "power_throttling", "tank_leak"):
            S.req("/api/inject", {"scenario": sc})
        iid, inc = wait_running_with_agents(before, A.incident_wait)
        u.data["incident"] = iid
        if not u.check(f"{key}: incident running before the fault", iid and inc, f"{iid}"):
            u.save(); continue
        time.sleep(A.kill_delay)
        was = (incident(iid) or {}).get("state")
        res = run_cmd(cmd)
        say(f"  {key}: {kind} while {iid} was {was}: {res}")
        u.data.update({"state_at_fault": was, "cmd": res, "t_fault": time.time()})
        u.check(f"{key}: fault landed while the analysis was running", was == "running", was, hard=False)
        time.sleep(3)
        if kind == "backend_restart":
            up = S.wait_backend(240)
            u.data["restart_s"] = round(time.time() - u.data["t_fault"], 1)
            u.check(f"{key}: backend back within 240 s", up, f"{u.data['restart_s']}s")
            inc2 = incident(iid) or {}
            u.check(f"{key}: interrupted incident not left 'running' (failed/done are both recorded)",
                    inc2.get("state") in DONE + ("failed",), inc2.get("state"))
            if inc2.get("state") == "failed":
                bef = set(S.incident_ids())
                code, _ = S.req(f"/api/incidents/{iid}/rerun?mode=3", {})
                nid, _ = S.wait_new_incident(bef, A.incident_wait)
                done = S.wait_done(nid, A.stage_timeout) if nid else None
                u.check(f"{key}: rerun of the interrupted incident completes", done and done.get("state") in DONE,
                        f"HTTP {code} {nid} {(done or {}).get('state')}")
            wjson(OUT / "raw" / "robust" / f"{kind}_{k + 1}_{iid}.json", inc2)
        else:
            done = S.wait_done(iid, A.stage_timeout + 120)
            u.check(f"{key}: incident ends done/done_with_errors after the htpd kill", done and done.get("state") in DONE,
                    (done or {}).get("state") or "timeout")
            if done:
                ex = extract(done)
                u.data["after"] = ex
                wjson(OUT / "raw" / "robust" / f"{kind}_{k + 1}_{iid}.json", done)
                u.check(f"{key}: every agent has an answer (AI or rule fallback)",
                        all(s["pattern"] or s["rule_pattern"] for s in ex["sensors"]), "")
                st = status()
                u.data["genie_daemon"] = st.get("genie_daemon")
        after_recovery_checks(u, key)
        u.save()


# ------------------------------------------------------------------ summary
def summarize():
    units = []
    for p in sorted((OUT / "units").glob("*.json")):
        try:
            units.append(json.loads(p.read_text(encoding="utf-8")))
        except Exception:
            pass
    phases = {}
    for un in units:
        ph = phases.setdefault(un["phase"], {"units": 0, "hard_pass": 0, "hard_fail": 0, "soft_warn": 0, "seconds": 0,
                                             "failures": [], "warnings": []})
        ph["units"] += 1
        ph["seconds"] += un.get("seconds", 0)
        for c in un["checks"]:
            if c["ok"]:
                ph["hard_pass"] += c["hard"]
            elif c["hard"]:
                ph["hard_fail"] += 1
                ph["failures"].append(f"{un['key']}: {c['check']} - {c['evidence'][:200]}")
            else:
                ph["soft_warn"] += 1
                ph["warnings"].append(f"{un['key']}: {c['check']} - {c['evidence'][:200]}")
    # latency / NPU metrics over every followed stage
    by_n, stage_ms, agent_lat, agent_ttft, agent_tps, final_lat = {}, {}, [], [], [], []
    solo = cached = npu_un = 0
    windows = []
    for un in units:
        d = un.get("data") or {}
        windows += d.get("window_rows", [])
        follows = [d.get("follow")] if d.get("follow") else []
        follows += [s.get("follow") for s in d.get("steps", []) if s.get("follow")]
        for fr in follows:
            for r in fr.values():
                for stg, ex in r["stages"].items():
                    ms = ex.get("stage_ms") or ex.get("total_ms")
                    stage_ms.setdefault(stg, []).append(ms)
                    if stg == "early":
                        by_n.setdefault(ex["n_llm_agents"], []).append(ms)
                    for s in ex["sensors"]:
                        if s["llm"]:
                            agent_lat.append(s["latency_ms"]); agent_ttft.append(s["ttft_ms"]); agent_tps.append(s["tokens_per_s"])
                    final_lat.append(ex["final"].get("latency_ms"))
                    tl = ex["timeline_new"] if stg != "early" else ex["timeline_all"]
                    solo += tl["solo_reruns"]; cached += tl["cached"]; npu_un += tl["npu_unavailable_reruns"]
    chaos = [un["data"].get("main") for un in units if un["phase"] == "chaos" and un["data"].get("main")]
    faults = [{"key": un["key"], "early": un["data"].get("early")} for un in units if un["phase"] == "faults"]
    streams = [s for un in units if un["phase"] == "stream" for s in un["data"].get("per_agent", [])]
    soak = [{"key": un["key"], "new_incidents": un["data"].get("new_incidents")} for un in units if un["phase"] == "soak"]
    summ = {"generated": datetime.now(IST).isoformat(timespec="seconds"), "phases": phases,
            "latency_ms": {"early_by_n_agents": {str(n): dist(v) for n, v in sorted(by_n.items())},
                           "by_stage": {k: dist(v) for k, v in stage_ms.items()},
                           "agent_latency": dist(agent_lat), "agent_ttft": dist(agent_ttft), "agent_tokens_per_s": dist(agent_tps),
                           "synth_latency": dist(final_lat)},
            "v1_chaos_baseline_ms": V1_CHAOS_BASELINE_MS, "chaos": chaos,
            "npu": {"solo_reruns": solo, "cached_answers": cached, "npu_unavailable_reruns": npu_un},
            "windows": {"rows": len(windows), "bad": sum(not w["ok"] for w in windows),
                        "inexact": sum(w["ok"] and not w["exact"] for w in windows),
                        "by_family_stage": _win_table(windows)},
            "faults": faults, "soak": soak,
            "stream": {"agents": len(streams), "first_token_s": dist([s["first_token_s_from_incident"] for s in streams]),
                       "max_gap_ms": dist([s["max_gap_ms"] for s in streams])}}
    wjson(OUT / "summary.json", summ)
    wjson(OUT / "window_check.json", windows)
    lines = [f"app_suite_v2 summary  {summ['generated']}  ({OUT})", ""]
    tf = 0
    for name in ALL_PHASES:
        ph = phases.get(name)
        if not ph:
            continue
        tf += ph["hard_fail"]
        lines.append(f"{name:10} units={ph['units']:3}  hard pass={ph['hard_pass']:4} FAIL={ph['hard_fail']:3}  "
                     f"WARN={ph['soft_warn']:3}  {ph['seconds'] / 60:6.1f} min")
    lines += ["", "early-analysis latency by NPU agents (ms):"]
    for n, dd in summ["latency_ms"]["early_by_n_agents"].items():
        lines.append(f"  N={n:>2}: {dd}")
    lines.append(f"by stage: {summ['latency_ms']['by_stage']}")
    lines.append(f"agent latency {summ['latency_ms']['agent_latency']}")
    lines.append(f"agent ttft    {summ['latency_ms']['agent_ttft']}")
    lines.append(f"agent tok/s   {summ['latency_ms']['agent_tokens_per_s']}")
    lines.append(f"synthesizer   {summ['latency_ms']['synth_latency']}")
    for c in chaos:
        lines.append(f"chaos {c['incident']}: {c['n_agents']} agents, early {c['early_ms'] / 1000:.1f}s vs v1 14.7 s "
                     f"({(c['early_ms'] - V1_CHAOS_BASELINE_MS) / 1000:+.1f}s)")
    lines.append(f"NPU: {summ['npu']}")
    lines.append(f"windows: {summ['windows']['rows']} sensor-stages, {summ['windows']['bad']} bad, "
                 f"{summ['windows']['inexact']} differ from recomputed WindowN")
    for k, v in summ["windows"]["by_family_stage"].items():
        lines.append(f"  {k:22} {v}")
    lines.append(f"stream: {summ['stream']}")
    for s in soak:
        lines.append(f"soak {s['key']}: {len(s['new_incidents'] or [])} false alarm(s) {s['new_incidents']}")
    lines += ["", f"==== {tf} hard failure(s) ===="]
    for ph in phases.values():
        lines += ["  FAIL " + f for f in ph["failures"]]
    for ph in phases.values():
        lines += ["  WARN " + w for w in ph["warnings"][:40]]
    (OUT / "summary.txt").write_text("\n".join(lines) + "\n", encoding="utf-8")
    say("\n" + "\n".join(lines))
    return tf


def _win_table(rows):
    t = {}
    for r in rows:
        k = f"{r['stage']} {r['early_family']}"
        t.setdefault(k, {})
        t[k][r["win_n"]] = t[k].get(r["win_n"], 0) + 1
    return {k: dict(sorted(v.items())) for k, v in sorted(t.items())}


def manifest(phases, t_start, t_end=None):
    git = subprocess.run(["git", "rev-parse", "HEAD"], capture_output=True, text=True, cwd=Path(__file__).parent).stdout.strip()
    dirty = subprocess.run(["git", "status", "--porcelain"], capture_output=True, text=True, cwd=Path(__file__).parent).stdout
    st = status()
    wjson(OUT / "manifest.json", {
        "tool": "app/tools/app_suite_v2.py", "args": vars(A), "phases": phases, "git_head": git,
        "git_dirty_files": len(dirty.splitlines()), "started": datetime.fromtimestamp(t_start, IST).isoformat(),
        "ended": datetime.fromtimestamp(t_end, IST).isoformat() if t_end else None,
        "backend": {k: st.get(k) for k in ("running_on", "models", "genie_daemon", "mode", "replay", "device", "npu", "uptime_s")},
        "files": {"units/*.json": "per-unit checks + data", "raw/<tag>/<INC>_<stage>.json": "full incident per stage",
                  "raw/sse_*.jsonl": "SSE events (token/incident/log)", "summary.json/.txt": "aggregate",
                  "window_check.json": "every sensor-stage window row", "console.txt": "console log"}})


def main():
    global A, OUT, LOG
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--out", required=True)
    ap.add_argument("--phases", default="all", help="comma list of " + ",".join(ALL_PHASES) + " or all")
    ap.add_argument("--quick", action="store_true", help="short pass: 3 scenarios, 2 multi sets, 1 chaos, 5 faults, 3 min soak")
    ap.add_argument("--fresh", action="store_true", help="redo units already finished in --out")
    ap.add_argument("--summarize-only", action="store_true")
    ap.add_argument("--base", default=S.B, help="backend URL (default via adb forward)")
    ap.add_argument("--no-adb", action="store_true", help="never call adb (local/host backend)")
    ap.add_argument("--seed", type=int, default=20261022)
    ap.add_argument("--warmup", type=int, default=48, help="seconds of history after a reset (1 reading/s)")
    ap.add_argument("--incident-wait", type=int, default=150)
    ap.add_argument("--stage-timeout", type=int, default=300, help="per analysis stage; following allows 3x")
    ap.add_argument("--scenarios", default="", help="comma list (default: every scenario from /api/scenarios)")
    ap.add_argument("--multi-sets", default="", help="comma list of a+b+c sets")
    ap.add_argument("--chaos-rounds", type=int, default=2)
    ap.add_argument("--fault-trials", type=int, default=10)
    ap.add_argument("--fault-wait", type=int, default=120)
    ap.add_argument("--soak-min", type=float, default=15)
    ap.add_argument("--stream-sets", default="")
    ap.add_argument("--robust-trials", type=int, default=2)
    ap.add_argument("--kill-delay", type=float, default=3.0, help="seconds after the agents start before the fault")
    ap.add_argument("--restart-cmd", default=None, help="default: adb shell pkill -x edge-agent (EdgeService restarts it)")
    ap.add_argument("--htpd-kill-cmd", default=None, help='default: adb shell pkill -x htpd ("" skips)')
    ap.add_argument("--max-temp", type=float, default=80.0)
    ap.add_argument("--resume-temp", type=float, default=70.0)
    ap.add_argument("--thermal-wait-max", type=int, default=1800)
    A = ap.parse_args()
    if A.quick:
        A.scenarios = A.scenarios or "ventilation_failure,stuck_sensor,crowded_room"
        A.multi_sets = A.multi_sets or "ventilation_failure+power_throttling,ventilation_failure+power_throttling+tank_leak+pm_spike"
        A.chaos_rounds, A.fault_trials, A.soak_min, A.robust_trials = 1, 5, min(A.soak_min, 3), 1
        A.stream_sets = A.stream_sets or "ventilation_failure+power_throttling"
    OUT = Path(A.out).resolve()
    (OUT / "units").mkdir(parents=True, exist_ok=True)
    LOG = open(OUT / "console.txt", "a", encoding="utf-8")
    S.B = A.base.rstrip("/")
    if A.no_adb:
        S.wait_backend = local_wait_backend
    if A.summarize_only:
        return summarize()
    phases = ALL_PHASES if A.phases == "all" else [p.strip() for p in A.phases.split(",") if p.strip()]
    unknown = [p for p in phases if p not in ALL_PHASES]
    if unknown:
        sys.exit(f"unknown phase(s) {unknown}; choose from {ALL_PHASES}")
    t_start = time.time()
    say(f"\n######## app_suite_v2 {datetime.now(IST).isoformat(timespec='seconds')} phases={phases} base={S.B}")
    if not S.wait_backend(60):
        sys.exit(f"backend not reachable at {S.B}")
    manifest(phases, t_start)
    st = status()
    say(f"backend: {st.get('running_on')} agent={((st.get('models') or {}).get('agent') or {}).get('name')} "
        f"daemon={st.get('genie_daemon')} temps={temps(st)}")
    fns = {"scenarios": phase_scenarios, "chain": phase_chain, "multi": phase_multi, "chaos": phase_chaos,
           "faults": phase_faults, "soak": phase_soak, "stream": phase_stream, "robust": phase_robust}
    try:
        for p in phases:
            fns[p]()
    except KeyboardInterrupt:
        say("\ninterrupted - finished units are kept; rerun with the same --out to resume")
    finally:
        try:
            S.reset()
            S.req("/api/replay", {"poll_ms": 2000})
            S.req("/api/sensors", {"noise_scale": 1})
        except Exception:
            pass
        manifest(phases, t_start, time.time())
        tf = summarize()
    return tf


if __name__ == "__main__":
    sys.exit(1 if main() else 0)
