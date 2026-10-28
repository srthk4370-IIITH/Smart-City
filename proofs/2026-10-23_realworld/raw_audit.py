#!/usr/bin/env python3
"""Real-world data-quality audit of the raw SCRC exports (ihub-clean-datasets/*.csv).

Streams each raw file (no pandas, low memory) and measures, per node, what a live feed into the
edge agent would actually look like: sampling interval, gaps, duplicates, out-of-order delivery,
late arrival (server Timestamp - Sensor_Timestamp), gateway bursts, device clocks that are not unix
time, mixed time-zone suffixes, stuck runs, single-point glitches, quantisation, out-of-range values,
firmware version changes and the level shift around them, and site-wide silent hours.

Data stays local. Output: raw_audit/<file>.json (+ summary.json).
Usage (WSL): python3 -I raw_audit.py <ihub-clean-datasets dir> <out dir> [file ...]
"""
import csv, json, math, os, statistics as stt, sys
from array import array
from collections import defaultdict, Counter
from datetime import datetime, timezone
from multiprocessing import Pool

# file -> (metric column, physical range lo, hi, expect-varying for stuck analysis)
SPECS = {
    "SR-AQ.csv": ("CO2", 250, 5000, True),
    "SR-EM.csv": ("Power", 0, 5e5, True),
    "WM-WL.csv": ("Water Level", 0.5, 500, True),
    "WM-WF.csv": ("Flowrate", 0, 40, False),
    "WM_WD.csv": ("Compensated TDS value", 1, 1000, True),
    "SR-OC.csv": ("Occupancy", 0, 1, False),
    "we.csv": ("Temperature", 5, 50, True),
    "air_qulaity.csv": ("PM2.5", 0, 999, True),
    "SL.csv": ("3_Active_power", 0, 2000, False),
    "EM.csv": ("GDPower", 0, 2e6, False),
    "SR-AC.csv": ("Room Temp", 10, 45, True),
}


def fnum(s):
    if s is None or s == "":
        return None
    try:
        x = float(s)
    except ValueError:
        return None
    return x if math.isfinite(x) else None


def pct(xs, q):
    if not xs:
        return None
    s = sorted(xs)
    return s[min(len(s) - 1, int(q * (len(s) - 1) + 0.5))]


