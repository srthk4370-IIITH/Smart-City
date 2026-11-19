"""BLEU-4, ROUGE-L and chrF for free-text gold fields (owner requirement, memory bleu-and-reasoning-metrics). Pure Python
(sacrebleu / rouge_score are not installed in the venvs; no downloads). Conventions:
- tokenisation for BLEU / ROUGE-L: lower case, words and single punctuation marks (re \\w+|[^\\w\\s]), close to sacrebleu 13a
  + lowercase;
- BLEU: corpus BLEU-4, uniform weights, brevity penalty, add-1 smoothing on n > 1 counts only when a count is 0 (smooth "exp"
  is not used; this is Lin & Och smoothing 2 at corpus level), x100;
- chrF: character n-grams n = 1..6 without spaces, beta = 2, corpus level (statistics summed over segments), x100 (= sacrebleu
  chrF defaults, word order 0);
- ROUGE-L: F1 of the token LCS per segment, averaged over segments, x100.
An empty prediction scores 0 on every metric (it is kept in the corpus, so a model that writes nothing is penalised)."""
import collections
import math
import re

TOK = re.compile(r"\w+|[^\w\s]", re.U)


def toks(s):
    return TOK.findall((s or "").lower())


def _ngrams(t, n):
    return collections.Counter(tuple(t[i:i + n]) for i in range(len(t) - n + 1))


def bleu(hyps, refs, n=4):
    match, total = [0] * n, [0] * n
    hl = rl = 0
    for h, r in zip(hyps, refs):
        ht, rt = toks(h), toks(r)
        hl += len(ht)
        rl += len(rt)
        for k in range(1, n + 1):
            hc, rc = _ngrams(ht, k), _ngrams(rt, k)
            match[k - 1] += sum(min(c, rc[g]) for g, c in hc.items())
            total[k - 1] += max(0, len(ht) - k + 1)
    if hl == 0 or match[0] == 0:
        return 0.0
    lp = 0.0
    for k in range(n):
        m, t = match[k], total[k]
        if k > 0 and m == 0:
            m, t = 1, t + 1
        lp += math.log(m / t) if t else 0.0
    bp = 1.0 if hl > rl else math.exp(1 - rl / max(1, hl))
    return round(100 * bp * math.exp(lp / n), 2)


def _chars(s, n):
    s = re.sub(r"\s+", "", s or "")
    return collections.Counter(s[i:i + n] for i in range(len(s) - n + 1))


def chrf(hyps, refs, n=6, beta=2.0):
    st = [[0, 0, 0] for _ in range(n)]        # match, hyp total, ref total
    for h, r in zip(hyps, refs):
        for k in range(1, n + 1):
            hc, rc = _chars(h, k), _chars(r, k)
            st[k - 1][0] += sum(min(c, rc[g]) for g, c in hc.items())
            st[k - 1][1] += sum(hc.values())
            st[k - 1][2] += sum(rc.values())
    ps = [m / th for m, th, tr in st if th > 0]
    rs = [m / tr for m, th, tr in st if tr > 0]
    if not ps or not rs:
        return 0.0
    p, r = sum(ps) / n, sum(rs) / n
    if p + r == 0:
        return 0.0
    b2 = beta * beta
    return round(100 * (1 + b2) * p * r / (b2 * p + r), 2)


def _lcs(a, b):
    if not a or not b:
        return 0
    prev = [0] * (len(b) + 1)
    for x in a:
        cur = [0]
        for j, y in enumerate(b):
            cur.append(prev[j] + 1 if x == y else max(prev[j + 1], cur[j]))
        prev = cur
    return prev[-1]


def rouge_l(hyps, refs):
    f = []
    for h, r in zip(hyps, refs):
        ht, rt = toks(h), toks(r)
        l = _lcs(ht, rt)
        if not l:
            f.append(0.0)
            continue
        p, rc = l / len(ht), l / len(rt)
        f.append(2 * p * rc / (p + rc))
    return round(100 * sum(f) / len(f), 2) if f else 0.0


def all_metrics(hyps, refs):
    pairs = [(h or "", r) for h, r in zip(hyps, refs) if (r or "").strip()]
    if not pairs:
        return None
    h, r = [p[0] for p in pairs], [p[1] for p in pairs]
    return {"n": len(pairs), "bleu": bleu(h, r), "rougeL": rouge_l(h, r), "chrf": chrf(h, r)}


if __name__ == "__main__":     # self-check
    assert bleu(["the cat sat on the mat"], ["the cat sat on the mat"]) == 100.0
    assert chrf(["abc def"], ["abc def"]) == 100.0 and rouge_l(["a b c"], ["a b c"]) == 100.0
    assert bleu([""], ["x y"]) == 0.0 and rouge_l([""], ["x"]) == 0.0
    m = all_metrics(["CO2 rose after people arrived", "pump fault"], ["CO2 rose when people arrived", "the pump failed"])
    assert 0 < m["bleu"] < 100 and 0 < m["chrf"] < 100 and 0 < m["rougeL"] < 100, m
    print("text_metrics ok", m)
