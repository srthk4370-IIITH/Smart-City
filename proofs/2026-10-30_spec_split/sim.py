# sim.py: offline simulation of speculative drafting inside htpd's split-3 reasoner decode.
# Uses the per-stream token sequences rebuilt by recon.py (validated against the board htpd logs: split point,
# per-stream tokens, forced tokens and decode steps match exactly for all 28 logged reports, validate.json).
import json, sys, os, collections, time
sys.path.insert(0, '/mnt/c/Users/hp/Desktop/qidk/proofs/2026-10-30_spec_split')
from recon import Tok, split_streams, replay
from data import eval_reports, load_req, corpus

OUT = '/mnt/c/Users/hp/Desktop/qidk/proofs/2026-10-30_spec_split'
KMAX = 8
NMAXC = 32    # longest corpus suffix considered
PNMAX = 4     # htpd ngram_draft n range (g_reason_spec_nmin..nmax = 2..4); 1 is allowed for the ungated variant

# ---- board cost per decode step by batch rows (ms); linear in between, extrapolated past 64
TABLE = [(1, 66), (2, 82), (3, 113), (4, 133), (6, 106), (8, 109), (16, 120), (64, 171)]


def cost(r):
    for (a, ca), (b, cb) in zip(TABLE, TABLE[1:]):
        if r <= b:
            return ca + (cb - ca) * (r - a) / (b - a)
    (a, ca), (b, cb) = TABLE[-2], TABLE[-1]
    return cb + (cb - ca) * (r - b) / (b - a)


# ---- draft sources. Each returns, for every position L of the sequence (history = ctx + seq[:L]), a tuple
# (draft tokens up to KMAX, match length) or None.
def prompt_lookup_all(ctx, seq, nmin=1, nmax=PNMAX):
    """htpd ngram_draft: most recent earlier occurrence of the longest history suffix (nmax..nmin tokens),
    then up to K tokens that followed it (within the history). Match length reported = n used; 'ext' = the
    match extended backwards (up to NMAXC) for the P+C comparison."""
    h = list(ctx)
    last = [dict() for _ in range(nmax + 1)]  # n -> {ngram: most recent start i with i+n <= len(h)-1}
    # index the context: occurrences starting at i are usable once i+n <= L-1
    res = {}

    def add_upto(L):
        # register all n-gram starts i with i + n == L - 1 (i.e. followed by at least one token)
        for n in range(1, nmax + 1):
            i = L - 1 - n
            if i >= 0:
                last[n][tuple(h[i:i + n])] = i

    for L in range(1, len(h) + 1):
        add_upto(L)
    base = len(h)
    for j in range(len(seq) + 1):
        L = base + j
        d = None
        for n in range(nmax, nmin - 1, -1):
            if L < n + 1: continue
            i = last[n].get(tuple(h[L - n:L]))
            if i is None: continue
            st = i + n
            dr = h[st:min(st + KMAX, L)]
            if dr:
                e = n
                while e < NMAXC and i - 1 - (e - n) >= 0 and h[i - 1 - (e - n)] == h[L - 1 - e]:
                    e += 1
                d = (dr, n, e); break
        res[j] = d
        if j < len(seq):
            h.append(seq[j]); add_upto(len(h))
    return res


