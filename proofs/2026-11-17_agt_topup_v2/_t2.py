import sys, json, time, traceback, collections
sys.path.insert(0, '/mnt/c/Users/hp/Desktop/qidk/proofs/2026-11-17_agt_topup_v2')
import gen_v2 as G
from tokenizers import Tokenizer
tk = Tokenizer.from_file('/home/hp_srthk4370/models/llama-3.2-3b-instruct/tokenizer.json')
fams = sys.argv[1].split(',')
tries = int(sys.argv[2])
show = int(sys.argv[3]) if len(sys.argv) > 3 else 1
for f in fams:
    T = G.GA.Task('train', 'ex_event', 0, 100, 5)
    ok = 0; errs = collections.Counter(); toks = []; t = time.time(); stats = collections.Counter()
    shown = 0
    for i in range(tries):
        try:
            r = G.FAMS[f](T)
        except Exception as e:
            errs[repr(e)[:90]] += 1
            if sum(errs.values()) < 2: traceback.print_exc()
            continue
        if not r: continue
        ok += 1
        L = len(tk.encode(r['prompt'], add_special_tokens=False).ids)
        toks.append(L)
        stats[(r['gold']['pattern'], r['gold']['status'])] += 1
        if shown < show:
            shown += 1
            print('-----', f, r['n'], r['family'], r['sub'], L, 'tok')
            print(r['prompt'].split('<|start_header_id|>user<|end_header_id|>\n\n')[1][:1800].replace('<|eot_id|>', ''))
            print('GOLD', r['completion'])
    toks.sort()
    print('==', f, 'ok', ok, '/', tries, 'sec %.1f' % (time.time() - t), 'tok med', toks[len(toks) // 2] if toks else None, '>904', sum(x > 904 for x in toks), dict(errs))
    print('   ', stats.most_common(8))
