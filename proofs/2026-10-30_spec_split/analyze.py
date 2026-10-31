# analyze.py: tables from sim_results.json -> tables.md (pasted into SIM.md) + summary json
import json, collections
D = '/mnt/c/Users/hp/Desktop/qidk/proofs/2026-10-30_spec_split'
import sys
TAG = sys.argv[1] if len(sys.argv) > 1 else ''
R = json.load(open(D + '/sim_results%s.json' % TAG))
reps = R['reports']
n = len(reps)


def mean(xs): return sum(xs) / len(xs)


base = {i: r['cfg']['none_K0_m1'] for i, r in enumerate(reps)}
rows = []
for c in R['configs']:
    v = [r['cfg'][c] for r in reps]
    st = mean([x['steps'] for x in v]); ms = mean([x['ms'] for x in v])
    dr = sum(x['drafted'] for x in v); kp = sum(x['kept'] for x in v)
    ds = sum(x['draft_steps'] for x in v); pa = sum(x['partial'] for x in v)
    gs = sum(x['steps'] for x in v); gp = sum(x['global_partial'] for x in v)
    rows.append(dict(cfg=c, steps=st, s=ms / 1000, rows=mean([x['rows_mean'] for x in v]), rows_max=max(x['rows_max'] for x in v),
                     acc=kp / dr if dr else 0, drafted=dr / n, kept=kp / n,
                     d_steps=mean([(x['steps'] - base[i]['steps']) / base[i]['steps'] for i, x in enumerate(v)]),
                     d_ms=mean([(x['ms'] - base[i]['ms']) / base[i]['ms'] for i, x in enumerate(v)]),
                     partial_of_draft_steps=pa / ds if ds else 0, global_partial=gp / gs))
best = min(rows[1:], key=lambda x: x['s'])
beststeps = min(rows[1:], key=lambda x: x['steps'])
out = []
b = rows[0]
out.append('Baseline (no drafts), mean of %d unique reports: %.1f steps, %.2f s projected decode, %.2f rows/step\n' % (n, b['steps'], b['s'], b['rows']))
out.append('| config | steps | decode s | rows/step | max rows | drafted/rep | kept/rep | accept | steps vs base | decode vs base | partial-reject (of drafted stream-steps) | global steps needing restore |')
out.append('|---|---|---|---|---|---|---|---|---|---|---|---|')
for x in rows:
    out.append('| %s | %.1f | %.2f | %.2f | %d | %.0f | %.0f | %.1f%% | %+.1f%% | %+.1f%% | %.1f%% | %.1f%% |' % (
        x['cfg'], x['steps'], x['s'], x['rows'], x['rows_max'], x['drafted'], x['kept'], 100 * x['acc'],
        100 * x['d_steps'], 100 * x['d_ms'], 100 * x['partial_of_draft_steps'], 100 * x['global_partial']))
out.append('')
out.append('Lowest projected decode: %s (%.2f s, %+.1f%%); fewest steps: %s (%.1f steps, %+.1f%%)' % (
    best['cfg'], best['s'], 100 * best['d_ms'], beststeps['cfg'], beststeps['steps'], 100 * beststeps['d_steps']))
out.append('')
# per report for baseline and best
out.append('Per report (baseline vs %s vs %s):\n' % (best['cfg'], beststeps['cfg']))
out.append('| q | files | base steps | base s | all-sampled steps | best-ms steps | best-ms s | accept | partial | fewest-steps steps | its s |')
out.append('|---|---|---|---|---|---|---|---|---|---|---|')
for r in reps:
    b0 = r['cfg']['none_K0_m1']; x = r['cfg'][best['cfg']]; y = r['cfg'][beststeps['cfg']]
    out.append('| q%d | %s | %d | %.2f | %d | %d | %.2f | %.0f%% | %d/%d | %d | %.2f |' % (
        r['q'], ', '.join(f.split('/')[-1] for f in r['files']), b0['steps'], b0['ms'] / 1000, r['all_sampled_steps'],
        x['steps'], x['ms'] / 1000, 100 * x['kept'] / max(1, x['drafted']), x['partial'], x['draft_steps'],
        y['steps'], y['ms'] / 1000))
open(D + '/tables%s.md' % TAG, 'w').write('\n'.join(out) + '\n')
json.dump(dict(rows=rows, best_ms=best, best_steps=beststeps), open(D + '/summary%s.json' % TAG, 'w'), indent=1)
print('\n'.join(out[:3])); print(out[-len(reps) - 4])
for x in sorted(rows, key=lambda x: x['s'])[:12]: print(x['cfg'], round(x['steps'], 1), round(x['s'], 2), round(100 * x['d_ms'], 1), round(100 * x['acc'], 1), round(100 * x['partial_of_draft_steps'], 1), round(x['rows'], 2))
