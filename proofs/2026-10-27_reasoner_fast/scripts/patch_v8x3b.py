"""htpd v8x3 (part 2): stall diagnosis + a CPU-side loop guard.
The host repro of the board stall (rsn_v2, q11, split-3) completes on CPU with 0 slow picks and the same split point
(147 tokens), so the board stall is either HTP-side (a DSP op that does not complete while OPPOLL busy-polls at 100%
CPU) or a token path only HTP numerics reach. This adds:
 - a heartbeat thread (HTPD_HEARTBEAT, default on): while a reason request runs and the decode step counter has not
   moved for >= 30 s, log every 15 s "htpd: heartbeat: no progress ..." with in_decode (inside llama_decode = HTP side)
   and the phase, so the next stall names its side;
 - Forcer::forced_text iteration cap (no-progress loop guard; same output whenever it terminates as before)."""
import sys, os
p = sys.argv[1]; rl = os.path.join(os.path.dirname(p), "reason_logic.h")
s = open(p, encoding="utf-8").read(); r = open(rl, encoding="utf-8").read()


def rep(txt, a, b):
    assert txt.count(a) == 1, a[:80]
    return txt.replace(a, b)


r = rep(r, """        std::string out;
        while (out.size() < cap) {""", """        std::string out;
        int iters = 0;
        while (out.size() < cap && iters++ < 1024) {  // v8x3: a no-progress state can never spin forever""")

s = rep(s, "#include <vector>\n", "#include <vector>\n#include <atomic>\n")
s = rep(s, """static bool g_pick_bounded = true, g_pick_debug = false;""", """static bool g_pick_bounded = true, g_pick_debug = false;
// v8x3 heartbeat: decode progress seen by a watcher thread (stall diagnosis: HTP side vs CPU side)
static std::atomic<long> g_hb_step{0};
static std::atomic<int> g_hb_in_decode{0}, g_hb_phase{0};  // phase 0 idle, 1 prefill, 2 decode step, 3 pick/handle
static void hb_thread() {
    long last = -1; int still = 0;
    for (;;) {
        std::this_thread::sleep_for(std::chrono::seconds(15));
        const int ph = g_hb_phase.load(); const long st = g_hb_step.load();
        if (ph == 0) { last = -1; still = 0; continue; }
        if (st == last) {
            still += 15;
            if (still >= 30)
                fprintf(stderr, "htpd: heartbeat: no progress for %d s at step %ld, phase %d, in_decode %d\\n", still, st, ph, g_hb_in_decode.load());
        } else { last = st; still = 0; }
    }
}""")
# instrument decodes inside run_reason (prefill lambda + main loop + spec loop)
s = rep(s, """            if (llama_decode(ctx, batch) != 0) { fprintf(stderr, "htpd: reason prefill failed\\n"); return false; }""",
        """            g_hb_phase = 1; g_hb_in_decode = 1;
            const int rc_pf = llama_decode(ctx, batch);
            g_hb_in_decode = 0; g_hb_step++;
            if (rc_pf != 0) { fprintf(stderr, "htpd: reason prefill failed\\n"); return false; }""")
s = rep(s, """        batch.n_tokens = 0;
        std::vector<int> last(NS, -1);""", """        g_hb_phase = 3; g_hb_step++;
        batch.n_tokens = 0;
        std::vector<int> last(NS, -1);""")
# the main-loop decode (the one followed by steps++)
a = """        if (llama_decode(ctx, batch) != 0) { fprintf(stderr, "htpd: reason decode failed\\n"); break; }
        steps++;"""
assert s.count(a) == 1
s = s.replace(a, """        g_hb_phase = 2; g_hb_in_decode = 1;
        const int rc_dec = llama_decode(ctx, batch);
        g_hb_in_decode = 0; g_hb_phase = 3; g_hb_step++;
        if (rc_dec != 0) { fprintf(stderr, "htpd: reason decode failed\\n"); break; }
        steps++;""")
s = rep(s, """    llama_batch_free(batch);
    for (int s = 0; s < NS; ++s) {
        llama_memory_seq_rm(mem, s, -1, -1);""", """    llama_batch_free(batch);
    g_hb_phase = 0;
    for (int s = 0; s < NS; ++s) {
        llama_memory_seq_rm(mem, s, -1, -1);""")
s = rep(s, """    g_pick_debug = env_int("HTPD_PICK_DEBUG", 0) != 0;""", """    g_pick_debug = env_int("HTPD_PICK_DEBUG", 0) != 0;
    if (env_int("HTPD_HEARTBEAT", 1) != 0) std::thread(hb_thread).detach();""")
open(p, "w", encoding="utf-8", newline="\n").write(s); open(rl, "w", encoding="utf-8", newline="\n").write(r)
print("v8x3b patched")
