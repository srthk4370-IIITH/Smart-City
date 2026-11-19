// Bit-identity test for the parallel Hexagon weight repack (rp1).
// Compiles the patched ggml-hexagon.cpp into this binary and compares, for random quantized tensors,
// the original single-threaded repack (repack_tensor_tiled_serial) with the parallel one (repack_tensor_tiled),
// byte for byte, over the full allocated tiled buffer. The two destination buffers are pre-filled with
// DIFFERENT patterns so a byte left unwritten by one path but written by the other is also caught.
// Thread count comes from GGML_HEXAGON_REPACK_THREADS (run the binary several times with different values).
#include "ggml-hexagon.rp.cpp"

#include <chrono>
#include <random>

struct tcase { ggml_type type; int64_t ne0, ne1, ne2, ne3; const char * what; };

static double now_ms() {
    return std::chrono::duration<double, std::milli>(std::chrono::steady_clock::now().time_since_epoch()).count();
}

int main(int argc, char ** argv) {
    unsigned seed = argc > 1 ? (unsigned) atoi(argv[1]) : 1234u;
    const tcase cases[] = {
        // shapes of the deployed Qwen3.5-0.8B-class reasoner and agents (hidden 1024, ffn 3584; vocab rows capped at 32768 to fit RAM) and edge cases
        { GGML_TYPE_Q4_0,  1024,   3584, 1, 1, "ffn_up/gate-like" },
        { GGML_TYPE_Q4_0,  3584,   1024, 1, 1, "ffn_down-like" },
        { GGML_TYPE_Q4_0,  1024,   6144, 1, 1, "qkv-like" },
        { GGML_TYPE_Q4_0,  1024,   1000, 1, 1, "ne1 not multiple of 32" },
        { GGML_TYPE_Q4_0,  2048,     33, 1, 1, "ne1=33 (2 col tiles, 31 pad rows)" },
        { GGML_TYPE_Q4_0,   512,    200, 3, 2, "4-D (6 slices), ne1 % 32 != 0" },
        { GGML_TYPE_Q4_0,  1024, 32768, 1, 1, "embd/output-like (large)" },
        { GGML_TYPE_IQ4_NL,1024,   3584, 1, 1, "iq4_nl" },
        { GGML_TYPE_Q8_0,  1024,   3584, 1, 1, "q8_0" },
        { GGML_TYPE_Q8_0,  1056,    999, 1, 1, "q8_0 ne0 not multiple of 256, ne1 odd" },
        { GGML_TYPE_Q8_0,   512,    100, 4, 1, "q8_0 3-D" },
        { GGML_TYPE_Q6_K,  1024, 32768, 1, 1, "q6_K output-like (large)" },
        { GGML_TYPE_Q6_K,  3584,   1024, 1, 1, "q6_K ffn_down-like" },
        { GGML_TYPE_Q6_K,  1024,   1001, 1, 1, "q6_K ne1 odd" },
        { GGML_TYPE_Q6_K,   512,    300, 2, 2, "q6_K 4-D" },
        { GGML_TYPE_Q4_1,  1024,   3584, 1, 1, "q4_1" },
        { GGML_TYPE_MXFP4, 1024,   1000, 1, 1, "mxfp4" },
        { GGML_TYPE_Q4_K,  1024,   3584, 1, 1, "q4_K" },
        { GGML_TYPE_Q4_K,  1024,    777, 2, 1, "q4_K 3-D odd" },
        { GGML_TYPE_Q5_K,  1024,   3584, 1, 1, "q5_K" },
        { GGML_TYPE_Q3_K,  1024,   3584, 1, 1, "q3_K" },
        { GGML_TYPE_Q2_K,  1024,   3584, 1, 1, "q2_K" },
        { GGML_TYPE_Q2_K,   768,    95, 3, 1, "q2_K 3-D odd" },
    };

    printf("rp_test: seed %u, GGML_HEXAGON_REPACK_THREADS=%s -> %d threads, hw %u\n", seed,
           getenv("GGML_HEXAGON_REPACK_THREADS") ? getenv("GGML_HEXAGON_REPACK_THREADS") : "(unset)",
           ggml_hexagon_repack_threads(), std::thread::hardware_concurrency());

    {
        double s0 = now_ms();
        for (int it = 0; it < 20; it++) {
            std::vector<std::thread> w;
            for (int i = 1; i < ggml_hexagon_repack_threads(); i++) w.emplace_back([] {});
            for (auto & x : w) x.join();
        }
        printf("rp_test: spawn+join of %d threads: %.3f ms each\n", ggml_hexagon_repack_threads() - 1, (now_ms() - s0) / 20);
    }

    std::mt19937 rng(seed);
    std::normal_distribution<float> nd(0.0f, 1.0f);
    int fails = 0;
    double ser_ms_tot = 0, par_ms_tot = 0;

    for (const auto & c : cases) {
        ggml_tensor t;
        memset(&t, 0, sizeof(t));
        t.type  = c.type;
        t.ne[0] = c.ne0; t.ne[1] = c.ne1; t.ne[2] = c.ne2; t.ne[3] = c.ne3;
        t.nb[0] = ggml_type_size(c.type);
        t.nb[1] = ggml_row_size(c.type, c.ne0);
        t.nb[2] = t.nb[1] * c.ne1;
        t.nb[3] = t.nb[2] * c.ne2;
        const size_t nbytes = ggml_nbytes(&t);
        const int64_t nrows = c.ne1 * c.ne2 * c.ne3;

        std::vector<float> f((size_t) c.ne0 * nrows);
        for (auto & x : f) x = nd(rng);
        std::vector<uint8_t> q(nbytes);
        size_t qb = ggml_quantize_chunk(c.type, f.data(), q.data(), 0, nrows, c.ne0, nullptr);
        if (qb != nbytes) { printf("FAIL quantize size %zu != %zu\n", qb, nbytes); fails++; continue; }

        const size_t alloc = ggml_hexagon_tiled_row_size(c.type, hex_round_up(c.ne0, 32)) * hex_round_up(c.ne1, 32) * c.ne2 * c.ne3;
        std::vector<uint8_t> a(alloc + 64, 0xA5), b(alloc + 64, 0x5A);

        t.data = a.data();
        double t0 = now_ms();
        repack_tensor_tiled_serial(&t, q.data(), nbytes);
        double t1 = now_ms();
        t.data = b.data();
        repack_tensor_tiled(&t, q.data(), nbytes);
        double t2 = now_ms();
        ser_ms_tot += t1 - t0; par_ms_tot += t2 - t1;

        size_t ndiff = 0, first = (size_t) -1;
        for (size_t i = 0; i < alloc; i++) if (a[i] != b[i]) { if (!ndiff) first = i; ndiff++; }
        bool guard_ok = true;  // nothing written past the allocation
        for (size_t i = alloc; i < alloc + 64; i++) if (a[i] != 0xA5 || b[i] != 0x5A) guard_ok = false;
        // hash for the record
        uint64_t h = 1469598103934665603ull;
        for (size_t i = 0; i < alloc; i++) { h ^= a[i]; h *= 1099511628211ull; }

        const bool ok = ndiff == 0 && guard_ok;
        if (!ok) fails++;
        printf("%-4s %-7s ne=[%lld,%lld,%lld,%lld] src %9zu B tiled %9zu B  serial %8.2f ms  parallel %8.2f ms  diff %zu%s guard %s fnv1a %016llx  (%s)\n",
               ok ? "OK" : "FAIL", ggml_type_name(c.type), (long long) c.ne0, (long long) c.ne1, (long long) c.ne2, (long long) c.ne3,
               nbytes, alloc, t1 - t0, t2 - t1, ndiff, ndiff ? (std::string(" first@") + std::to_string(first)).c_str() : "",
               guard_ok ? "ok" : "BAD", (unsigned long long) h, c.what);
    }
    // scaling probe (not part of the identity check): static split over k threads pinned to the fast cores first
    if (getenv("RP_SCALING")) {
        static const int order[8] = { 7, 4, 3, 2, 6, 5, 1, 0 };
        for (ggml_type ty : { GGML_TYPE_Q4_0, GGML_TYPE_Q6_K }) {
            ggml_tensor t; memset(&t, 0, sizeof(t));
            t.type = ty; t.ne[0] = 1024; t.ne[1] = 32768; t.ne[2] = 1; t.ne[3] = 1;
            t.nb[0] = ggml_type_size(ty); t.nb[1] = ggml_row_size(ty, 1024); t.nb[2] = t.nb[1] * 32768; t.nb[3] = t.nb[2];
            std::vector<uint8_t> q(ggml_nbytes(&t));
            for (size_t i = 0; i < q.size(); i++) q[i] = (uint8_t) (rng() & 0x3f);  // values irrelevant for timing (scales small)
            const size_t alloc = ggml_hexagon_tiled_row_size(ty, 1024) * 32768;
            std::vector<uint8_t> d(alloc, 0);
            t.data = d.data();
            const int64_t n_total = 32768 / 32;
            for (int k : { 1, 2, 3, 4, 6, 8 }) {
                double best = 1e9;
                for (int rep = 0; rep < 3; rep++) {
                    double s0 = now_ms();
                    std::vector<std::thread> w;
                    for (int i = 0; i < k; i++) {
                        w.emplace_back([&, i] {
                            cpu_set_t cs; CPU_ZERO(&cs); CPU_SET(order[i], &cs);
                            sched_setaffinity(0, sizeof(cs), &cs);
                            repack_tensor_tiled_range(&t, q.data(), n_total * i / k, n_total * (i + 1) / k);
                        });
                    }
                    for (auto & x : w) x.join();
                    best = (std::min)(best, now_ms() - s0);
                }
                printf("scaling %s 1024x32768 (%zu MB): %d pinned threads %.2f ms\n", ggml_type_name(ty), q.size() >> 20, k, best);
            }
        }
    }

    printf("rp_test: %s  (%d failures)  serial total %.1f ms  parallel total %.1f ms  speedup %.2fx\n",
           fails ? "FAILED" : "ALL BYTE-IDENTICAL", fails, ser_ms_tot, par_ms_tot, ser_ms_tot / par_ms_tot);
    return fails ? 1 : 0;
}
