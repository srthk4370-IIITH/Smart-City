import json, sys, random
from transformers import AutoTokenizer
tok = AutoTokenizer.from_pretrained(sys.argv[2])
rows = [json.loads(l) for l in open(sys.argv[1] + '/data/train_mix.jsonl', encoding='utf-8')]
inc = [r for r in rows if r.get('tools') == 'incident']; random.seed(0); inc = random.sample(inc, 300)
F = S = T = 0; ex = None
for r in inc:
    fin = r['messages'][-1]['content']; ex = ex or fin
    o = json.loads(fin)
    def sk(v):
        if isinstance(v, dict): return {k: sk(x) for k, x in v.items()}
        if isinstance(v, list): return [sk(x) for x in v[:1]] if v else []
        return ''
    n = len(tok(fin)['input_ids']); F += n
    S += len(tok(json.dumps(sk(o), ensure_ascii=False, separators=(',', ':')))['input_ids'])
    T += len(tok(o.get('title', ''))['input_ids'])
print('mean final', F / 300, 'top-level-key skeleton', S / 300, 'title', T / 300)
print(ex[:300])
