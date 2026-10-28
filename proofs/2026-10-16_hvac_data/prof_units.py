import csv, sys, json, statistics as S
from collections import Counter
from datetime import datetime, timezone, timedelta
from pathlib import Path
IST = timezone(timedelta(hours=5, minutes=30))
d = Path(sys.argv[1]); out = {}
def q(xs, k): 
    if not xs: return None
    xs = sorted(xs); return round(xs[int(k*(len(xs)-1))], 2)
G = dict(err_on=[], pull=[], runs=[], offs=[], thermo_runs=[], noise=[], hours_on=Counter(), hours_n=Counter(), wk_on=[0,0], we_on=[0,0])
for p in sorted(d.glob("SR-AC-*.csv")):
    R = list(csv.DictReader(open(p)))
    b = [int(r["bucket"]) for r in R]
    on = [int(r["on"]) for r in R]
    rt = [float(r["room_temp"]) if r["room_temp"] else None for r in R]
    sp = [float(r["setpoint"]) if r["setpoint"] else None for r in R]
    th = [float(r["thermo"]) for r in R]
    mode = Counter(r["mode"] for r, o in zip(R, on) if o)
    alarm = sum(int(r["alarm"]) for r in R); malf = Counter(r["malf"] for r in R if r["malf"] != "1")
    gaps = sum(1 for i in range(1, len(b)) if b[i]-b[i-1] > 300)
    missing = sum(1 for x in rt if x is None)
    # runs
    runs=[]; offs=[]; cur=0; offc=0; starts=0
    for i,o in enumerate(on):
        if o: 
            if cur==0 and i>0: starts+=1; offs.append(offc) if offc else None
            cur+=1; offc=0
        else:
            if cur: runs.append(cur)
            cur=0; offc+=1
    # error after 30 min running
    err=[]; pull=[]; dn=[]
    for i in range(len(R)):
        if i>=6 and all(on[i-6:i+1]) and rt[i] is not None and sp[i] is not None and b[i]-b[i-6]==1800:
            err.append(rt[i]-sp[i])
        if i>0 and on[i] and not on[i-1] and i+6 < len(R) and all(on[i:i+7]) and rt[i] is not None and rt[i+6] is not None and b[i+6]-b[i]==1800:
            pull.append((rt[i+6]-rt[i])*2)  # C/h over first 30 min
        if i>0 and rt[i] is not None and rt[i-1] is not None and b[i]-b[i-1]==300: dn.append(rt[i]-rt[i-1])
    # thermo cycling when on
    tr=[]; c=0
    for i in range(len(R)):
        if on[i] and th[i]>=0.5: c+=1
        elif c: tr.append(c); c=0
    # flat runs in temp
    flat=0; best=1; cur2=1
    for i in range(1,len(rt)):
        if rt[i] is not None and rt[i-1] is not None and abs(rt[i]-rt[i-1])<0.005: cur2+=1; best=max(best,cur2)
        else:
            if cur2>=16: flat+=1
            cur2=1
    hrs=Counter(); hn=Counter()
    for x,o in zip(b,on):
        t=datetime.fromtimestamp(x,IST); hn[t.hour]+=1; hrs[t.hour]+=o
        (G["we_on"] if t.weekday()>=5 else G["wk_on"])[0]+=o; (G["we_on"] if t.weekday()>=5 else G["wk_on"])[1]+=1
    G["hours_on"].update(hrs); G["hours_n"].update(hn)
    mad = q([abs(x) for x in dn], .5)
    noise=[x for x in dn]
    rtv=[x for x in rt if x is not None]
    out[p.stem]=dict(buckets=len(R), first=str(datetime.fromtimestamp(b[0],IST).date()), last=str(datetime.fromtimestamp(b[-1],IST).date()),
        gaps=gaps, rt_missing=missing, on_frac=round(sum(on)/len(on),3), starts=starts, run_p50=q(runs,.5), run_p10=q(runs,.1), run_max=max(runs) if runs else 0,
        short_runs_le2=sum(1 for r in runs if r<=2), rt_p5=q(rtv,.05), rt_p50=q(rtv,.5), rt_p95=q(rtv,.95), rt_min=min(rtv) if rtv else None, rt_max=max(rtv) if rtv else None,
        err_on_p10=q(err,.1), err_on_p50=q(err,.5), err_on_p90=q(err,.9), n_err=len(err), pull_p50=q(pull,.5), n_pull=len(pull),
        thermo_runs=len(tr), thermo_run_p50=q(tr,.5), d5_abs_p50=mad, d5_p95=q([abs(x) for x in dn],.95), flat16_runs=flat, longest_flat=best,
        mode_on=dict(mode), alarm_buckets=alarm, malf=dict(malf), sp_distinct=len(set(x for x in sp if x is not None)),
        hour_on=[round(hrs[h]/hn[h],2) for h in range(24)])
    G["err_on"]+=err; G["pull"]+=pull; G["runs"]+=runs; G["thermo_runs"]+=tr
summary=dict(units=len(out), err_on_q={k:q(G["err_on"],k) for k in (.05,.1,.25,.5,.75,.9,.95)}, pull_q={k:q(G["pull"],k) for k in (.1,.25,.5,.75,.9)},
   runs_q={k:q(G["runs"],k) for k in (.1,.25,.5,.75,.9)}, n_runs=len(G["runs"]), runs_le2=sum(1 for r in G["runs"] if r<=2), thermo_q={k:q(G["thermo_runs"],k) for k in (.1,.5,.9)},
   hour_on=[round(G["hours_on"][h]/G["hours_n"][h],3) for h in range(24)], weekday_on=round(G["wk_on"][0]/G["wk_on"][1],3), weekend_on=round(G["we_on"][0]/G["we_on"][1],3))
json.dump(dict(summary=summary, units=out), open(sys.argv[2],"w"), indent=1)
print(json.dumps(summary, indent=1))
for k,v in out.items():
    if v["on_frac"]>0: print(k, {x:v[x] for x in ("on_frac","starts","run_p50","run_p10","short_runs_le2","rt_p5","rt_p50","rt_p95","err_on_p10","err_on_p50","err_on_p90","n_err","pull_p50","n_pull","thermo_runs","thermo_run_p50","d5_abs_p50","d5_p95","flat16_runs","mode_on","alarm_buckets","malf","rt_missing")})
print("never-on units:", [k for k,v in out.items() if v["on_frac"]==0])
print("never-on sample:", {k:{x:v[x] for x in ("rt_p5","rt_p50","rt_p95","flat16_runs","longest_flat","rt_missing","alarm_buckets","malf","d5_abs_p50")} for k,v in list(out.items()) if v["on_frac"]==0 and k.endswith(("00","03","11"))})
