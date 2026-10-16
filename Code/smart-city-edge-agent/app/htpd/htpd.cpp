// htpd: batched multi-agent inference daemon for the QIDK NPU (llama.cpp Hexagon backend).
//
// Why: the incident pipeline fires N independent agent calls, then one synthesizer call. On the NPU,
// decode is bandwidth-bound, so serving N sequences per weight sweep is the only big latency lever.
// llama-server can batch, but all its slots share one size: slots big enough for the synthesizer
// (~2.5k tokens) x 13 overflow the DSP's mappable memory, and 8-bit KV (to make it fit) halves decode
// speed on HTP. htpd loads the model ONCE and creates two contexts on it:
//   agents: n_seq = A, ctx = A x agent_ctx, per-sequence KV streams (non-unified), f16 KV, flash attn
//   synth : n_seq = 1, ctx = synth_ctx
// Measured on the QIDK (llama-batched-bench, same settings): 13 x (600-token prompt -> 80 tokens) in
// ~23 s vs ~68 s one at a time. Requires GGML_HEXAGON_FA_STREAMS=1 (patched ggml-hexagon, QIDK
// 2026-10-16) so per-stream flash attention runs on HTP instead of the CPU.
//
// Protocol: TCP, one JSON object per line in, one per line out.
//   -> {"kind":"agents","prompts":["...", ...]}      (prompts end with the JSON prefill)
//   -> {"kind":"synth","prompt":"..."}
//   <- {"outputs":[{"text":"...","tokens":n,"ttft_ms":x,"ms":y,"stop":"json|action|eog|max"}],
//       "prefill_ms":p,"total_ms":t}
// Greedy decoding. Generation stops exactly where the app stops (app/backend/answerscan.go): when the
// JSON object closes, or - for agent calls - where the top-level "action" key starts (policy derives
// action), the text then being closed with '}'.

#include "llama.h"
#include "ggml-backend.h"

#if defined(__ARM_NEON)
#include <arm_neon.h>
#endif

#include <arpa/inet.h>
#include <netinet/in.h>
#include <sys/socket.h>
#include <unistd.h>

#include <algorithm>
#include <chrono>
#include <cstdio>
#include <cstdlib>
#include <cstring>
#include <string>
#include <vector>

using clk = std::chrono::steady_clock;
static double ms_since(clk::time_point t) { return std::chrono::duration<double, std::milli>(clk::now() - t).count(); }

// ------------------------------------------------------------------ minimal JSON helpers

static std::string json_escape(const std::string & s) {
    std::string o;
    o.reserve(s.size() + 16);
    for (unsigned char c : s) {
        switch (c) {
            case '"': o += "\\\""; break;
            case '\\': o += "\\\\"; break;
            case '\n': o += "\\n"; break;
            case '\r': o += "\\r"; break;
            case '\t': o += "\\t"; break;
            default:
                if (c < 0x20) { char b[8]; snprintf(b, sizeof b, "\\u%04x", c); o += b; }
                else o += (char) c;
        }
    }
    return o;
}

// parse a JSON string literal starting at s[i] == '"'; returns end index after closing quote
static size_t parse_string(const std::string & s, size_t i, std::string & out) {
    out.clear();
    ++i;
    while (i < s.size() && s[i] != '"') {
        if (s[i] == '\\' && i + 1 < s.size()) {
            char e = s[++i];
            switch (e) {
                case 'n': out += '\n'; break;
                case 't': out += '\t'; break;
                case 'r': out += '\r'; break;
                case 'b': out += '\b'; break;
                case 'f': out += '\f'; break;
                case 'u': {
                    unsigned cp = (unsigned) strtoul(s.substr(i + 1, 4).c_str(), nullptr, 16);
                    i += 4;
                    if (cp >= 0xD800 && cp <= 0xDBFF && i + 6 < s.size() && s[i + 1] == '\\' && s[i + 2] == 'u') {
                        unsigned lo = (unsigned) strtoul(s.substr(i + 3, 4).c_str(), nullptr, 16);
                        cp = 0x10000 + ((cp - 0xD800) << 10) + (lo - 0xDC00);
                        i += 6;
                    }
                    if (cp < 0x80) out += (char) cp;
                    else if (cp < 0x800) { out += (char) (0xC0 | (cp >> 6)); out += (char) (0x80 | (cp & 0x3F)); }
                    else if (cp < 0x10000) { out += (char) (0xE0 | (cp >> 12)); out += (char) (0x80 | ((cp >> 6) & 0x3F)); out += (char) (0x80 | (cp & 0x3F)); }
                    else { out += (char) (0xF0 | (cp >> 18)); out += (char) (0x80 | ((cp >> 12) & 0x3F)); out += (char) (0x80 | ((cp >> 6) & 0x3F)); out += (char) (0x80 | (cp & 0x3F)); }
                    break;
                }
                default: out += e;
            }
        } else {
            out += s[i];
        }
        ++i;
    }
    return i + 1;
}

// find "key": and return position of its value
static size_t find_key(const std::string & s, const char * key) {
    std::string k = std::string("\"") + key + "\"";
    size_t p = s.find(k);
    if (p == std::string::npos) return p;
    p = s.find(':', p + k.size());
    if (p == std::string::npos) return p;
    ++p;
    while (p < s.size() && isspace((unsigned char) s[p])) ++p;
    return p;
}

