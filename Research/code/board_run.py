"""board_run.py: board cost phase through the app's OWN API (the surface the dashboard sliders / stress_app.py use: /api/ingest, /api/incidents).
The app stays the only NPU client (no second harness touches the NPU, no probe requests to htpd). Per run: wait idle + cool, push abnormal values for N sensors
(like stress_app chaos), wait for the incident(s), keep the incident JSON + the htpd.log delta (swap / prefill lines). Mode stays 3 (full path); cheap-arm time
is derived: total_ms - reasoner latency - swap-in (what the incident would cost if it stopped after the agents + template).
  python board_run.py setc [--reps 5]      Set C stress sweep N = 1,2,4,8,12
  python board_run.py sub                  30-case timing subset (10 per stratum of Set B; flagged sensors' final values pushed)
Windows python; adb at Code/platform-tools/adb.exe."""
import json, re, subprocess, sys, time, urllib.request, urllib.error, argparse, random
from pathlib import Path

Q = Path("C:/Users/hp/Desktop/qidk"); P = Q / "proofs/2026-11-26_paper"
ADB = str(Q / "Code/platform-tools/adb.exe"); BASE = "http://127.0.0.1:8000"
LOG = "/data/local/tmp/smart_city_edge/state/htpd.log"
rng = random.Random(26112603)
GAP_S = 360


def req(path, body=None, timeout=30):
    d = json.dumps(body).encode() if body is not None else None
    r = urllib.request.Request(BASE + path, data=d, method="POST" if d is not None else "GET", headers={"Content-Type": "application/json"} if d else {})
    try:
        with urllib.request.urlopen(r, timeout=timeout) as f:
            return f.status, json.loads(f.read() or b"null")
    except urllib.error.HTTPError as e:
        return e.code, None
    except Exception as e:
        return 0, str(e)


def sh(cmd, t=30):
    return subprocess.run([ADB, "shell", cmd], capture_output=True, text=True, timeout=t).stdout


def status():
    return req("/api/status")[1] or {}


def sensors():
    return req("/api/sensors")[1]["sensors"]


def ids():
    d = req("/api/incidents")[1]
    items = d if isinstance(d, list) else (d or {}).get("incidents") or []
    return [i["id"] for i in items]


def temp():
    return (status().get("device") or {}).get("thermal_max_c") or 99


def settle(max_cool=45.0, limit=900):
    """no incident running, NPU idle, board cool"""
    t0 = time.time()
    while time.time() - t0 < limit:
        s = status()
        busy = (s.get("npu") or {}).get("busy")
        run = False
        for i in ids()[:6]:
            d = req("/api/incidents/" + i)[1] or {}
            if d.get("state") not in ("done", "done_with_errors"):
                run = True
        if not busy and not run and temp() <= max_cool:
            return round(time.time() - t0, 1)
        time.sleep(5)
    raise SystemExit("board did not settle (busy/temp) in %d s: stop and report" % limit)


def sim_now():
    bd = int(sh("date +%s").strip()); off = int(sh("cat /data/local/tmp/smart_city_edge/state/clock_offset_s").strip())
    return (bd + off) // 300 * 300


def push(wins, end):
    """wins {(node,metric): 144 values ending at bucket `end`} through /api/ingest {"readings":[..]} with ts (the device path the campus feed uses)"""
    rd = []
    for (node, metric), xs in wins.items():
        n = len(xs)
        rd += [{"node": node, "metric": metric, "value": float(v), "ts": end - 300 * (n - 1 - i)} for i, v in enumerate(xs)]
    for i in range(0, len(rd), 2500):
        code, o = req("/api/ingest", {"readings": rd[i:i + 2500]}, timeout=60)
        if code != 200:
            raise SystemExit("ingest failed %s: stop and report" % code)


def base_series(s):
    return [min(s["max"], max(s["min"], s["default"] + rng.gauss(0, s.get("noise") or 0) * 0.5)) for _ in range(144)]


