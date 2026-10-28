"""Offline replay of htpd's verified n-gram drafting (HTPD_DRAFT=1) on real v2 device outputs.

Verified drafting never changes greedy text; it only changes HOW MANY decode steps produce it. Given the
final greedy outputs (device eval, host400 set: 6 roles, real batches of 8) we can replay the exact draft
policy of app/htpd/htpd.cpp (propose_chain: n-gram 3..1 over other streams -> recent outputs -> own
prompt+output; k = min(kmax, 32/streams - 1); accept the prefix that equals greedy) and count steps.
Then we test output-identical variants:
  corpus : a static per-role draft corpus (trained completions, data/sft_v2/train.jsonl, NOT the test set)
           consulted after the existing sources at each n-gram level
  kmax   : longer chains for small batches (HTPD_DRAFT_K)
  rows   : a 64-row cap instead of 32
WSL: nice ~/venvs/train/bin/python sim_draft.py  -> sim_draft.json
Caveat: tokens are re-tokenised from text (canonical BPE), which can differ from the model's own token
split in rare places; drafting from a corpus is still verified, so the device text cannot change.
"""
import json, os, collections, random, statistics as st
from tokenizers import Tokenizer
H = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.abspath(os.path.join(H, "..", "..", ".."))
tok = Tokenizer.from_file(os.path.expanduser("~/models/llama-3.2-3b-instruct/tokenizer.json"))
enc = lambda s: tok.encode(s, add_special_tokens=False).ids
PREFILL = '{"pattern": "'

def gen_text(r):
    t = r["text"]
    assert t.startswith(PREFILL)
    g = t[len(PREFILL):]
    if r["stop"] == "action" and g.endswith("}"):
        g = g[:-1] + ', "action"'
    return g

# ---- data: host400 outputs (real batches) + their prompts from the test split
test = {}
for l in open(os.path.join(ROOT, "Code/smart-city-edge-agent/data/sft_v2/test.jsonl"), encoding="utf-8"):
    r = json.loads(l); test[r["id"]] = r
rows = [json.loads(l) for l in open(os.path.join(ROOT, "proofs/2026-10-20_v2_post/device/host400/samples.jsonl"), encoding="utf-8")]
rows = [r for r in rows if r["stop"] != "ctx" and r["id"] in test]
batches = collections.OrderedDict()
for r in rows:
    batches.setdefault((r["batch_s"], r["prefill_ms"]), []).append(r)
batches = list(batches.values())
for r in rows:
    r["g"] = enc(gen_text(r))
    r["p"] = enc(test[r["id"]]["prompt"] + PREFILL)

# ---- static per-role corpus from TRAIN completions (n-gram -> most frequent next token)
random.seed(7)
per_role = collections.defaultdict(list)
for l in open(os.path.join(ROOT, "Code/smart-city-edge-agent/data/sft_v2/train.jsonl"), encoding="utf-8"):
    if random.random() > 0.12:
        continue
    r = json.loads(l)
    if len(per_role[r["role"]]) < 1500:
        c = r["completion"]
        if c.startswith(PREFILL):
            c = c[len(PREFILL):]
        per_role[r["role"]].append(enc(c))
corpus = {}
for role, seqs in per_role.items():
    tab = collections.defaultdict(collections.Counter)
    for s in seqs:
        for ng in (1, 2, 3):
            for i in range(len(s) - ng):
                tab[tuple(s[i:i + ng])][s[i + ng]] += 1
    corpus[role] = {k: v.most_common(1)[0][0] for k, v in tab.items()}

class Idx:
    # n-gram (1..3) -> next token at its LATEST occurrence (= htpd's backwards linear search)
    def __init__(self, seq=(), frm=0):
        self.d = {}
        self.s = []
        self.frm = frm
        for t in seq:
            self.push(t)

    def push(self, t):
        self.s.append(t)
        j = len(self.s) - 1
        for ng in (1, 2, 3):
            if j - ng >= self.frm:
                self.d[tuple(self.s[j - ng:j])] = t

    def get(self, key):
        return self.d.get(tuple(key), -1)


