import json, glob, os, statistics as s
rows=[]
out={}
for f in sorted(glob.glob(os.path.join(os.path.dirname(os.path.abspath(__file__)),'raw_audit','*.json'))):
    if f.endswith('summary.json'): continue
    d=json.load(open(f)); P=d['per_node'].values()
    tot=lambda k: sum((p.get(k) or 0) for p in P)
    gt=lambda k: sum(p['gaps'].get(k,0) for p in P)
    n=d['rows']
    shifts=[(nd,x) for nd,p in d['per_node'].items() for x in p['version_shifts'] if x['ratio'] and (x['ratio']>1.5 or x['ratio']<0.67)]
    r={'file':d['file'],'metric':d['metric'],'rows':n,'nodes':d['nodes'],'tz':d['tz_suffix'],
       'median_interval_s':s.median([p['median_interval_s'] for p in P if p['median_interval_s']]) if any(p['median_interval_s'] for p in P) else None,
       'gap_time_frac_median':round(s.median([p['gap_time_frac'] for p in P if p['gap_time_frac'] is not None]),3),
       'gaps_gt1h':gt('gt1h'),'gaps_gt24h':gt('gt24h'),'dup_ts':tot('dup_timestamp'),'dup_exact':tot('dup_exact'),
       'out_of_order':tot('out_of_order_arrival'),'late_gt10m':tot('late_gt10m'),'bursts':tot('bursts'),
       'clock_not_epoch':tot('device_clock_not_epoch'),'below':tot('below_range'),'above':tot('above_range'),'missing_val':tot('missing_value'),
       'stuck_ge2h':tot('stuck_runs_ge2h'),'stuck_ge6h':tot('stuck_runs_ge6h'),'stuck_longest_h':max(p['stuck_longest_h'] for p in P),
       'glitch_per_10k_median':s.median([p['glitch_per_10k'] for p in P]),
       'version_changes':sum(max(0,len(p['versions'])-1) for p in P),'level_shift_at_version':len(shifts),
       'shift_examples':[{'node':a,**b} for a,b in shifts[:4]],
       'sitewide_silent_hours':d.get('sitewide_silent_hours'),'span_hours':d.get('span_hours'),'outages_ge2h':len(d.get('sitewide_outages',[]))}
    rows.append(r)
json.dump(rows,open(os.path.join(os.path.dirname(os.path.abspath(__file__)),'raw_audit','summary.json'),'w'),indent=1)
for r in rows:
    print({k:v for k,v in r.items() if k not in('shift_examples',)})
    for x in r['shift_examples']: print('   shift',x)