// ------------------------------------------------------------------ the app's stop rule

struct Scanner {
    int depth = 0;
    bool in_str = false, esc = false, after_colon = false, in_key = false, trim;
    std::string key, text;
    std::string stop;

    Scanner(const std::string & prefill, bool trim_action) : trim(trim_action) { feed(prefill, false); }

    // returns true when generation must stop
    bool feed(const std::string & s, bool count = true) {
        for (char c : s) {
            if (count) text += c;
            if (in_str) {
                if (esc) { esc = false; }
                else if (c == '\\') { esc = true; }
                else if (c == '"') {
                    in_str = false;
                    if (in_key) {
                        in_key = false;
                        if (trim && depth == 1 && key == "action") {
                            // cut at the comma before "action" and close the object
                            size_t q = text.rfind("\"action\"");
                            size_t comma = text.rfind(',', q);
                            if (comma != std::string::npos) text = text.substr(0, comma);
                            text += "}";
                            stop = "action";
                            return true;
                        }
                    }
                } else if (in_key) {
                    key += c;
                }
                continue;
            }
            if (c == '"') {
                in_str = true;
                if (depth == 1 && !after_colon) { in_key = true; key.clear(); }
            } else if (c == '{' || c == '[') {
                ++depth; after_colon = false;
            } else if (c == '}' || c == ']') {
                if (--depth == 0) { stop = "json"; return true; }
            } else if (c == ':') {
                after_colon = true;
            } else if (c == ',') {
                after_colon = false;
            }
        }
        return false;
    }
};

static std::string prefill_of(const std::string & prompt) {
    const std::string m = "<|end_header_id|>\n\n";
    size_t i = prompt.rfind(m);
    return i == std::string::npos ? std::string() : prompt.substr(i + m.size());
}

// ------------------------------------------------------------------ inference

struct Out {
    std::string text, stop;
    int tokens = 0;
    double ttft_ms = 0, ms = 0;
};

static const llama_vocab * g_vocab;
static int g_max_new = 320;

static std::vector<llama_token> tokenize(const std::string & s) {
    std::vector<llama_token> t(s.size() + 16);
    int n = llama_tokenize(g_vocab, s.c_str(), (int) s.size(), t.data(), (int) t.size(), false, true);
    if (n < 0) { t.resize(-n); n = llama_tokenize(g_vocab, s.c_str(), (int) s.size(), t.data(), (int) t.size(), false, true); }
    t.resize(std::max(n, 0));
    return t;
}

static std::string piece(llama_token tok) {
    char buf[256];
    int n = llama_token_to_piece(g_vocab, tok, buf, sizeof buf, 0, false);
    return n > 0 ? std::string(buf, n) : std::string();
}

// greedy pick = first index of the maximum (same as the scalar loop). NEON max-reduce, then a scan for
// the first element equal to it: ~4x fewer cycles than the compare-and-branch loop over 128k logits,
// which ran up to 32 times per decode step (QIDK 2026-10-16). Falls back to the scalar loop on NaN.
static llama_token argmax(const float * logits, int n_vocab) {
#if defined(__ARM_NEON)
    if (n_vocab >= 16) {
        float32x4_t m0 = vld1q_f32(logits), m1 = vld1q_f32(logits + 4), m2 = vld1q_f32(logits + 8), m3 = vld1q_f32(logits + 12);
        int i = 16;
        for (; i + 16 <= n_vocab; i += 16) {
            m0 = vmaxq_f32(m0, vld1q_f32(logits + i));      m1 = vmaxq_f32(m1, vld1q_f32(logits + i + 4));
            m2 = vmaxq_f32(m2, vld1q_f32(logits + i + 8));  m3 = vmaxq_f32(m3, vld1q_f32(logits + i + 12));
        }
        float mx = vmaxvq_f32(vmaxq_f32(vmaxq_f32(m0, m1), vmaxq_f32(m2, m3)));
        for (; i < n_vocab; ++i) mx = logits[i] > mx ? logits[i] : mx;
        for (int j = 0; j < n_vocab; ++j) if (logits[j] == mx) return j;
    }
#endif
    int best = 0;
    for (int i = 1; i < n_vocab; ++i) if (logits[i] > logits[best]) best = i;
    return best;
}