def run(batch_rows, recent, kmax, row_cap, use_corpus):
    n = len(batch_rows)
    hist = []
    for r in batch_rows:
        ix = Idx(r["p"]); ix.push(r["g"][0]); hist.append(ix)
    gen = [Idx([r["g"][0]]) for r in batch_rows]       # generated part only (what other streams search)
    rec = {}
    for rv in recent:                                    # newer outputs override older
        rec.update(rv)
    pos = [0] * n
    done = [len(r["g"]) <= 1 for r in batch_rows]
    roles = [test[r["id"]]["role"] for r in batch_rows]
    steps = 0

    def propose(s, h):
        L = len(h)
        for ng in (3, 2, 1):
            if L < ng + 1:
                continue
            key = tuple(h[L - ng:])
            for o in range(n):
                if o != s:
                    t = gen[o].get(key)
                    if t >= 0:
                        return t
            t = rec.get(key, -1)
            if t >= 0:
                return t
            t = hist[s].get(key)
            if t >= 0:
                return t
            if use_corpus:
                t = corpus.get(roles[s], {}).get(key, -1)
                if t >= 0:
                    return t
        return -1

    while not all(done):
        act = [s for s in range(n) if not done[s]]
        n_run = max(act) - min(act) + 1
        k = max(1, min(kmax, row_cap // max(1, n_run) - 1))
        steps += 1
        for s in act:
            g = batch_rows[s]["g"]
            h = list(hist[s].s[-3:])
            d = []
            for _ in range(k):
                t = propose(s, h)
                if t < 0:
                    break
                d.append(t); h.append(t)
            i = pos[s]
            new = []
            for j in range(k + 1):
                if i + 1 + j >= len(g):
                    break
                nt = g[i + 1 + j]
                new.append(nt)
                if j < len(d) and d[j] == nt:
                    continue
                break
            for t in new:
                hist[s].push(t); gen[s].push(t)
            pos[s] = i + len(new)
            if pos[s] >= len(g) - 1:
                done[s] = True
    for s in range(n):
        recent.append(dict(gen[s].d))
        del recent[:-64]
    return steps


def evaluate(mode, kmax, row_cap, use_corpus, cold=False):
    recent, steps, toks = [], [], []
    groups = batches
    if mode == "batch10":                               # 10-stream batches (app: --agents 10)
        flat = [r for b in batches for r in b]
        groups = [flat[i:i + 10] for i in range(0, len(flat), 10)]
    for b in groups:
        if mode in ("batch", "batch10"):
            units = [b]
        elif mode == "batch4":
            units = [b[i:i + 4] for i in range(0, len(b), 4)]
        else:
            units = [[r] for r in b]
        for u in units:
            steps.append(run(u, [] if cold else recent, kmax, row_cap, use_corpus))
            toks.append(max(len(r["g"]) for r in u))
    return dict(units=len(steps), mean_steps=round(st.mean(steps), 1), mean_max_tokens=round(st.mean(toks), 1),
                tokens_per_step=round(sum(toks) / sum(steps), 2))

out = {}
for name, args in {
    "single_k4_cold": ("single", 4, 32, False, True),
    "single_k4_corpus_cold": ("single", 4, 32, True, True),
    "single_k8_corpus_cold": ("single", 8, 32, True, True),
    "single_k16_corpus_cold": ("single", 16, 32, True, True),
    "batch4_now": ("batch4", 4, 32, False),
    "batch4_k7_corpus": ("batch4", 8, 32, True),
    "batch10_k2_now": ("batch10", 4, 32, False),
    "batch10_rows44_k3_corpus": ("batch10", 4, 44, True),
    "single_k4_now": ("single", 4, 32, False),
    "single_k4_corpus": ("single", 4, 32, True),
    "single_k8_now": ("single", 8, 32, False),
    "single_k8_corpus": ("single", 8, 32, True),
    "batch8_k3_now": ("batch", 4, 32, False),
    "batch8_k3_corpus": ("batch", 4, 32, True),
    "batch8_rows64_k7_now": ("batch", 8, 64, False),
    "batch8_rows64_k7_corpus": ("batch", 8, 64, True),
}.items():
    out[name] = evaluate(*args)
    print(name, out[name], flush=True)
json.dump(out, open(os.path.join(H, "sim_draft.json"), "w"), indent=1)