def wall():
    return int(sh("date +%s").strip()) + int(sh("cat /data/local/tmp/smart_city_edge/state/clock_offset_s").strip())


def push_now(vals):
    """one fresh reading per sensor at the current board time (lands in the open 5-min bucket; boundary/old ts are 'late'/'duplicate')"""
    t = wall() + 1
    if t % 300 == 0:
        t += 1
    rd = [{"node": n, "metric": m, "value": float(v), "ts": t} for (n, m), v in vals.items()]
    code, o = req("/api/ingest", {"readings": rd}, timeout=60)
    if code != 200:
        raise SystemExit("ingest failed %s: stop and report" % code)
    return (t + 299) // 300 * 300  # bucket end


def wait_bucket(b):
    while status().get("sim_time", 0) < b:
        time.sleep(5)


def reset(ss, restart=False):
    b = push_now({(s["node"], s["metric"]): s["default"] for s in ss})
    wait_bucket(b)


def ramp_series(s, top, n_ramp=40):
    b = base_series(s)
    for i in range(144 - n_ramp, 144):
        f = (i - (144 - n_ramp) + 1) / n_ramp
        b[i] = b[i] + (top - b[i]) * f
    return b


def target(s, frac=0.8):
    if s["metric"] == "occ":
        return 1
    if s["metric"] in ("pf", "level"):
        return round(s["default"] - (s["default"] - s["min"]) * frac, 3)
    return round(s["default"] + (s["max"] - s["default"]) * frac, 3)


ORDER = [("SR-AQ-KH03-03", "co2"), ("WE-VN04-00", "temp"), ("SR-EM-KH04-01", "power_kw"), ("AQ-KN00-00", "pm25"), ("WM-WF-KH98-40", "flow"), ("EM-CR-SB00-00", "pf"),
         ("SR-AQ-KH03-03", "temp"), ("EM-CR-SB00-00", "power_kw"), ("WE-VN04-00", "wind"), ("AQ-KN00-00", "pm10"), ("SR-AQ-KH03-03", "rh"), ("WE-VN04-00", "rh"),
         ("WM-WD-KH98-00", "tds"), ("WM-WD-KH98-00", "ph")]


def parse_log(txt):
    o = dict(swap_in_ms=None, agents_unload_ms=None, swap_out_ms=None, unload_ms=None, prefill_ms=[], decode_steps=[], load_model_ms=None)
    for l in txt.splitlines():
        m = re.search(r"reasoner loaded in (\d+) ms \(agents' model unloaded in (\d+) ms\)", l)
        if m:
            o["swap_in_ms"] = (o["swap_in_ms"] or 0) + int(m[1]); o["agents_unload_ms"] = (o["agents_unload_ms"] or 0) + int(m[2])
        m = re.search(r"reasoner unloaded \(idle\): unload (\d+) ms, agents' model back in (\d+) ms", l)
        if m:
            o["unload_ms"] = int(m[1]); o["swap_out_ms"] = int(m[2])
        m = re.search(r"reasoner load phases: model (\d+) ms", l)
        if m:
            o["load_model_ms"] = int(m[1])
        m = re.search(r"reason \d+ streams?, (\d+) decode steps, prefill (\d+) ms", l)
        if m:
            o["decode_steps"].append(int(m[1])); o["prefill_ms"].append(int(m[2]))
    return o