// run prompts as parallel sequences 0..n-1 on ctx; returns per-prompt outputs and prefill time
static std::vector<Out> run_batch(llama_context * ctx, const std::vector<std::string> & prompts, bool trim_action,
                                  double & prefill_ms) {
    const int n = (int) prompts.size();
    const int n_vocab = llama_vocab_n_tokens(g_vocab);
    const int n_batch = (int) llama_n_batch(ctx);
    llama_memory_t mem = llama_get_memory(ctx);
    for (int s = 0; s < (int) llama_n_seq_max(ctx); ++s) llama_memory_seq_rm(mem, s, -1, -1);

    std::vector<Out> out(n);
    std::vector<std::vector<llama_token>> toks(n);
    std::vector<Scanner> scan;
    scan.reserve(n);
    for (int i = 0; i < n; ++i) { toks[i] = tokenize(prompts[i]); scan.emplace_back(prefill_of(prompts[i]), trim_action); }

    auto t0 = clk::now();
    llama_batch batch = llama_batch_init(std::max(n_batch, n), 0, 1);
    std::vector<int> logit_idx(n, -1);   // index in the current batch holding seq i's next-token logits
    std::vector<int> pos(n, 0);

    // ---- shared prefixes: agents of the same role share a ~350-token system prompt. Prefill each
    // shared prefix once on a leader stream, copy it to the other streams (llama_memory_seq_cp across
    // streams copies the KV buffer), and prefill only each prompt's own tail.
    std::vector<int> start(n, 0);
    // ---- cross-request prefix cache (HTPD_PREFIX_CACHE=1): the system turn of each role (tokens up
    // to the first <|eot_id|>) is identical in every incident. Its KV is saved to host memory the first
    // time and restored into a leader stream afterwards; same-role streams get it by seq_cp.
    if (trim_action && getenv("HTPD_PREFIX_CACHE") != nullptr) {
        static std::vector<std::pair<std::vector<llama_token>, std::vector<uint8_t>>> cache;
        auto tpc = clk::now();
        int n_hit = 0, n_saved = 0, n_cp = 0, n_skip = 0;
        // the turn delimiter as it appears in OUR prompts (vocab EOT metadata may name another id)
        static const llama_token eot = [] { auto t = tokenize("<|eot_id|>"); return t.size() == 1 ? t[0] : llama_vocab_eot(g_vocab); }();
        std::vector<int> leader_of(n, -1);
        for (int i = 0; i < n; ++i) {
            auto it = std::find(toks[i].begin(), toks[i].end(), eot);
            if (it == toks[i].end()) { n_skip++; continue; }
            const int P = (int) (it - toks[i].begin()) + 1;
            if (P < 64 || P >= (int) toks[i].size()) { n_skip++; continue; }
            // a stream earlier in this batch with the same system turn becomes this one's leader
            int lead = -1;
            for (int j = 0; j < i; ++j)
                if (leader_of[j] == j && start[j] == P && std::equal(toks[j].begin(), toks[j].begin() + P, toks[i].begin())) { lead = j; break; }
            if (lead >= 0) {
                // restore the cached blob (~40 MB memcpy) instead of a whole-stream seq_cp (~88 MB
                // through host memory: Hexagon has no device-to-device copy)
                std::vector<llama_token> mkey(toks[i].begin(), toks[i].begin() + P);
                auto mh = std::find_if(cache.begin(), cache.end(), [&](auto & e) { return e.first == mkey; });
                if (mh == cache.end() || llama_state_seq_set_data(ctx, mh->second.data(), mh->second.size(), i) == 0)
                    llama_memory_seq_cp(mem, lead, i, -1, -1);
                leader_of[i] = lead; start[i] = P; n_cp++;
                continue;
            }
            std::vector<llama_token> key(toks[i].begin(), toks[i].begin() + P);
            auto hit = std::find_if(cache.begin(), cache.end(), [&](auto & e) { return e.first == key; });
            if (hit != cache.end()) {
                if (llama_state_seq_set_data(ctx, hit->second.data(), hit->second.size(), i) == 0) { n_skip++; continue; }
                n_hit++;
            } else {
                // prefill the system turn alone, then save it
                for (int k = 0; k < P; ) {
                    batch.n_tokens = 0;
                    for (; k < P && batch.n_tokens < n_batch; ++k) {
                        int idx = batch.n_tokens++;
                        batch.token[idx] = toks[i][k]; batch.pos[idx] = k; batch.n_seq_id[idx] = 1;
                        batch.seq_id[idx][0] = i; batch.logits[idx] = false;
                    }
                    if (llama_decode(ctx, batch) != 0) { fprintf(stderr, "htpd: prefix-cache prefill failed\n"); break; }
                }
                std::vector<uint8_t> st(llama_state_seq_get_size(ctx, i));
                st.resize(llama_state_seq_get_data(ctx, st.data(), st.size(), i));
                if (!st.empty()) { cache.emplace_back(std::move(key), std::move(st)); n_saved++; }
            }
            leader_of[i] = i; start[i] = P;
        }
        fprintf(stderr, "htpd: prefix cache: %d hit, %d saved, %d member restores, %d skipped, %.0f ms, cache %zu\n",
                n_hit, n_saved, n_cp, n_skip, ms_since(tpc), cache.size());
    }
    bool have_prefix = std::any_of(start.begin(), start.end(), [](int v) { return v > 0; });
    if (n > 1 && !have_prefix && getenv("HTPD_NO_PREFIX") == nullptr) {
        std::vector<int> lead(n, -1);
        auto lcp = [&](int a, int b) {
            size_t m = std::min(toks[a].size(), toks[b].size()) - 1;  // keep >= 1 token per tail
            size_t k = 0;
            while (k < m && toks[a][k] == toks[b][k]) ++k;
            return (int) k;
        };
        std::vector<std::pair<int, int>> groups;  // (leader, prefix length)
        for (int i = 0; i < n; ++i) {
            if (lead[i] != -1) continue;
            int L = INT32_MAX, members = 0;
            for (int j = i + 1; j < n; ++j) {
                if (lead[j] != -1) continue;
                int l = lcp(i, j);
                if (l >= 64) { lead[j] = i; L = std::min(L, l); ++members; }
            }
            if (members > 0) { lead[i] = i; groups.emplace_back(i, L); }
        }
        if (!groups.empty()) {
            // phase A: the prefixes, no logits needed
            std::vector<std::pair<int, int>> pre_order;
            for (auto & g : groups) for (int j = 0; j < g.second; ++j) pre_order.emplace_back(g.first, j);
            size_t k = 0;
            while (k < pre_order.size()) {
                batch.n_tokens = 0;
                for (int b = 0; b < n_batch && k < pre_order.size(); ++b, ++k) {
                    auto [s, j] = pre_order[k];
                    int idx = batch.n_tokens++;
                    batch.token[idx] = toks[s][j];
                    batch.pos[idx] = j;
                    batch.n_seq_id[idx] = 1;
                    batch.seq_id[idx][0] = s;
                    batch.logits[idx] = false;
                }
                if (llama_decode(ctx, batch) != 0) { fprintf(stderr, "htpd: prefix decode failed\n"); break; }
            }
            // phase B: copy each leader's prefix to its members
            for (auto & g : groups) {
                start[g.first] = g.second;
                for (int j = 0; j < n; ++j) {
                    if (j != g.first && lead[j] == g.first) {
                        llama_memory_seq_cp(mem, g.first, j, -1, -1);
                        start[j] = g.second;
                    }
                }
            }
        }
    }

    // ---- prefill: interleave all prompts' tokens, n_batch at a time; logits only for each last token
    {
        std::vector<std::pair<int, int>> order;  // (seq, token index)
        size_t total = 0;
        for (int i = 0; i < n; ++i) total += toks[i].size() - start[i];
        order.reserve(total);
        for (int i = 0; i < n; ++i) for (int j = start[i]; j < (int) toks[i].size(); ++j) order.emplace_back(i, j);
        // With per-sequence KV streams llama.cpp splits a batch into ubatches that take the SAME number of
        // tokens from a run of CONSECUTIVE sequence ids (split_equal); anything else leaves small
        // leftover ubatches, each paying a full weight sweep. So each llama_decode here is exactly one
        // such ubatch: the first run of consecutive sequences that still have prompt tokens, T tokens
        // each, T = min(shortest remaining, n_ubatch / run length). HTPD_LEGACY_PREFILL=1 = old order.
        const bool legacy = getenv("HTPD_LEGACY_PREFILL") != nullptr;
        const int n_ub = (int) llama_n_ubatch(ctx);
        std::vector<int> next(n);
        for (int i = 0; i < n; ++i) next[i] = start[i];
        size_t k = 0;
        std::vector<int> plen(n);  // prompt lengths: toks[s] grows by the sampled token below
        for (int i = 0; i < n; ++i) plen[i] = (int) toks[i].size();
        auto remaining = [&](int s) { return plen[s] - next[s]; };
        auto any_left = [&] { for (int s = 0; s < n; ++s) if (remaining(s) > 0) return true; return false; };
        while (legacy ? k < order.size() : any_left()) {
            batch.n_tokens = 0;
            std::fill(logit_idx.begin(), logit_idx.end(), -1);
            auto put = [&](int s, int j) {
                int idx = batch.n_tokens++;
                batch.token[idx] = toks[s][j];
                batch.pos[idx] = j;
                batch.n_seq_id[idx] = 1;
                batch.seq_id[idx][0] = s;
                bool last = j == plen[s] - 1;
                batch.logits[idx] = last;
                if (last) logit_idx[s] = idx;
            };
            if (legacy) {
                for (int b = 0; b < n_batch && k < order.size(); ++b, ++k) put(order[k].first, order[k].second);
            } else {
                int a = 0;
                while (a < n && remaining(a) <= 0) ++a;
                int b = a;
                while (b < n && remaining(b) > 0) ++b;  // run [a, b)
                const int len = b - a;
                int T = n_ub / len;
                for (int s = a; s < b; ++s) T = std::min(T, remaining(s));
                T = std::max(T, 1);
                for (int s = a; s < b; ++s) {
                    for (int t = 0; t < T; ++t) put(s, next[s] + t);
                    next[s] += T;
                }
            }
            if (llama_decode(ctx, batch) != 0) { fprintf(stderr, "htpd: prefill decode failed\n"); break; }
            // sample the first generated token for every sequence whose prompt ended in this chunk
            for (int s = 0; s < n; ++s) {
                if (logit_idx[s] < 0) continue;
                pos[s] = (int) toks[s].size();
                out[s].ttft_ms = ms_since(t0);
                llama_token t = argmax(llama_get_logits_ith(ctx, logit_idx[s]), n_vocab);
                toks[s].push_back(t);  // pending token to feed next
                logit_idx[s] = -2;     // marks: has pending token
            }
        }
    }
    prefill_ms = ms_since(t0);

    // ---- decode: one token per active sequence per step
    std::vector<bool> done(n, false);
    std::vector<llama_token> pending(n);
    for (int s = 0; s < n; ++s) pending[s] = toks[s].back();
    // never let a sequence overflow its KV stream (n_ctx / n_seq cells): cap its new tokens
    const int per_seq = (int) (llama_n_ctx(ctx) / std::max<uint32_t>(1, llama_n_seq_max(ctx)));
    std::vector<int> room(n);
    for (int s = 0; s < n; ++s) room[s] = std::min(g_max_new, per_seq - pos[s] - 1);
    int active = n;
    auto handle = [&](int s, llama_token t) {
        if (llama_vocab_is_eog(g_vocab, t)) { done[s] = true; out[s].stop = "eog"; return; }
        out[s].tokens++;
        if (scan[s].feed(piece(t))) { done[s] = true; out[s].stop = scan[s].stop; return; }
        if (out[s].tokens >= room[s]) { done[s] = true; out[s].stop = out[s].tokens >= g_max_new ? "max" : "ctx"; }
    };
    for (int s = 0; s < n; ++s) handle(s, pending[s]);
    for (int s = 0; s < n; ++s) if (done[s]) { out[s].ms = ms_since(t0); llama_memory_seq_rm(mem, s, -1, -1); active--; }

    // ---- batched verified drafting (HTPD_DRAFT=1). Agents of one role emit near-identical JSON
    // scaffolding and copy numbers from their prompts, so the next token is often predictable by
    // n-gram lookup (other streams of this batch, recent outputs, the stream's own prompt). Every
    // active stream feeds [pending, draft] - equal rows per stream keep it ONE ubatch (split_equal),
    // 26 rows still fit the 32-row HMX tile. The draft is kept only if it equals the greedy argmax at
    // that position, and then the token after it is taken too; otherwise its KV is dropped. Greedy
    // output is unchanged by construction.
    static const bool draft_on = getenv("HTPD_DRAFT") != nullptr;
    static std::vector<std::vector<llama_token>> g_recent;  // recent outputs (generated tokens)
    if (draft_on) {
        std::vector<std::vector<llama_token>> hist(n);
        std::vector<int> gen0(n);
        for (int s = 0; s < n; ++s) { hist[s] = toks[s]; gen0[s] = (int) toks[s].size() - 1; }
        for (int s = 0; s < n; ++s) room[s] = std::max(0, room[s] - 5);  // drafts occupy up to 4 more cells
        auto search = [](const std::vector<llama_token> & v, int from, int to, const llama_token * key, int ng) -> int {
            for (int p = to - ng - 1; p >= from; --p) {
                bool m = true;
                for (int q = 0; q < ng; ++q) if (v[p + q] != key[q]) { m = false; break; }
                if (m) return v[p + ng];
            }
            return -1;
        };
        auto propose = [&](int s) -> int {
            const auto & h = hist[s];
            const int L = (int) h.size();
            for (int ng = 3; ng >= 1; --ng) {
                if (L < ng + 1) continue;
                const llama_token * key = h.data() + L - ng;
                for (int o = 0; o < n; ++o) {
                    if (o == s) continue;
                    int t = search(hist[o], gen0[o], (int) hist[o].size(), key, ng);
                    if (t >= 0) return t;
                }
                for (auto it = g_recent.rbegin(); it != g_recent.rend(); ++it) {
                    int t = search(*it, 0, (int) it->size(), key, ng);
                    if (t >= 0) return t;
                }
                int t = search(h, 0, L - 1, key, ng);
                if (t >= 0) return t;
            }
            return -1;
        };
        // chain: extend the history with each proposed token and look up again
        auto propose_chain = [&](int s, int k) {
            std::vector<llama_token> d;
            const size_t L0 = hist[s].size();
            for (int j = 0; j < k; ++j) {
                int t = propose(s);
                if (t < 0) break;
                d.push_back(t);
                hist[s].push_back(t);  // temporary, rolled back below
            }
            hist[s].resize(L0);
            return d;
        };
        static const int kmax = getenv("HTPD_DRAFT_K") ? atoi(getenv("HTPD_DRAFT_K")) : 4;
        int steps = 0, accepted = 0, proposed = 0;
        while (active > 0) {
            batch.n_tokens = 0;
            int lo = n, hi = -1, n_act = 0;
            for (int s = 0; s < n; ++s) if (!done[s]) { lo = std::min(lo, s); hi = std::max(hi, s); n_act++; }
            // rows are free up to the 32-row HMX tile: k drafts per stream with (k+1) * streams <= 32
            const int n_run = hi - lo + 1;  // parked streams in the run take rows too
            const int k = std::max(1, std::min(kmax, 32 / std::max(1, n_run) - 1));
            std::vector<std::vector<int>> ri(n);
            std::vector<std::vector<llama_token>> drs(n);
            auto add = [&](llama_token t, int p, int s, bool lg) {
                int idx = batch.n_tokens++;
                batch.token[idx] = t; batch.pos[idx] = p; batch.n_seq_id[idx] = 1; batch.seq_id[idx][0] = s;
                batch.logits[idx] = lg;
                return idx;
            };
            for (int s = 0; s < n; ++s) {
                if (done[s]) {
                    if (s > lo && s < hi) {
                        llama_memory_seq_rm(mem, s, -1, -1);
                        for (int j = 0; j <= k; ++j) add(pending[s], j, s, false);
                    }
                    continue;
                }
                drs[s] = propose_chain(s, k);
                proposed += (int) drs[s].size();
                ri[s].push_back(add(pending[s], pos[s], s, true));
                for (int j = 0; j < k; ++j)  // pad with the pending token: a draft that is simply rejected
                    ri[s].push_back(add(j < (int) drs[s].size() ? drs[s][j] : pending[s], pos[s] + 1 + j, s, true));
            }
            if (llama_decode(ctx, batch) != 0) { fprintf(stderr, "htpd: draft decode failed\n"); break; }
            steps++;
            for (int s = 0; s < n; ++s) {
                if (ri[s].empty()) continue;
                // row j's argmax is the token after input j; accept drafts while they match it
                int used = 0;  // number of inputs whose outputs are valid (pending + accepted drafts)
                llama_token t = 0;
                for (int j = 0; j <= k; ++j) {
                    t = argmax(llama_get_logits_ith(ctx, ri[s][j]), n_vocab);
                    used = j + 1;
                    hist[s].push_back(t);
                    handle(s, t);
                    if (done[s]) break;
                    if (j < (int) drs[s].size() && t == drs[s][j]) { accepted++; continue; }
                    break;
                }
                pending[s] = t;
                pos[s] += used;
                llama_memory_seq_rm(mem, s, pos[s], -1);  // drop KV of rejected drafts
                if (done[s]) { out[s].ms = ms_since(t0); llama_memory_seq_rm(mem, s, -1, -1); active--; }
            }
        }
        for (int s = 0; s < n; ++s) {
            g_recent.emplace_back(hist[s].begin() + gen0[s], hist[s].end());
            if (g_recent.size() > 64) g_recent.erase(g_recent.begin());
        }
        fprintf(stderr, "htpd: draft steps %d proposed %d accepted %d\n", steps, proposed, accepted);
    }
    while (!draft_on && active > 0) {
        batch.n_tokens = 0;
        std::vector<int> idx_of(n, -1);
        // Finished streams that sit BETWEEN active ones would split this step into one ubatch per run
        // of consecutive ids (split_equal), each a full weight sweep. Park them with a throwaway token at
        // position 0 (no logits, KV cleared every step) so the active ids stay one run; rows up to the
        // 32-row HMX tile cost nothing extra. HTPD_NO_PARK=1 disables this.
        static const bool no_park = getenv("HTPD_NO_PARK") != nullptr;
        int lo = n, hi = -1;
        for (int s = 0; s < n; ++s) if (!done[s]) { lo = std::min(lo, s); hi = std::max(hi, s); }
        for (int s = 0; s < n; ++s) {
            if (done[s]) {
                if (!no_park && s > lo && s < hi) {
                    llama_memory_seq_rm(mem, s, -1, -1);
                    int idx = batch.n_tokens++;
                    batch.token[idx] = pending[s];
                    batch.pos[idx] = 0;
                    batch.n_seq_id[idx] = 1;
                    batch.seq_id[idx][0] = s;
                    batch.logits[idx] = false;
                }
                continue;
            }
            int idx = batch.n_tokens++;
            batch.token[idx] = pending[s];
            batch.pos[idx] = pos[s]++;
            batch.n_seq_id[idx] = 1;
            batch.seq_id[idx][0] = s;
            batch.logits[idx] = true;
            idx_of[s] = idx;
        }
        if (llama_decode(ctx, batch) != 0) { fprintf(stderr, "htpd: decode failed\n"); break; }
        for (int s = 0; s < n; ++s) {
            if (idx_of[s] < 0) continue;
            pending[s] = argmax(llama_get_logits_ith(ctx, idx_of[s]), n_vocab);
            handle(s, pending[s]);
            if (done[s]) { out[s].ms = ms_since(t0); llama_memory_seq_rm(mem, s, -1, -1); active--; }
        }
    }
    llama_batch_free(batch);
    for (int s = 0; s < n; ++s) out[s].text = scan[s].text;
    return out;
}

