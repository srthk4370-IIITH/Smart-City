import json, sys
from collections import Counter
for p in sys.argv[1:]:
    try:
        n=0; keys=Counter(); src=Counter(); fam=Counter()
        with open(p) as f:
            for l in f:
                r=json.loads(l); n+=1
                if n<=200: keys.update(r.keys())
                src[str(r.get('source', r.get('synthetic')))[:40]]+=1
                fam[str(r.get('family'))]+=1
        print(p.split('smartcity_runs/')[-1], n, 'src', dict(src.most_common(8)), 'fam', dict(fam.most_common(6)))
        print('   keys', sorted(keys)[:40])
    except Exception as e: print(p, 'ERR', e)
