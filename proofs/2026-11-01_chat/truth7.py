"""Truth for blind sweep 7 (partial): incident snapshot at each question's sim time (IST) + device live feed. usage: python3 truth7.py"""
import json, datetime as D
IST = D.timezone(D.timedelta(hours=5, minutes=30))
inc = [i for i in json.load(open('inc_sweep7_blind_end.json')) if str(i['injected']) != 'True']
R = {r['i']: r for r in map(json.loads, open('sweep7_blind.jsonl'))}
t = lambda i: int(i['created_sim'])
ist = lambda s: D.datetime.fromtimestamp(s, IST).strftime('%a %d %b %H:%M')
def rng(a, b, **f):
    return [i for i in inc if a <= t(i) < b and all((v in i['roles']) if k == 'role' else (v in str(i['sensors'])) if k == 'sensor' else i[k] in v for k, v in f.items())]
out = {'latest_incident_sim': ist(max(map(t, inc))), 'n_incidents': len(inc)}
live = json.load(open('live_sweep7_blind_start.json'))
out['live_feed'] = sorted({(s['quality'], s['feed']) for r in live['roles'].values() for s in r['sensors']})
out['open_needs_decision'] = len([i for i in inc if i['workflow'] == 'needs_decision'])
for k, r in R.items():
    n = r['sim_time']; o = {'sim_ist': ist(n)}
    if k == 1: o['crit_warn_last12h'] = len(rng(n - 12*3600, n, severity=('critical', 'warning')))
    if k == 3: o['co2_KH03_24h'] = len(rng(n - 86400, n, sensor='SR-AQ-KH03-03 co2'))
    if k == 5: o['feeder_slider_kw'] = [s['value'] for s in json.load(open('sensors_sweep7_blind_start.json'))['sensors'] if s['node'] == 'EM-CR-SB00-00' and s['metric'] == 'power_kw']
    if k == 7: o['weather_last12h'] = len(rng(n - 12*3600, n, role='weather'))
    if k == 8:
        d = D.datetime.fromtimestamp(n, IST); mon = (d - D.timedelta(days=d.weekday())).replace(hour=8, minute=0, second=0, microsecond=0).timestamp()
        o['since_mon8'] = (ist(mon), len(rng(mon, n)))
    if k == 11: o['KH95-02_14d'] = len(rng(n - 14*86400, n, sensor='SR-AC-KH95-02')); o['KH95-02_alltime'] = len(rng(0, n, sensor='SR-AC-KH95-02'))
    out[k] = o
print(json.dumps(out, indent=1)); json.dump(out, open('truth7.json', 'w'), indent=1)
