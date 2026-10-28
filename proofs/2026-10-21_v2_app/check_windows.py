"""Check the dynamic agent window on every refine stage saved by refine_check.py.

For each incident stage file (INC-xxxx_<stage>.json) and flagged sensor: the window length the app used
(win_n), whether it is a trained length (24..144, step 6), the early pattern family that chose it, and
whether the window holds the onset the previous stage reported plus >= 1 h (12 readings) of baseline.
  py -3 check_windows.py DIR
"""
import glob, json, os, sys
from datetime import datetime, timedelta, timezone

IST = timezone(timedelta(hours=5, minutes=30))
FAM = {"flatline": "flat", "spike": "transient", "dip": "transient", "erratic": "noisy", "oscillation": "noisy",
       "stable": "stable", "gradual_increase": "trend", "gradual_decrease": "trend", "exponential_increase": "trend",
       "step_increase": "step", "step_decrease": "step", "throttling": "step"}


def onset_age(onset, end):
    """readings from HH:MM onset to end (1 = the last reading), searching back 12 h."""
    for i in range(0, 145):
        t = datetime.fromtimestamp(end - i * 300, IST).strftime("%H:%M")
        if t == onset:
            return i + 1
    return None


def main(d):
    rows, bad = [], 0
    by = {}
    for f in glob.glob(os.path.join(d, "INC-*_*.json")):
        iid, stage = os.path.basename(f)[:-5].split("_", 1)
        by.setdefault(iid, {})[stage] = json.load(open(f))
    for iid, st in sorted(by.items()):
        early = {a["ref"]: (a.get("parsed") or {}) for a in (st.get("early") or {}).get("agents", [])}
        prev = early
        for stage in ("early", "1.5h", "3h"):
            inc = st.get(stage)
            if not inc:
                continue
            agents = {a["ref"]: a for a in inc.get("agents", [])}
            for s in inc["sensors"]:
                if s.get("context"):
                    continue
                n = s.get("win_n") or 48
                end = s["window_end"]
                p = prev.get(s["ref"], {})
                age = onset_age(p.get("onset"), end) if p.get("onset") and stage != "early" else None
                trained = 24 <= n <= 144 and n % 6 == 0
                covered = age is None or n >= min(age + 12, 144)
                ok = trained and covered
                bad += not ok
                cur = (agents.get(s["ref"]) or {}).get("parsed") or {}
                rows.append((iid, stage, s["metric"], n, FAM.get(early.get(s["ref"], {}).get("pattern"), "?"),
                             p.get("onset"), age, cur.get("pattern"), cur.get("status"), "ok" if ok else "BAD"))
            prev = {a["ref"]: (a.get("parsed") or {}) for a in inc.get("agents", [])}
    print(f"{'incident':9} {'stage':5} {'metric':9} {'win_n':>5} {'h':>5} {'early fam':9} {'prev onset':10} {'age':>4} -> {'pattern/status':32} check")
    for r in rows:
        print(f"{r[0]:9} {r[1]:5} {r[2]:9} {r[3]:5d} {r[3]/12:5.1f} {r[4]:9} {str(r[5]):10} {str(r[6]):>4} -> {str(r[7])+'/'+str(r[8]):32} {r[9]}")
    print(f"\n{len(rows)} sensor-stages, {bad} with a window that is untrained or misses onset + 1 h baseline")
    json.dump([dict(zip(["incident", "stage", "metric", "win_n", "early_family", "prev_onset", "age", "pattern", "status", "check"], r))
               for r in rows], open(os.path.join(d, "window_check.json"), "w"), indent=1)


if __name__ == "__main__":
    main(sys.argv[1])
