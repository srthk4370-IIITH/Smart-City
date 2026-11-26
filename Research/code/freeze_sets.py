"""freeze_sets.py: freeze the paper test sets (sets/{A,B,D,F}.jsonl + MANIFEST.json). Deterministic (seed 26112601).
 B  injected multi-domain cases (150) into REAL held-out campus windows (all windows end >= cutoff + 12 h, so the 12 h history is after the cutoff too)
 D  negative controls: normal real windows (50) + real rule-detected sensor-fault windows (15)
 A  natural replay windows (200; real, unscored: cost / routing only)
 F  forced single-domain cases (50): 30 injected single-domain (gold) + 20 natural single-domain real (rule critical / fault weighted)
Needs natural_scan.json (scan_natural.py)."""
import collections, hashlib, json, os, random, sys
import pdata as D, pcore as C, pinject as I

R = random.Random(26112601)
OUT = D.PAPER + "/sets"; os.makedirs(OUT, exist_ok=True)
T0 = D.CUTOFF + 12 * 3600
SLOTS = list(range(T0 - T0 % 900 + 900, D.DATA_END - 300, 900))
scan = collections.defaultdict(dict)       # T -> key -> (pattern, status)
for e, k, p, s in json.load(open(D.PAPER + "/natural_scan.json")):
    scan[e][k] = (p, s)
used = []


def free(T, sep=1200):
    return all(abs(T - u) >= sep for u in used)


def ist(e):
    return C.dtime(e).strftime("%Y-%m-%d %H:%M IST")


def hour(e):
    return C.dtime(e).hour


def real_series(T):
    out = {}
    for s in D.SENSORS:
        w = D.window(s["node"], s["metric"], T, 144)
        if w is not None:
            out[s["key"]] = C.rnd(w, s["role"], s["metric"])
    return out


def mk(set_, n, kind, T, fam, series, flagged, gold, params=None, stratum=None):
    used.append(T)
    return dict(id="%s-%03d" % (set_, n), set=set_, kind=kind, family=fam, stratum=stratum, end=T, end_ist=ist(T), series=series, flagged=flagged,
                gold=gold, params=params or {})


# ---------------------------------------------------------------- Set B
B = []
heat = {"heat_room", "heat_ac3", "heat_ac_water", "crowd_heat", "heat_feeder", "heat_crowd_water", "heat_crowd_water_hvac", "crowd_co2"}
PRIO = ["heat_crowd_water", "heat_crowd_water_hvac", "heat_ac_water", "heat_ac3", "crowd_heat", "heat_room", "pm_ingress", "heat_feeder", "crowd_co2", "ac_fail", "fault_vs_event"]
for name in PRIO:
    fn, strat, cnt = I.FAMS_B[name]
    got = tries = 0
    while got < cnt and tries < 5000:
        tries += 1
        T = R.choice(SLOTS)
        if not free(T) or (name in heat and not 8 <= hour(T) <= 19):
            continue
        try:
            r = fn(R, T)
        except KeyError:
            continue
        B.append(mk("B", len(B), "injected", T, name, r["series"], r["flagged"], r["gold"], r["params"], strat))
        got += 1
    if got < cnt:
        print("WARN family %s only %d/%d" % (name, got, cnt))
R.shuffle(B)
for i, c in enumerate(B):
    c["id"] = "B-%03d" % i

# ---------------------------------------------------------------- Set D
Dn = []
cand = [T for T in SLOTS if free(T)]
R.shuffle(cand)
SKIP = {"pf", "occ", "ac_units_on", "room_temp", "tds", "ph", "level"}
for T in cand:
    if len(Dn) >= 50:
        break
    if not free(T):
        continue
    ok = [k for k, (p, s) in scan[T].items() if s == "normal" and k.split("/")[1] not in SKIP]
    nd = 2 if len(Dn) % 5 < 3 else 1
    pick = []
    for k in R.sample(ok, len(ok)):
        if D.BY_KEY[k]["role"] not in [D.BY_KEY[x]["role"] for x in pick]:
            pick.append(k)
        if len(pick) == nd:
            break
    if len(pick) < nd:
        continue
    gold = dict(label="normal_operation", severity="normal", affected_domains=[], n_domains=nd, n_sensors=nd)
    Dn.append(mk("D", len(Dn), "real", T, "normal_%dd" % nd, real_series(T), pick, gold))
