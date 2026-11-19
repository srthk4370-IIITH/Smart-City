import sys, json, time, traceback, collections
sys.path.insert(0, '/mnt/c/Users/hp/Desktop/qidk/proofs/2026-11-17_agt_topup_v2')
import gen_tools as GT
from tokenizers import Tokenizer
tk = Tokenizer.from_file('/home/hp_srthk4370/models/llama-3.2-3b-instruct/tokenizer.json')
name = sys.argv[1]; tries = int(sys.argv[2]); show = int(sys.argv[3])
T = GT.GA.Task('train', 'ex_event', 0, 100, 9)
ok = 0; fit = 0; errs = collections.Counter(); shown = 0; mx = []
for i in range(tries):
    try:
        r = GT.SC[name][0](T)
    except Exception as e:
        errs[repr(e)[:100]] += 1
        if sum(errs.values()) < 2: traceback.print_exc()
        continue
    if not r: continue
    rows, meta = r
    ok += 1
    L = [len(tk.encode(x['prompt'], add_special_tokens=False).ids) for x in rows]
    mx.append(max(L))
    if max(L) <= 904: fit += 1
    if shown < show and max(L) <= 904:
        shown += 1
        for x, l in zip(rows, L):
            print('=====', x['turn'], x['tool_kind'], 'tokens', l)
            if x['turn'] == 'call' and x is not rows[0]: pass
        print(rows[-1]['prompt'].split('<|start_header_id|>user<|end_header_id|>\n\n', 1)[1].replace('<|eot_id|>', '<EOT>'))
        for x in rows: print('COMPLETION', x['turn'], x['completion'])
mx.sort()
print(name, 'ok', ok, 'fit904', fit, 'of', tries, 'max-tok med', mx[len(mx)//2] if mx else None, dict(errs))
