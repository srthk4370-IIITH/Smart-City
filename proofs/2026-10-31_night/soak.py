#!/usr/bin/env python3
"""Overnight soak (2026-10-31 night steward). Every ~20 min ONE realistic small test through the app's own API
(adb shell curl on the board, chaos2.py helpers), rotating: incident story (critical breach, fast path + AI update),
chat question, normal-readings story (must NOT raise an incident). Logs soak.csv + soak.log + raw/.
Pacing: board < 60 C or the cycle is skipped. PAUSE file = skip cycles (lab windows); while a test runs BUSY exists.
DEMO_NOW = stop. Stops at 09:00 IST.  usage (WSL): python3 -I soak.py [gap_s=1200]"""
import csv, json, os, random, sys, time
sys.path.insert(0, "/mnt/c/Users/hp/Desktop/qidk/proofs/2026-10-27_reasoner_fast/scripts")
import chaos2 as C

N = "/mnt/c/Users/hp/Desktop/qidk/proofs/2026-10-31_night"
DEMO = "/mnt/c/Users/hp/Desktop/qidk/proofs/2026-10-29_latency/DEMO_NOW"
GAP = int(sys.argv[1]) if len(sys.argv) > 1 else 1200
END_IST = (9, 0)
INC = [("SR-AQ-KH03-03", "co2", 2000, "CO2 2000 ppm"), ("AQ-KN00-00", "pm25", 200, "PM2.5 200"),
       ("WM-WD-KH98-00", "ph", 9.6, "water pH 9.6"), ("EM-CR-SB00-00", "pf", 0.62, "power factor 0.62"),
       ("WE-VN04-00", "temp", 45, "outdoor temp 45 C"), ("SR-AQ-KH03-03", "temp", 38, "room temp 38 C"),
       ("WE-VN04-00", "wind", 20, "wind 20 m/s"), ("AQ-KN00-00", "pm10", 320, "PM10 320")]
CHAT = ["List the incidents", "How many incidents were there today?", "What is the status of the CO2 sensor in KH03?",
        "What if occupancy increases by 50%, impact on other domains", "Which sensors are abnormal right now?",
        "What was the last critical incident and what caused it?", "Is the water quality OK?",
        "What if the outdoor temperature rises by 5 C?", "How many critical incidents are there?",
        "Summarise the power situation", "Are any sensors offline or faulty?", "What should the facility team check first?"]
NORMAL = [[("SR-AQ-KH03-03", "co2", 620), ("SR-AQ-KH03-03", "temp", 25.5)], [("AQ-KN00-00", "pm25", 32), ("AQ-KN00-00", "pm10", 55)],
          [("WM-WD-KH98-00", "ph", 7.4), ("WM-WD-KH98-00", "tds", 180)], [("WE-VN04-00", "temp", 31), ("WE-VN04-00", "wind", 4)],
          [("EM-CR-SB00-00", "pf", 0.93), ("SR-AQ-KH03-03", "rh", 58)]]
COLS = ["ts_ist", "n", "kind", "story", "pass", "fast_s", "ai_update_s", "chat_s", "severity", "title", "note",
        "temp_c", "memavail_mb", "htpd", "edge_agent", "crash_lines"]

def ist(): return time.strftime("%H:%M:%S", time.gmtime(time.time() + 19800))
def log(m):
    with open(f"{N}/soak.log", "a") as f: f.write(f"[{ist()}] {m}\n")

