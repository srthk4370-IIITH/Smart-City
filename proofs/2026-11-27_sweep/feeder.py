"""feeder.py: hands-on sweep driver (2026-11-27). Owner-approved: full faults through /api/ingest, state restored after.
Phase 0: backfill 12 h of normal history for every sensor (late readings into closed buckets).
Phase 1: real time, one reading per sensor per minute (ts = board-corrected now), scenarios switched on by elapsed minutes.
Every minute: snapshot /api/incidents (+ new timeline lines) -> incidents_log.jsonl; ingest results -> feeder.log.
usage: python feeder.py [minutes]   (adb forward tcp:8000 tcp:8000; stop = create file STOP_FEEDER next to this script)"""
import json, math, os, random, subprocess, sys, time, urllib.request
HERE = os.path.dirname(os.path.abspath(__file__))
ADB = os.path.join(HERE, "..", "..", "Code", "platform-tools", "adb.exe")
B = "http://127.0.0.1:8000"
RUN_MIN = int(sys.argv[1]) if len(sys.argv) > 1 else 150
random.seed(27)
LOG = open(os.path.join(HERE, "feeder.log"), "a", encoding="utf-8")
ILOG = os.path.join(HERE, "incidents_log.jsonl")


def log(*a):
    s = time.strftime("%H:%M:%S ") + " ".join(str(x) for x in a)
    print(s, flush=True); LOG.write(s + "\n"); LOG.flush()


def req(p, body=None, timeout=60):
    r = urllib.request.Request(B + p, data=json.dumps(body).encode() if body is not None else None, headers={"Content-Type": "application/json"})
    try:
        with urllib.request.urlopen(r, timeout=timeout) as x:
            return x.status, x.read().decode()
    except urllib.error.HTTPError as e:
        return e.code, e.read().decode()


def board_now():
    o = subprocess.run([ADB, "shell", "echo $(date +%s) $(cat /data/local/tmp/smart_city_edge/state/clock_offset_s)"], capture_output=True, text=True).stdout.split()
    return int(o[0]) + int(o[1])


SENS = json.loads(req("/api/sensors")[1])["sensors"]
OFF = board_now() - int(time.time())          # board-corrected clock minus laptop clock


def now():
    return int(time.time()) + OFF


def normal(s, t):
    """realistic normal value at unix t (IST diurnal for weather / outdoor / power)."""
    h = ((t + 19800) % 86400) / 3600.0
    d = s["default"]; n = s["noise"] or 0
    m, node = s["metric"], s["node"]
    day = math.sin((h - 9) / 24 * 2 * math.pi)           # peaks ~15 h
    if m in ("ac_on", "occ", "setpoint", "ac_units_on"):
        return d
    if node.startswith("WE-") and m == "temp":
        v = 27 + 4 * day
    elif node.startswith("WE-") and m == "rh":
        v = 62 - 10 * day
    elif m == "wind":
        v = 3 + 1.2 * day
    elif m in ("pm25", "pm10"):
        v = d * (1 + 0.15 * math.sin((h - 20) / 24 * 2 * math.pi))
    elif node == "EM-CR-SB00-00" and m == "power_kw":
        v = 600 + 120 * day
    else:
        v = d
    v += random.gauss(0, n)
    return round(min(max(v, s["min"]), s["max"]), 3)


# scenarios: (start_min, end_min, {key: f(minutes_into_scenario) -> value}, name)
def ramp(a, b, mins):
    return lambda k: a + (b - a) * min(1.0, k / mins)


