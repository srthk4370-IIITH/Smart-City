import sys, collections, re
sys.path.insert(0, sys.argv[1])
from gguf import GGUFReader
r = GGUFReader(sys.argv[2])
for k, f in r.fields.items():
    if k.startswith('tokenizer.ggml.') and k not in ('tokenizer.ggml.model','tokenizer.ggml.pre','tokenizer.ggml.eos_token_id','tokenizer.ggml.bos_token_id','tokenizer.ggml.padding_token_id'): continue
    if k == 'tokenizer.chat_template': print(k, 'len', len(bytes(f.parts[-1]))); continue
    try: v = f.contents()
    except Exception: v = '?'
    print(k, '=', v)
pat = collections.Counter(); types = collections.Counter()
for t in r.tensors:
    pat[re.sub(r'blk\.\d+\.', 'blk.N.', t.name)] += 1
    types[(re.sub(r'blk\.\d+\.', 'blk.N.', t.name), t.tensor_type.name)] += 1
print('n_tensors', len(r.tensors))
for (n, ty), c in sorted(types.items()): print(c, n, ty)
