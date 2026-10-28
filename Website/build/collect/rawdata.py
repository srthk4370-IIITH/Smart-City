"""Raw data explorer collector (SPEC data policy item 3): cleaned SCRC series -> Website/data/raw/.

Writes
  data/raw/index.json                 domains, sensors, metrics, thresholds, coverage, breach/usage counts, sankey
  data/raw/s/<sid>.json               per sensor: hourly mean/min/max for the year, breaches (+ reason), usage windows
  data/raw/c/<sid>/<YYYY-MM>.json     per sensor+month: full 5-min readings (loaded on demand)
Series are packed as strings of delta-coded scaled integers ("d" = delta, "d*k" = d repeated k times,
"~k" = k missing), scale = 10^dec. Occupancy rooms appear only as codes (Room A, B...); the code -> real
id mapping goes to Code/smart-city-edge-agent/data/series/_room_codes.json (never into Website/).
"""
from __future__ import annotations

import csv
import json
import warnings

import numpy as np
import math
import sys
from collections import Counter, defaultdict
from datetime import datetime, timedelta, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parents[3]
REPO = ROOT / "Code" / "smart-city-edge-agent"
SERIES = REPO / "data" / "series"
OUT = ROOT / "Website" / "data" / "raw"
sys.path.insert(0, str(REPO / "training"))
import features as F  # noqa: E402
import generate_dataset as G  # noqa: E402

IST = timezone(timedelta(hours=5, minutes=30))
Y0 = int(datetime(2025, 1, 1, tzinfo=IST).timestamp())
Y1 = int(datetime(2026, 1, 1, tzinfo=IST).timestamp())
STEP = 300
MONTHS = [int(datetime(2025, m, 1, tzinfo=IST).timestamp()) for m in range(1, 13)] + [Y1]

HV = dict(warn=30, crit=34, band_lo=3.0, cold_abs=24.0, warn_pts=6)
EXTRA = {  # metrics outside features.METRICS
    ("hvac", "room_temp"): dict(unit="C", dec=1, warn=30, crit=34, dir="high"),
    ("hvac", "setpoint"): dict(unit="C", dec=1, warn=None, crit=None, dir="both"),
    ("hvac", "on"): dict(unit="0/1", dec=2, warn=None, crit=None, dir="high"),
    ("hvac", "ac_units_on"): dict(unit="units", dec=1, warn=None, crit=None, dir="high"),
}
DOMAIN_LABEL = {"air_quality": "Indoor air", "outdoor_air": "Outdoor air", "water": "Water", "power": "Power",
                "weather": "Weather", "occupancy": "Occupancy", "hvac": "HVAC floors", "hvac_units": "HVAC units"}
NICE = {"co2": "CO2", "pm25": "PM2.5", "pm10": "PM10", "temp": "Temperature", "rh": "Humidity", "level": "Tank level",
        "flow": "Flow", "tds": "TDS", "ph": "pH", "power_kw": "Power", "pf": "Power factor", "wind": "Wind",
        "occ": "Occupied", "room_temp": "Room temp", "setpoint": "Setpoint", "on": "AC on", "ac_units_on": "Units on"}


def metrics_for(domain, node):
    if domain == "hvac_units":
        return "hvac", ["room_temp", "setpoint", "on"]
    if domain == "hvac":
        return "hvac", ["room_temp", "ac_units_on"]
    return G.node_role(domain, node)


def spec(role, metric, node, limits):
    if role == "hvac":
        m = dict(EXTRA[("hvac", metric)])
        if node.startswith("AC-") and metric == "room_temp":
            m.update(warn=None, crit=None)
    else:
        b = F.METRICS[(role, metric)]
        m = dict(unit=b["unit"], dec=b["dec"], warn=b["warn"], crit=b["crit"], dir="low" if b["dir"] == "low" else "high")
        if metric == "occ":
            m["unit"] = "0/1"
    if metric == "level" and node in limits:
        m.update(warn=limits[node]["high"], crit=limits[node]["overflow"], dir="high", unit="level")
    if role == "water" and metric == "ph":  # two-sided, as generate_dataset.status_of: low warn < 6.5, crit < 6.0
        m.update(lo_warn=6.5, lo_crit=6.0, dir="both")
    return m


