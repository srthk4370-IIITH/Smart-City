#!/usr/bin/env python3
"""Smoke test + small slow chaos run of the domain agents + the htpd v8 reasoner, through the running app.
Run inside WSL (stdlib only). All HTTP goes through `adb shell curl` on the board (no port-forward networking).

  python3 -I chaos.py smoke                      # 1 incident (crowded_room, cross-domain), end to end
  python3 -I chaos.py chaos [n=3] [gap_s=210]    # n incidents, gap_s apart, paced by board temperature

Per incident: waits until the hottest thermal zone is < 74 C, injects a scenario, waits for the incident to
finish, saves the incident JSON, screenshots (start / title shown / done), and the new htpd.log lines (swap,
reasoner and reload timings). After each incident it checks that the agents' model came back: the log must
show "agents' model back" after any "reasoner loaded", and no "reload failed"/"exiting". If not, it stops with
exit code 9 and prints ROLLBACK: run `board.sh rollback` at once.
"""
import json, os, re, shlex, subprocess, sys, time

ADB = "/mnt/c/Users/hp/Desktop/qidk/Code/platform-tools/adb.exe"
P = "/mnt/c/Users/hp/Desktop/qidk/proofs/2026-10-27_reasoner_board"
D = "/data/local/tmp/smart_city_edge"
HOT_C = 74
SCEN = ["crowded_room", "ventilation_failure", "heat_buildup", "tank_leak"]

def adb(*a, binary=False, timeout=120):
    r = subprocess.run([ADB, *a], capture_output=True, timeout=timeout)
    return r.stdout if binary else r.stdout.decode("utf-8", "replace").replace("\r", "")

def sh(cmd, timeout=120):
    return adb("shell", cmd, timeout=timeout)

def api(path, body=None, timeout=60):
    if body is None:
        cmd = f"curl -s -m {timeout} http://127.0.0.1:8000{path}"
    else:
        cmd = (f"curl -s -m {timeout} -X POST -H 'Content-Type: application/json' "
               f"-d {shlex.quote(json.dumps(body))} http://127.0.0.1:8000{path}")
    out = sh(cmd, timeout=timeout + 15)
    try:
        return json.loads(out)
    except Exception:
        return out

def temp_c():
    t = sh("cat /sys/class/thermal/thermal_zone*/temp | sort -rn | head -1").strip()
    return int(t) // 1000 if t.isdigit() else -1

def shot(tag):
    png = adb("exec-out", "screencap", "-p", binary=True, timeout=60)
    if png[:4] == b"\x89PNG":
        with open(f"{P}/screens/{tag}.png", "wb") as f:
            f.write(png)

def log_lines():
    return int((sh(f"wc -l < {D}/state/htpd.log").strip() or "0"))

def note(msg, run):
    line = f"[{time.strftime('%H:%M:%S')}] {msg}"
    print(line, flush=True)
    with open(f"{P}/logs/{run}.log", "a") as f:
        f.write(line + "\n")

def ids():
    d = api("/api/incidents")
    return [i["id"] for i in d] if isinstance(d, list) else []

def one(scenario, k, run):
    while (t := temp_c()) >= HOT_C:
        note(f"board {t} C >= {HOT_C} C: waiting 30 s", run)
        time.sleep(30)
    note(f"incident {k}: inject {scenario} (board {temp_c()} C, MemAvailable {sh('grep MemAvailable /proc/meminfo').split()[1:2]})", run)
    n0, before = log_lines(), set(ids())
    t0 = time.time()
    api("/api/inject", {"scenario": scenario})
    shot(f"{run}_{k}_0_injected")
    iid, title_shot, inc = None, False, None
    while time.time() - t0 < 900:
        if iid is None:
            new = [i for i in ids() if i not in before]
            iid = new[0] if new else None
        else:
            inc = api(f"/api/incidents/{iid}")
            if isinstance(inc, dict):
                if not title_shot and inc.get("title") and inc.get("state") == "running":
                    shot(f"{run}_{k}_1_title"); title_shot = True
                if inc.get("state") in ("done", "failed"):
                    break
        time.sleep(3)
    wall = time.time() - t0
    shot(f"{run}_{k}_2_done")
    new_log = sh(f"tail -n +{n0 + 1} {D}/state/htpd.log")
    with open(f"{P}/raw/{run}_{k}_htpd.log", "w") as f:
        f.write(new_log)
    with open(f"{P}/raw/{run}_{k}_incident.json", "w") as f:
        json.dump({"scenario": scenario, "id": iid, "wall_s": round(wall, 1), "incident": inc}, f, indent=1)
    fin = (inc.get("final") or {}) if isinstance(inc, dict) else {}
    rep = dict(fin.get("parsed") or {}, model=fin.get("model"), latency_ms=fin.get("latency_ms"), valid=fin.get("valid"),
               errors=fin.get("errors"), title=(inc or {}).get("title") if isinstance(inc, dict) else None)
    keys = [l for l in new_log.splitlines() if re.search(r"reasoner (loaded|unloaded)|reason stream|reason \d+ streams|agents' model|reload failed|exiting|ready in", l)]
    for l in keys:
        note("  htpd: " + l.strip()[:220], run)
    note(f"incident {k}: {iid} state={(inc or {}).get('state') if isinstance(inc, dict) else None} wall {wall:.0f} s "
         f"model={rep.get('model')!r} source={rep.get('source')!r} reasoner_ms={rep.get('latency_ms')} valid={rep.get('valid')} "
         f"errors={rep.get('errors')} title={rep.get('title')!r}", run)
    loaded = [i for i, l in enumerate(keys) if "reasoner loaded" in l]
    back = [i for i, l in enumerate(keys) if "agents' model back" in l]
    bad = any(("reload failed" in l) or ("exiting" in l) for l in keys)
    procs = sh("pgrep -fl '[b]in/htpd'").strip()
    if bad or not procs:
        note("ROLLBACK: the agents' model did not come back (reload failed / htpd gone)", run)
        sys.exit(9)
    if loaded and not (back and back[-1] > loaded[-1]):
        # keep=true: the reload happens on the next agents request or after HTPD_REASON_IDLE_MS (20 s)
        # follow-up reason calls (refinements) may reload the reasoner; give the swap-back up to 3 min
        for _ in range(18):
            time.sleep(10)
            later = sh(f"tail -n +{n0 + 1} {D}/state/htpd.log")
            if "agents' model back" in later.split("reasoner loaded")[-1]:
                break
        else:
            note("ROLLBACK: reasoner still held 3 min after the incident (no agents' model back)", run)
            sys.exit(9)
        note("  agents' model back (idle release)", run)
    return wall

def main():
    for d in ("logs", "raw", "screens"):
        os.makedirs(f"{P}/{d}", exist_ok=True)
    mode = sys.argv[1] if len(sys.argv) > 1 else "smoke"
    if mode == "smoke":
        one("crowded_room", 0, "smoke")
    else:
        n = int(sys.argv[2]) if len(sys.argv) > 2 else 3
        gap = int(sys.argv[3]) if len(sys.argv) > 3 else 210
        for k in range(n):
            t0 = time.time()
            one(SCEN[k % len(SCEN)], k, "chaos")
            if k + 1 < n:
                rest = max(0, gap - (time.time() - t0))
                note(f"next incident in {rest:.0f} s", "chaos")
                time.sleep(rest)
    note("finished", mode)

if __name__ == "__main__":
    main()
