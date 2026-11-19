# calib.py: the cost table projects 1.53x less than the board's measured in-loop decode. Two calibrations:
# multiplicative (x ratio) and additive (table + c ms per step, c fitted on the 28 logged reports).
import json
D = '/mnt/c/Users/hp/Desktop/qidk/proofs/2026-10-30_spec_split'
ck = json.load(open(D + '/check_board_vs_proj.json'))
c = sum(o['board_decode_s'] - o['proj_s'] for o in ck['rows']) / sum(o['board_steps'] for o in ck['rows'])
print('additive overhead c = %.1f ms/step, ratio %.3f' % (1000 * c, ck['ratio']))
out = ['| config | table s | x%.2f s | table + %.0f ms/step s | vs base (additive) |' % (ck['ratio'], 1000 * c), '|---|---|---|---|---|']
res = {}
for tag in ['', '_genonly', '_boardonly', '_norwh']:
    R = json.load(open(D + '/sim_results%s.json' % tag))
    n = len(R['reports'])
    def m(cfg, f): return sum(f(r['cfg'][cfg]) for r in R['reports']) / n
    b_add = m('none_K0_m1', lambda x: x['ms'] / 1000 + c * x['steps'])
    for cfg in ['none_K0_m1', 'P_K4_m3', 'P_K6_m3', 'C_K8_m2', 'PC_K6_m2', 'PC_K8_m2', 'PC_K8_m3']:
        t = m(cfg, lambda x: x['ms'] / 1000); a = m(cfg, lambda x: x['ms'] / 1000 + c * x['steps'])
        res[tag + ':' + cfg] = dict(table_s=t, mult_s=t * ck['ratio'], add_s=a, add_vs_base=a / b_add - 1)
        out.append('| %s%s | %.2f | %.2f | %.2f | %+.1f%% |' % (cfg, (' [' + tag[1:] + ']') if tag else '', t, t * ck['ratio'], a, 100 * (a / b_add - 1)))
open(D + '/calib.md', 'w').write('\n'.join(out) + '\n')
json.dump(dict(c_ms=1000 * c, ratio=ck['ratio'], res=res), open(D + '/calib.json', 'w'), indent=1)
print('\n'.join(out))