def one_run(tag, wins, ss):
    cool_wait = settle()
    reset(ss); settle()  # one normal bucket closes the previous episode; fast_cooldown=1 lets the sensor open a new fast incident
    before = set(ids())
    off = int((sh("wc -c < " + LOG).strip() or "0"))
    t_hot = temp(); t0 = time.time()
    new = []
    for _ in range(2):  # two abnormal buckets (abnormal_of_window=2) on every target
        if new:
            break
        b = push_now({k: xs[-1] for k, xs in wins.items()})
        while status().get("sim_time", 0) < b and not new:
            time.sleep(2); new = [i for i in ids() if i not in before]
    while time.time() - t0 < 900 and not new:
        time.sleep(1); new = [i for i in ids() if i not in before]
    if not new:
        reset(ss)
        return dict(tag=tag, error="no incident in 900 s", n_targets=len(wins))
    t_raise = time.time() - t0
    time.sleep(20)
    new = [i for i in ids() if i not in before]
    incs = []
    for i in new:
        t1 = time.time(); d = None
        while time.time() - t1 < 300:
            d = req("/api/incidents/" + i)[1]
            if d and d.get("state") in ("done", "done_with_errors"):
                break
            time.sleep(1.5)
        incs.append(d)
    time.sleep(6)
    logtxt = sh("tail -c +%d %s" % (off + 1, LOG), 60)
    reset(ss); reset(ss)
    return dict(tag=tag, n_targets=len(wins), cool_wait_s=cool_wait, temp_start_c=t_hot, temp_end_c=temp(), t_raise_s=round(t_raise, 1), incidents=[slim(d) for d in incs if d], log=parse_log(logtxt))


def slim(d):
    f = d.get("final") or {}
    ag = [dict(ref=a.get("ref"), role=a.get("role"), latency_ms=a.get("latency_ms"), ttft_ms=a.get("ttft_ms"), gen_tokens=a.get("gen_tokens"), valid=a.get("valid")) for a in d.get("agents") or [] if a.get("prompt") or a.get("latency_ms")]
    p = f.get("parsed") or {}
    return dict(id=d["id"], state=d["state"], mode=d.get("mode"), total_ms=d.get("total_ms"), npu_calls=d.get("npu_calls"), n_sensors=len(d.get("sensors") or []), n_primary=sum(1 for x in d.get("sensors") or [] if not x.get("context")),
                agents=ag, reasoner=dict(model=f.get("model"), latency_ms=f.get("latency_ms"), ttft_ms=f.get("ttft_ms"), gen_tokens=f.get("gen_tokens"), valid=f.get("valid"),
                                         label=p.get("label"), severity=p.get("severity"), domains=p.get("affected_domains")), timeline=[(x["t"], x["msg"]) for x in d.get("timeline") or []])


def derive(r):
    """per-run main incident (max npu_calls): stage times"""
    if "error" in r:
        return r
    m = max(r["incidents"], key=lambda i: i.get("npu_calls") or 0)
    lg = r["log"]; rl = m["reasoner"]["latency_ms"] or 0; used = bool(rl)
    swap = lg["swap_in_ms"] or 0
    ag = m["agents"]
    r["main"] = dict(id=m["id"], total_ms=m["total_ms"], n_agents=len(ag), agent_sum_ms=round(sum(a["latency_ms"] or 0 for a in ag)), agent_max_ms=round(max([a["latency_ms"] or 0 for a in ag] or [0])),
                     agent_ttft_mean_ms=round(sum(a["ttft_ms"] or 0 for a in ag) / max(1, len(ag))), agent_tokens=sum(a["gen_tokens"] or 0 for a in ag), reasoner_used=used,
                     reasoner_ms=rl, reasoner_ttft_ms=m["reasoner"]["ttft_ms"], reasoner_gen_tokens=m["reasoner"]["gen_tokens"], reasoner_prefill_ms=sum(lg["prefill_ms"]) if lg["prefill_ms"] else None,
                     swap_in_ms=lg["swap_in_ms"], swap_out_ms=lg["swap_out_ms"], npu_calls=m["npu_calls"], n_incidents=len(r["incidents"]),
                     cheap_ms=(m["total_ms"] - rl - swap) if used else m["total_ms"], full_ms=m["total_ms"])
    return r


