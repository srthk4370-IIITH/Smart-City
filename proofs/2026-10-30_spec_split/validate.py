# validate.py: check the reconstruction against htpd's own per-stream counts in the board logs.
import json, sys
sys.path.insert(0, '/mnt/c/Users/hp/Desktop/qidk/proofs/2026-10-30_spec_split')
from recon import Tok, split_streams
from data import eval_reports, load_req

tok = Tok()
rows = []
for r in eval_reports():
    req = load_req(r['q'])
    ss = split_streams(tok, req['schema'], r['text'])
    if ss is None:
        print(r['file'], 'NO SPLIT KEYS'); continue
    fork = [s['fork'] for s in ss]
    head_picks = sum(ss[0]['pick'][:fork[0] + 1])
    cont = [sum(s['pick'][s['fork'] + 1:]) for s in ss]
    steps = head_picks - 1 + max(cont)
    rec = dict(file=r['file'], q=r['q'], split=fork[0],
               streams=[(len(s['toks']), sum(1 for x in s['pick'] if not x)) for s in ss],
               steps=steps, mism=[s['mism'] for s in ss], stop=[s['stop'] for s in ss],
               tot_tokens=fork[0] + sum(len(s['toks']) - fork[0] for s in ss),
               resp_tokens=r['tokens'], resp_forced=r['forced'])
    lg = r['log']
    if lg:
        rec['log'] = dict(split=lg['split'], streams=[lg['streams'][i] for i in sorted(lg['streams'])], steps=lg['steps'])
    print(json.dumps(rec))
    rows.append(rec)
json.dump(rows, open('/mnt/c/Users/hp/Desktop/qidk/proofs/2026-10-30_spec_split/validate.json', 'w'), indent=1)