SCEN = [
    (3, 30, {"WM-WD-KH98-00/ph": ramp(7.2, 9.6, 4)}, "S1 water pH critical (single domain)"),
    (20, 75, {"AC-KH03/ac_units_on": lambda k: 0, "AC-KH03/room_temp": ramp(24, 33.5, 25), "SR-AQ-KH03-03/temp": ramp(25, 34.5, 25),
              "SR-AQ-KH03-03/co2": ramp(450, 1350, 25), "SR-AC-KH03-15/room_temp": ramp(25.1, 33.8, 25), "SR-AC-KH03-15/ac_on": lambda k: 0},
     "S2 KH level 03 AC failure: heat + CO2 (multi domain)"),
    (40, 90, {"WM-WD-KH98-00/tds": lambda k: 152.0}, "S3 TDS flatline (sensor fault: stuck value)"),
    (55, 110, {"EM-CR-SB00-00/pf": ramp(0.95, 0.81, 6), "EM-CR-SB00-00/power_kw": ramp(650, 980, 6)}, "S4 feeder pf drop + load up (power warning)"),
    (75, 120, {"AQ-KN00-00/pm25": ramp(25, 135, 5), "AQ-KN00-00/pm10": ramp(45, 270, 5), "WE-VN04-00/wind": lambda k: 0.6},
     "S5 outdoor PM spike, calm wind (air critical + weather context)"),
    (95, 125, {"SR-AQ-KH03-03/co2": lambda k: 300.0}, "S6 impossible CO2 300 ppm (sensor fault: below physical floor)"),
]


def value(s, t, minute):
    k = s["node"] + "/" + s["metric"]
    for a, b, f, _ in SCEN:
        if a <= minute < b and k in f:
            v = f[k](minute - a) + random.gauss(0, (s["noise"] or 0) * 0.5)
            return round(min(max(v, s["min"]), s["max"]), 3)
    return normal(s, t)


def ingest(rows):
    out = {}
    for i in range(0, len(rows), 2000):
        c, b = req("/api/ingest", {"readings": rows[i:i + 2000]}, timeout=120)
        if c != 200:
            out["http_%d" % c] = out.get("http_%d" % c, 0) + 1; continue
        for r in json.loads(b)["results"]:
            out[r] = out.get(r, 0) + 1
    return out


seen_tl = {}
OLD = set()


def snap(tag):
    c, b = req("/api/incidents?all=1")
    if c != 200:
        return
    for inc in json.loads(b):
        iid = inc["id"]
        if tag != "start" and iid in OLD:
            continue
        if tag == "start":
            OLD.add(iid); continue
        c2, b2 = req("/api/incidents/" + iid)
        if c2 != 200:
            continue
        inc = dict(inc, **json.loads(b2)); tl = inc.get("timeline") or []
        n0 = seen_tl.get(iid, 0)
        if len(tl) > n0 or iid not in seen_tl:
            rec = dict(at=time.strftime("%H:%M:%S"), tag=tag, id=iid, state=inc.get("state"), severity=inc.get("severity"), title=inc.get("title"),
                       approval=inc.get("approval"), refine=inc.get("refine_stage"), new_timeline=tl[n0:])
            open(ILOG, "a", encoding="utf-8").write(json.dumps(rec) + "\n")
            for t in tl[n0:]:
                log("   ", iid, t.get("t"), str(t.get("msg"))[:200])
            seen_tl[iid] = len(tl)


if __name__ == "__main__":
    t0 = now() // 300 * 300
    snap("start")
    log("phase 0: backfill 12 h normal, %d sensors, clock offset %d s" % (len(SENS), OFF))
    rows = []
    for s in SENS:
        for i in range(144, 0, -1):
            t = t0 - 300 * i + 30
            rows.append(dict(node=s["node"], metric=s["metric"], value=normal(s, t), ts=t))
    log("backfill", ingest(rows))
    start = time.time()
    active = set()
    while (time.time() - start) / 60 < RUN_MIN and not os.path.exists(os.path.join(HERE, "STOP_FEEDER")):
        minute = (time.time() - start) / 60
        for a, b, f, nm in SCEN:
            st = a <= minute < b
            if st and nm not in active:
                active.add(nm); log("SCENARIO ON  m=%.1f %s" % (minute, nm))
            if not st and nm in active:
                active.discard(nm); log("SCENARIO OFF m=%.1f %s" % (minute, nm))
        t = now()
        res = ingest([dict(node=s["node"], metric=s["metric"], value=value(s, t, minute), ts=t) for s in SENS])
        if set(res) - {"accepted"}:
            log("ingest", res)
        snap("m%.0f" % minute)
        time.sleep(max(5, 60 - (time.time() - start - minute * 60)))
    log("feeder end")