class Corpus:
    def __init__(self, docs):
        self.docs = docs                     # list of (inc, toks)
        self.idx = [collections.defaultdict(list) for _ in range(5)]  # n=1..4 -> ngram -> [(doc, end)]
        for di, (_, t) in enumerate(docs):
            for n in range(1, 5):
                for e in range(n, len(t)):   # ngram t[e-n:e] followed by t[e]
                    self.idx[n][tuple(t[e - n:e])].append((di, e))

    def draft(self, hist, excl, nmin=1):
        """SuffixDecoding-style: longest suffix of hist (<= NMAXC) found in the corpus (docs of incident excl
        removed); continuation = frequency-weighted walk over all occurrences with that longest match."""
        for n in range(4, nmin - 1, -1):
            if len(hist) < n: continue
            cands = self.idx[n].get(tuple(hist[-n:]))
            if not cands: continue
            best, bl = [], 0
            for di, e in cands:
                inc, t = self.docs[di]
                if inc in excl: continue
                l = n
                while l < NMAXC and e - 1 - l >= 0 and l < len(hist) and t[e - 1 - l] == hist[-1 - l]:
                    l += 1
                if l > bl: best, bl = [(di, e)], l
                elif l == bl: best.append((di, e))
            if not best: continue
            dr = []
            cur = best
            for k in range(KMAX):
                cnt = collections.Counter()
                for di, e in cur:
                    t = self.docs[di][1]
                    if e + k < len(t): cnt[t[e + k]] += 1
                if not cnt: break
                tk = cnt.most_common(1)[0][0]
                dr.append(tk)
                cur = [(di, e) for di, e in cur if e + k < len(self.docs[di][1]) and self.docs[di][1][e + k] == tk]
            if dr: return (dr, bl, bl)
            return None
        return None


# ---- one stream's step-by-step greedy verification
def run_stream(seq, pick, start, end, drafts, K, m, src, cap=None):
    """seq/pick: the stream's tokens; start: index of the first cert token (a known pick); end: index after the
    last pick (stream done once that pick is known). drafts[L] = {'P':(..),'C':(..)} for history seq[:L].
    cap: drafts may not run past this index (head: the fork pick). Returns per-step list of
    (rows, drafted, kept, partial)."""
    steps = []
    c = start
    if start >= end - 1 and pick[start]:
        return steps
    while True:
        nxt = c + 1
        while nxt < len(seq) and not pick[nxt]: nxt += 1
        if nxt >= end: break  # (cannot happen: last pick already known)
        d = []
        if K > 0:
            dp = drafts[nxt].get('P'); dc = drafts[nxt].get('C')
            ch = None
            if src == 'P': ch = dp
            elif src == 'C': ch = dc
            else:
                if dp and dc: ch = dp if dp[2] >= dc[2] else dc
                else: ch = dp or dc
            if ch and ch[1] >= m:
                d = ch[0][:K]
                if cap is not None: d = d[:max(0, cap + 1 - nxt)]
        rows = (nxt - c) + len(d)
        a = 0
        while a < len(d) and nxt + a < len(seq) and d[a] == seq[nxt + a]: a += 1
        k = nxt + a
        done = False
        # last pick obtained? picks up to index k (if seq[k] is a pick it comes as the bonus pick)
        last_pick = end - 1
        if k > last_pick: done = True
        elif pick[k] and k == last_pick: done = True
        partial = (a < len(d)) and not done
        steps.append((rows, len(d), min(a, len(d)), partial))
        if done: break
        c = k
    return steps


def simulate(rep, K, m, src):
    head, conts = rep['head'], rep['conts']
    hs = run_stream(head['seq'], head['pick'], 0, head['fork'] + 1, head['drafts'], K, m, src, cap=head['fork'])
    cs = [run_stream(s['seq'], s['pick'], s['fork'], s['end'], s['drafts'], K, m, src) for s in conts]
    rows = [x[0] for x in hs]
    T = max(len(x) for x in cs)
    for t in range(T):
        rows.append(sum(x[t][0] for x in cs if t < len(x)))
    allst = hs + [y for x in cs for y in x]
    drafted = sum(x[1] for x in allst); kept = sum(x[2] for x in allst)
    nd = sum(1 for x in allst if x[1] > 0); npart = sum(1 for x in allst if x[3])
    # global steps with at least one stream needing a restore
    gpart = sum(1 for x in hs if x[3]) + sum(1 for t in range(T) if any(t < len(x) and x[t][3] for x in cs))
    return dict(steps=len(rows), ms=sum(cost(r) for r in rows), rows_mean=sum(rows) / len(rows), rows_max=max(rows),
                head_steps=len(hs), cont_steps=T, drafted=drafted, kept=kept, draft_steps=nd, partial=npart,
                stream_steps=len(allst), global_partial=gpart)


