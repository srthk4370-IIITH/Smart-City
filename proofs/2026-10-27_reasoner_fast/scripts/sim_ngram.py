"""Offline n-gram (prompt lookup) acceptance simulation on real greedy outputs (board llama-server base runs + gold).
Steps = decode calls needed when every step verifies an n-gram draft of up to K tokens (accepted prefix + 1 model token)."""
import json, sys
from tokenizers import Tokenizer
tk = Tokenizer.from_file(sys.argv[1])
P = [json.loads(l) for l in open(sys.argv[2], encoding="utf-8")]
outs = sys.argv[3:]
def draft(h, K, nmin, nmax):
    L = len(h)
    for nn in range(nmax, nmin - 1, -1):
        if L < nn + 1: continue
        tail = h[L - nn:]
        for i in range(L - nn - 1, -1, -1):
            if h[i:i + nn] == tail:
                d = h[i + nn:i + nn + K]
                if d: return d
    return []
COST = {1: 67, 2: 80, 3: 111, 4: 135, 5: 120, 6: 109, 7: 110, 8: 110, 9: 112, 10: 114, 11: 116, 12: 117, 13: 118, 14: 119, 15: 120, 16: 121, 17: 122}
for K, nmin, nmax in [(1, 1, 4), (1, 2, 4), (1, 3, 6), (2, 2, 4), (2, 3, 6), (8, 2, 4), (16, 3, 6)]:
    tot_tok = tot_steps = 0; ms_base = ms_spec = 0
    for i, o in enumerate(outs):
        prompt = tk.encode(P[i]["prompt"], add_special_tokens=False).ids
        gen = tk.encode(json.load(open(o, encoding="utf-8"))["content"], add_special_tokens=False).ids
        h = list(prompt); t = 0; steps = 0
        while t < len(gen):
            d = draft(h, K, nmin, nmax)
            a = 0
            while a < len(d) and t + a < len(gen) and d[a] == gen[t + a]: a += 1
            n = min(a + 1, len(gen) - t)
            h += gen[t:t + n]; t += n; steps += 1
            ms_spec += COST[min(17, 1 + len(d))]
        tot_tok += len(gen); tot_steps += steps; ms_base += len(gen) * COST[1]
    print(f"K={K} n={nmin}-{nmax}: {tot_tok} tokens in {tot_steps} steps ({tot_tok/tot_steps:.2f} tok/step); est decode {ms_spec/1000:.1f}s vs plain {ms_base/1000:.1f}s")
