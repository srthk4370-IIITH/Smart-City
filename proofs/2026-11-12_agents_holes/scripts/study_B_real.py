"""Study B add-on: report accuracy of the 4B r3 on incidents whose agent findings came from REAL agent runs
(family real_agent:<model>), by agent model / root domain / gold severity. -> raw/B_real_agent_rows.json"""
import json, collections, sys
sys.path.insert(0, '2026-10-25_reasoner_final/eval')
import score_v3 as S
F = {'rwh': '2026-10-25_reasoner_final/data/incidents_rwh.jsonl', 'rwh2': '2026-10-29_rsn_v3/kaggle/build/r1/heldout/incidents_rwh2.jsonl',
     'dev': '2026-10-25_reasoner_final/data/incidents_dev.jsonl', 'test_r2': '2026-11-06_4b_local/data/final/incidents_test_r2.jsonl'}
c = collections.defaultdict(collections.Counter)
for s, f in F.items():
    rows = {json.loads(l)['id']: json.loads(l) for l in open(f, encoding='utf-8')}
    for l in open(f'2026-10-25_reasoner_final/eval/results/rsn_v3_4b_r3/{s}.jsonl', encoding='utf-8'):
        rec = json.loads(l); r = rows.get(rec['id'])
        if not r or not r['family'].startswith('real_agent'): continue
        r['meta'].setdefault('checks', [])
        o = S.score_incident(r, rec)
        for k in ('ALL', r['meta']['root_role'] + '|gold=' + r['meta']['severity'], r['family'].split('+')[0] + '|' + r['meta']['root_role'] + '|gold=' + r['meta']['severity']):
            c[k]['n'] += 1; c[k]['label_ok'] += o.get('label', 0) >= 1; c[k]['sev_ok'] += o.get('severity', 0) >= 1
            c[k]['agent_wrong(gold checks)'] += bool(r['meta']['checks'])
            c[k]['agent_wrong_and_report_wrong'] += bool(r['meta']['checks']) and o.get('severity', 0) < 1
out = {k: dict(v) for k, v in sorted(c.items())}
json.dump(out, open('2026-11-12_agents_holes/raw/B_real_agent_rows.json', 'w'), indent=1)
for k, v in out.items():
    if '|' not in k or k.count('|') == 1: print(k, v)
