# checks.py: (1) corpus replay failures by source, (2) projected vs board-measured decode time of the baseline
import json, re, collections, sys
sys.path.insert(0, '/mnt/c/Users/hp/Desktop/qidk/proofs/2026-10-30_spec_split')
from data import eval_reports
D = '/mnt/c/Users/hp/Desktop/qidk/proofs/2026-10-30_spec_split'
c = json.load(open(D + '/corpus_tokens.json'))
print('replay ok by src', dict(collections.Counter((d['src'], d['ok']) for d in c)))
# board ms/step from the logs
L = '/mnt/c/Users/hp/Desktop/qidk/proofs/2026-10-29_latency'
def prof(path):
    return [(int(m.group(1)), float(m.group(2)), float(m.group(3))) for m in re.finditer(r'reason step profile: (\d+) steps, rows ([\d.]+)/step \(max \d+\); ms/step build [\d.]+ decode ([\d.]+)', open(path, errors='replace').read())]
R = json.load(open(D + '/sim_results.json'))
proj = {}
for r in R['reports']:
    for f in r['files']: proj[f.split('/')[-1]] = r['cfg']['none_K0_m1']
out = []
for cfg, d, lg, nq in [('base', 'rp29_ab', 'htpd_base.log', 7), ('rb29', 'rp29_ab', 'htpd_rb29.log', 7), ('rp29', 'rp29_ab', 'htpd_rp29.log', 7), ('4b', 'q2b_ab', 'htpd_4b.log', 7)]:
    ps = prof(f'{L}/{d}/{lg}')[-nq:]
    files = sorted([e['file'].split('/')[-1] for e in eval_reports() if e['cfg'] == cfg], key=lambda f: int(re.search(r'_(\d+)\.json$', f).group(1)))
    for f, (st, rows, ms) in zip(files, ps):
        p = proj[f]
        out.append(dict(file=f, board_steps=st, board_rows=rows, board_decode_s=st * ms / 1000, sim_steps=p['steps'], sim_rows=round(p['rows_mean'], 2), proj_s=round(p['ms'] / 1000, 2)))
for o in out: print(o)
rat = sum(o['board_decode_s'] for o in out) / sum(o['proj_s'] for o in out)
print('board/projected decode time ratio %.3f' % rat)
json.dump(dict(rows=out, ratio=rat), open(D + '/check_board_vs_proj.json', 'w'), indent=1)
