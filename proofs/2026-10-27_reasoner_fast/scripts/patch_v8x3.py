"""htpd v8x3: bounded constrained pick + per-request wall-clock guard + slow-path counters (rsn_v2 board hang, 2026-10-29).
(a) pick_forced_impl: argmax -> top-64 (unchanged) -> top-1024 (nth_element) -> first token of the forced text -> full
    scan only as a last resort. The top-1024 stage returns the same token the full scan did whenever an allowed token
    is among the 1024 best, so outputs only change when the old code would have scanned past rank 1024.
    HTPD_PICK_BOUNDED=0 restores the v8x2 path (for the A/B and the host repro).
(b) HTPD_REASON_TIMEOUT_MS (default 150000): a reason request that decodes longer stops every active stream with
    stop "timeout" (the Go gate then rejects the text and the deterministic report stays).
(c) stream summary lines carry the slow-path counts (top64 miss, top1024 miss, full scans); HTPD_PICK_DEBUG=1 logs
    every slow pick (Forcer mode/key/val/need, the argmax piece) and a per-100-step timing line."""
import sys
p = sys.argv[1]
s = open(p, encoding="utf-8").read()


def rep(a, b, n=1):
    global s
    assert s.count(a) == n, (s.count(a), a[:90])
    s = s.replace(a, b)


rep("""static llama_token pick_forced_impl(const float * lg, int n_vocab, const htpd::Forcer & fz, int * changed);
static llama_token pick_forced(""", """static llama_token pick_forced_impl(const float * lg, int n_vocab, const htpd::Forcer & fz, int * changed);
// v8x3 pick statistics (per request) and the kind of the last pick: 0 argmax, 1 top-64, 2 top-1024, 3 forced token, 4 full scan
static int g_pick_kind = 0;
static long g_pick_slow64 = 0, g_pick_slow1k = 0, g_pick_full = 0;
static bool g_pick_bounded = true, g_pick_debug = false;
static llama_token pick_forced(""")

rep("""    if (ok(t)) return t;
    constexpr int K = 64;
    std::vector<std::pair<float, int>> top;
    top.reserve(K + 1);
    for (int i = 0; i < n_vocab; ++i) {
        if ((int) top.size() == K && !(lg[i] > top.back().first)) continue;
        auto it = std::find_if(top.begin(), top.end(), [&](auto & e) { return lg[i] > e.first; });
        top.insert(it, {lg[i], i});
        if ((int) top.size() > K) top.pop_back();
    }
    llama_token best = -1;
    for (auto & e : top) if (ok(e.second)) { best = e.second; break; }
    if (best < 0) {""", """    g_pick_kind = 0;
    if (ok(t)) return t;
    constexpr int K = 64;
    std::vector<std::pair<float, int>> top;
    top.reserve(K + 1);
    for (int i = 0; i < n_vocab; ++i) {
        if ((int) top.size() == K && !(lg[i] > top.back().first)) continue;
        auto it = std::find_if(top.begin(), top.end(), [&](auto & e) { return lg[i] > e.first; });
        top.insert(it, {lg[i], i});
        if ((int) top.size() > K) top.pop_back();
    }
    llama_token best = -1;
    g_pick_kind = 1;
    for (auto & e : top) if (ok(e.second)) { best = e.second; break; }
    if (best < 0) {
        g_pick_slow64++;
        if (g_pick_debug) {
            const std::string tp = t >= 0 && t < (llama_token) g_rpieces.size() ? g_rpieces[t] : std::string("?");
            fprintf(stderr, "htpd: pick slow: mode %d key '%s' val '%.40s' need '%.40s' argmax '%s'\\n", (int) fz.mode,
                    fz.key.c_str(), fz.val.c_str(), fz.need.c_str(), tp.c_str());
        }
    }
    if (best < 0 && g_pick_bounded) {
        // (a) top-1024 by logit (same order as the full scan, so the same token when one of them is allowed)
        constexpr int K2 = 1024;
        std::vector<int> idx(n_vocab);
        for (int i = 0; i < n_vocab; ++i) idx[i] = i;
        const int k2 = std::min(K2, n_vocab);
        std::nth_element(idx.begin(), idx.begin() + k2, idx.end(), [&](int a, int b) { return lg[a] > lg[b]; });
        std::sort(idx.begin(), idx.begin() + k2, [&](int a, int b) { return lg[a] > lg[b] || (lg[a] == lg[b] && a < b); });
        g_pick_kind = 2;
        for (int j = 0; j < k2; ++j) if (ok(idx[j])) { best = idx[j]; break; }
        if (best < 0) {
            g_pick_slow1k++;
            // then the first token of the deterministic continuation, when there is one
            const std::string ft = fz.forced_text();
            if (!ft.empty()) {
                std::vector<llama_token> ftk = tokenize(ft);
                if (!ftk.empty() && ok(ftk[0])) { best = ftk[0]; g_pick_kind = 3; }
            }
        }
    }
    if (best < 0) {
        g_pick_kind = 4; g_pick_full++;""")

