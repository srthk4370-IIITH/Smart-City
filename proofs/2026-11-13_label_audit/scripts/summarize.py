"""Numbers for AUDIT.md: unsupported rows by file/role/kind, unique windows, r3-2800 rescored on cleaned golds."""
import json, collections, re
P = '/mnt/c/Users/hp/Desktop/qidk/proofs/'
O = P + '2026-11-13_label_audit/'
A = [json.loads(l) for l in open(O + 'audit.jsonl')]
S = {}
for name in ('r3_train', 'test_r2', 'rwh', 'rwh2', 'dev', 'dev_r3', 'dev60', 'r1_train', 'r4_replay'):
    rows = [a for a in A if a['file'] == name]
    un = [a for a in rows if a['supported'] == 'n']
    S[name] = {'rows': len(rows), 'unsupported': len(un),
               'unsupported_by_gold': dict(collections.Counter(a['gold'] for a in un)),
               'gold_counts': dict(collections.Counter(a['gold'] for a in rows)),
               'unsupported_windows': len({a['pool_id'] or a['id'] for a in un}),
               'fault_rows_windows': len({a['pool_id'] or a['id'] for a in rows if a['gold'] == 'sensor_fault'}),
               'unsupported_fault_by_role_kind': dict(collections.Counter('%s/%s/%s' % (a['role'], a['metric'], a['fault_kind']) for a in un if a['gold'] == 'sensor_fault').most_common()),
               'unsupported_fault_agent_status': dict(collections.Counter(a['agent_status'] for a in un if a['gold'] == 'sensor_fault')),
               'unsupported_nonfault_reasons': dict(collections.Counter(re.sub(r'[-+]?\d[\d.]*', '#', a['reason'])[:80] for a in un if a['gold'] != 'sensor_fault').most_common(8))}
# test_r2 sensor_fault windows
tf = [a for a in A if a['file'] == 'test_r2' and a['gold'] == 'sensor_fault']
S['test_r2_fault_windows'] = dict(collections.Counter('%s %s %s %s' % (a['node'], a['metric'], a['fault_kind'], a['supported']) for a in tf).most_common())
# r3-2800 rescored on suites (raw outputs of the gate_r3 runs)
FILES = {'rwh': 'rwh', 'rwh2': 'rwh2', 'dev': 'dev', 'test_r2': 'test_r2'}
res = {}
for s in FILES:
    out = {}
    for l in open(P + '2026-10-25_reasoner_final/eval/results/rsn_v3_4b_r3/%s.jsonl' % s, encoding='utf-8'):
        r = json.loads(l)
        try:
            c = r['final']['content']; i = c.find('{'); out[r['id']] = json.JSONDecoder().raw_decode(c[i:])[0].get('severity')
        except Exception:
            out[r['id']] = None
    rows = [a for a in A if a['file'] == s]
    c = collections.Counter()
    for a in rows:
        p = out.get(a['id'])
        if a['id'] not in out:
            continue
        c['n'] += 1
        c['sev_ok_orig'] += p == a['gold']
        new = a['gold']
        if a['supported'] == 'n':
            new = 'normal' if (a['gold'] == 'sensor_fault' and a['agent_status'] == 'normal') else ('sensor_fault' if a['gold'] == 'normal' else None)
        if new is None:
            c['dropped'] += 1; continue
        c['n_clean'] += 1; c['sev_ok_clean'] += p == new
    res[s] = dict(c)
S['r3_rescored'] = res
json.dump(S, open(O + 'summary_numbers.json', 'w'), indent=1)
print(json.dumps(S, indent=1)[:6000])
