"""Patch htpd.cpp (v8r) into v8s: prompt-lookup speculative decoding for the reasoner (HTPD_REASON_SPEC)."""
import sys
p = sys.argv[1]
s = open(p, encoding="utf-8").read()


def rep(old, new):
    global s
    assert s.count(old) == 1, old[:80]
    s = s.replace(old, new)


rep("""static bool g_reason_disk_cache = true;       // HTPD_REASON_DISK_CACHE=0: static-prefix state not persisted
""", """static bool g_reason_disk_cache = true;       // HTPD_REASON_DISK_CACHE=0: static-prefix state not persisted
// v8s: prompt-lookup (n-gram) speculative decoding for the reasoner (single stream). HTPD_REASON_SPEC=K drafts up to K
// tokens copied from the prompt/answer history; hybrid models get K recurrent snapshots (n_rs_seq) for the rollback.
// Verified with the same greedy + forcer pick as plain decoding, so only drafts that match the model's choice are kept.
static int g_reason_spec = 0;                 // max draft tokens (0 = off: v8r decoding)
static int g_reason_spec_nmin = 2, g_reason_spec_nmax = 4;  // n-gram match length range (longest first)
static int g_reason_rs = 0;                   // n_rs_seq of the reasoner context
""")

rep("""        h = fnv1a(k.data(), k.size() * sizeof(llama_token), h);
        char b[40];""", """        h = fnv1a(k.data(), k.size() * sizeof(llama_token), h);
        if (g_reason_rs > 0) h = fnv1a(&g_reason_rs, sizeof g_reason_rs, h);  // snapshot planes change the state layout
        char b[40];""")

rep("""// prompts run as parallel sequences 0..n-1 (n <= n_seq_max); prefix = the static prompt prefix to cache ("" = none)
static std::vector<Out> run_reason(""", """// prompt lookup: the most recent earlier occurrence of the longest history suffix (nmax..nmin tokens) and the up to K
// tokens that followed it
static void ngram_draft(const std::vector<llama_token> & h, int K, int nmin, int nmax, std::vector<llama_token> & d) {
    d.clear();
    const int L = (int) h.size();
    for (int nn = nmax; nn >= nmin; --nn) {
        if (L < nn + 1) continue;
        const llama_token * tail = h.data() + L - nn;
        for (int i = L - nn - 1; i >= 0; --i) {
            if (h[i] != tail[0] || !std::equal(tail, tail + nn, h.begin() + i)) continue;
            for (int k = 0, st = i + nn; k < K && st + k < L; ++k) d.push_back(h[st + k]);
            if (!d.empty()) return;
        }
    }
}

struct SpecStats { int steps = 0, drafted = 0, accepted = 0, drafts = 0; };

// prompts run as parallel sequences 0..n-1 (n <= n_seq_max); prefix = the static prompt prefix to cache ("" = none)
static std::vector<Out> run_reason(""")