# ------------------------------------------------------------------ packing
def pack(vals, dec):
    """list of float|None -> delta/RLE string."""
    sc = 10 ** dec
    toks, prev, i, n = [], 0, 0, len(vals)
    q = [None if v is None else int(round(v * sc)) for v in vals]
    while i < n:
        if q[i] is None:
            j = i
            while j < n and q[j] is None:
                j += 1
            toks.append(f"~{j - i}")
            i = j
            continue
        d = q[i] - prev
        prev = q[i]
        j = i + 1
        while j < n and q[j] is not None and q[j] - prev == d:
            prev = q[j]
            j += 1
        k = j - i
        if k >= 3:
            toks.append(f"{d}*{k}")
        else:
            toks.append(str(d))
            prev = q[i]
            j = i + 1
        i = j
    return ",".join(toks)


def fdur(n):
    m = n * 5
    return f"{m // 60} h {m % 60} min" if m >= 60 else f"{m} min"


def tstr(t):
    return datetime.fromtimestamp(t, IST).strftime("%d %b %H:%M")


# ------------------------------------------------------------------ breaches
def runs(mask, gap=6):
    """indices where mask True -> [(i0, i1)] merging gaps < gap."""
    out = []
    i, n = 0, len(mask)
    while i < n:
        if mask[i]:
            j = i
            while j + 1 < n and mask[j + 1]:
                j += 1
            if out and i - out[-1][1] <= gap:
                out[-1] = (out[-1][0], j)
            else:
                out.append((i, j))
            i = j + 1
        else:
            i += 1
    return out


def rule_pat(role, metric, arr, i_end):
    if role not in ("air_quality", "water", "power", "weather"):
        return None
    i0 = i_end - 47
    if i0 < 0:
        return None
    xs = arr[i0:i_end + 1]
    if sum(v is not None for v in xs) < 45 or xs[0] is None or xs[-1] is None:
        return None
    xs = list(xs)
    for k in range(48):  # linear fill
        if xs[k] is None:
            a = k - 1
            b = next(j for j in range(k, 48) if xs[j] is not None)
            xs[k] = xs[a] + (xs[b] - xs[a]) * (k - a) / (b - a)
    try:
        return F.rule_pattern(role, metric, xs, Y0 + i_end * STEP)
    except Exception:
        return None


def breaches(role, metric, sp, arr, cols, nice):
    w, c, hi = sp["warn"], sp["crit"], sp["dir"] != "low"
    if w is None:
        return []
    unit = sp["unit"]
    if role == "hvac" and "on" in cols:  # per unit: only while the AC runs (AC-off rooms read the ceiling, not the room)
        on, setp = cols["on"], cols["setpoint"]
        hot = [v is not None and on[i] == 1 and v >= w for i, v in enumerate(arr)]
        cold = [v is not None and on[i] == 1 and setp[i] is not None and v < min(setp[i] - HV["band_lo"] - 1, HV["cold_abs"])
                for i, v in enumerate(arr)]
        out = []
        for (i0, i1) in runs(hot, gap=2):
            if i1 - i0 + 1 < HV["warn_pts"]:
                continue
            seg = [(arr[k], k) for k in range(i0, i1 + 1) if arr[k] is not None]
            pk, pi = max(seg)
            lv = "crit" if pk >= c else "warn"
            out.append([i0, i1, round(pk, 1), lv, f"Room {pk:g} C while the AC runs, above the {c if lv == 'crit' else w} C "
                        f"{'critical' if lv == 'crit' else 'warning'} limit for {fdur(i1 - i0 + 1)}; peak {tstr(Y0 + pi * STEP)}."])
        for (i0, i1) in runs(cold, gap=2):
            if i1 - i0 + 1 < HV["warn_pts"]:
                continue
            seg = [(arr[k], k) for k in range(i0, i1 + 1) if arr[k] is not None]
            pk, pi = min(seg)
            out.append([i0, i1, round(pk, 1), "warn", f"Room {pk:g} C while cooling: more than 4 C below setpoint and under 24 C "
                        f"for {fdur(i1 - i0 + 1)} (overcooling)."])
        return sorted(out)
    out = []
    sides = [(hi, w, c)]
    if sp.get("lo_warn") is not None:  # pH: also the low side
        sides.append((False, sp["lo_warn"], sp["lo_crit"]))
    for hi, w, c in sides:
        out += _side_breaches(role, metric, arr, hi, w, c, unit, nice)
    return sorted(out)