# per-request reset + timeout guard + debug timing in the decode loops
rep("""    auto t0 = clk::now();
    llama_batch batch = llama_batch_init(std::max(n_batch, n * 72), 0, 1);""", """    auto t0 = clk::now();
    g_pick_slow64 = g_pick_slow1k = g_pick_full = 0;
    llama_batch batch = llama_batch_init(std::max(n_batch, n * 72), 0, 1);""")

rep("""    while (active > 0) {
        batch.n_tokens = 0;
        std::vector<int> last(NS, -1);""", """    while (active > 0) {
        if (g_reason_timeout_ms > 0 && ms_since(t0) > g_reason_timeout_ms) {  // (b) wall-clock guard
            for (int s = 0; s < NS; ++s) if (!done[s]) { done[s] = true; out[s].stop = "timeout"; out[s].ms = ms_since(t0); }
            fprintf(stderr, "htpd: reason timeout after %.0f ms (%d active streams stopped)\\n", ms_since(t0), active);
            active = 0;
            break;
        }
        if (g_pick_debug && steps % 100 == 0 && steps > 0)
            fprintf(stderr, "htpd: step %d at %.0f ms, slow picks %ld/%ld/%ld\\n", steps, ms_since(t0), g_pick_slow64, g_pick_slow1k, g_pick_full);
        batch.n_tokens = 0;
        std::vector<int> last(NS, -1);""")

rep("""        while (!fin) {
            ngram_draft(hist, K, g_reason_spec_nmin, g_reason_spec_nmax, draft);""", """        while (!fin) {
            if (g_reason_timeout_ms > 0 && ms_since(t0) > g_reason_timeout_ms) { out[0].stop = "timeout"; out[0].ms = ms_since(t0); break; }
            ngram_draft(hist, K, g_reason_spec_nmin, g_reason_spec_nmax, draft);""")

rep("""        fprintf(stderr, "htpd: reason stream %d: %d tokens (%d forced, %d constrained picks), stop %s, %.0f ms\\n",
                s, out[s].tokens, out[s].forced, changed[s], out[s].stop.c_str(), out[s].ms);""", """        fprintf(stderr, "htpd: reason stream %d: %d tokens (%d forced, %d constrained picks), stop %s, %.0f ms\\n",
                s, out[s].tokens, out[s].forced, changed[s], out[s].stop.c_str(), out[s].ms);
        if (s == NS - 1)
            fprintf(stderr, "htpd: reason picks: %ld top64 misses, %ld top1024 misses, %ld full scans (bounded %d)\\n",
                    g_pick_slow64, g_pick_slow1k, g_pick_full, (int) g_pick_bounded);""")

rep("""static int g_reason_rs = 0;                   // n_rs_seq of the reasoner context
""", """static int g_reason_rs = 0;                   // n_rs_seq of the reasoner context
static double g_reason_timeout_ms = 150000;   // v8x3: HTPD_REASON_TIMEOUT_MS wall-clock guard per reason request (0 = off)
""")

rep("""    g_reason_spec = std::max(0, std::min(16, env_int("HTPD_REASON_SPEC", 0)));""", """    g_reason_spec = std::max(0, std::min(16, env_int("HTPD_REASON_SPEC", 0)));
    g_reason_timeout_ms = env_int("HTPD_REASON_TIMEOUT_MS", 150000);
    g_pick_bounded = env_int("HTPD_PICK_BOUNDED", 1) != 0;
    g_pick_debug = env_int("HTPD_PICK_DEBUG", 0) != 0;""")
open(p, "w", encoding="utf-8", newline="\n").write(s)
print("v8x3 patched")
