import json, sys, copy, os
sys.path.insert(0, '/mnt/c/Users/hp/Desktop/qidk/proofs/2026-11-17_agt_topup_v2')
import checks_v2 as C
K = os.path.expanduser('~/smartcity_runs/agt_topup_k2/dry_run')
rows = [json.loads(l) for l in open(K + '/mixdata/train.jsonl')]
full = K + '/gen/new_full.jsonl'
hold = [K + '/local/' + n for n in ('val_sel.jsonl', 'syn_slice.jsonl', 'unseen100.jsonl', 'tool_t1.jsonl', 'tool_t2.jsonl', 'hard_val.jsonl')]
def run(name, rs):
    p = '/tmp/neg_train.jsonl'
    with open(p, 'w') as f:
        for r in rs: f.write(json.dumps(r) + '\n')
    import io, contextlib
    buf = io.StringIO()
    with contextlib.redirect_stdout(buf):
        rep = C.run(p, K + '/mixdata/gendev.jsonl', full, K + '/local', None, hold)
    print('%-28s pass=%s %s' % (name, rep['pass'], [f[:70] for f in rep['fails'][:2]]))
run('baseline', rows)
calls = [r for r in rows if r['completion'].startswith('{"tool"') and r['prompt'].count('<|start_header_id|>assistant') == 1]
run('drop parent call turn', [r for r in rows if r is not calls[0]])
bad = copy.deepcopy(rows); i = next(j for j, r in enumerate(bad) if r.get('turn') == 'final'); bad[i]['completion'] = bad[i]['completion'].replace('"status": "', '"status": "bogus_', 1)
run('bad status enum', bad)
bad = copy.deepcopy(rows); i = next(j for j, r in enumerate(bad) if r['completion'].startswith('{"tool"')); bad[i]['completion'] = '{"tool": "get_weather", "args": {}}<|eot_id|>'
run('unknown tool', bad)
bad = copy.deepcopy(rows); bad[5]['prompt'] = bad[5]['prompt'].replace('EVIDENCE:', 'EVIDENCE:\n' + 'E1 padding line to overflow the context ' * 40, 1)
run('token overflow', bad)
bad = copy.deepcopy(rows); v = [json.loads(l) for l in open(K + '/local/val_sel.jsonl')][0]; bad.append(dict(rows[0], id='leak1', prompt=v['prompt'], completion=v['completion']))
run('val prompt leaked', bad)
bad = copy.deepcopy(rows); i = next(j for j, r in enumerate(bad) if r.get('turn') == 'final' and bad[j]['prompt'].count('get_history') > 0); bad[i]['prompt'] = bad[i]['prompt'].replace('HISTORY 12 h', 'HISTORY 6 h').replace('HISTORY 6 h', 'HISTORY 3 h', 1)
run('result hours mismatch', bad)