// ------------------------------------------------------------------ prompt-lookup speculation
//
// The synthesizer's JSON copies long spans of its own prompt (sensor names, agent findings, numbers).
// Draft up to k tokens by finding the latest earlier occurrence of the last few tokens in
// prompt+generated text and proposing what followed it; verify all drafts in ONE decode; keep the
// longest prefix that greedy decoding would also have produced. Accepted tokens are exactly the
// greedy argmax at each position, so the text equals plain greedy decoding (up to batch-vs-single
// numerics, checked against the non-speculative path).

static int g_spec_k = 8;

static std::vector<Out> run_single_spec(llama_context * ctx, const std::string & prompt, double & prefill_ms) {
    const int n_vocab = llama_vocab_n_tokens(g_vocab);
    llama_memory_t mem = llama_get_memory(ctx);
    llama_memory_seq_rm(mem, 0, -1, -1);
    std::vector<Out> out(1);
    std::vector<llama_token> hist = tokenize(prompt);
    Scanner scan(prefill_of(prompt), false);
    const int n_prompt = (int) hist.size();
    const int n_ctx = (int) llama_n_ctx(ctx);
    const int n_batch = (int) llama_n_batch(ctx);

    auto t0 = clk::now();
    llama_batch batch = llama_batch_init(std::max(n_batch, g_spec_k + 1), 0, 1);
    // prefill
    llama_token pending = 0;
    for (int i = 0; i < n_prompt; ) {
        batch.n_tokens = 0;
        for (; i < n_prompt && batch.n_tokens < n_batch; ++i) {
            int idx = batch.n_tokens++;
            batch.token[idx] = hist[i]; batch.pos[idx] = i; batch.n_seq_id[idx] = 1; batch.seq_id[idx][0] = 0;
            batch.logits[idx] = (i == n_prompt - 1);
        }
        if (llama_decode(ctx, batch) != 0) { fprintf(stderr, "htpd: spec prefill failed\n"); llama_batch_free(batch); return out; }
    }
    pending = argmax(llama_get_logits_ith(ctx, batch.n_tokens - 1), n_vocab);
    prefill_ms = ms_since(t0);
    out[0].ttft_ms = prefill_ms;
    int pos = n_prompt;
    int steps = 0, drafted = 0, accepted_total = 0;

    auto emit = [&](llama_token t) -> bool {  // true = stop
        if (llama_vocab_is_eog(g_vocab, t)) { out[0].stop = "eog"; return true; }
        out[0].tokens++;
        hist.push_back(t);
        if (scan.feed(piece(t))) { out[0].stop = scan.stop; return true; }
        if (out[0].tokens >= g_max_new || pos + g_spec_k + 2 >= n_ctx) { out[0].stop = out[0].tokens >= g_max_new ? "max" : "ctx"; return true; }
        return false;
    };
    if (emit(pending)) goto done;

    for (;;) {
        // draft: match the last n tokens (n = 4..1) at an earlier position, propose what followed
        std::vector<llama_token> draft;
        for (int ng = 4; ng >= 1 && draft.empty(); --ng) {
            if ((int) hist.size() <= ng) continue;
            const int tail = (int) hist.size() - ng;
            for (int p = tail - 1; p >= 0; --p) {
                bool m = true;
                for (int q = 0; q < ng; ++q) if (hist[p + q] != hist[tail + q]) { m = false; break; }
                if (!m) continue;
                for (int q = p + ng; q < (int) hist.size() && (int) draft.size() < g_spec_k; ++q) draft.push_back(hist[q]);
                break;
            }
        }
        // verify: [pending, d1..dk] in one decode
        batch.n_tokens = 0;
        auto add = [&](llama_token t, int p) {
            int idx = batch.n_tokens++;
            batch.token[idx] = t; batch.pos[idx] = p; batch.n_seq_id[idx] = 1; batch.seq_id[idx][0] = 0; batch.logits[idx] = true;
        };
        add(pending, pos);
        for (size_t j = 0; j < draft.size(); ++j) add(draft[j], pos + 1 + (int) j);
        if (llama_decode(ctx, batch) != 0) { fprintf(stderr, "htpd: spec decode failed\n"); break; }
        steps++; drafted += (int) draft.size();
        // accept the longest matching prefix; the first mismatch's argmax becomes the next pending
        int acc = 0;
        llama_token next = argmax(llama_get_logits_ith(ctx, 0), n_vocab);
        bool stop = false;
        while (true) {
            if (acc < (int) draft.size() && next == draft[acc]) {
                if (emit(next)) { stop = true; break; }
                ++acc;
                next = argmax(llama_get_logits_ith(ctx, acc), n_vocab);
            } else {
                break;
            }
        }
        accepted_total += acc;
        pos += 1 + acc;                                   // pending + accepted drafts are now in the KV
        llama_memory_seq_rm(mem, 0, pos, -1);             // drop rejected draft positions
        if (stop) break;
        pending = next;
        if (emit(pending)) break;
    }
done:
    out[0].ms = ms_since(t0);
    out[0].text = scan.text;
    fprintf(stderr, "htpd: spec steps %d drafted %d accepted %d tokens %d\n", steps, drafted, accepted_total, out[0].tokens);
    llama_batch_free(batch);
    return out;
}

