"""Add a determinism trace to htpd (env HTPD_REASON_TRACE=<dir>): for every reasoner pick, one line
'<step> <picked> <top1 id> <top1 logit> <top2 id> <top2 logit> <fnv64 of the whole logits row>' into
<dir>/trace_<n>.txt (n = request counter). Off when the env is unset (no behaviour change)."""
import sys
p = sys.argv[1]
s = open(p, encoding="utf-8").read()


def rep(old, new):
    global s
    assert s.count(old) == 1, old[:80]
    s = s.replace(old, new)


rep("""static llama_token pick_forced(const float * lg, int n_vocab, const htpd::Forcer & fz, int * changed) {
    llama_token t = argmax(lg, n_vocab);""", """static FILE * g_trace = nullptr;  // HTPD_REASON_TRACE: per-pick logits trace of the current reason request
static int g_trace_step = 0;
static void trace_pick(const float * lg, int n_vocab, llama_token picked) {
    if (!g_trace) return;
    int a = -1, b = -1;
    for (int i = 0; i < n_vocab; ++i) {
        if (a < 0 || lg[i] > lg[a]) { b = a; a = i; }
        else if (b < 0 || lg[i] > lg[b]) b = i;
    }
    uint64_t h = 1469598103934665603ULL;
    const uint8_t * p = (const uint8_t *) lg;
    for (size_t i = 0; i < (size_t) n_vocab * sizeof(float); ++i) { h ^= p[i]; h *= 1099511628211ULL; }
    fprintf(g_trace, "%d %d %d %.6f %d %.6f %016llx\\n", g_trace_step++, picked, a, lg[a], b, lg[b], (unsigned long long) h);
}

static llama_token pick_forced_impl(const float * lg, int n_vocab, const htpd::Forcer & fz, int * changed);
static llama_token pick_forced(const float * lg, int n_vocab, const htpd::Forcer & fz, int * changed) {
    const llama_token t = pick_forced_impl(lg, n_vocab, fz, changed);
    trace_pick(lg, n_vocab, t);
    return t;
}
static llama_token pick_forced_impl(const float * lg, int n_vocab, const htpd::Forcer & fz, int * changed) {
    llama_token t = argmax(lg, n_vocab);""")

rep("""    for (int s = 0; s < (int) llama_n_seq_max(ctx); ++s) llama_memory_seq_rm(mem, s, -1, -1);  // whole: always valid
""", """    for (int s = 0; s < (int) llama_n_seq_max(ctx); ++s) llama_memory_seq_rm(mem, s, -1, -1);  // whole: always valid
    static int trace_req = 0;
    if (const char * td = getenv("HTPD_REASON_TRACE"); td && *td) {
        char path[512];
        snprintf(path, sizeof path, "%s/trace_%03d.txt", td, trace_req++);
        g_trace = fopen(path, "w");
        g_trace_step = 0;
    }
    struct TraceClose { ~TraceClose() { if (g_trace) { fclose(g_trace); g_trace = nullptr; } } } trace_close;""")
open(p, "w", encoding="utf-8", newline="\n").write(s)
print("trace patched")
