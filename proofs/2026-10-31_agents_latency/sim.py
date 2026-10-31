# Offline replay of htpd's batched verified drafting (run_batch, HTPD_DRAFT) on real app agent requests.
# Acceptance = draft token == the token the model actually produced (greedy), so steps are exact for the
# current proposer (up to tokenization at the prompt/generation boundary). Variants change the proposer.
import json,sys,collections
reqs=[[x for x in r if len(x["gen"])>=2] for r in json.load(open(sys.argv[1]))]; reqs=[r for r in reqs if r]
def run(kmax=8, recent_cap=64, ngs=(3,2,1), corpus=None, rows=32, single_k=None, R=None, seed=()):
    global reqs
    R0=reqs
    if R is not None: reqs=R
    recent=collections.deque(maxlen=recent_cap)
    for sq in seed: recent.append(sq)
    tot_steps=0; tot_tok=0; per=[]
    for r in reqs:
        n=len(r)
        # merged index of recent outputs: most recent occurrence wins
        ridx={}
        for seq in list(recent)+([] if corpus is None else []):
            pass
        ridx={}
        for seq in recent:  # oldest -> newest, later overwrite = most recent wins (deque oldest first)
            for ng in ngs:
                for p in range(len(seq)-ng):
                    ridx[(ng,)+tuple(seq[p:p+ng])]=seq[p+ng]
        hist=[list(x['prompt']) + [x['gen'][0]] for x in r]   # prefill emits gen[0]
        gen0=[len(h)-1 for h in hist]
        tgt=[x['gen'] for x in r]
        done=[len(t)<=1 for t in tgt]
        pos=[1]*n   # tokens of gen emitted
        # own-hist index: continuation index <= L-2
        own=[{} for _ in range(n)]
        def own_reg(s, upto):
            h=hist[s]
            for c in range(own_reg.last[s]+1, upto+1):
                for ng in ngs:
                    if c-ng>=0: own[s][(ng,)+tuple(h[c-ng:c])]=h[c]
            own_reg.last[s]=max(own_reg.last[s],upto)
        own_reg.last=[-1]*n
        for s in range(n): own_reg(s, len(hist[s])-2)
        oidx=[{} for _ in range(n)]; olast=[gen0[s]-1 for s in range(n)]
        def oth_reg(o):
            h=hist[o]
            for c in range(max(olast[o]+1,gen0[o]), len(h)):
                for ng in ngs:
                    if c-ng>=gen0[o]: oidx[o][(ng,)+tuple(h[c-ng:c])]=h[c]
            olast[o]=len(h)-1
        steps=0
        while not all(done):
            act=[s for s in range(n) if not done[s]]
            lo,hi=min(act),max(act); nrun=hi-lo+1
            k=max(1,min(kmax, rows//max(1,nrun)-1))
            if single_k and nrun==1: k=single_k
            for o in range(n): oth_reg(o)
            props={}
            for s in act:
                h=hist[s]; L0=len(h); d=[]
                for j in range(k):
                    t=-1
                    for ng in ngs:
                        if len(h)<ng+1: continue
                        key=(ng,)+tuple(h[-ng:])
                        for o in range(n):
                            if o!=s and key in oidx[o]: t=oidx[o][key]; break
                        if t>=0: break
                        if key in ridx: t=ridx[key]; break
                        # own history: temp tail first (highest p), then committed index
                        for p in range(len(h)-ng-2, L0-ng-2, -1):
                            if p>=0 and h[p:p+ng]==list(key[1:]): t=h[p+ng]; break
                        if t>=0: break
                        if key in own[s]: t=own[s][key]; break
                        if corpus is not None and key in corpus: t=corpus[key]; break
                    if t<0: break
                    d.append(t); h.append(t)
                del h[L0:]
                props[s]=d
            steps+=1
            for s in act:
                d=props[s]; g=tgt[s]
                j=0
                while True:
                    t=g[pos[s]]; hist[s].append(t); pos[s]+=1
                    if pos[s]>=len(g): done[s]=True; break
                    if j<len(d) and d[j]==t: j+=1; continue
                    break
                own_reg(s, len(hist[s])-2)
        for s in range(n): recent.append(hist[s][gen0[s]:])
        tot_steps+=steps; tot_tok+=sum(len(t) for t in tgt); per.append((n,steps,sum(len(t) for t in tgt)))
    reqs=R0
    return tot_steps,tot_tok,per
import statistics as S
def show(name,res):
    st,tk,per=res
    one=[p[1] for p in per if p[0]==1]; two=[p[1] for p in per if p[0]==2]; big=[p[1] for p in per if p[0]>=8]
    print(f"{name:34s} steps {st:6d} tok {tk} tok/step {tk/st:.2f} | 1-agent mean steps {S.mean(one):.1f} (n={len(one)}) | 2-agent {S.mean(two) if two else 0:.1f} | 8+ {S.mean(big) if big else 0:.1f}", flush=True)
    return per
V=sys.argv[2].split(',') if len(sys.argv)>2 else ['cur']
for v in V:
    if v=='cur': show('cur (K8, recent 64, ng 3..1)',run())
    if v=='rec3000': show('recent 3000',run(recent_cap=3000))
    if v=='ng6': show('ng 6..1',run(ngs=(6,5,4,3,2,1)))
    if v=='ng6r': show('ng 6..1 + recent 3000',run(ngs=(6,5,4,3,2,1),recent_cap=3000))
    if v=='k16': show('single-stream k16',run(single_k=16))
    if v=='k16r': show('single k16 + recent 3000 + ng6',run(single_k=16,recent_cap=3000,ngs=(6,5,4,3,2,1)))
    if v=='k12': show('single-stream k12',run(single_k=12))
    if v=='rec0': show('no recent (fresh process)',run(recent_cap=1))
    if v=='ng6r500': show('ng 6..1 + recent 500',run(ngs=(6,5,4,3,2,1),recent_cap=500))
    if v=='ng6r1000': show('ng 6..1 + recent 1000',run(ngs=(6,5,4,3,2,1),recent_cap=1000))
    if v=='ng4r1000': show('ng 4..1 + recent 1000',run(ngs=(4,3,2,1),recent_cap=1000))
    if v=='ng8r1000': show('ng 8..1 + recent 1000',run(ngs=(8,7,6,5,4,3,2,1),recent_cap=1000))
    if v.startswith('lab'):
        allr=json.load(open(sys.argv[1])); idx=[i for i,r in enumerate(allr) if len(r)<=2][-24:]
        LR=[[x for x in allr[i] if len(x['gen'])>=2] for i in idx]
        seed=[x['gen'] for r in allr[:idx[0]] for x in r if len(x['gen'])>=2]
        per=show('lab base (fresh v9d)',run(R=LR)); print('  per-req steps',[p[1] for p in per])
        per=show('lab v9e ng8 r500 + corpus',run(R=LR,ngs=(8,7,6,5,4,3,2,1),recent_cap=500,seed=seed[-500:])); print('  per-req steps',[p[1] for p in per])
