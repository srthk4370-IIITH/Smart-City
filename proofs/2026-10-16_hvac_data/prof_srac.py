import csv, sys, json
from collections import Counter, defaultdict
from datetime import datetime
path = sys.argv[1]; out = sys.argv[2]
CAT = ["Version","Start Stop Status","Alarm","Malfunction Code","Air Con Mode Status","Air Flow Rate Status","Filter Sign",
       "Air Direction Status","Forced Thermo OFF Status","Energy Efficiency Status","Thermo Status","Compressor Status","Indoor Fan Status","Heater Status"]
NUM = ["Room Temp","Temp Adjust","Gas Total Power","Elec Total Power"]
def f(s):
    try: return float(s)
    except: return None
cat = {c: Counter() for c in CAT}
num = {c: dict(n=0, s=0.0, mn=1e18, mx=-1e18, miss=0, hist=Counter()) for c in NUM}
node = defaultdict(lambda: dict(n=0, first=None, last=None, prev=None, dt=Counter(), months=Counter(), sp_changes=0, prev_sp=None,
                                 ep_up=0, ep_down=0, ep_same=0, prev_ep=None, on=0, comp_on=0, thermo_on=0))
joint = Counter(); diff_on = Counter(); diff_off=Counter(); sp_on = Counter(); mode_on=Counter()
hour_on = Counter(); hour_n = Counter(); dow_on=Counter(); dow_n=Counter()
rows = 0
with open(path, encoding="utf-8", errors="replace", newline="") as fh:
    for r in csv.DictReader(fh):
        rows += 1
        nd = r["Node_id"]
        try: t = datetime.fromisoformat(r["Timestamp"]).timestamp()
        except: continue
        S = node[nd]; S["n"] += 1
        if S["first"] is None or t < S["first"]: S["first"] = t
        if S["last"] is None or t > S["last"]: S["last"] = t
        if S["prev"] is not None:
            d = int(t - S["prev"]); S["dt"][min(d, 7200)//60] += 1
        S["prev"] = t
        dt = datetime.fromtimestamp(t + 19800)
        S["months"][dt.strftime("%Y-%m")] += 1
        for c in CAT: 
            if len(cat[c]) < 60 or r.get(c) in cat[c]: cat[c][r.get(c)] += 1
        for c in NUM:
            v = f(r.get(c)); a = num[c]
            if v is None: a["miss"] += 1; continue
            a["n"] += 1; a["s"] += v; a["mn"] = min(a["mn"], v); a["mx"] = max(a["mx"], v)
            a["hist"][round(v) if c in ("Room Temp","Temp Adjust") else int(v//100)*100 if v < 100000 else int(v//100000)*100000] += 1
        ss, th, cp = r.get("Start Stop Status"), r.get("Thermo Status"), r.get("Compressor Status")
        joint[(ss, th, cp, r.get("Indoor Fan Status"))] += 1
        rt, sp = f(r.get("Room Temp")), f(r.get("Temp Adjust"))
        on = f(ss) == 1.0
        hour_n[dt.hour] += 1; dow_n[dt.weekday()] += 1
        if on:
            S["on"] += 1; hour_on[dt.hour] += 1; dow_on[dt.weekday()] += 1
            mode_on[r.get("Air Con Mode Status")] += 1
            if sp is not None: sp_on[sp] += 1
        if f(cp) == 1.0: S["comp_on"] += 1
        if f(th) == 1.0: S["thermo_on"] += 1
        if rt is not None and sp is not None:
            dd = round(rt - sp)
            (diff_on if on else diff_off)[(dd, cp)] += 1
        if sp is not None:
            if S["prev_sp"] is not None and sp != S["prev_sp"]: S["sp_changes"] += 1
            S["prev_sp"] = sp
        ep = f(r.get("Elec Total Power"))
        if ep is not None:
            if S["prev_ep"] is not None:
                if ep > S["prev_ep"]: S["ep_up"] += 1
                elif ep < S["prev_ep"]: S["ep_down"] += 1
                else: S["ep_same"] += 1
            S["prev_ep"] = ep
res = dict(rows=rows, cat={c: dict(v.most_common(40)) for c, v in cat.items()},
           num={c: dict(n=a["n"], miss=a["miss"], mean=a["s"]/max(1,a["n"]), mn=a["mn"], mx=a["mx"], hist=sorted(a["hist"].items())) for c, a in num.items()},
           joint={"|".join(map(str,k)): v for k, v in joint.most_common(40)},
           diff_on=sorted(((str(k), v) for k, v in diff_on.items())), diff_off=sorted(((str(k), v) for k, v in diff_off.items())),
           sp_on=sorted(sp_on.items()), mode_on=dict(mode_on), hour_on_frac={h: hour_on[h]/hour_n[h] for h in sorted(hour_n)},
           dow_on_frac={d: dow_on[d]/dow_n[d] for d in sorted(dow_n)},
           nodes={k: dict(n=S["n"], first=datetime.fromtimestamp(S["first"]+19800).isoformat(), last=datetime.fromtimestamp(S["last"]+19800).isoformat(),
                          dt_top=S["dt"].most_common(6), months=dict(sorted(S["months"].items())), sp_changes=S["sp_changes"],
                          ep=(S["ep_up"], S["ep_down"], S["ep_same"]), on_frac=S["on"]/S["n"], comp_frac=S["comp_on"]/S["n"], thermo_frac=S["thermo_on"]/S["n"])
                  for k, S in sorted(node.items())})
json.dump(res, open(out, "w"), indent=1, default=str)
print("rows", rows, "nodes", len(node))