def main():
    t0 = time.time()
    tok = Tok()
    # corpus: tokenized as htpd would emit it (full-schema replay), cached
    cpath = OUT + '/corpus_tokens.json'
    if os.path.exists(cpath):
        cdocs = json.load(open(cpath))
    else:
        cdocs = []
        S = load_req(10)['schema']
        for d in corpus():
            r = replay(tok, S, d['text'].encode('utf-8'))
            ok = r['mism'] == 0 and r['stop'] == 'json'
            cdocs.append(dict(src=d['src'], inc=d['inc'], ok=ok, toks=r['toks'] if ok else tok.enc(d['text'].encode())))
        json.dump(cdocs, open(cpath, 'w'))
    # dedupe identical corpus texts (same tokens)
    seen = set(); uniq = []
    for d in cdocs:
        k = tuple(d['toks'])
        if k in seen: continue
        seen.add(k); uniq.append(d)
    srcs = os.environ.get("CORPUS_SRC")
    if srcs: uniq = [d for d in uniq if d["src"] in srcs.split(",")]
    tag = os.environ.get("TAG", "")
    csum = collections.Counter(d["src"] for d in uniq)
    print('corpus', dict(csum), 'replay ok', sum(d['ok'] for d in uniq), '/', len(uniq), flush=True)
    C = Corpus([(d['inc'], d['toks']) for d in uniq])
    print('corpus index built %.0fs' % (time.time() - t0), flush=True)

    # evaluated reports: unique (q, text)
    reps, seenr = [], {}
    for r in eval_reports():
        key = (r['q'], r['text'])
        if key in seenr: seenr[key]['files'].append(r['file']); continue
        req = load_req(r['q'])
        ss = split_streams(tok, req['schema'], r['text'])
        ptoks = tok.enc_str(req['prompt'])
        excl = {req['id']}
        conts = []
        for s in ss:
            seq, pk = s['toks'], s['pick']
            P = prompt_lookup_all(ptoks, seq)
            dr = []
            for L in range(len(seq) + 1):
                dr.append({'P': P[L], 'C': C.draft(ptoks[-0:0] + seq[:L], excl) if L > 0 else None})
            conts.append(dict(seq=seq, pick=pk, fork=s['fork'], end=s['end'], drafts=dr))
        rep = dict(q=r['q'], inc=req['id'], files=[r['file']], head=conts[0], conts=conts)
        seenr[key] = rep; reps.append(rep)
        print('report q%d prepared (%d tokens) %.0fs' % (r['q'], sum(len(c['seq']) for c in conts), time.time() - t0), flush=True)

    configs = [('none', 0, 1)]
    for src in ['P', 'C', 'PC']:
        for K in [2, 4, 6, 8]:
            for m in [1, 2, 3, 4]:
                configs.append((src, K, m))
    results = []
    for rep in reps:
        row = dict(q=rep['q'], inc=rep['inc'], files=rep['files'], cfg={})
        for src, K, m in configs:
            row['cfg']['%s_K%d_m%d' % (src, K, m)] = simulate(rep, K, m, src if src != 'none' else 'P')
        results.append(row)
    # all-tokens-sampled upper bound for the baseline (every token costs a step)
    for rep, row in zip(reps, results):
        hp = rep['head']['fork'] + 1
        T = max(len(s['seq']) - s['fork'] - 1 for s in rep['conts'])
        row['all_sampled_steps'] = hp - 1 + T
    json.dump(dict(configs=[('%s_K%d_m%d' % c) for c in configs], table=TABLE, corpus=dict(csum),
                   corpus_n=len(uniq), corpus_replay_ok=sum(d['ok'] for d in uniq), reports=results),
              open(OUT + '/sim_results%s.json' % tag, 'w'), indent=1)
    print('done %.0fs' % (time.time() - t0))


if __name__ == '__main__':
    main()
