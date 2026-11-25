p='build/build_big.py'; s=open(p,encoding='utf-8').read()
old='    R.shuffle(new)\n    R.shuffle(A)\n    n_new, n_rep = wr(OUT + "/train_new.jsonl", new), wr(OUT + "/replay.jsonl", A)'
new='''    R.shuffle(new)
    R.shuffle(A)
    wr(OUT + "/pool_train_new.jsonl", new)
    wr(OUT + "/pool_replay.jsonl", A)

    def bal(rows, n, key):   # equal quota per key (families/blocks), leftovers redistributed: every family stays represented
        g = collections.defaultdict(list)
        for r in rows:
            g[key(r)].append(r)
        out, ks = [], sorted(g)
        while len(out) < n and any(g.values()):
            q = max(1, (n - len(out)) // max(1, sum(1 for k in ks if g[k])))
            for k in ks:
                take, g[k] = g[k][:q], g[k][q:]
                out += take
                if len(out) >= n:
                    break
        return out[:n]
    NEW_N = int(os.environ.get("SEL_NEW", 2500)); REP_N = int(os.environ.get("SEL_REP", 1500))   # owner 2026-11-20: ~4k rows seen, ~37.5 % replay
    nd = [r for r in new if not r.get("dup_of")]
    Bs = [r for r in nd if r["big"] == "B"]; Cs = [r for r in nd if r["big"] == "C"]; Ds = [r for r in nd if r["big"] == "D"]
    Ct = [r for r in Cs if r["kind"].startswith(TOOL_PREFIX)]; Co = [r for r in Cs if not r["kind"].startswith(TOOL_PREFIX)]
    sel = (bal(Bs, int(NEW_N * .30), lambda r: r["block"]) + bal(Ct, int(NEW_N * .27), lambda r: r["kind"]) + bal(Co, int(NEW_N * .08), lambda r: r["kind"])
           + bal(Ds, NEW_N - int(NEW_N * .30) - int(NEW_N * .27) - int(NEW_N * .08), lambda r: r.get("family", "").split(":")[-1][:12]))
    rsel = bal(A, REP_N, lambda r: r.get("block", r.get("tools")))
    R.shuffle(sel); R.shuffle(rsel)
    new, A = sel, rsel
    n_new, n_rep = wr(OUT + "/train_new.jsonl", new), wr(OUT + "/replay.jsonl", A)'''
assert old in s; s=s.replace(old,new); open(p,'w',encoding='utf-8').write(s)
p='build/plan_big.py'; s=open(p,encoding='utf-8').read()
s=s.replace('steps = int(TRAIN_H * 3600 * TOK_S / tps)\nepochs = round(steps * k_new / nn, 4)','steps = min(int(TRAIN_H * 3600 * TOK_S / tps), math.ceil(nn / k_new))\nepochs = round(min(1.0, steps * k_new / nn), 4)')
s=s.replace('IS the sampling weight.','IS the sampling weight; the files are already the prioritised selection (build_big assemble: B 30 %, tool-critical chat 27 %, other chat 8 %, agent rows 35 %; replay balanced over every block), full pools in pool_*.jsonl.')
open(p,'w',encoding='utf-8').write(s)
