"""Truth for blind sweep 7 Q12-40 (deploy24 r2): incident snapshot at the end of the run, each question's sim time (IST)."""
import json, datetime as D
IST = D.timezone(D.timedelta(hours=5, minutes=30))
inc = [i for i in json.load(open('inc_sweep7_blind_rest_end.json')) if str(i['injected']) != 'True']
R = {r['i']: r for r in map(json.loads, open('sweep7_blind.jsonl'))}
t = lambda i: int(i['created_sim'])
ist = lambda s: D.datetime.fromtimestamp(s, IST).strftime('%a %d %b %Y %H:%M')
day0 = lambda s: int(D.datetime.fromtimestamp(s, IST).replace(hour=0, minute=0, second=0, microsecond=0).timestamp())
def rng(a, b, **f):
    return [i for i in inc if a <= t(i) < b and all((v in i['roles']) if k == 'role' else (v in str(i['sensors'])) if k == 'sensor' else i[k] in v for k, v in f.items())]
ids = lambda xs: [i['id'] for i in xs]
out = {}
for k, r in R.items():
    n = r['sim_time']; o = {'sim_ist': ist(n)}; d0 = day0(n)
    if k == 12: o['INC-0620'] = [(i['approval'], i['workflow']) for i in inc if i['id'] == 'INC-0620']
    if k == 14:
        a = int(D.datetime(2026, 10, 22, tzinfo=IST).timestamp()); o['tds_22oct'] = ids(rng(a, a + 86400, sensor='tds'))
    if k == 15: o['last7'] = len(rng(n - 7*86400, n)); o['prev7'] = len(rng(n - 14*86400, n - 7*86400))
    if k == 26:
        dd = D.datetime.fromtimestamp(n, IST); sun = d0 - ((dd.weekday() + 1) % 7) * 86400
        o['sunday'] = (ist(sun), len(rng(sun, sun + 86400)))
    if k == 27: y = d0 - 86400; o['crit_17_21_yday'] = ids(rng(y + 17*3600, y + 21*3600, severity=('critical',)))
    if k == 29:
        m0 = int(D.datetime.fromtimestamp(n, IST).replace(day=1, hour=0, minute=0, second=0, microsecond=0).timestamp())
        o['AQ-KN00_month'] = ids(rng(m0, n, sensor='AQ-KN00-00')); o['aq_month'] = len(rng(m0, n, role='air_quality'))
    if k == 30: o['dismissed_7d'] = ids(rng(n - 7*86400, n, approval=('dismissed',)))
    if k in (31, 32):
        p = sorted([i for i in inc if i['workflow'] == 'needs_decision'], key=t)
        o['oldest_pending'] = (p[0]['id'], ist(t(p[0])), round((n - t(p[0])) / 86400, 1)) if p else None
    if k == 38:
        dd = D.datetime.fromtimestamp(n, IST); mon = d0 - dd.weekday() * 86400
        o['this_week_since_mon'] = len(rng(mon, n)); o['last_7d'] = len(rng(n - 7*86400, n))
        o['sev_this_week'] = {s: len(rng(mon, n, severity=(s,))) for s in ('critical', 'warning', 'sensor_fault', 'normal')}
    if k == 40: o['hvac_today'] = ids(rng(d0, n, role='hvac')); o['power_today'] = ids(rng(d0, n, role='power'))
    out[k] = o
print(json.dumps(out, indent=1)); json.dump(out, open('truth7b.json', 'w'), indent=1)