fault_quota = {"co2": 4, "temp": 3, "rh": 2, "flow": 2, "wind": 2, "pf": 2}
fc = collections.Counter()
cand = [T for T in SLOTS if free(T)]
R.shuffle(cand)
for T in cand:
    if sum(fc.values()) >= 15:
        break
    for k, (p, s) in scan[T].items():
        m = k.split("/")[1]
        if s == "sensor_fault" and fc[m] < fault_quota.get(m, 0) and free(T):
            gold = dict(label="sensor_fault", severity="sensor_fault", affected_domains=[D.BY_KEY[k]["role"]], n_domains=1, n_sensors=1)
            Dn.append(mk("D", len(Dn), "real", T, "real_fault_" + m, real_series(T), [k], gold, dict(rule_pattern=p)))
            fc[m] += 1
            break
for i, c in enumerate(Dn):
    c["id"] = "D-%03d" % i


# ---------------------------------------------------------------- Set A (natural replay) and natural single for F
def natural_flagged(T):
    return sorted([k for k, (p, s) in scan[T].items() if s != "normal" and D.BY_KEY[k]["role"] != "hvac"])


multi, single = [], collections.defaultdict(list)
cand = [T for T in SLOTS if free(T, 900)]
R.shuffle(cand)
for T in cand:
    fl = natural_flagged(T)
    doms = {D.BY_KEY[k]["role"] for k in fl}
    if len(doms) >= 2:
        multi.append((T, fl))
    elif len(doms) == 1:
        single[fl[0].split("/")[1]].append((T, fl))
A = []
for T, fl in multi:
    if len(A) >= 28:
        break
    if free(T, 900):
        fl2 = fl[:6]; nd = len({D.BY_KEY[k]["role"] for k in fl2})
        A.append(mk("A", len(A), "real", T, "natural_multi", real_series(T), fl2, None, stratum="2-4" if nd < 5 else "5+"))
keys = sorted(single)
j = 0
reserve = {k: v[-40:] for k, v in single.items()}      # natural-single candidates kept for Set F
for k in single:
    single[k] = single[k][:-40]
while len(A) < 200 and any(single.values()):
    k = keys[j % len(keys)]; j += 1
    while single[k]:
        T, fl = single[k].pop()
        if free(T, 900):
            A.append(mk("A", len(A), "real", T, "natural_single_" + k, real_series(T), fl[:1], None, stratum="1"))
            break
R.shuffle(A)
for i, c in enumerate(A):
    c["id"] = "A-%03d" % i

# ---------------------------------------------------------------- Set F: forced single-domain
F = []
names = list(I.FAMS_S)
tries = 0
while len(F) < 30 and tries < 3000:
    tries += 1
    T = R.choice(SLOTS)
    if not free(T):
        continue
    nm = names[len(F) % len(names)]
    try:
        r = I.FAMS_S[nm](R, T)
    except KeyError:
        continue
    F.append(mk("F", len(F), "injected", T, nm, r["series"], r["flagged"], r["gold"], r["params"], "1"))
pool = [(k, T, fl) for k, v in reserve.items() for (T, fl) in v]
R.shuffle(pool)
crit = [p for p in pool if scan[p[1]][p[2][0]][1] in ("critical", "sensor_fault")]
rest = [p for p in pool if p not in crit]
for k, T, fl in (crit[:14] + rest[:6]) + crit[14:] + rest[6:]:
    if len(F) >= 50:
        break
    if free(T, 900):
        F.append(mk("F", len(F), "real", T, "natural_single_" + k, real_series(T), fl[:1], None, stratum="1"))
for i, c in enumerate(F):
    c["id"] = "F-%03d" % i

man = {"seed": 26112601, "cutoff_epoch": D.CUTOFF, "min_window_end_epoch": T0,
       "note": "all windows (incl. the 12 h history) end after the training cutoff; real baselines from the 18-sensor campus network", "files": {}}
for nm, rows in (("A", A), ("B", B), ("D", Dn), ("F", F)):
    p = OUT + "/%s.jsonl" % nm
    open(p, "w", newline="\n").write("".join(json.dumps(c, ensure_ascii=False, sort_keys=True) + "\n" for c in rows))
    man["files"][nm] = dict(sha256=hashlib.sha256(open(p, "rb").read()).hexdigest(), n=len(rows), ids=[c["id"] for c in rows],
                            by_stratum=dict(collections.Counter(str(c.get("stratum")) for c in rows)), by_family=dict(collections.Counter(c["family"] for c in rows)),
                            by_kind=dict(collections.Counter(c["kind"] for c in rows)))
json.dump(man, open(OUT + "/MANIFEST.json", "w", newline="\n"), indent=1, sort_keys=True)
print({k: v["n"] for k, v in man["files"].items()})
for k, v in man["files"].items():
    print(k, v["by_stratum"], v["by_kind"])
