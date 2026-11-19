import json, sys
from collections import Counter
for p in sys.argv[1:]:
    rs=[json.loads(l) for l in open(p)]
    c=Counter((r.get('split'),str(r.get('seen'))) for r in rs)
    nodes=Counter(r.get('node') for r in rs)
    print(p.split('/')[-1], len(rs), 'split/seen', dict(c.most_common(6)), 'nodes', len(nodes))
    r=rs[0]; print('   id', r['id'], 'd', r.get('d'), 'end', r.get('end_epoch'), 'n', r.get('n'), 'hist_len', r.get('hist_len'), 'node', r.get('node'), 'sub', r.get('sub'), 'src', r.get('source'), r.get('evalset'))
    ds=sorted(set(str(r.get('d')) for r in rs)); print('   d', len(ds), ds[:3], ds[-3:])