def health():
    t = C.temp_c()
    mem = C.sh("grep MemAvailable /proc/meminfo").split()
    procs = C.sh("ps -A -o NAME=").split()
    hp = ",".join(sorted({p for p in procs if p.startswith("htpd")})) or "-"
    crash = C.sh("logcat -b crash -d 2>/dev/null | wc -l").strip()
    return t, (int(mem[1]) // 1024 if len(mem) > 1 and mem[1].isdigit() else -1), hp, int("edge-agent" in procs), int(crash or 0) if crash.isdigit() else -1

def incident(k):
    node, metric, val, story = INC[k % len(INC)]
    C.reset("10:00"); before = set(C.ids()); t0 = time.time()
    C.api("/api/ingest", {"node": node, "metric": metric, "value": val})
    fast_id = fast_t = ai_t = inc = None
    while time.time() - t0 < 900:
        for cand in [i for i in C.ids() if i not in before]:
            ci = C.api(f"/api/incidents/{cand}")
            if not isinstance(ci, dict) or node not in {x.get("node") for x in (ci.get("sensors") or [])}:
                continue
            if ci.get("fast_path") and fast_id is None: fast_id, fast_t = cand, time.time() - t0
            if fast_id == cand: inc = ci
        if inc:
            fin = inc.get("final") or {}
            ran = any("Reasoner v3" in (t.get("msg") or "") for t in inc.get("timeline") or [])
            if fin and not fin.get("preliminary") and ran and inc.get("state") == "done":
                ai_t = time.time() - t0; break
            if inc.get("state") == "failed": break
        time.sleep(2)
    C.reset("10:00")
    fin = (inc or {}).get("final") or {}
    json.dump({"story": story, "incident": inc}, open(f"{N}/raw/inc_{int(t0)}.json", "w"), indent=1)
    ok = bool(fast_id and ai_t and fin.get("valid", True) is not False)
    note = f"{fast_id} model={fin.get('model')} valid={fin.get('valid')} state={(inc or {}).get('state')}"
    return dict(story=story, **{"pass": int(ok)}, fast_s=round(fast_t, 1) if fast_t else "", ai_update_s=round(ai_t, 1) if ai_t else "",
                severity=(inc or {}).get("severity", ""), title=(inc or {}).get("title", ""), note=note)

def chat(k):
    q = CHAT[k % len(CHAT)]; t0 = time.time()
    d = C.api("/api/chat", {"session": "", "message": q}, timeout=200); s = time.time() - t0
    try:
        m = d["messages"][-1]; txt = m.get("text") or ""
        bad = m.get("error") or m.get("busy") or "could not find an answer" in txt or not txt.strip()
        json.dump({"q": q, "s": s, "resp": d}, open(f"{N}/raw/chat_{int(t0)}.json", "w"), indent=1)
        return dict(story=q, **{"pass": int(not bad)}, chat_s=round(s, 1),
                    note=f"tools={[t.get('name') for t in m.get('tools') or []]} | {txt[:300]}")
    except Exception as e:
        return dict(story=q, **{"pass": 0}, chat_s=round(s, 1), note=f"FAIL {e} {str(d)[:200]}")

def normal(k):
    vals = NORMAL[k % len(NORMAL)]; story = "normal " + " ".join(f"{n}/{m}={v}" for n, m, v in vals)
    C.reset("10:00"); before = set(C.ids()); t0 = time.time()
    for n, m, v in vals: C.api("/api/ingest", {"node": n, "metric": m, "value": v})
    new = []
    while time.time() - t0 < 240:
        time.sleep(20)
        new = [i for i in C.ids() if i not in before]
        if new: break
    C.reset("10:00")
    titles = [(C.api(f"/api/incidents/{i}") or {}).get("title") if isinstance(C.api(f"/api/incidents/{i}"), dict) else "?" for i in new]
    return dict(story=story, **{"pass": int(not new)}, note=f"new incidents {new} {titles}" if new else "no incident (as expected)")

def main():
    if not os.path.exists(f"{N}/soak.csv"):
        with open(f"{N}/soak.csv", "w", newline="") as f: csv.DictWriter(f, fieldnames=COLS).writeheader()
    _, _, _, _, crash0 = health()
    n = 0; kinds = [incident, chat, normal]
    log(f"soak start gap {GAP} s, crash buffer lines {crash0}")
    while True:
        h, m = map(int, ist().split(":")[:2])
        if (h, m) >= END_IST and h < 12: log("09:00 IST: soak done"); break
        if os.path.exists(DEMO): log("DEMO_NOW: stop"); break
        t0 = time.time()
        if os.path.exists(f"{N}/PAUSE"):
            log("PAUSE: cycle skipped"); time.sleep(60); continue
        try:
            t, mem, hp, ea, cr = health()
            if t >= 60 or t < 0:
                log(f"board {t} C: cycle skipped"); time.sleep(300); continue
            if hp == "-" or not ea:
                row = dict(kind="health", story="app/htpd not running", **{"pass": 0}, note="")
            else:
                open(f"{N}/BUSY", "w").close()
                fn = kinds[n % 3]; row = dict(kind=fn.__name__, **fn(n // 3))
            t2, mem2, hp2, ea2, cr2 = health()
            if cr2 > crash0 >= 0:
                new = C.sh(f"logcat -b crash -d 2>/dev/null | tail -n {cr2 - crash0}")
                open(f"{N}/raw/crash_{int(t0)}.txt", "w").write(new); row["note"] = (row.get("note", "") + f" CRASH +{cr2 - crash0} lines")
            crash0 = cr2
            row.update(ts_ist=ist(), n=n, temp_c=t2, memavail_mb=mem2, htpd=hp2, edge_agent=ea2, crash_lines=cr2)
            with open(f"{N}/soak.csv", "a", newline="") as f:
                csv.DictWriter(f, fieldnames=COLS).writerow({k: str(row.get(k, "")).replace("\n", " ")[:400] for k in COLS})
            log(f"#{n} {row['kind']} pass={row['pass']} fast={row.get('fast_s','')} ai={row.get('ai_update_s','')} chat={row.get('chat_s','')} "
                f"sev={row.get('severity','')} title={str(row.get('title',''))[:80]!r} {t2}C mem={mem2}MB htpd={hp2} | {str(row.get('note',''))[:160]}")
        except Exception as e:
            log(f"#{n} ERROR {e!r}")
        finally:
            if os.path.exists(f"{N}/BUSY"): os.remove(f"{N}/BUSY")
        n += 1
        time.sleep(max(30, GAP - (time.time() - t0)))

if __name__ == "__main__":
    main()