def _side_breaches(role, metric, arr, hi, w, c, unit, nice):
    if hi:
        mask = [v is not None and v >= w for v in arr]
    else:
        mask = [v is not None and (v < w if metric == "ph" else v <= w) for v in arr]
    out = []
    for (i0, i1) in runs(mask):
        seg = [(arr[k], k) for k in range(i0, i1 + 1) if arr[k] is not None and mask[k]]
        pk, pi = (max(seg) if hi else min(seg))
        lv = "crit" if (pk >= c if hi else (pk < c if metric == "ph" else pk <= c)) else "warn"
        lim = c if lv == "crit" else w
        rel = "above" if hi else "below"
        rp = rule_pat(role, metric, arr, min(i1, i0 + 47))
        r = (f"{nice} {pk:g} {unit} {rel} the {lim:g} {unit} {'critical' if lv == 'crit' else 'warning'} limit; "
             f"{fdur(i1 - i0 + 1)} from {tstr(Y0 + i0 * STEP)}.")
        if rp:
            r += f" Rule pattern (4 h window): {rp.replace('_', ' ')}."
        out.append([i0, i1, pk, lv, r])
    return out


# ------------------------------------------------------------------ usage
def load_usage(room_code):
    use = defaultdict(list)   # (node, metric) -> [[end_epoch, n, pattern, family, split, ver]]
    sank = Counter()
    for ver, folder in (("v1", "sft"), ("v2", "sft_v2")):
        for sp in ("train", "dev", "test"):
            p = REPO / "data" / folder / f"{sp}.jsonl"
            if not p.exists():
                continue
            with open(p, encoding="utf-8") as fh:
                for line in fh:
                    # cheap parse: drop the long fields before json
                    i = line.find('"xs"') if ver == "v1" else line.find('"hist"')
                    r = json.loads(line[:i].rstrip(", ") + "}") if i > 0 else json.loads(line)
                    if ver == "v2" and "pattern" not in r:
                        r = json.loads(line)
                    node, met = r["node"], r["metric"]
                    if ver == "v1":
                        fam = "occupancy" if r["role"] == "occupancy" else ("stable" if r["pattern"] == "stable" else "injected")
                        n = 48
                    else:
                        fam = r.get("family") or "?"
                        n = int(r.get("n") or 48)
                    use[(node, met)].append([int(r["end_epoch"]), n, r.get("pattern"), fam, r.get("split", sp), ver])
                    sank[(ver, fam, r.get("split", sp))] += 1
    return use, sank


HOURLY, ANA = [], {}


def building(node):
    for p in node.split("-"):
        if len(p) == 4 and p[:2].isalpha() and p[2:].isdigit():
            return p[:2]
    return node.split("-")[1][:2]


def r3(x, dec=3):
    return None if x is None or not np.isfinite(x) else round(float(x), dec)


def hhmm(h):
    return f"{int(h):02d}:00"


def mname(k):
    return datetime(2025, k + 1, 1).strftime("%b")