// ------------------------------------------------------------------ main / server

int main(int argc, char ** argv) {
    const char * model_path = nullptr;
    const char * dev_name = "HTP0";
    int port = 8091, n_agents = 13, agent_ctx = 1024, synth_ctx = 4096, n_threads = 4, n_ubatch = 512, n_ubatch_synth = 1024;
    for (int i = 1; i < argc; ++i) {
        std::string a = argv[i];
        auto next = [&]() { return i + 1 < argc ? argv[++i] : (char *) ""; };
        if (a == "-m") model_path = next();
        else if (a == "--device") dev_name = next();
        else if (a == "--port") port = atoi(next());
        else if (a == "--agents") n_agents = atoi(next());
        else if (a == "--agent-ctx") agent_ctx = atoi(next());
        else if (a == "--synth-ctx") synth_ctx = atoi(next());
        else if (a == "--max-new") g_max_new = atoi(next());
        else if (a == "-t") n_threads = atoi(next());
        else if (a == "--ubatch") n_ubatch = atoi(next());
        else if (a == "--ubatch-synth") n_ubatch_synth = atoi(next());
        else if (a == "--spec-k") g_spec_k = atoi(next());
    }
    if (!model_path) { fprintf(stderr, "usage: htpd -m model.gguf [--device HTP0] [--port 8091] [--agents 13] [--agent-ctx 1024] [--synth-ctx 4096]\n"); return 1; }

    llama_backend_init();
    ggml_backend_load_all();
    ggml_backend_dev_t devs[2] = { ggml_backend_dev_by_name(dev_name), nullptr };
    if (!devs[0]) { fprintf(stderr, "htpd: device %s not found\n", dev_name); return 1; }

    auto mp = llama_model_default_params();
    mp.devices = devs;
    mp.n_gpu_layers = 99;
    auto t_load = clk::now();
    llama_model * model = llama_model_load_from_file(model_path, mp);
    if (!model) { fprintf(stderr, "htpd: model load failed\n"); return 1; }
    g_vocab = llama_model_get_vocab(model);

    // ONE context at a time: weights + 13-stream KV + a second 4k context exceed what one DSP session
    // can map (fastrpc_mmap fails, measured). The agent context stays resident; a synthesizer call
    // swaps in a single-sequence context (weights stay loaded, so a swap is cheap).
    auto make_ctx = [&](bool agents_ctx) {
        auto cp = llama_context_default_params();
        cp.flash_attn_type = LLAMA_FLASH_ATTN_TYPE_ENABLED;
        cp.n_threads = cp.n_threads_batch = n_threads;
        cp.kv_unified = false;
        cp.n_seq_max = agents_ctx ? n_agents : 1;
        cp.n_ctx = agents_ctx ? (uint32_t) (n_agents * agent_ctx) : (uint32_t) synth_ctx;
        cp.n_batch = 2048;
        cp.n_ubatch = agents_ctx ? n_ubatch : n_ubatch_synth;  // the synth context is alone on the DSP
        return llama_init_from_model(model, cp);
    };
    llama_context * ctx = make_ctx(true);
    bool ctx_is_agents = true;
    if (!ctx) { fprintf(stderr, "htpd: context creation failed\n"); return 1; }
    fprintf(stderr, "htpd: ready in %.0f ms: %d agent streams x %d ctx, synth ctx %d, device %s, port %d\n",
            ms_since(t_load), n_agents, agent_ctx, synth_ctx, dev_name, port);

    int srv = socket(AF_INET, SOCK_STREAM, 0);
    int one = 1;
    setsockopt(srv, SOL_SOCKET, SO_REUSEADDR, &one, sizeof one);
    sockaddr_in addr{};
    addr.sin_family = AF_INET;
    addr.sin_port = htons(port);
    addr.sin_addr.s_addr = htonl(INADDR_LOOPBACK);
    if (bind(srv, (sockaddr *) &addr, sizeof addr) != 0 || listen(srv, 8) != 0) { perror("htpd: bind/listen"); return 1; }

    for (;;) {
        int c = accept(srv, nullptr, nullptr);
        if (c < 0) continue;
        std::string buf;
        char tmp[65536];
        for (;;) {
            ssize_t r = read(c, tmp, sizeof tmp);
            if (r <= 0) break;
            buf.append(tmp, r);
            size_t nl;
            while ((nl = buf.find('\n')) != std::string::npos) {
                std::string line = buf.substr(0, nl);
                buf.erase(0, nl + 1);
                auto t0 = clk::now();
                std::string kind;
                size_t p = find_key(line, "kind");
                if (p != std::string::npos && line[p] == '"') parse_string(line, p, kind);
                std::vector<std::string> prompts;
                bool agents = kind == "agents";
                if (agents) {
                    p = find_key(line, "prompts");
                    if (p != std::string::npos && line[p] == '[') {
                        ++p;
                        while (p < line.size() && line[p] != ']') {
                            if (line[p] == '"') { std::string s; p = parse_string(line, p, s); prompts.push_back(s); }
                            else ++p;
                        }
                    }
                } else {
                    p = find_key(line, "prompt");
                    if (p != std::string::npos && line[p] == '"') { std::string s; parse_string(line, p, s); prompts.push_back(s); }
                }
                std::string resp;
                if (prompts.empty() || (agents && (int) prompts.size() > n_agents) || (!agents && prompts.size() != 1)) {
                    resp = "{\"error\":\"bad request\"}";
                } else {
                    double pre = 0, swap_ms = 0;
                    if (ctx_is_agents != agents) {
                        auto ts = clk::now();
                        llama_free(ctx);
                        ctx = make_ctx(agents);
                        ctx_is_agents = agents;
                        swap_ms = ms_since(ts);
                        if (!ctx) { fprintf(stderr, "htpd: context swap failed\n"); return 1; }
                    }
                    // HTPD_SPEC=0 turns prompt-lookup speculation off for the synthesizer
                    const char * spec_env = getenv("HTPD_SPEC");
                    bool spec = !agents && (spec_env == nullptr || atoi(spec_env) != 0);
                    auto outs = spec ? run_single_spec(ctx, prompts[0], pre) : run_batch(ctx, prompts, agents, pre);
                    resp = "{\"outputs\":[";
                    for (size_t i = 0; i < outs.size(); ++i) {
                        char num[160];
                        snprintf(num, sizeof num, "\",\"tokens\":%d,\"ttft_ms\":%.1f,\"ms\":%.1f,\"stop\":\"%s\"}",
                                 outs[i].tokens, outs[i].ttft_ms, outs[i].ms, outs[i].stop.c_str());
                        resp += (i ? ",{\"text\":\"" : "{\"text\":\"") + json_escape(outs[i].text) + num;
                    }
                    char tail[96];
                    snprintf(tail, sizeof tail, "],\"prefill_ms\":%.1f,\"swap_ms\":%.1f,\"total_ms\":%.1f}", pre, swap_ms, ms_since(t0));
                    resp += tail;
                }
                resp += "\n";
                (void) !write(c, resp.data(), resp.size());
            }
        }
        close(c);
    }
}