def audit(path):
    fname = os.path.basename(path)
    col, lo, hi, varying = SPECS[fname]
    per = {}
    tz = Counter()
    rows = 0
    with open(path, encoding="utf-8", errors="replace", newline="") as fh:
        rd = csv.reader(fh)
        hdr = next(rd)
        ix = {h: i for i, h in enumerate(hdr)}
        i_node, i_ts, i_ver = ix["Node_id"], ix["Timestamp"], ix["Version"]
        i_sts, i_val = ix.get("Sensor_Timestamp"), ix[col]
        for r in rd:
            if len(r) <= i_val:
                continue
            rows += 1
            node = r[i_node]
            t = r[i_ts]
            tz[t[-6:] if len(t) > 6 and t[-6] in "+-" else "none"] += 1
            try:
                srv = datetime.fromisoformat(t).timestamp()
            except ValueError:
                continue
            sts = fnum(r[i_sts]) if i_sts is not None else None
            v = fnum(r[i_val])
            d = per.get(node)
            if d is None:
                d = per[node] = {"srv": array("d"), "sts": array("d"), "val": array("d"),
                                 "ver": [], "prev_srv": -1, "prev_sts": -1, "ooo_srv": 0, "ooo_sts": 0}
            if srv < d["prev_srv"]:
                d["ooo_srv"] += 1
            d["prev_srv"] = srv
            if sts is not None:
                if sts < d["prev_sts"]:
                    d["ooo_sts"] += 1  # arrived after a newer reading (out of order delivery)
                d["prev_sts"] = sts
            d["srv"].append(srv)
            d["sts"].append(sts if sts is not None else float("nan"))
            d["val"].append(v if v is not None else float("nan"))
            ver = r[i_ver]
            if not d["ver"] or d["ver"][-1][1] != ver:
                d["ver"].append((srv, ver))
    out = {"file": fname, "metric": col, "rows": rows, "nodes": len(per), "tz_suffix": dict(tz), "per_node": {}}
    hours = defaultdict(set)
    for node, d in per.items():
        n = len(d["srv"])
        srv, sts, val = d["srv"], d["sts"], d["val"]
        epoch_ok = sum(1 for s in sts if s == s and s > 1e9)
        non_epoch = sum(1 for s in sts if s == s and s <= 1e9)
        use_sts = epoch_ok >= 0.9 * n
        tline = [sts[i] if use_sts and sts[i] == sts[i] and sts[i] > 1e9 else srv[i] for i in range(n)]
        for t in srv:
            hours[int(t // 3600)].add(node)
        # duplicates on the device timestamp
        cnt = Counter(tline)
        dup_ts = sum(c - 1 for c in cnt.values() if c > 1)
        seen, dup_exact = set(), 0
        for i in range(n):
            k = (tline[i], val[i])
            if k in seen:
                dup_exact += 1
            seen.add(k)
        # late arrival
        skew = [srv[i] - sts[i] for i in range(n) if sts[i] == sts[i] and sts[i] > 1e9]
        late10 = sum(1 for s in skew if s > 600)
        late60 = sum(1 for s in skew if s > 3600)
        ahead = sum(1 for s in skew if s < -300)  # device clock ahead of server by > 5 min
        # bursts: >= 5 readings received within 60 s whose device times span > 10 min
        bursts = 0
        if use_sts:
            j = 0
            idx = sorted(range(n), key=lambda i: srv[i])
            i = 0
            while i < n:
                j = i
                while j + 1 < n and srv[idx[j + 1]] - srv[idx[i]] <= 60:
                    j += 1
                if j - i + 1 >= 5:
                    span = max(sts[idx[k]] for k in range(i, j + 1)) - min(sts[idx[k]] for k in range(i, j + 1))
                    if span > 600:
                        bursts += 1
                        i = j + 1
                        continue
                i += 1
        # time-ordered series (dedup on time)
        order = sorted(range(n), key=lambda i: tline[i])
        ts_o, v_o = [], []
        last_t = None
        for i in order:
            if tline[i] == last_t:
                continue
            last_t = tline[i]
            ts_o.append(tline[i]); v_o.append(val[i])
        dts = [ts_o[i + 1] - ts_o[i] for i in range(len(ts_o) - 1)]
        med_dt = stt.median(dts) if dts else None
        gaps = Counter()
        lost = 0.0
        for g in dts:
            for lab, s in (("gt3x_interval", max(900, 3 * (med_dt or 0))), ("gt1h", 3600), ("gt6h", 21600), ("gt24h", 86400)):
                if g > s:
                    gaps[lab] += 1
            if med_dt and g > max(900, 3 * med_dt):
                lost += g
        span = (ts_o[-1] - ts_o[0]) if len(ts_o) > 1 else 0
        # value checks
        vv = [x for x in v_o if x == x]
        miss_val = len(v_o) - len(vv)
        below = sum(1 for x in vv if x < lo)
        above = sum(1 for x in vv if x > hi)
        zeros = sum(1 for x in vv if x == 0)
        # quantisation: smallest positive step between consecutive values; distinct-value ratio
        steps = [abs(vv[i + 1] - vv[i]) for i in range(len(vv) - 1) if vv[i + 1] != vv[i]]
        qstep = min(steps) if steps else None
        distinct = len(set(vv))
        # stuck runs: identical consecutive values (time ordered), duration in hours
        runs = []
        k0 = 0
        for i in range(1, len(v_o) + 1):
            if i == len(v_o) or v_o[i] != v_o[k0] or v_o[i] != v_o[i]:
                if i - k0 >= 3:
                    runs.append((ts_o[i - 1] - ts_o[k0]) / 3600)
                k0 = i
        stuck2h = sum(1 for r in runs if r >= 2)
        stuck6h = sum(1 for r in runs if r >= 6)
        longest = max(runs) if runs else 0
        # single-point glitches: a reading far from both neighbours, the neighbours agreeing
        dd = [abs(vv[i + 1] - vv[i]) for i in range(len(vv) - 1)]
        mad = stt.median(dd) if dd else 0
        sig = max(1.4826 * mad, 1e-9)
        glitch = 0
        for i in range(1, len(vv) - 1):
            a, b, c = vv[i - 1], vv[i], vv[i + 1]
            if abs(b - a) > 8 * sig and abs(b - c) > 8 * sig and abs(c - a) < 2 * sig and abs(b - (a + c) / 2) > 0.1 * max(abs(a), 1e-9):
                glitch += 1
        # firmware versions and the level shift around each change (median 24 h before vs after)
        vers = []
        for t, ver in d["ver"]:
            vers.append({"from": datetime.fromtimestamp(t, tz=timezone.utc).strftime("%Y-%m-%d %H:%M"), "version": ver})
        shifts = []
        for t, ver in d["ver"][1:]:
            b4 = [v_o[i] for i in range(len(ts_o)) if t - 86400 <= ts_o[i] < t and v_o[i] == v_o[i]]
            af = [v_o[i] for i in range(len(ts_o)) if t <= ts_o[i] < t + 86400 and v_o[i] == v_o[i]]
            if len(b4) > 10 and len(af) > 10:
                mb, ma = stt.median(b4), stt.median(af)
                shifts.append({"at": datetime.fromtimestamp(t, tz=timezone.utc).strftime("%Y-%m-%d"), "to": ver,
                               "median_before": round(mb, 3), "median_after": round(ma, 3),
                               "ratio": round(ma / mb, 3) if mb else None})
        out["per_node"][node] = {
            "rows": n, "device_clock_epoch": epoch_ok, "device_clock_not_epoch": non_epoch,
            "timeline": "sensor" if use_sts else "server",
            "median_interval_s": med_dt, "span_days": round(span / 86400, 1),
            "gaps": dict(gaps), "gap_time_frac": round(lost / span, 3) if span else None,
            "dup_timestamp": dup_ts, "dup_exact": dup_exact,
            "out_of_order_arrival": d["ooo_sts"], "server_ts_backwards": d["ooo_srv"],
            "late_gt10m": late10, "late_gt1h": late60, "device_ahead_gt5m": ahead,
            "skew_p50_s": pct(skew, .5), "skew_p95_s": pct(skew, .95), "skew_p99_s": pct(skew, .99),
            "bursts": bursts,
            "missing_value": miss_val, "below_range": below, "above_range": above, "zeros": zeros,
            "quant_step": qstep, "distinct_values": distinct,
            "stuck_runs_ge2h": stuck2h, "stuck_runs_ge6h": stuck6h, "stuck_longest_h": round(longest, 1),
            "glitches": glitch, "glitch_per_10k": round(1e4 * glitch / max(1, len(vv)), 2),
            "versions": vers, "version_shifts": shifts,
        }
    # site-wide silence: hours in the file's span where >= 80% of nodes sent nothing
    if hours:
        h0, h1 = min(hours), max(hours)
        nn = len(per)
        silent = [h for h in range(h0, h1 + 1) if len(hours.get(h, ())) <= 0.2 * nn]
        # group consecutive hours into outages
        outs, cur = [], None
        for h in silent:
            if cur and h == cur[1] + 1:
                cur[1] = h
            else:
                if cur:
                    outs.append(cur)
                cur = [h, h]
        if cur:
            outs.append(cur)
        out["sitewide_silent_hours"] = len(silent)
        out["sitewide_outages"] = [{"from": datetime.fromtimestamp(a * 3600, tz=timezone.utc).strftime("%Y-%m-%d %H:00"),
                                    "hours": b - a + 1} for a, b in outs if b - a + 1 >= 2][:40]
        out["span_hours"] = h1 - h0 + 1
    return out


def main():
    src, dst = sys.argv[1], sys.argv[2]
    files = sys.argv[3:] or list(SPECS)
    os.makedirs(dst, exist_ok=True)
    with Pool(4) as p:
        for res in p.imap_unordered(audit, [os.path.join(src, f) for f in files]):
            with open(os.path.join(dst, res["file"] + ".json"), "w") as o:
                json.dump(res, o, indent=1)
            print("done", res["file"], res["rows"], flush=True)


if __name__ == "__main__":
    main()