def analyse(x, mm, brs):
    """Compact per-metric analysis with one auto insight per chart. x = 5-min array over the year (nan = missing)."""
    with warnings.catch_warnings():
        warnings.simplefilter("ignore")
        try:
            return _analyse(x, mm, brs)
        except Exception as e:  # too few readings for some statistic
            return {"n": int(np.isfinite(x).sum()), "error": f"too few readings ({type(e).__name__})"}


def _analyse(x, mm, brs):
    dec = mm["dec"] + 1
    d0 = mm["dec"]
    unit = mm["unit"]
    ok = np.isfinite(x)
    v = x[ok]
    n = int(ok.sum())
    out = {"n": n}
    rd = lambda a: [r3(t, dec) for t in a]
    # distribution
    pq = np.percentile(v, [1, 5, 25, 50, 75, 95, 99])
    lo, hi = (pq[0], pq[-1]) if pq[-1] > pq[0] else (v.min(), v.max() + 1e-9)
    if hi <= lo:
        hi = lo + 1
    cnt, edges = np.histogram(np.clip(v, lo, hi), bins=30, range=(lo, hi))
    mb_ = int(cnt.argmax())
    skew = float(((v - v.mean()) ** 3).mean() / (v.std() ** 3 + 1e-12))
    ins = (f"Median {pq[3]:.{d0}f} {unit}, middle half {pq[2]:.{d0}f} to {pq[4]:.{d0}f}; "
           f"most common {edges[mb_]:.{d0}f}-{edges[mb_ + 1]:.{d0}f}"
           + ("; long upper tail" if skew > 1 else "; long lower tail" if skew < -1 else ""))
    if mm["warn"] is not None:
        frac = float((v >= mm["warn"]).mean() if mm["dir"] != "low" else (v <= mm["warn"]).mean())
        if mm.get("lo_warn") is not None:
            frac += float((v < mm["lo_warn"]).mean())
        ins += f"; {frac * 100:.1f}% of readings past the warning limit"
    out["dist"] = {"edges": rd(edges), "counts": cnt.tolist(),
                   "pct": dict(zip(["p1", "p5", "p25", "p50", "p75", "p95", "p99"], rd(pq))),
                   "mean": r3(v.mean(), dec), "std": r3(v.std(), dec), "insight": ins}
    # monthly boxplots [p1, q1, med, q3, p99, n]
    box = []
    for k in range(12):
        a, b = (MONTHS[k] - Y0) // STEP, (MONTHS[k + 1] - Y0) // STEP
        s = x[a:b]
        s = s[np.isfinite(s)]
        if len(s) < 12:
            box.append(None)
            continue
        box.append(rd(np.percentile(s, [1, 25, 50, 75, 99])) + [int(len(s))])
    meds = [(b[2], k) for k, b in enumerate(box) if b and b[2] is not None]
    if meds:
        mx, mn = max(meds), min(meds)
        ins = f"Highest median in {mname(mx[1])} ({mx[0]:g} {unit}), lowest in {mname(mn[1])} ({mn[0]:g} {unit})"
    else:
        ins = "Too few readings for monthly statistics"
    out["monthly"] = {"box": box, "insight": ins}
    # hour x weekday heatmap (IST)
    idx = np.nonzero(ok)[0]
    tt = Y0 + idx * STEP + 19800
    hour = (tt // 3600) % 24
    wd = ((tt // 86400) + 3) % 7  # 0 = Monday
    s_ = np.zeros((7, 24))
    c_ = np.zeros((7, 24))
    np.add.at(s_, (wd, hour), v)
    np.add.at(c_, (wd, hour), 1)
    hm = s_ / c_
    prof = np.nanmean(hm, axis=0)
    ph, lh = int(np.nanargmax(prof)), int(np.nanargmin(prof))
    wk, we = np.nanmean(hm[:5]), np.nanmean(hm[5:])
    ins = f"Peak at {hhmm(ph)} ({prof[ph]:.{d0}f}), low at {hhmm(lh)} ({prof[lh]:.{d0}f})"
    if prof[lh] > 0 and prof[ph] / prof[lh] < 100:
        ins += f", {prof[ph] / prof[lh]:.1f}x"
    if np.isfinite(wk) and np.isfinite(we) and abs(wk) > 1e-9:
        ins += f"; weekends {(we / wk - 1) * 100:+.0f}% vs weekdays"
    out["heat"] = {"grid": [[r3(t, dec) for t in row] for row in hm], "n": c_.astype(int).tolist(), "insight": ins}
    # daily mean, 7-day rolling mean/std, coverage
    ND = (Y1 - Y0) // 86400
    xd = x[:ND * 288].reshape(ND, 288)
    cov = np.isfinite(xd).mean(axis=1)
    dm = np.nanmean(xd, axis=1)
    rm = np.array([np.nanmean(dm[max(0, i - 6):i + 1]) for i in range(ND)])
    rs = np.array([np.nanstd(dm[max(0, i - 6):i + 1]) for i in range(ND)])
    fi = np.nonzero(np.isfinite(dm))[0]
    first, last = fi[0], fi[-1]
    chg = np.nanmean(dm[max(first, last - 29):last + 1]) - np.nanmean(dm[first:first + 30])
    vw = int(np.nanargmax(np.where(np.isfinite(rs), rs, -1)))
    out["trend"] = {"day": rd(dm), "roll": rd(rm), "rstd": rd(rs),
                    "insight": f"Last 30 days vs first 30: {chg:+.{d0}f} {unit}; most variable week ends "
                               f"{(datetime(2025, 1, 1) + timedelta(days=vw)).strftime('%d %b')}"}
    gaps = int((cov == 0).sum())
    full = int((cov >= 0.95).sum())
    out["coverage"] = {"day": [round(float(c), 2) for c in cov],
                       "insight": f"{n / (ND * 288) * 100:.1f}% of 5-min slots filled; {full} full days, {gaps} empty days"}
    # breaches
    if mm["warn"] is not None:
        bm, bh, dur_c = [0] * 12, [0] * 24, [0] * 6
        longest = None
        for (_, i0, i1, pk, lv, _r) in brs:
            t = Y0 + i0 * STEP
            dt_ = datetime.fromtimestamp(t, IST)
            bm[dt_.month - 1] += 1
            bh[dt_.hour] += 1
            mins = (i1 - i0 + 1) * 5
            dur_c[0 if mins < 30 else 1 if mins < 60 else 2 if mins < 120 else 3 if mins < 360 else 4 if mins < 1440 else 5] += 1
            if longest is None or mins > longest[0]:
                longest = [mins, t, pk, lv]
        nb = len(brs)
        if nb:
            m_, h_ = int(np.argmax(bm)), int(np.argmax(bh))
            ins = (f"{dur_c[0] / nb * 100:.0f}% last under 30 min; most in {mname(m_)} ({bm[m_]}); "
                   f"most start around {hhmm(h_)}; longest {fdur(longest[0] // 5)} from {tstr(longest[1])}")
        else:
            ins = "No warning or critical breach in the year"
        out["breach"] = {"by_month": bm, "by_hour": bh, "dur_labels": ["<30 min", "30-60 min", "1-2 h", "2-6 h", "6-24 h", ">24 h"],
                         "dur": dur_c, "n": nb, "longest": longest, "insight": ins}
    # autocorrelation of hourly means (lags 1..72 h) + daily-cycle strength
    hrs = np.nanmean(x[:(len(x) // 12) * 12].reshape(-1, 12), axis=1)
    hz = hrs - np.nanmean(hrs)
    var = np.nanmean(hz * hz)
    acf = []
    for L in range(1, 73):
        a, b = hz[:-L], hz[L:]
        m_ = np.isfinite(a) & np.isfinite(b)
        acf.append(r3(np.mean(a[m_] * b[m_]) / var, 3) if m_.sum() > 48 and var > 0 else None)
    tv = np.nanvar(v)
    dcs = min(float(np.nanvar(prof) / tv), 1.0) if tv > 0 else 0.0
    a24 = acf[23]
    out["acf"] = {"lags": acf, "daily_strength": round(dcs, 3),
                  "insight": f"Daily cycle explains {dcs * 100:.0f}% of the variance; r(24 h) = {a24 if a24 is not None else 'n/a'}"
                             + (", strong daily rhythm" if a24 and a24 > 0.5 else ", weak daily rhythm" if a24 is not None and a24 < 0.2 else "")}
    return out


def main():
    limits = json.loads((REPO / "data" / "sft_v2" / "node_limits.json").read_text())
    man = json.loads((REPO / "data" / "sft_v2" / "manifest.json").read_text())
    held = {n for v in man["heldout_nodes"].values() for n in v}
    occ_nodes = sorted(p.stem for p in (SERIES / "occupancy").glob("*.csv"))
    room = {n: f"Room {chr(65 + i)}" for i, n in enumerate(occ_nodes)}
    (SERIES / "_room_codes.json").write_text(json.dumps(room, indent=1))
    use, sank = load_usage(room)
    print(f"[rawdata] usage: {sum(len(v) for v in use.values())} windows", flush=True)

    if OUT.exists():
        import shutil
        shutil.rmtree(OUT)
    (OUT / "s").mkdir(parents=True)
    NB = (Y1 - Y0) // STEP
    NH = (Y1 - Y0) // 3600
    HOURLY.clear(); ANA.clear()
    sensors, tot_read, tot_br, tot_used = [], 0, Counter(), 0
    raw_windows = Counter()
    for d in sorted(p for p in SERIES.iterdir() if p.is_dir()):
        for fpath in sorted(d.glob("*.csv")):
            node = fpath.stem
            role, mets = metrics_for(d.name, node)
            if not role:
                continue
            occ = d.name == "occupancy"
            sid = ("room-" + room[node][-1].lower()) if occ else node
            label = (room[node] + ", occupancy sensor") if occ else (
                f"{node.split('-')[2][:2]} building, level {node.split('-')[2][2:]}, AC unit {node.split('-')[3]}"
                if d.name == "hvac_units" else (f"{node[3:5]} building, level {node[5:]}, all AC units" if d.name == "hvac"
                                                 else G.describe(node)))
            cols = {m: [None] * NB for m in mets}
            with open(fpath, newline="") as fh:
                for r in csv.DictReader(fh):
                    i = (int(r["bucket"]) - Y0) // STEP
                    if 0 <= i < NB:
                        for m in mets:
                            v = r.get(m, "")
                            if v not in ("", None):
                                x = float(v)
                                if m == "occ":
                                    x = 1.0 if x >= 0.5 else 0.0
                                cols[m][i] = x
            if d.name == "hvac_units":
                cols["on"] = [None if v is None else (1 if v >= 0.5 else 0) for v in cols["on"]]
            mmeta, hourly, brs = [], {}, []
            sp_all = {}
            for m in mets:
                arr = cols[m]
                n = sum(v is not None for v in arr)
                if n == 0:
                    continue
                sp = spec(role, m, node, limits)
                sp_all[m] = sp
                mean, mn, mx = [], [], []
                for hidx in range(NH):
                    seg = [v for v in arr[hidx * 12:(hidx + 1) * 12] if v is not None]
                    if seg:
                        mean.append(sum(seg) / len(seg)); mn.append(min(seg)); mx.append(max(seg))
                    else:
                        mean.append(None); mn.append(None); mx.append(None)
                hd = sp["dec"] + (1 if sp["dec"] < 2 and m in ("occ", "ac_units_on") else 0)
                hourly[m] = {"dec": hd, "mean": pack(mean, hd), "min": pack(mn, sp["dec"]), "max": pack(mx, sp["dec"])}
                b = breaches(role, m, sp, arr, cols, NICE.get(m, m))
                for x in b:
                    brs.append([m] + x)
                bw = sum(1 for x in b if x[3] == "warn"); bc = len(b) - bw
                tot_br["warn"] += bw; tot_br["crit"] += bc
                key_node = node
                u = sorted(use.get((key_node, m), []))
                tot_used += len(u)
                tot_read += n
                mmeta.append(dict(m=m, label=NICE.get(m, m), unit=sp["unit"], dec=sp["dec"], warn=sp["warn"], crit=sp["crit"],
                                  dir=sp["dir"], lo_warn=sp.get("lo_warn"), lo_crit=sp.get("lo_crit"), n=n, cov=round(n / NB, 4), bw=bw, bc=bc, used=len(u)))
                # raw 4 h windows (stride 1 h) for the sankey
                if role != "hvac" or d.name == "hvac_units":
                    raw_windows[role] += sum(1 for e in range(47, NB, 12) if arr[e] is not None and arr[e - 47] is not None)
            if not mmeta:
                continue
            bld = building(node)
            ana = {}
            for mm in mmeta:
                hm = np.array([np.nan if v is None else v for v in cols[mm["m"]]], dtype=float)
                ana[mm["m"]] = analyse(hm, mm, [b for b in brs if b[0] == mm["m"]])
                with warnings.catch_warnings():
                    warnings.simplefilter("ignore")
                    hr = np.nanmean(hm[:NH * 12].reshape(NH, 12), axis=1)
                HOURLY.append((sid, mm["m"], bld, mm["label"], hr))
            ANA[sid] = ana
            usage = []
            for mm in mmeta:
                for w in sorted(use.get((node, mm["m"]), [])):
                    usage.append([mm["m"]] + w)
            months = []
            (OUT / "c" / sid).mkdir(parents=True, exist_ok=True)
            for k in range(12):
                a, b = (MONTHS[k] - Y0) // STEP, (MONTHS[k + 1] - Y0) // STEP
                chunk = {}
                for mm in mmeta:
                    seg = cols[mm["m"]][a:b]
                    if any(v is not None for v in seg):
                        chunk[mm["m"]] = pack(seg, mm["dec"])
                if chunk:
                    months.append(k + 1)
                    (OUT / "c" / sid / f"2025-{k + 1:02d}.json").write_text(
                        json.dumps({"t0": MONTHS[k], "step": STEP, "len": b - a, "m": chunk}, separators=(",", ":")))
            doc = {"id": sid, "t0": Y0, "hour": 3600, "hourly": hourly, "breaches": brs, "usage": usage}
            (OUT / "s" / f"{sid}.json").write_text(json.dumps(doc, separators=(",", ":")))
            sensors.append(dict(id=sid, domain=d.name, label=label, role=role, heldout=node in held, months=months,
                                metrics=mmeta, breaches=len(brs), used=len(usage)))
            print(f"[rawdata] {d.name}/{sid}: {len(brs)} breaches, {len(usage)} windows", flush=True)

    # correlations with sensors in the same building (hourly means, Pearson)
    for (sid, m, bld, lab, hr) in HOURLY:
        best = []
        f1 = np.isfinite(hr)
        for (sid2, m2, bld2, lab2, hr2) in HOURLY:
            if sid2 == sid or bld2 != bld:
                continue
            ok = f1 & np.isfinite(hr2)
            if ok.sum() < 24 * 14:
                continue
            a, b = hr[ok], hr2[ok]
            if a.std() == 0 or b.std() == 0:
                continue
            r = float(np.corrcoef(a, b)[0, 1])
            best.append((abs(r), r, sid2, m2, lab2, int(ok.sum())))
        best.sort(reverse=True)
        top = [dict(id=x[2], m=x[3], label=x[4], r=round(x[1], 3), n=x[5]) for x in best[:3]]
        ins = (f"Strongest link: {top[0]['id']} {top[0]['label']} (r = {top[0]['r']:+.2f}, n = {top[0]['n']} h)" if top
               else "No other sensor in this building overlaps 2 weeks")
        ANA[sid][m]["corr"] = {"top": top, "insight": ins, "building": bld}
    (OUT / "a").mkdir(exist_ok=True)
    for sid, ana in ANA.items():
        (OUT / "a" / f"{sid}.json").write_text(json.dumps(ana, separators=(",", ":"), allow_nan=False))

    # sankey: real windows -> bases -> families -> splits
    used_v = Counter(); fam_c = Counter(); fam_sp = Counter()
    group = {"injected": "Injected pattern", "stable": "Calm, untouched", "occupancy": "Real occupancy", "event": "Injected pattern",
             "compound": "Injected pattern", "recurring": "Injected pattern", "old_shift": "Injected pattern",
             "long_drift": "Injected pattern", "fault": "Injected fault", "routine": "Routine", "real_routine": "Routine",
             "water_fill": "Routine", "real_longrange": "Calm, untouched", "zero_idle": "Calm, untouched", "hvac": "HVAC rule-labelled"}
    for (ver, fam, sp), n in sank.items():
        g = group.get(fam, fam)
        fam_c[g] += n; fam_sp[(g, sp)] += n; used_v[ver] += n
    total_raw = sum(raw_windows.values())
    used = sum(used_v.values())
    links = [{"source": "Real 4 h windows", "target": "Used as base", "value": used},
             {"source": "Real 4 h windows", "target": "Not used", "value": max(total_raw - used, 0)}]
    for g, n in fam_c.items():
        links.append({"source": "Used as base", "target": g, "value": n})
    for (g, sp), n in fam_sp.items():
        links.append({"source": g, "target": sp.capitalize(), "value": n})
    names = ["Real 4 h windows", "Used as base", "Not used"] + sorted(fam_c) + ["Train", "Dev", "Test"]
    doms = Counter(s["domain"] for s in sensors)
    index = {
        "generated_at": datetime.now().replace(microsecond=0).isoformat(), "script": "Website/build/collect/rawdata.py",
        "source_files": ["Code/smart-city-edge-agent/data/series/", "Code/smart-city-edge-agent/data/sft/*.jsonl",
                         "Code/smart-city-edge-agent/data/sft_v2/*.jsonl", "Code/smart-city-edge-agent/data/sft_v2/manifest.json"],
        "year_t0": Y0, "month_t0": MONTHS, "step": STEP,
        "splits_v1": {"train": [1, 8], "dev": [9, 10], "test": [11, 12]},
        "domains": [{"id": k, "label": DOMAIN_LABEL.get(k, k), "n": v} for k, v in doms.items()],
        "totals": {"sensors": len(sensors), "readings": tot_read, "months": 12, "breaches": tot_br["warn"] + tot_br["crit"],
                   "breaches_crit": tot_br["crit"], "windows_used": tot_used, "examples_v1": used_v["v1"], "examples_v2": used_v["v2"],
                   "real_windows": total_raw},
        "sankey": {"nodes": [{"name": n, "ours": n == "Used as base"} for n in names], "links": links},
        "sensors": sensors,
    }
    (OUT / "index.json").write_text(json.dumps(index, separators=(",", ":")))
    size = sum(f.stat().st_size for f in OUT.rglob("*") if f.is_file())
    nf = sum(1 for f in OUT.rglob("*") if f.is_file())
    print(f"[rawdata] {len(sensors)} sensors, {tot_read} readings, {index['totals']['breaches']} breaches, "
          f"{tot_used} windows; {nf} files, {size / 1e6:.1f} MB", flush=True)


if __name__ == "__main__":
    main()