def main():
    ap = argparse.ArgumentParser(); ap.add_argument("what"); ap.add_argument("--reps", type=int, default=5); ap.add_argument("--limit", type=int, default=0)
    a = ap.parse_args()
    st = status(); 
    if not st or st.get("mode") != 3:
        raise SystemExit("app not reachable or not in mode 3: %s" % (st or {}).get("mode"))
    ss = sensors(); by = {(s["node"], s["metric"]): s for s in ss}
    out = P / ("results/board_%s.json" % a.what); out.parent.mkdir(exist_ok=True)
    res = json.loads(out.read_text()) if out.exists() else []
    done = {r["tag"] for r in res}
    runs = []
    if a.what == "setc":
        POOL = [("AQ-KN00-00", "pm25"), ("SR-AQ-KH03-03", "temp"), ("EM-CR-SB00-00", "pf"), ("WE-VN04-00", "temp"), ("AQ-KN00-00", "pm10")]
        VAL = {("AQ-KN00-00", "pm25"): 250, ("SR-AQ-KH03-03", "temp"): 40, ("EM-CR-SB00-00", "pf"): 0.55, ("WE-VN04-00", "temp"): 47, ("AQ-KN00-00", "pm10"): 450}
        for rep in range(a.reps):
            for n in (1, 2, 3, 5):
                od = POOL[rep % 5:] + POOL[:rep % 5]
                runs.append(("N%d-r%d" % (n, rep + 1), {k: [VAL[k]] for k in od[:n]}, dict(N=n, rep=rep + 1, sensors=["/".join(k) for k in od[:n]])))
        for _x in ():
            for n in ():
                od = [k for k in ORDER if k[0] != "SR-AQ-KH03-03" or k[1] == "temp"]  # co2/rh of KH03-03 still hold probe episodes in their 4 h window
                od = od[(rep * 5) % len(od):] + od[:(rep * 5) % len(od)]  # rotate so no sensor fills its window
                runs.append(("N%d-r%d" % (n, rep + 1), {k: ramp_series(by[k], target(by[k])) for k in od[:n]}, dict(N=n, rep=rep + 1, sensors=["/".join(k) for k in od[:n]])))
    else:
        for stt in ("2", "3-4", "5+"):
            cs = [json.loads(l) for l in open(P / "sets/B.jsonl")]
            cs = [c for c in cs if c["stratum"] == stt][:10]
            for c in cs:
                tg = {}
                for k, xs in c["series"].items():
                    node, metric = k.split("/")
                    if (node, metric) in by:
                        s = by[(node, metric)]
                        tg[(node, metric)] = [max(s["min"], min(s["max"], v)) for v in xs]
                runs.append((c["id"], tg, dict(stratum=stt, n_flagged=len(c["flagged"]), family=c["family"])))
    if a.limit:
        runs = runs[:a.limit]
    trig0 = req("/api/rules")[1]["trigger"]
    (P / "results/rules_before_board.json").write_text(json.dumps(trig0))
    c, _ = req("/api/rules", dict(trigger=dict(trig0, fast_cooldown=1, fast_readings=1, abnormal_of_window=2)))
    if c != 200:
        raise SystemExit("could not set fast_cooldown=1: %s" % c)
    try:
        run_all(runs, done, res, out, ss)
    finally:
        c, _ = req("/api/rules", dict(trigger=trig0))
        print("rules restored", c, flush=True)


def run_all(runs, done, res, out, ss):
    for tag, tg, meta in runs:
        if tag in done:
            continue
        print(time.strftime("%H:%M:%S"), tag, len(tg), flush=True)
        r = derive(one_run(tag, tg, ss)); r["meta"] = meta
        res.append(r); out.write_text(json.dumps(res, indent=1))
        m = r.get("main")
        print("   ", r.get("error") or {k: m[k] for k in ("n_agents", "total_ms", "cheap_ms", "reasoner_ms", "swap_in_ms")}, flush=True)
        if r.get("error"):
            fails = sum(1 for x in res if x.get("error"))
            if fails >= 4:
                raise SystemExit("4 runs failed: stop and report")
    reset(ss, restart=False)
    print("done", len(res))


if __name__ == "__main__":
    main()
