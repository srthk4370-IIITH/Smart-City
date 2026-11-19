"""Truth for the held-out sweep: counts from the incident snapshot at each question's sim time (IST). usage: python3 truth3.py"""
import json, ast, datetime as D
IST = D.timezone(D.timedelta(hours=5, minutes=30))
inc = [i for i in json.load(open('inc_sweep4_heldout_after_end.json')) if str(i['injected']) != 'True']
rows = [json.loads(l) for l in open('sweep4_heldout_after.jsonl')]
def t(i): return int(i['created_sim'])
def L(x): return x if isinstance(x, list) else ast.literal_eval(x)
def dom(i): return L(i['roles'])
def win(now, kind, n=None):
    d = D.datetime.fromtimestamp(now, IST); today = d.replace(hour=0, minute=0, second=0, microsecond=0).timestamp()
    if kind == 'h': return now - n * 3600, now
    if kind == 'today': return today, today + 86400
    if kind == 'yday': return today - 86400, today
    if kind == 'week': return now - 7 * 86400, now
    if kind == 'month': return d.replace(day=1, hour=0, minute=0, second=0, microsecond=0).timestamp(), now
    if kind == 'yeve': return today - 86400 + 17 * 3600, today - 86400 + 22 * 3600
def sel(now, kind, n=None, domain=None, sev=None, **kw):
    a, b = win(now, kind, n)
    return [i for i in inc if a <= t(i) < b and (domain is None or domain in dom(i)) and (sev is None or i['severity'] in sev)]
R = {r['i']: r for r in rows}
def now(i): return R[i]['sim_time']
out = {}
for i in R: out[i] = {'sim_ist': D.datetime.fromtimestamp(now(i), IST).strftime('%a %d %b %H:%M')}
out[1]['last48h'] = len(sel(now(1), 'h', 48))
out[2]['hvac48h'] = len(sel(now(2), 'h', 48, 'hvac'))
out[3]['aq48h'] = len(sel(now(3), 'h', 48, 'air_quality'))
out[4]['aq48h_pending'] = len([i for i in sel(now(4), 'h', 48, 'air_quality') if i['workflow'] == 'needs_decision'])
out[5]['week_aq_water'] = (len(sel(now(5), 'week', domain='air_quality')), len(sel(now(5), 'week', domain='water')))
out[6]['pf_incidents_30d'] = [(i['id'], i['severity'], i['created_sim_ist'], i['workflow']) for i in inc if 'pf' in str(i['sensors']) and now(6) - 30 * 86400 <= t(i) < now(6)][-5:]
a, b = D.datetime(2026, 10, 20, tzinfo=IST).timestamp(), D.datetime(2026, 10, 26, tzinfo=IST).timestamp()
r13 = [i for i in inc if a <= t(i) < b]; out[13]['20-25oct'] = len(r13); out[14]['20-25oct_critical'] = len([i for i in r13 if i['severity'] == 'critical'])
out[26]['water_yday_evening_17_22'] = [(i['id'], i['created_sim_ist']) for i in sel(now(26), 'yeve', domain='water')]
out[26]['water_yday'] = len(sel(now(26), 'yday', domain='water'))
out[27]['latest3_critical'] = [i['id'] for i in sorted([i for i in inc if i['severity'] == 'critical' and t(i) <= now(27)], key=t)[-3:]]
out[28]['dismissed_month'] = len([i for i in sel(now(28), 'month') if i['approval'] == 'dismissed'])
out[29]['hvac_yday'] = len(sel(now(29), 'yday', domain='hvac'))
out[32]['today_yday'] = (len(sel(now(32), 'today')), len(sel(now(32), 'yday')))
from collections import Counter
c = Counter()
for i in inc:
    if now(39) - 30 * 86400 <= t(i) < now(39):
        for s in L(i['sensors']): c[s.split()[0]] += 1
out[39]['top_sensor_30d'] = c.most_common(2)
w = sel(now(40), 'week'); out[40]['week_fault_real'] = (len([i for i in w if i['severity'] == 'sensor_fault']), len([i for i in w if i['severity'] in ('critical', 'warning')]))
out[15]['needs_decision'] = len([i for i in inc if i['workflow'] == 'needs_decision'])
out[25]['SR-AC-KH02-24_30d'] = len([i for i in inc if 'SR-AC-KH02-24' in str(i['sensors']) and now(25) - 30 * 86400 <= t(i) < now(25)])
out[30]['tank_level_incidents'] = [(i['id'], i['severity'], i['created_sim_ist']) for i in inc if 'WM-WL' in str(i['sensors'])][-3:]
for k, v in out.items():
    if len(v) > 1: print(k, v)
json.dump(out, open('truth4.json', 'w'), indent=1)