rep("""    int active = 0;
    for (int s = 0; s < n; ++s) {
        if (out[s].stop == "error") { done[s] = true; continue; }""", r"""    SpecStats sp;
    const bool spec = n == 1 && g_reason_spec > 0 && out[0].stop != "error";
    if (spec) {
        // ---- v8s speculative decoding (one stream). cert = tokens certain to come next (the model's pick + its
        // forced tokens, already emitted); the batch is cert + an n-gram draft. Drafts are checked in order against
        // the pick plain decoding would make; forced tokens after an accepted pick are matched against the following
        // drafts; the rejected tail is rolled back (recurrent snapshots, n_rs_seq >= K).
        const int K = g_reason_rs > 0 ? std::min(g_reason_spec, g_reason_rs) : g_reason_spec;
        std::vector<llama_token> hist = toks[0], cert, draft, next;
        bool fin = handle(0);
        if (!fin) { cert.push_back(pending[0]); cert.insert(cert.end(), inj[0].begin(), inj[0].end()); }
        else out[0].ms = ms_since(t0);
        hist.insert(hist.end(), cert.begin(), cert.end());
        flush_step();
        while (!fin) {
            ngram_draft(hist, K, g_reason_spec_nmin, g_reason_spec_nmax, draft);
            const int room = per_seq - 72 - pos[0] - (int) cert.size() - 1;
            if ((int) draft.size() > room) draft.resize(std::max(0, room));
            batch.n_tokens = 0;
            const int p0 = pos[0];
            for (size_t j = 0; j < cert.size(); ++j) {
                int idx = batch.n_tokens++;
                batch.token[idx] = cert[j]; batch.pos[idx] = p0 + (int) j; batch.n_seq_id[idx] = 1; batch.seq_id[idx][0] = 0;
                batch.logits[idx] = j + 1 == cert.size();
            }
            const int pd = p0 + (int) cert.size();  // position of draft[0]
            for (size_t j = 0; j < draft.size(); ++j) {
                int idx = batch.n_tokens++;
                batch.token[idx] = draft[j]; batch.pos[idx] = pd + (int) j; batch.n_seq_id[idx] = 1; batch.seq_id[idx][0] = 0;
                batch.logits[idx] = true;
            }
            if (llama_decode(ctx, batch) != 0) { fprintf(stderr, "htpd: reason decode failed\n"); break; }
            steps++; sp.steps++;
            if (!draft.empty()) { sp.drafts++; sp.drafted += (int) draft.size(); }
            int row = (int) cert.size() - 1;  // batch row whose logits predict the next token
            size_t j = 0;                     // drafts kept (accepted picks and matched forced tokens)
            next.clear();
            while (true) {
                pos[0] = pd + (int) j;
                const llama_token e = pick_forced(llama_get_logits_ith(ctx, row), n_vocab, fz[0], &changed[0]);
                if (j < draft.size() && e == draft[j] && !llama_vocab_is_eog(g_vocab, e)) {
                    row = (int) cert.size() + (int) j; j++; sp.accepted++;
                    pos[0] = pd + (int) j;
                    pending[0] = e;
                    hist.push_back(e);
                    if ((fin = handle(0))) break;
                    size_t m = 0;  // forced tokens after it that the draft already holds
                    while (m < inj[0].size() && j < draft.size() && draft[j] == inj[0][m]) {
                        hist.push_back(draft[j]); row = (int) cert.size() + (int) j; j++; m++; sp.accepted++;
                    }
                    pos[0] = pd + (int) j;
                    if (m < inj[0].size()) { next.assign(inj[0].begin() + m, inj[0].end()); break; }
                    continue;
                }
                pending[0] = e;
                if (!(fin = handle(0))) { next.push_back(e); next.insert(next.end(), inj[0].begin(), inj[0].end()); }
                break;
            }
            if (j < draft.size() && !fin) {
                if (!llama_memory_seq_rm(mem, 0, pd + (int) j, -1)) {
                    fprintf(stderr, "htpd: reason spec rollback failed at %d (%zu of %zu drafts kept)\n", pd + (int) j, j, draft.size());
                    out[0].stop = "error"; fin = true;
                }
            }
            pos[0] = pd + (int) j;
            if (!fin) hist.insert(hist.end(), next.begin(), next.end());
            cert.swap(next);
            if (fin) out[0].ms = ms_since(t0);
            flush_step();
        }
        fprintf(stderr, "htpd: reason spec: %d steps, %d drafts, %d drafted, %d kept (K %d, n %d-%d, rs %d)\n",
                sp.steps, sp.drafts, sp.drafted, sp.accepted, K, g_reason_spec_nmin, g_reason_spec_nmax, g_reason_rs);
    }
    int active = 0;
    for (int s = 0; s < n && !spec; ++s) {
        if (out[s].stop == "error") { done[s] = true; continue; }""")

rep("""            cp.n_ubatch = (uint32_t) reason_ubatch;
            rctx = llama_init_from_model(rmodel, cp);""", """            cp.n_ubatch = (uint32_t) reason_ubatch;
            g_reason_rs = 0;
            if (g_reason_spec > 0 && (llama_model_is_hybrid(rmodel) || llama_model_is_recurrent(rmodel))) cp.n_rs_seq = (uint32_t) g_reason_spec;
            rctx = llama_init_from_model(rmodel, cp);
            if (rctx) g_reason_rs = (int) llama_n_rs_seq(rctx);""")

rep("""    g_reason_disk_cache = env_int("HTPD_REASON_DISK_CACHE", 1) != 0;
""", """    g_reason_disk_cache = env_int("HTPD_REASON_DISK_CACHE", 1) != 0;
    g_reason_spec = std::max(0, std::min(16, env_int("HTPD_REASON_SPEC", 0)));
    g_reason_spec_nmin = std::max(1, env_int("HTPD_REASON_SPEC_NMIN", 2));
    g_reason_spec_nmax = std::max(g_reason_spec_nmin, env_int("HTPD_REASON_SPEC_NMAX", 4));
""")

rep("""llama_model_is_hybrid(rmodel) || llama_model_is_recurrent(rmodel) ? "hybrid/recurrent (no rollback, whole-state cache)" : "attention-only",""",
    """llama_model_is_hybrid(rmodel) || llama_model_is_recurrent(rmodel) ? (g_reason_rs > 0 ? "hybrid/recurrent (rollback snapshots for spec, whole-state cache)" : "hybrid/recurrent (no rollback, whole-state cache)") : "attention-only",""")
open(p, "w", encoding="utf-8", newline="\n").write(s)
print("patched")
