"""pdata.py: real campus series access (the 18-sensor campus network of sensors.json), window grid + gap rule (app: 20-min linear fill, states held)."""
import csv, glob, json, os, bisect
Q = "/mnt/c/Users/hp/Desktop/qidk"
PAPER = Q + "/proofs/2026-11-26_paper"
SER = Q + "/Code/smart-city-edge-agent/data/series"
CUTOFF = 1765391400          # 2025-12-11 00:00 IST (proofs/2026-11-21_rsn_full/CUTOFF.md)
DATA_END = 1767205800        # 2026-01-01 00:00 IST
STATE_METRICS = {"occ", "ac_units_on"}
SENSORS = json.load(open(PAPER + "/_appdata/sensors.json"))["sensors"]
for s in SENSORS:
    s["key"] = s["node"] + "/" + s["metric"]
BY_KEY = {s["key"]: s for s in SENSORS}
_cache = {}


def raw(node, metric):
    k = (node, metric)
    if k not in _cache:
        f = glob.glob("%s/*/%s.csv" % (SER, node))[0]
        t, v = [], []
        for r in csv.DictReader(open(f)):
            x = r.get(metric)
            if x in (None, ""):
                continue
            try:
                t.append(int(float(r["bucket"]))); v.append(float(x))
            except ValueError:
                pass
        o = sorted(range(len(t)), key=t.__getitem__)
        _cache[k] = ([t[i] for i in o], [v[i] for i in o])
    return _cache[k]


def value_at(node, metric, e, fill_min=20):
    """value at bucket epoch e: exact, else linear (continuous) / held (states) across a gap <= fill_min, else None"""
    ts, vs = raw(node, metric)
    i = bisect.bisect_right(ts, e) - 1
    if i < 0:
        return None
    if ts[i] == e:
        return vs[i]
    if metric in STATE_METRICS:
        return vs[i] if e - ts[i] <= 24 * 3600 else None
    if i + 1 >= len(ts) or ts[i + 1] - ts[i] > fill_min * 60:
        return None
    a = (e - ts[i]) / (ts[i + 1] - ts[i])
    return vs[i] + a * (vs[i + 1] - vs[i])


def window(node, metric, end, n=144, min_cov=0.92):
    """last n 5-min values ending at bucket `end` (inclusive); None when coverage < min_cov (leftover gaps held)"""
    xs = [value_at(node, metric, end - 300 * (n - 1 - i)) for i in range(n)]
    ok = sum(x is not None for x in xs)
    if ok < min_cov * n or xs[-1] is None:
        return None
    last = None
    for i, x in enumerate(xs):
        if x is None:
            xs[i] = last if last is not None else next(y for y in xs if y is not None)
        else:
            last = x
    return xs
