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
//
// ---- v7 protocol additions (2026-10-21). All optional; a v6 client sees byte-identical behaviour as long as
// the env flags below are unset. Unknown request keys are ignored and clients must ignore unknown response
// keys, so later additions (e.g. per-stream token streaming) can extend both sides. Full spec with
// examples: proofs/2026-10-21_v2_research/htpd_v7/PROTOCOL.md.
//   request (kind "agents"), per-prompt arrays aligned with "prompts" (null or missing element = none):
//     "labels":  [ ["stable","spike",...] | {"pattern":[...],"status":[...]} | null, ... ]
//                allowed values per top-level key (a bare array = "pattern"), for HTPD_PATTERN_TRIE and
//                the HTPD_JSON_ABORT length rule
//     "draft":   [ "reference completion" | ["completion", ...] | null, ... ]   per-stream draft corpus
//                (HTPD_ROLE_DRAFT); the n-gram table is built once per distinct text set and cached
//     "logprobs": true    -> each output carries the top-5 log-probabilities of its first generated token
//     "id": any           -> echoed back as "id"
//     "stream": true      (agents and synth) -> before the result line, one progress line per decode step:
//                {"kind":"toks","t":["<new raw text of stream 0>","",...]}  (bytes fed to the stop scanner,
//                no action trim, whole UTF-8 characters only; none during prefill). Written by a writer
//                thread so the decode loop never blocks; the unchanged result line is always last.
//   command line: --agent-layouts 14x1024,10x1280  agent KV layouts; a request runs as one batch on the
//                current/first layout that fits it (count, prompt + HTPD_LAYOUT_HEADROOM(136) tokens per
//                stream), else is split by prompt length and merged in request order. Default: the single
//                --agents x --agent-ctx layout (v6).
//   response, per output (only when the feature is on): "stop":"abort" (+ "abort_why"),
//     "forced": n (tokens the label constraint changed), "logprobs":[{"tok":"stable","lp":-0.01},...]
//   env flags (all default off):
//     HTPD_AGENT_MAX_NEW=N   new-token cap for agent batches only (the synthesizer keeps --max-new)
//     HTPD_JSON_ABORT=1|2    stop an agent stream once its text can no longer be JSON of the agent schema
//                            (htpd_logic.h AbortRule); stop reason "abort". 2 = also newline/nesting rule.
//                            HTPD_JSON_ABORT_MAXVAL = enum value length limit when no labels (48)
//     HTPD_PATTERN_TRIE=1|2  greedy argmax restricted, inside a labelled top-level string value, to tokens
//                            that keep the value a prefix of an allowed label (and exactly a label when it
//                            closes). 1 = labels from the request only; 2 = request, else parsed from the
//                            prompt's "JSON keys: pattern (a|b|...)" list. HTPD_TRIE_KEYS (default
//                            "pattern,status") selects which prompt-parsed keys are constrained. Identical
//                            to plain greedy whenever the unconstrained argmax is already allowed.
//     HTPD_ROLE_DRAFT=1      (with HTPD_DRAFT=1) static per-role draft source after the n-gram sources:
//                            request "draft" texts, else HTPD_ROLE_DRAFT_FILE (JSONL lines
//                            {"match":"<substring of the prompt>","texts":[...]}, first match wins).
//                            Verified like every other draft, so outputs are unchanged.
//     HTPD_SYNTH_PREFIX_CACHE=1  (with HTPD_PREFIX_CACHE=1) also cache the synthesizer's system-turn KV
//     HTPD_LOGITS_READ=1     (with HTPD_DRAFT=1) request logits only for the rows that are read (pending +
//                            real drafts); pad rows past a short draft get none, so lm_head runs on fewer rows.
//
// ---- v8 protocol additions (2026-10-22): a LoRA adapter on the synthesizer context ONLY. Without --lora-synth
// the binary behaves exactly like v7 (same code paths, same response bytes). Full spec:
// proofs/2026-10-23_reasoner_research/P0/PROTOCOL_LORA.md.
//   command line: --lora-synth PATH        GGUF LoRA adapter (convert_lora_to_gguf.py, F16 for the HTP backend),
//                                          loaded once at start (llama_adapter_lora_init); a load failure exits 1
//                 (env HTPD_LORA_SYNTH / HTPD_LORA_SYNTH_SCALE: the same, for htpd_profile "env="; flags win)
//                 --lora-synth-scale S     default scale (1.0). The adapter is attached with
//                                          llama_set_adapters_lora to the synthesizer context only (every request
//                                          whose kind is not "agents"); agent contexts never get it.
//   request (any non-"agents" kind, only when --lora-synth is given; ignored otherwise):
//     "lora": false | true | S             off for this request / default scale / scale S (0 = off)
//   response (only when --lora-synth is given): "lora_scale": S actually used (0 = base model).
//   Prefix-cache entries (HTPD_SYNTH_PREFIX_CACHE) are keyed by the adapter scale as well as the tokens, so a
//   system-turn KV computed with the adapter is never restored into a base-model run, nor the reverse.
//
// ---- v8 reasoner additions (2026-10-26, proofs/2026-10-26_reasoner_deploy/htpd_v8/). Without --reasoner-model and
// without the new kinds below, the binary behaves exactly like before (same code paths and response bytes).
//   command line: --reasoner-model PATH  reasoner GGUF (env HTPD_REASONER_MODEL), e.g. Qwen3.5-4B Q4_0 (arch qwen35)
//                 --reason-ctx 4096 --reason-streams 1 --reason-ubatch 512 --reason-max-new 700
//   env: HTPD_REASON_IDLE_MS (20000) release a held reasoner after this idle time; HTPD_REASON_TURN_CACHE=0 /
//        HTPD_REASON_DISK_CACHE=0 turn the last-prompt state cache / the on-disk static-prefix state off.
//   -> {"kind":"caps"}  <- {"caps":["agents","synth","reason","release"],"reasoner":"PATH"|null,"loaded":"agents|reasoner"}
//   -> {"kind":"reason","prompt":"..." | "prompts":[...], "max_new":N, "keep":bool, "prefix":"static prompt prefix",
//       "schema":{"keys":[...],"items":{...},"types":{...},"enums":{...}}, "stream":bool, "id":any}
//      In-process swap: the agents' context and model are freed, the reasoner is loaded (never two models at
//      once), the prompts run (batched prompts share the one swap, --reason-streams at a time as parallel
//      sequences), then the agents' model is reloaded - right after the answer is sent, or with "keep" on the
//      next agents/synth request, a {"kind":"release"}, or after HTPD_REASON_IDLE_MS. A failed reasoner load
//      returns {"error":...} with the agents' model back; a failed agents' reload is retried 3 times, then htpd
//      exits (the app's supervisor restarts it).
//      Decoding: greedy, stop at EOG (tool calls are not JSON) or when the forced JSON answer closes ("json").
//      Hybrid/recurrent model: no draft, no rollback, no seq_cp; "prefix" is cached as a whole sequence state
//      (llama_state_seq_get/set_data; persisted next to the GGUF as PATH.prefix_<hash>.state via .part+rename)
//      and the state after each single-prompt request is kept for the next tool round (longest-prefix match).
//      "schema": the answer's keys, punctuation and unique enum rests are fed as forced tokens (reason_logic.h
//      Forcer; the last forced token is left to the model, constrained, to keep its own tokenization), enum
//      values are constrained to their labels; tool-call turns are never constrained.
//   <- {"outputs":[{"text","tokens","ttft_ms","ms","stop":"eog|json|max|ctx|error","forced":n}],"prefill_ms","swap_ms",
//       "total_ms","reason":{"swapped","unload_ms","load_ms","cache":"mem|disk|saved|turn|none","cached_tokens",
//       "cache_ms","kept","streams"}}   (+ "toks" progress lines with "stream":true, as for the other kinds)
//   -> {"kind":"release"}  <- {"released":bool,"reload_ms":x}
//   The agents' model being hybrid/recurrent turns HTPD_DRAFT / prefix sharing / HTPD_SPEC off for it as well.

#include "htpd_logic.h"
#include "reason_logic.h"
#include "llama.h"
#include "ggml-backend.h"

#if defined(__ARM_NEON)
#include <arm_neon.h>
#endif

#include <arpa/inet.h>
#include <netinet/in.h>
#include <poll.h>
#include <sys/socket.h>
#include <unistd.h>

#include <algorithm>
#include <chrono>
#include <cstdio>
#include <cstdlib>
#include <cstring>
#include <string>
#include <condition_variable>
#include <deque>
#include <memory>
#include <mutex>
#include <thread>
#include <vector>

using clk = std::chrono::steady_clock;
static double ms_since(clk::time_point t) { return std::chrono::duration<double, std::milli>(clk::now() - t).count(); }

// JSON helpers, the app's stop rule (Scanner), label constraint, abort guard and draft table live in
// htpd_logic.h (pure code, unit-tested on the host by test_logic.cpp).
using htpd::json_escape;
using htpd::Scanner;
using htpd::Labels;
using htpd::JVal;

static std::string prefill_of(const std::string & prompt) {
    const std::string m = "<|end_header_id|>\n\n";
    size_t i = prompt.rfind(m);
    return i == std::string::npos ? std::string() : prompt.substr(i + m.size());
}

// ------------------------------------------------------------------ inference

struct Out {
    std::string text, stop, abort_why;
    int tokens = 0;
    int forced = 0;                                  // tokens the label constraint changed
    std::vector<std::pair<std::string, float>> lp;   // top logprobs of the first generated token
    double ttft_ms = 0, ms = 0;
};

// per-stream options of one agent request (all optional)
struct StreamOpt {
    Labels labels;                            // abort length rule labels (request, else prompt-parsed)
    Labels trie_labels;                       // HTPD_PATTERN_TRIE: constrain argmax with these (empty = off)
    const htpd::NgramTable * table = nullptr; // static draft source
};

static const llama_vocab * g_vocab;
static int g_max_new = 320;
static int g_agent_max_new = 0;  // HTPD_AGENT_MAX_NEW (0 = use g_max_new)
static int g_json_abort = 0;     // HTPD_JSON_ABORT
static size_t g_abort_maxval = 48;
static int g_trie = 0;           // HTPD_PATTERN_TRIE
static std::vector<std::string> g_trie_keys = {"pattern", "status"};
static bool g_role_draft = false;  // HTPD_ROLE_DRAFT
static bool g_logits_read = false; // HTPD_LOGITS_READ
static std::vector<std::string> g_pieces;  // token -> piece, filled once when a feature needs it
static std::vector<std::pair<std::string, htpd::NgramTable>> g_file_tables;  // HTPD_ROLE_DRAFT_FILE
// v8: --lora-synth. g_kv_tag != 0 while the current context runs with an adapter (one id per distinct scale);
// it is appended to prefix-cache keys so KV computed with and without the adapter never mix. 0 = v7 keys.
static llama_adapter_lora * g_lora = nullptr;
static float g_lora_scale = 1.0f;
static int g_kv_tag = 0;

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

static const std::string & piece_of(llama_token t) {
    static const std::string empty;
    return t >= 0 && t < (llama_token) g_pieces.size() ? g_pieces[t] : empty;
}

static bool allowed_tok(llama_token t, const htpd::JState & st, const Labels & L) {
    if (llama_vocab_is_eog(g_vocab, t)) return !htpd::in_constrained(st, L);
    return htpd::piece_allowed(st, piece_of(t), L);
}

// greedy pick under the label constraint (HTPD_PATTERN_TRIE): the plain argmax when it is allowed (so the
// output is plain greedy whenever greedy already stays on-label), else the highest-logit allowed token
// (first index on ties, like argmax). The top 64 are tried first; a full scan is the fallback.
static llama_token pick(const float * logits, int n_vocab, const Scanner & sc, const StreamOpt * o, int * forced) {
    llama_token t = argmax(logits, n_vocab);
    if (!o || o->trie_labels.empty()) return t;
    const Labels & L = o->trie_labels;
    if (allowed_tok(t, sc.js, L)) return t;
    constexpr int K = 64;
    std::vector<std::pair<float, int>> top;  // (logit, index), best first; ties keep the lower index first
    top.reserve(K + 1);
    for (int i = 0; i < n_vocab; ++i) {
        if ((int) top.size() == K && !(logits[i] > top.back().first)) continue;
        auto it = std::find_if(top.begin(), top.end(), [&](auto & e) { return logits[i] > e.first; });
        top.insert(it, {logits[i], i});
        if ((int) top.size() > K) top.pop_back();
    }
    llama_token best = -1;
    for (auto & e : top) if (allowed_tok(e.second, sc.js, L)) { best = e.second; break; }
    if (best < 0) {
        float bv = -INFINITY;
        for (int i = 0; i < n_vocab; ++i) {
            if (best >= 0 && !(logits[i] > bv)) continue;
            if (!allowed_tok(i, sc.js, L)) continue;
            best = i; bv = logits[i];
        }
    }
    if (best < 0) return t;  // nothing allowed (cannot happen for label characters): stay greedy
    if (best != t && forced) (*forced)++;
    return best;
}

// run prompts as parallel sequences 0..n-1 on ctx; returns per-prompt outputs and prefill time
// ------------------------------------------------------------------ streaming ("stream":true)
//
// Progress lines go through a small writer thread, so a slow reader can never stall the decode loop: the
// loop only appends to a queue. finish() writes everything queued (the final result line last) and joins.
struct LineWriter {
    int fd;
    std::mutex mu;
    std::condition_variable cv;
    std::deque<std::string> q;
    bool closing = false, broken = false;
    size_t lines = 0, bytes = 0;
    std::thread th;
    explicit LineWriter(int f) : fd(f), th([this] { loop(); }) {}
    void push(std::string && l) {
        { std::lock_guard<std::mutex> lk(mu); lines++; bytes += l.size(); q.push_back(std::move(l)); }
        cv.notify_one();
    }
    void finish() {
        { std::lock_guard<std::mutex> lk(mu); closing = true; }
        cv.notify_one();
        if (th.joinable()) th.join();
    }
    ~LineWriter() { finish(); }
  private:
    void loop() {
        for (;;) {
            std::string l;
            {
                std::unique_lock<std::mutex> lk(mu);
                cv.wait(lk, [&] { return closing || !q.empty(); });
                if (q.empty()) return;
                l = std::move(q.front());
                q.pop_front();
            }
            for (size_t off = 0; !broken && off < l.size();) {
                ssize_t w = send(fd, l.data() + off, l.size() - off, MSG_NOSIGNAL);
                if (w <= 0) { broken = true; break; }  // client gone: drop the rest, decoding goes on
                off += (size_t) w;
            }
        }
    }
};

// opts: per-stream options (agents only; empty = none), want_lp: top-5 logprobs of the first token,
// lw: streaming writer (nullptr = no progress lines)
static std::vector<Out> run_batch(llama_context * ctx, const std::vector<std::string> & prompts, bool trim_action,
                                  double & prefill_ms, const std::vector<StreamOpt> & opts = {}, bool want_lp = false,
                                  LineWriter * lw = nullptr, int n_glob = 0, const int * gmap = nullptr) {
    const int n = (int) prompts.size();
    const int n_vocab = llama_vocab_n_tokens(g_vocab);
    const int n_batch = (int) llama_n_batch(ctx);
    llama_memory_t mem = llama_get_memory(ctx);
    for (int s = 0; s < (int) llama_n_seq_max(ctx); ++s) llama_memory_seq_rm(mem, s, -1, -1);
    // agent batches may have their own new-token cap (HTPD_AGENT_MAX_NEW); the synthesizer keeps --max-new
    const int max_new = trim_action && g_agent_max_new > 0 ? g_agent_max_new : g_max_new;
    auto opt = [&](int s) -> const StreamOpt * { return s < (int) opts.size() ? &opts[s] : nullptr; };

    std::vector<Out> out(n);
    std::vector<std::vector<llama_token>> toks(n);
    std::vector<Scanner> scan;
    scan.reserve(n);
    for (int i = 0; i < n; ++i) { toks[i] = tokenize(prompts[i]); scan.emplace_back(prefill_of(prompts[i]), trim_action); }
    if (trim_action && g_json_abort > 0) {
        for (int i = 0; i < n; ++i) {
            scan[i].abort.level = g_json_abort;
            scan[i].abort.maxval = g_abort_maxval;
            if (opt(i) && !opt(i)->labels.empty()) scan[i].labels = &opt(i)->labels;
        }
    }

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
    // HTPD_SYNTH_PREFIX_CACHE=1 (v7) applies the same cache to the synthesizer's system turn (same KV bytes,
    // restored instead of recomputed; one more blob of ~P x 112 KB in host memory).
    static const bool synth_pc = getenv("HTPD_SYNTH_PREFIX_CACHE") != nullptr;
    if ((trim_action || synth_pc) && getenv("HTPD_PREFIX_CACHE") != nullptr) {
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
                if (g_kv_tag) mkey.push_back(-g_kv_tag);  // v8: adapter-specific entry (tokens are never < 0)
                auto mh = std::find_if(cache.begin(), cache.end(), [&](auto & e) { return e.first == mkey; });
                if (mh == cache.end() || llama_state_seq_set_data(ctx, mh->second.data(), mh->second.size(), i) == 0)
                    llama_memory_seq_cp(mem, lead, i, -1, -1);
                leader_of[i] = lead; start[i] = P; n_cp++;
                continue;
            }
            std::vector<llama_token> key(toks[i].begin(), toks[i].begin() + P);
            if (g_kv_tag) key.push_back(-g_kv_tag);  // v8: adapter-specific entry
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
                const float * lg = llama_get_logits_ith(ctx, logit_idx[s]);
                if (want_lp)
                    for (auto & e : htpd::top_logprobs(lg, n_vocab, 5)) out[s].lp.emplace_back(piece(e.first), e.second);
                llama_token t = pick(lg, n_vocab, scan[s], opt(s), &out[s].forced);
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
    for (int s = 0; s < n; ++s) room[s] = std::min(max_new, per_seq - pos[s] - 1);
    int active = n;
    // progress lines index streams by their position in the request (gmap: a split request's sub-batch)
    htpd::StepStream ss;
    ss.reset(gmap ? n_glob : n);
    std::string sline;
    auto flush_step = [&] { if (lw && ss.line(sline)) lw->push(std::move(sline)); };
    auto handle = [&](int s, llama_token t) {
        if (llama_vocab_is_eog(g_vocab, t)) { done[s] = true; out[s].stop = "eog"; return; }
        out[s].tokens++;
        const std::string p = piece(t);
        if (lw) ss.add(gmap ? gmap[s] : s, p);  // raw piece, exactly the bytes the stop scanner sees
        if (scan[s].feed(p)) { done[s] = true; out[s].stop = scan[s].stop; out[s].abort_why = scan[s].abort_why; return; }
        if (out[s].tokens >= room[s]) { done[s] = true; out[s].stop = out[s].tokens >= max_new ? "max" : "ctx"; }
    };
    for (int s = 0; s < n; ++s) handle(s, pending[s]);
    for (int s = 0; s < n; ++s) if (done[s]) { out[s].ms = ms_since(t0); llama_memory_seq_rm(mem, s, -1, -1); active--; }
    flush_step();  // the first token of every stream (prefill is over)

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
        // drafts occupy up to 4 more cells. v6 took the 5 off the token cap as well (a --max-new 320 runaway
        // stops at 315, "ctx"); the v7 agent cap (HTPD_AGENT_MAX_NEW) only takes it off the KV room, so the
        // cap is exact and reported as "max".
        for (int s = 0; s < n; ++s)
            room[s] = trim_action && g_agent_max_new > 0 ? std::max(0, std::min(max_new, per_seq - pos[s] - 1 - 5))
                                                          : std::max(0, room[s] - 5);
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
                // HTPD_ROLE_DRAFT: the stream's static per-role table (most frequent continuation)
                if (g_role_draft && opt(s) && opt(s)->table) {
                    t = opt(s)->table->lookup(h.data(), L, ng);
                    if (t >= 0) return t;
                }
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
                // pad with the pending token: a draft that is simply rejected. Row j (input j) is read only
                // for j <= drafts (the loop below stops at the first non-draft), so with HTPD_LOGITS_READ
                // the pad rows past that request no logits.
                for (int j = 0; j < k; ++j)
                    ri[s].push_back(add(j < (int) drs[s].size() ? drs[s][j] : pending[s], pos[s] + 1 + j, s,
                                        !g_logits_read || j < (int) drs[s].size()));
            }
            if (llama_decode(ctx, batch) != 0) { fprintf(stderr, "htpd: draft decode failed\n"); break; }
            steps++;
            for (int s = 0; s < n; ++s) {
                if (ri[s].empty()) continue;
                // row j's argmax is the token after input j; accept drafts while they match it
                int used = 0;  // number of inputs whose outputs are valid (pending + accepted drafts)
                llama_token t = 0;
                for (int j = 0; j <= k; ++j) {
                    t = pick(llama_get_logits_ith(ctx, ri[s][j]), n_vocab, scan[s], opt(s), &out[s].forced);
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
            flush_step();
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
            pending[s] = pick(llama_get_logits_ith(ctx, idx_of[s]), n_vocab, scan[s], opt(s), &out[s].forced);
            handle(s, pending[s]);
            if (done[s]) { out[s].ms = ms_since(t0); llama_memory_seq_rm(mem, s, -1, -1); active--; }
        }
        flush_step();
    }
    llama_batch_free(batch);
    int n_abort = 0, n_forced = 0;
    for (int s = 0; s < n; ++s) {
        out[s].text = scan[s].text;
        if (out[s].stop == "abort") { n_abort++; fprintf(stderr, "htpd: stream %d aborted after %d tokens: %s\n", s, out[s].tokens, out[s].abort_why.c_str()); }
        n_forced += out[s].forced;
    }
    if (g_trie || g_json_abort) fprintf(stderr, "htpd: %d streams, %d aborted, %d forced tokens\n", n, n_abort, n_forced);
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

static std::vector<Out> run_single_spec(llama_context * ctx, const std::string & prompt, double & prefill_ms,
                                        LineWriter * lw = nullptr) {
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

    htpd::StepStream ss;
    ss.reset(1);
    std::string sline;
    auto flush_step = [&] { if (lw && ss.line(sline)) lw->push(std::move(sline)); };
    auto emit = [&](llama_token t) -> bool {  // true = stop
        if (llama_vocab_is_eog(g_vocab, t)) { out[0].stop = "eog"; return true; }
        out[0].tokens++;
        hist.push_back(t);
        const std::string p = piece(t);
        if (lw) ss.add(0, p);
        if (scan.feed(p)) { out[0].stop = scan.stop; return true; }
        if (out[0].tokens >= g_max_new || pos + g_spec_k + 2 >= n_ctx) { out[0].stop = out[0].tokens >= g_max_new ? "max" : "ctx"; return true; }
        return false;
    };
    if (emit(pending)) goto done;

    for (;;) {
        flush_step();  // one progress line per verified step
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
    flush_step();
    out[0].ms = ms_since(t0);
    out[0].text = scan.text;
    fprintf(stderr, "htpd: spec steps %d drafted %d accepted %d tokens %d\n", steps, drafted, accepted_total, out[0].tokens);
    llama_batch_free(batch);
    return out;
}

// ------------------------------------------------------------------ v8 reasoner (kind "reason")
//
// Runs on its own model (--reasoner-model) and context, loaded only while the agents' model is unloaded (main).
// The reasoner (Qwen3.5, arch qwen35) is hybrid: 24 gated-delta-net layers keep a recurrent state per sequence, so
// a partial llama_memory_seq_rm (draft rollback) cannot work and llama_memory_seq_cp shares nothing useful. This
// path therefore never rolls back and never copies streams: plain greedy decode, prompt prefixes restored as WHOLE
// sequence states (llama_state_seq_get/set_data: attention KV + recurrent + conv state at the prefix end), and the
// answer schema's fixed bytes fed as forced tokens (reason_logic.h Forcer), which only ever appends.

struct ReasonCache { std::vector<llama_token> key; std::vector<uint8_t> blob; bool turn; };
static std::vector<ReasonCache> g_rcache;     // static-prefix + last-turn states; cleared when the reasoner unloads
static std::vector<std::string> g_rpieces;    // reasoner token -> piece (forcer checks); cleared at unload
static std::string g_reason_path_s;           // reasoner GGUF (disk cache files are named after it)
static int g_reason_max_new = 700;            // PLAN H2: tool calls and answers stop at EOG, not at a JSON close
static bool g_reason_turn_cache = true;       // HTPD_REASON_TURN_CACHE=0: no state blob after each prompt
static bool g_reason_disk_cache = true;       // HTPD_REASON_DISK_CACHE=0: static-prefix state not persisted
// v8s: prompt-lookup (n-gram) speculative decoding for the reasoner (single stream). HTPD_REASON_SPEC=K drafts up to K
// tokens copied from the prompt/answer history; hybrid models get K recurrent snapshots (n_rs_seq) for the rollback.
// Verified with the same greedy + forcer pick as plain decoding, so only drafts that match the model's choice are kept.
static int g_reason_spec = 0;                 // max draft tokens (0 = off: v8r decoding)
static int g_reason_spec_nmin = 2, g_reason_spec_nmax = 4;  // n-gram match length range (longest first)
static int g_reason_rs = 0;                   // n_rs_seq of the reasoner context
// v8x split decoding: request "split": [[keys...], ...] (+ "split_after": key); empty = off
static std::vector<std::vector<std::string>> g_req_split;
static std::string g_req_split_after = "causal_chain";

struct ReasonStats {
    std::string cache = "none";  // mem | disk | saved | turn | none (stream 0)
    int cached_tokens = 0;       // prompt tokens restored instead of prefilled (all streams)
    double cache_ms = 0;
};

static uint64_t fnv1a(const void * p, size_t n, uint64_t h = 1469598103934665603ULL) {
    const uint8_t * b = (const uint8_t *) p;
    for (size_t i = 0; i < n; ++i) { h ^= b[i]; h *= 1099511628211ULL; }
    return h;
}

static bool starts_with_toks(const std::vector<llama_token> & v, const std::vector<llama_token> & k) {
    return k.size() <= v.size() && std::equal(k.begin(), k.end(), v.begin());
}

// greedy argmax restricted to the bytes the forcer allows (EOG only once the answer is complete); the plain
// argmax whenever it is allowed, so outside schema deviations the model's own choice is kept
static FILE * g_trace = nullptr;  // HTPD_REASON_TRACE: per-pick logits trace of the current reason request
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
    fprintf(g_trace, "%d %d %d %.6f %d %.6f %016llx\n", g_trace_step++, picked, a, lg[a], b, lg[b], (unsigned long long) h);
}

static llama_token pick_forced_impl(const float * lg, int n_vocab, const htpd::Forcer & fz, int * changed);
static llama_token pick_forced(const float * lg, int n_vocab, const htpd::Forcer & fz, int * changed) {
    const llama_token t = pick_forced_impl(lg, n_vocab, fz, changed);
    trace_pick(lg, n_vocab, t);
    return t;
}
static llama_token pick_forced_impl(const float * lg, int n_vocab, const htpd::Forcer & fz, int * changed) {
    llama_token t = argmax(lg, n_vocab);
    if (!fz.constrained()) return t;
    auto ok = [&](llama_token x) {
        if (llama_vocab_is_eog(g_vocab, x)) return fz.done();
        return x >= 0 && x < (llama_token) g_rpieces.size() && fz.allows(g_rpieces[x]);
    };
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
    for (auto & e : top) if (ok(e.second)) { best = e.second; break; }
    if (best < 0) {
        float bv = -INFINITY;
        for (int i = 0; i < n_vocab; ++i) {
            if (best >= 0 && !(lg[i] > bv)) continue;
            if (!ok(i)) continue;
            best = i; bv = lg[i];
        }
    }
    if (best < 0) return t;
    if (changed) (*changed)++;
    return best;
}

// prompt lookup: the most recent earlier occurrence of the longest history suffix (nmax..nmin tokens) and the up to K
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
static std::vector<Out> run_reason(llama_context * ctx, const std::vector<std::string> & prompts, const std::string & prefix,
                                   const htpd::Schema * schema, int max_new, double & prefill_ms, LineWriter * lw,
                                   ReasonStats & rs, int n_glob = 0, const int * gmap = nullptr) {
    const int n = (int) prompts.size();
    const int n_vocab = llama_vocab_n_tokens(g_vocab);
    const int n_batch = (int) llama_n_batch(ctx);
    llama_memory_t mem = llama_get_memory(ctx);
    for (int s = 0; s < (int) llama_n_seq_max(ctx); ++s) llama_memory_seq_rm(mem, s, -1, -1);  // whole: always valid
    static int trace_req = 0;
    if (const char * td = getenv("HTPD_REASON_TRACE"); td && *td) {
        char path[512];
        snprintf(path, sizeof path, "%s/trace_%03d.txt", td, trace_req++);
        g_trace = fopen(path, "w");
        g_trace_step = 0;
    }
    struct TraceClose { ~TraceClose() { if (g_trace) { fclose(g_trace); g_trace = nullptr; } } } trace_close;    std::vector<Out> out(n);
    std::vector<std::vector<llama_token>> toks(n);
    for (int i = 0; i < n; ++i) toks[i] = tokenize(prompts[i]);
    const std::vector<llama_token> ptoks = prefix.empty() ? std::vector<llama_token>() : tokenize(prefix);
    std::vector<htpd::Forcer> fz;
    for (int i = 0; i < n; ++i) {
        fz.emplace_back(schema && !schema->empty() ? schema : nullptr);
        if (fz[i].active() && !fz[i].feed(htpd::answer_prefix(prompts[i]))) fz[i] = htpd::Forcer(nullptr);
    }

    auto t0 = clk::now();
    llama_batch batch = llama_batch_init(std::max(n_batch, n * 72), 0, 1);
    auto prefill = [&](int s, int from, int to, bool want_last) -> bool {  // tokens [from, to) of stream s
        for (int k = from; k < to;) {
            batch.n_tokens = 0;
            for (; k < to && batch.n_tokens < n_batch; ++k) {
                int idx = batch.n_tokens++;
                batch.token[idx] = toks[s][k]; batch.pos[idx] = k; batch.n_seq_id[idx] = 1; batch.seq_id[idx][0] = s;
                batch.logits[idx] = want_last && k == to - 1;
            }
            if (llama_decode(ctx, batch) != 0) { fprintf(stderr, "htpd: reason prefill failed\n"); return false; }
        }
        return true;
    };
    auto disk_path = [&](const std::vector<llama_token> & k) {
        uint64_t h = fnv1a(g_reason_path_s.data(), g_reason_path_s.size());
        h = fnv1a(k.data(), k.size() * sizeof(llama_token), h);
        if (g_reason_rs > 0) h = fnv1a(&g_reason_rs, sizeof g_reason_rs, h);  // snapshot planes change the state layout
        char b[40];
        snprintf(b, sizeof b, "%016llx", (unsigned long long) h);
        return g_reason_path_s + ".prefix_" + b + ".state";
    };

    // ---- restore the longest cached prefix state of each stream (whole-state, recurrent-safe)
    std::vector<int> start(n, 0);
    auto tc = clk::now();
    for (int i = 0; i < n; ++i) {
        const ReasonCache * best = nullptr;
        for (auto & e : g_rcache)
            if (e.key.size() < toks[i].size() && starts_with_toks(toks[i], e.key) && (!best || e.key.size() > best->key.size())) best = &e;
        std::string how = "none";
        if (best && llama_state_seq_set_data(ctx, best->blob.data(), best->blob.size(), i) != 0) {
            start[i] = (int) best->key.size();
            how = best->turn ? "turn" : "mem";
        } else if ((int) ptoks.size() >= 64 && ptoks.size() < toks[i].size() && starts_with_toks(toks[i], ptoks)) {
            const int P = (int) ptoks.size();
            bool ok = false;
            const std::string path = disk_path(ptoks);
            if (g_reason_disk_cache) {
                std::vector<llama_token> ft(P + 1);
                size_t nt = 0;
                if (FILE * fp = fopen(path.c_str(), "rb")) {
                    fclose(fp);
                    if (llama_state_seq_load_file(ctx, path.c_str(), i, ft.data(), ft.size(), &nt) != 0 && (int) nt == P &&
                        std::equal(ptoks.begin(), ptoks.end(), ft.begin())) { ok = true; how = "disk"; }
                    else llama_memory_seq_rm(mem, i, -1, -1);
                }
            }
            if (!ok) {
                if (!prefill(i, 0, P, false)) { llama_memory_seq_rm(mem, i, -1, -1); }
                else {
                    ok = true; how = "saved";
                    if (g_reason_disk_cache) {  // .part + rename: a crash never leaves a torn state file
                        const std::string part = path + ".part";
                        if (llama_state_seq_save_file(ctx, part.c_str(), i, ptoks.data(), ptoks.size()) != 0) rename(part.c_str(), path.c_str());
                        else remove(part.c_str());
                    }
                }
            }
            if (ok) {
                start[i] = P;
                std::vector<uint8_t> blob(llama_state_seq_get_size(ctx, i));
                blob.resize(llama_state_seq_get_data(ctx, blob.data(), blob.size(), i));
                if (!blob.empty()) {
                    // at most 2 static-prefix states (~100 MB each) in host memory: drop the oldest
                    int n_static = 0;
                    for (auto & e : g_rcache) n_static += !e.turn;
                    if (n_static >= 2)
                        for (auto it = g_rcache.begin(); it != g_rcache.end(); ++it) if (!it->turn) { g_rcache.erase(it); break; }
                    g_rcache.push_back({ptoks, std::move(blob), false});
                }
            }
        }
        if (i == 0) rs.cache = how;
        rs.cached_tokens += start[i];
    }
    rs.cache_ms = ms_since(tc);

    // ---- prefill the rest, stream by stream (no interleaving: one recurrent state per stream), then the first token
    std::vector<int> pos(n, 0);
    std::vector<llama_token> pending(n, 0);
    std::vector<int> changed(n, 0);
    for (int i = 0; i < n; ++i) {
        const int L = (int) toks[i].size();
        if (!prefill(i, start[i], L, true)) { out[i].stop = "error"; continue; }
        pos[i] = L;
        out[i].ttft_ms = ms_since(t0);
        pending[i] = pick_forced(llama_get_logits_ith(ctx, batch.n_tokens - 1), n_vocab, fz[i], &changed[i]);
        if (g_reason_turn_cache && n == 1) {  // the next tool round's prompt extends this one
            g_rcache.erase(std::remove_if(g_rcache.begin(), g_rcache.end(), [](auto & e) { return e.turn; }), g_rcache.end());
            std::vector<uint8_t> blob(llama_state_seq_get_size(ctx, i));
            blob.resize(llama_state_seq_get_data(ctx, blob.data(), blob.size(), i));
            if (!blob.empty()) g_rcache.push_back({toks[i], std::move(blob), true});
        }
    }
    prefill_ms = ms_since(t0);

    // ---- decode: each step feeds every active stream's pending token plus its forced tokens, logits on the last row
    const int per_seq = (int) (llama_n_ctx(ctx) / std::max<uint32_t>(1, llama_n_seq_max(ctx)));
    // v8x split: k parallel continuation streams after the head (streams 1..k-1 start inactive)
    const int K_split = (int) g_req_split.size();
    const bool split = n == 1 && schema && !schema->empty() && K_split >= 2 && K_split <= (int) llama_n_seq_max(ctx) &&
                       out[0].stop != "error" && g_reason_spec == 0;
    std::vector<htpd::Schema> subs;
    std::vector<std::string> sentinel;  // per split stream: stop when the forced text names this key ("" = run to the end)
    std::string split_key0;
    if (split) {
        std::vector<std::string> head;
        for (auto & k : schema->keys) { head.push_back(k); if (k == g_req_split_after) break; }
        for (size_t gi = 0; gi < g_req_split.size(); ++gi) {
            htpd::Schema sc = *schema;
            sc.keys = head;
            for (auto & k : g_req_split[gi]) sc.keys.push_back(k);
            // the next group's first key is kept as a sentinel: the group's last value then ends exactly as trained
            // (", " + next key), and the stream stops when the forcer would write that key
            if (gi + 1 < g_req_split.size()) {
                sc.keys.push_back(g_req_split[gi + 1][0]);
                sentinel.push_back("\"" + g_req_split[gi + 1][0] + "\"");
            } else sentinel.push_back("");
            subs.push_back(sc);
        }
        split_key0 = "\"" + g_req_split[0][0] + "\"";
    }
    const int NS = split ? K_split : n;
    out.resize(NS); pos.resize(NS, 0); pending.resize(NS, 0); changed.resize(NS, 0); fz.resize(NS);
    bool forked = false;
    int fork_tokens = 0, fork_forced = 0;
    size_t fork_len = 0;
    std::string fork_pick;
    std::vector<bool> done(NS, false);
    for (int s = n; s < NS; ++s) done[s] = true;
    std::vector<std::vector<llama_token>> inj(NS);
    htpd::StepStream ss;
    ss.reset(gmap ? n_glob : n);
    std::string sline;
    auto flush_step = [&] { if (lw && ss.line(sline)) lw->push(std::move(sline)); };
    auto emit = [&](int s, const std::string & p) {
        out[s].text += p;
        if (lw && s < n) ss.add(gmap ? gmap[s] : s, p);
        if (fz[s].active() && !fz[s].feed(p)) fz[s] = htpd::Forcer(nullptr);  // cannot happen; never constrain blind
    };
    // emit the pending token, then plan the forced tokens after it; true = stream finished
    auto handle = [&](int s) -> bool {
        const llama_token t = pending[s];
        if (llama_vocab_is_eog(g_vocab, t)) { out[s].stop = "eog"; return true; }
        out[s].tokens++;
        emit(s, piece(t));
        inj[s].clear();
        if (fz[s].done()) { out[s].stop = "json"; return true; }
        const std::string ft = fz[s].forced_text();
        if (forked && s < (int) sentinel.size() && !sentinel[s].empty() && ft.find(sentinel[s]) != std::string::npos) {
            out[s].stop = "json"; return true;  // group complete: the next group's key comes next
        }
        if (!ft.empty()) {
            htpd::Forcer g = fz[s];
            g.feed(ft);
            std::vector<llama_token> ftk = tokenize(ft);
            // keep the last forced token to the model (constrained), so the boundary into the free value it
            // starts keeps the model's own tokenization; if the forced text ends the answer, take all of it
            size_t take = g.done() ? ftk.size() : (ftk.size() > 0 ? ftk.size() - 1 : 0);
            take = std::min<size_t>(take, 64);
            std::string acc;
            for (size_t j = 0; j < take; ++j) {
                const std::string p = piece(ftk[j]);
                if (ft.compare(acc.size(), p.size(), p) != 0) break;  // detokenize mismatch: stop injecting here
                acc += p;
                inj[s].push_back(ftk[j]);
            }
            for (llama_token x : inj[s]) { emit(s, piece(x)); out[s].tokens++; out[s].forced++; }
            if (fz[s].done()) { out[s].stop = "json"; return true; }
        }
        if (out[s].tokens >= max_new) { out[s].stop = "max"; return true; }
        if (pos[s] + 1 + (int) inj[s].size() + 72 >= per_seq) { out[s].stop = "ctx"; return true; }
        return false;
    };
    SpecStats sp;
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
            sp.steps++;
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
        if (out[s].stop == "error") { done[s] = true; continue; }
        done[s] = handle(s);
        if (done[s]) out[s].ms = ms_since(t0); else active++;
    }
    flush_step();
    int steps = spec ? sp.steps : 0;
    while (active > 0) {
        batch.n_tokens = 0;
        std::vector<int> last(NS, -1);
        for (int s = 0; s < NS; ++s) {
            if (done[s]) continue;
            auto add = [&](llama_token t, bool lg) {
                int idx = batch.n_tokens++;
                batch.token[idx] = t; batch.pos[idx] = pos[s]++; batch.n_seq_id[idx] = 1; batch.seq_id[idx][0] = s;
                batch.logits[idx] = lg;
                return idx;
            };
            last[s] = add(pending[s], inj[s].empty());
            for (size_t j = 0; j < inj[s].size(); ++j) {
                int idx = add(inj[s][j], j + 1 == inj[s].size());
                if (j + 1 == inj[s].size()) last[s] = idx;
            }
        }
        if (llama_decode(ctx, batch) != 0) { fprintf(stderr, "htpd: reason decode failed\n"); break; }
        steps++;
        for (int s = 0; s < NS; ++s) {
            if (last[s] < 0) continue;
            pending[s] = pick_forced(llama_get_logits_ith(ctx, last[s]), n_vocab, fz[s], &changed[s]);
            if (split && !forked && s == 0) {
                // fork when the head key's value has closed: the forced text after this pick names the 1st group key
                htpd::Forcer g = fz[0];
                g.feed(piece(pending[0]));
                if (g.forced_text().find(split_key0) != std::string::npos) {
                    forked = true;
                    fork_len = out[0].text.size(); fork_tokens = out[0].tokens; fork_forced = out[0].forced;
                    fork_pick = piece(pending[0]);
                    std::vector<uint8_t> blob(llama_state_seq_get_size(ctx, 0));
                    blob.resize(llama_state_seq_get_data(ctx, blob.data(), blob.size(), 0));
                    const std::string ap = htpd::answer_prefix(prompts[0]);
                    for (int i = 0; i < NS; ++i) {
                        if (i > 0) {
                            if (llama_state_seq_set_data(ctx, blob.data(), blob.size(), i) == 0) { fprintf(stderr, "htpd: split fork %d failed\n", i); continue; }
                            out[i] = out[0]; pos[i] = pos[0]; pending[i] = pending[0]; done[i] = false; active++;
                        }
                        fz[i] = htpd::Forcer(&subs[i]);
                        if (!fz[i].feed(ap) || !fz[i].feed(out[i].text)) fz[i] = htpd::Forcer(nullptr);
                        if (i > 0 && handle(i)) { done[i] = true; out[i].ms = ms_since(t0); active--; }
                    }
                    fprintf(stderr, "htpd: split at %d tokens into %d streams (state %zu B)\n", fork_tokens, NS, blob.size());
                }
            }
            if (handle(s)) { done[s] = true; out[s].ms = ms_since(t0); active--; }
        }
        flush_step();
    }
    llama_batch_free(batch);
    for (int s = 0; s < NS; ++s) {
        llama_memory_seq_rm(mem, s, -1, -1);
        if (out[s].stop.empty()) out[s].stop = "error";
        fprintf(stderr, "htpd: reason stream %d: %d tokens (%d forced, %d constrained picks), stop %s, %.0f ms\n",
                s, out[s].tokens, out[s].forced, changed[s], out[s].stop.c_str(), out[s].ms);
    }
    fprintf(stderr, "htpd: reason %d streams, %d decode steps, prefill %.0f ms, cache %s (%d tokens, %.0f ms)\n",
            NS, steps, prefill_ms, rs.cache.c_str(), rs.cached_tokens, rs.cache_ms);
    if (split && forked) {
        // assemble: head + each group's continuation in group order; every group but the last loses its closing '}',
        // and a group that does not start with ',' gets one (the pick that closed the head may carry the comma)
        Out o = out[0];
        o.text = out[0].text.substr(0, fork_len);
        o.tokens = fork_tokens; o.forced = fork_forced; o.ms = 0; o.stop = "json";
        for (int i = 0; i < NS; ++i) {
            std::string seg = out[i].text.substr(std::min(fork_len, out[i].text.size()));
            if (i > 0) {  // drop the shared closing pick (already in group 0) and fix the separator
                seg = seg.substr(std::min(fork_pick.size(), seg.size()));
                size_t a = seg.find_first_not_of(" ");
                seg = a == std::string::npos ? "" : seg.substr(a);
                if (!seg.empty() && seg[0] != ',') seg = ", " + seg;
            }
            if (i + 1 < NS) { size_t e = seg.find_last_not_of(" \n,"); seg = e == std::string::npos ? "" : seg.substr(0, e + 1); }
            o.text += seg;
            o.tokens += out[i].tokens - fork_tokens; o.forced += out[i].forced - fork_forced;
            o.ms = std::max(o.ms, out[i].ms);
            if (out[i].stop != "json") o.stop = out[i].stop;
        }
        fprintf(stderr, "htpd: split answer: %zu bytes, %d tokens, stop %s\n", o.text.size(), o.tokens, o.stop.c_str());
        out.assign(1, o);
    } else {
        out.resize(n);
    }
    return out;
}

// ------------------------------------------------------------------ main / server

int main(int argc, char ** argv) {
    const char * model_path = nullptr;
    const char * dev_name = "HTP0";
    int port = 8091, n_agents = 13, agent_ctx = 1024, synth_ctx = 4096, n_threads = 4, n_ubatch = 512, n_ubatch_synth = 1024;
    std::string layouts_arg;  // --agent-layouts 14x1024,10x1280 (v7): agent KV layouts, picked per request
    const char * lora_path = nullptr;  // --lora-synth (v8)
    bool lora_scale_set = false;
    const char * reasoner_path = nullptr;  // --reasoner-model (v8 reasoner slot)
    int reason_ctx = 4096, reason_streams = 1, reason_ubatch = 512;
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
        else if (a == "--agent-layouts") layouts_arg = next();
        else if (a == "--lora-synth") lora_path = next();
        else if (a == "--lora-synth-scale") { g_lora_scale = (float) atof(next()); lora_scale_set = true; }
        else if (a == "--reasoner-model") reasoner_path = next();
        else if (a == "--reason-ctx") reason_ctx = atoi(next());
        else if (a == "--reason-streams") reason_streams = std::max(1, atoi(next()));
        else if (a == "--reason-ubatch") reason_ubatch = atoi(next());
        else if (a == "--reason-max-new") g_reason_max_new = atoi(next());
    }
    if (!model_path) { fprintf(stderr, "usage: htpd -m model.gguf [--device HTP0] [--port 8091] [--agents 13] [--agent-ctx 1024] [--synth-ctx 4096] [--lora-synth adapter.gguf [--lora-synth-scale 1]]\n"); return 1; }

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
    // a hybrid/recurrent agents' model cannot take partial seq_rm (draft rollback) or seq_cp sharing: force them off
    if (llama_model_is_hybrid(model) || llama_model_is_recurrent(model)) {
        unsetenv("HTPD_DRAFT"); unsetenv("HTPD_PREFIX_CACHE");
        setenv("HTPD_NO_PREFIX", "1", 1); setenv("HTPD_SPEC", "0", 1);
        fprintf(stderr, "htpd: agents' model is hybrid/recurrent: draft, prefix sharing and speculation off\n");
    }

    // v8: the synthesizer's LoRA adapter (loaded once; attached per request to the synth context only).
    // HTPD_LORA_SYNTH / HTPD_LORA_SYNTH_SCALE are the same as the flags (the flags win), so the app's
    // htpd_profile "env=" line can enable it without a backend change.
    if (!lora_path) if (const char * e = getenv("HTPD_LORA_SYNTH"); e && *e) {
        lora_path = e;
        if (const char * s = getenv("HTPD_LORA_SYNTH_SCALE"); s && *s && !lora_scale_set) g_lora_scale = (float) atof(s);
    }
    if (lora_path && *lora_path) {
        auto tl = clk::now();
        g_lora = llama_adapter_lora_init(model, lora_path);
        if (!g_lora) { fprintf(stderr, "htpd: LoRA adapter load failed: %s\n", lora_path); return 1; }
        char nm[256] = "", al[64] = "";
        llama_adapter_meta_val_str(g_lora, "general.name", nm, sizeof nm);
        llama_adapter_meta_val_str(g_lora, "adapter.lora.alpha", al, sizeof al);
        fprintf(stderr, "htpd: v8 LoRA for the synth context: %s (name '%s', alpha %s), default scale %.3f, loaded in %.0f ms\n",
                lora_path, nm, al, g_lora_scale, ms_since(tl));
    }

    // v7 feature flags (all off by default)
    auto env_int = [](const char * k, int d) { const char * v = getenv(k); return v && *v ? atoi(v) : d; };
    g_agent_max_new = env_int("HTPD_AGENT_MAX_NEW", 0);
    g_json_abort = env_int("HTPD_JSON_ABORT", 0);
    g_abort_maxval = (size_t) std::max(1, env_int("HTPD_JSON_ABORT_MAXVAL", 48));
    g_trie = env_int("HTPD_PATTERN_TRIE", 0);
    g_role_draft = env_int("HTPD_ROLE_DRAFT", 0) != 0;
    g_logits_read = env_int("HTPD_LOGITS_READ", 0) != 0;
    if (const char * tk = getenv("HTPD_TRIE_KEYS"); tk && *tk) {
        g_trie_keys.clear();
        std::string cur;
        for (const char * p = tk;; ++p) {
            if (*p == ',' || *p == 0) { if (!cur.empty()) g_trie_keys.push_back(cur); cur.clear(); if (!*p) break; }
            else cur += *p;
        }
    }
    if (g_trie) {
        const int nv = llama_vocab_n_tokens(g_vocab);
        g_pieces.resize(nv);
        for (int t = 0; t < nv; ++t) g_pieces[t] = piece(t);
    }
    if (g_role_draft) {
        if (const char * f = getenv("HTPD_ROLE_DRAFT_FILE"); f && *f) {
            FILE * fp = fopen(f, "rb");
            if (!fp) fprintf(stderr, "htpd: cannot open HTPD_ROLE_DRAFT_FILE %s\n", f);
            std::string line;
            int c;
            auto flush = [&]() {
                JVal e;
                if (!line.empty() && htpd::json_parse(line, e) && e.type == JVal::OBJ) {
                    const JVal * m = e.get("match");
                    const JVal * tx = e.get("texts");
                    if (m && m->type == JVal::STR && tx && tx->type == JVal::ARR) {
                        std::vector<std::vector<int32_t>> seqs;
                        for (auto & t : tx->arr) if (t.type == JVal::STR) { auto v = tokenize(t.str); seqs.emplace_back(v.begin(), v.end()); }
                        g_file_tables.emplace_back(m->str, htpd::NgramTable());
                        g_file_tables.back().second.build(seqs);
                        fprintf(stderr, "htpd: role draft '%s': %zu texts, %zu n-grams\n", m->str.c_str(), seqs.size(), g_file_tables.back().second.next.size());
                    }
                }
                line.clear();
            };
            while (fp && (c = fgetc(fp)) != EOF) { if (c == '\n') flush(); else if (c != '\r') line += (char) c; }
            flush();
            if (fp) fclose(fp);
        }
    }
    fprintf(stderr, "htpd: v7 flags: agent_max_new %d, json_abort %d, trie %d, role_draft %d (%zu file tables), logits_read %d\n",
            g_agent_max_new, g_json_abort, g_trie, (int) g_role_draft, g_file_tables.size(), (int) g_logits_read);

    // ONE context at a time: weights + 13-stream KV + a second 4k context exceed what one DSP session
    // can map (fastrpc_mmap fails, measured). The agent context stays resident; a synthesizer call
    // swaps in a single-sequence context (weights stay loaded, so a swap is cheap).
    // Agent KV layouts (streams x cells per stream). Default: the one --agents x --agent-ctx layout, exactly
    // as before. With --agent-layouts A1xC1,A2xC2,... a request runs in ONE batch on the current layout if
    // it fits (count <= streams and every prompt + HTPD_LAYOUT_HEADROOM tokens <= cells), else on the first
    // layout that fits; if none fits all, it is split by prompt length (each prompt to the first layout its
    // length fits) and the outputs are merged in request order. Per-stream KV slices stay fixed size
    // (non-unified, FA_STREAMS): a unified pool measured 1.6x slower at 13 streams
    // (proofs/2026-10-16_htp_bringup/real_fa_kvu.txt vs real_fa_streams_patch.txt).
    struct Layout { int streams, cells; };
    std::vector<Layout> layouts;
    for (size_t p = 0; p < layouts_arg.size();) {
        size_t e = layouts_arg.find(',', p);
        std::string item = layouts_arg.substr(p, e == std::string::npos ? std::string::npos : e - p);
        int a = 0, c = 0;
        if (sscanf(item.c_str(), "%dx%d", &a, &c) == 2 && a > 0 && c > 0) layouts.push_back({a, c});
        if (e == std::string::npos) break;
        p = e + 1;
    }
    if (layouts.empty()) layouts.push_back({n_agents, agent_ctx});
    int max_streams = 0;
    for (auto & L : layouts) max_streams = std::max(max_streams, L.streams);
    const int headroom = [] { const char * v = getenv("HTPD_LAYOUT_HEADROOM"); return v && *v ? atoi(v) : 136; }();
    auto make_ctx = [&](int li) {  // li < 0: the synthesizer context
        auto cp = llama_context_default_params();
        cp.flash_attn_type = LLAMA_FLASH_ATTN_TYPE_ENABLED;
        cp.n_threads = cp.n_threads_batch = n_threads;
        cp.kv_unified = false;
        cp.n_seq_max = li >= 0 ? layouts[li].streams : 1;
        cp.n_ctx = li >= 0 ? (uint32_t) (layouts[li].streams * layouts[li].cells) : (uint32_t) synth_ctx;
        cp.n_batch = 2048;
        cp.n_ubatch = li >= 0 ? n_ubatch : n_ubatch_synth;  // the synth context is alone on the DSP
        return llama_init_from_model(model, cp);
    };
    llama_context * ctx = make_ctx(0);
    int cur_layout = 0;  // -1 = synth context
    if (!ctx) { fprintf(stderr, "htpd: context creation failed\n"); return 1; }

    // ---- v8 reasoner slot: ONE model on the NPU at any time (two resident models rebooted the board, HANDBOOK
    // 2.27/2.37). Kind "reason" frees the agents' context and model, loads the reasoner, answers, and brings the
    // agents' model back (at once, or - "keep" - on the next agents/synth request, a "release", or after
    // HTPD_REASON_IDLE_MS). If the agents' model cannot be reloaded, htpd retries, then exits so the app's
    // supervisor restarts it with the agents' model; it never keeps serving without one.
    if (!reasoner_path) if (const char * e = getenv("HTPD_REASONER_MODEL"); e && *e) reasoner_path = e;
    if (reasoner_path && !*reasoner_path) reasoner_path = nullptr;
    if (reasoner_path) g_reason_path_s = reasoner_path;
    g_reason_turn_cache = env_int("HTPD_REASON_TURN_CACHE", 1) != 0;
    g_reason_disk_cache = env_int("HTPD_REASON_DISK_CACHE", 1) != 0;
    g_reason_spec = std::max(0, std::min(16, env_int("HTPD_REASON_SPEC", 0)));
    g_reason_spec_nmin = std::max(1, env_int("HTPD_REASON_SPEC_NMIN", 2));
    g_reason_spec_nmax = std::max(g_reason_spec_nmin, env_int("HTPD_REASON_SPEC_NMAX", 4));
    const int reason_idle_ms = env_int("HTPD_REASON_IDLE_MS", 20000);
    llama_model * rmodel = nullptr;
    llama_context * rctx = nullptr;
    auto t_reason = clk::now();  // last reason request (idle release)
    auto reload_domain = [&]() -> bool {
        model = llama_model_load_from_file(model_path, mp);
        if (!model) return false;
        g_vocab = llama_model_get_vocab(model);
        if (lora_path && *lora_path) {
            g_lora = llama_adapter_lora_init(model, lora_path);
            if (!g_lora) { llama_model_free(model); model = nullptr; return false; }
        }
        ctx = make_ctx(cur_layout);
        if (!ctx) { llama_model_free(model); model = nullptr; g_lora = nullptr; return false; }
        return true;
    };
    auto domain_back = [&]() -> double {  // the guard: the agents' model must come back
        auto t = clk::now();
        for (int attempt = 1;; ++attempt) {
            if (reload_domain()) break;
            fprintf(stderr, "htpd: agents' model reload failed (attempt %d)\n", attempt);
            if (attempt >= 3) { fprintf(stderr, "htpd: exiting so the supervisor restarts htpd with the agents' model\n"); exit(1); }
            std::this_thread::sleep_for(std::chrono::seconds(2 * attempt));
        }
        return ms_since(t);
    };
    auto reasoner_down = [&](const char * why) -> double {  // reasoner -> agents' model
        if (!rmodel) return 0;
        auto t = clk::now();
        if (rctx) llama_free(rctx);
        rctx = nullptr;
        llama_model_free(rmodel);
        rmodel = nullptr;
        g_rcache.clear(); g_rcache.shrink_to_fit();
        g_rpieces.clear(); g_rpieces.shrink_to_fit();
        const double unload = ms_since(t);
        const double reload = domain_back();
        fprintf(stderr, "htpd: reasoner unloaded (%s): unload %.0f ms, agents' model back in %.0f ms\n", why, unload, reload);
        return ms_since(t);
    };
    // agents' model -> reasoner; false (agents' model back, err set) when the reasoner cannot be loaded
    auto reasoner_up = [&](std::string & err, double & unload_ms, double & load_ms) -> bool {
        if (rmodel) return true;
        auto t = clk::now();
        llama_free(ctx);
        ctx = nullptr;
        llama_model_free(model);  // frees the LoRA adapter with it
        model = nullptr;
        g_lora = nullptr;
        unload_ms = ms_since(t);
        t = clk::now();
        rmodel = llama_model_load_from_file(reasoner_path, mp);
        if (!rmodel) err = "reasoner model load failed";
        else {
            auto cp = llama_context_default_params();
            cp.flash_attn_type = LLAMA_FLASH_ATTN_TYPE_ENABLED;
            cp.n_threads = cp.n_threads_batch = n_threads;
            cp.kv_unified = false;
            cp.n_seq_max = (uint32_t) reason_streams;
            cp.n_ctx = (uint32_t) (reason_streams * reason_ctx);
            cp.n_batch = 2048;
            cp.n_ubatch = (uint32_t) reason_ubatch;
            g_reason_rs = 0;
            if (g_reason_spec > 0 && (llama_model_is_hybrid(rmodel) || llama_model_is_recurrent(rmodel))) cp.n_rs_seq = (uint32_t) g_reason_spec;
            rctx = llama_init_from_model(rmodel, cp);
            if (rctx) g_reason_rs = (int) llama_n_rs_seq(rctx);
            if (!rctx) { llama_model_free(rmodel); rmodel = nullptr; err = "reasoner context creation failed"; }
        }
        if (!rmodel) {
            fprintf(stderr, "htpd: %s: %s\n", err.c_str(), reasoner_path);
            domain_back();
            return false;
        }
        g_vocab = llama_model_get_vocab(rmodel);
        const int nv = llama_vocab_n_tokens(g_vocab);
        g_rpieces.resize(nv);
        for (int k = 0; k < nv; ++k) g_rpieces[k] = piece(k);
        load_ms = ms_since(t);
        fprintf(stderr, "htpd: reasoner loaded in %.0f ms (agents' model unloaded in %.0f ms): %s, %s, %d streams x %d ctx\n",
                load_ms, unload_ms, reasoner_path,
                llama_model_is_hybrid(rmodel) || llama_model_is_recurrent(rmodel) ? (g_reason_rs > 0 ? "hybrid/recurrent (rollback snapshots for spec, whole-state cache)" : "hybrid/recurrent (no rollback, whole-state cache)") : "attention-only",
                reason_streams, reason_ctx);
        return true;
    };
    if (layouts.size() > 1)
        for (auto & L : layouts) fprintf(stderr, "htpd: agent layout %d x %d cells (headroom %d)\n", L.streams, L.cells, headroom);
    fprintf(stderr, "htpd: ready in %.0f ms: %d agent streams x %d ctx, synth ctx %d, device %s, port %d\n",
            ms_since(t_load), layouts[0].streams, layouts[0].cells, synth_ctx, dev_name, port);

    int srv = socket(AF_INET, SOCK_STREAM, 0);
    int one = 1;
    setsockopt(srv, SOL_SOCKET, SO_REUSEADDR, &one, sizeof one);
    sockaddr_in addr{};
    addr.sin_family = AF_INET;
    addr.sin_port = htons(port);
    addr.sin_addr.s_addr = htonl(INADDR_LOOPBACK);
    if (bind(srv, (sockaddr *) &addr, sizeof addr) != 0 || listen(srv, 8) != 0) { perror("htpd: bind/listen"); return 1; }

    if (reasoner_path) fprintf(stderr, "htpd: v8 reasoner slot: %s (ctx %d x %d streams, max_new %d, idle release %d ms)\n",
                               reasoner_path, reason_ctx, reason_streams, g_reason_max_new, reason_idle_ms);
    for (;;) {
        if (rmodel) {  // reasoner held ("keep"): give the NPU back to the agents' model after the idle time
            pollfd pf{srv, POLLIN, 0};
            const int left = reason_idle_ms - (int) ms_since(t_reason);
            if (left <= 0 || poll(&pf, 1, left) == 0) { reasoner_down("idle"); continue; }
        }
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
                if (!line.empty() && line.back() == '\r') line.pop_back();
                JVal req;
                const bool parsed = htpd::json_parse(line, req) && req.type == JVal::OBJ;
                std::string kind;
                if (parsed) if (auto k = req.get("kind"); k && k->type == JVal::STR) kind = k->str;
                std::vector<std::string> prompts;
                bool agents = kind == "agents";
                if (parsed && agents) {
                    if (auto a = req.get("prompts"); a && a->type == JVal::ARR)
                        for (auto & e : a->arr) if (e.type == JVal::STR) prompts.push_back(e.str);
                } else if (parsed) {
                    if (auto a = req.get("prompt"); a && a->type == JVal::STR) prompts.push_back(a->str);
                }
                const bool want_lp = parsed && req.get("logprobs") && req.get("logprobs")->truthy();
                const bool want_stream = parsed && req.get("stream") && req.get("stream")->truthy();
                // v8: adapter scale for this request (synth context only; agents never get the adapter)
                float lora_s = 0.0f;
                if (g_lora && !agents) {
                    lora_s = g_lora_scale;
                    if (parsed) if (auto v = req.get("lora")) {
                        if (v->type == JVal::BOOL) lora_s = v->b ? g_lora_scale : 0.0f;
                        else if (v->type == JVal::NUM) lora_s = (float) v->num;
                    }
                }
                std::unique_ptr<LineWriter> lw;
                std::string id_field;  // echoed request id
                if (parsed) if (auto v = req.get("id")) {
                    if (v->type == JVal::STR) id_field = ",\"id\":\"" + json_escape(v->str) + "\"";
                    else if (v->type == JVal::NUM) { char b[48]; snprintf(b, sizeof b, ",\"id\":%.17g", v->num); id_field = b; }
                }
                std::string resp;
                bool handled = false, release_after = false;
                if (parsed && kind == "caps") {  // v8: capability probe (a v7 htpd answers "bad request")
                    handled = true;
                    resp = std::string("{\"caps\":[\"agents\",\"synth\"") + (reasoner_path ? ",\"reason\",\"release\"" : "") +
                           "],\"reasoner\":" + (reasoner_path ? "\"" + json_escape(reasoner_path) + "\"" : std::string("null")) +
                           ",\"loaded\":\"" + (rmodel ? "reasoner" : "agents") + "\"" + id_field + "}";
                } else if (parsed && kind == "release") {
                    handled = true;
                    const bool was = rmodel != nullptr;
                    const double ms = reasoner_down("release");
                    char b[96];
                    snprintf(b, sizeof b, "{\"released\":%s,\"reload_ms\":%.1f", was ? "true" : "false", ms);
                    resp = b + id_field + "}";
                } else if (parsed && kind == "reason") {
                    handled = true;
                    // request: "prompt" or "prompts" (batched: one swap, run as parallel streams, --reason-streams at a
                    // time), "max_new", "keep", "prefix" (static prompt prefix: whole-state cache), "schema" (forced
                    // JSON skeleton, reason_logic.h), "stream", "id"
                    std::vector<std::string> rp;
                    if (auto a = req.get("prompts"); a && a->type == JVal::ARR) for (auto & e : a->arr) if (e.type == JVal::STR) rp.push_back(e.str);
                    if (auto a = req.get("prompt"); a && a->type == JVal::STR) rp.push_back(a->str);
                    htpd::Schema schema;
                    const JVal * sv = req.get("schema");
                    const bool schema_ok = !sv || sv->type == JVal::NUL || htpd::schema_from_json(sv, schema);
                    if (!reasoner_path) resp = "{\"error\":\"no reasoner model (--reasoner-model)\"" + id_field + "}";
                    else if (rp.empty() || !schema_ok) resp = "{\"error\":\"bad request\"" + id_field + "}";
                    else {
                        int max_new = g_reason_max_new;
                        if (auto v = req.get("max_new"); v && v->type == JVal::NUM && v->num > 0) max_new = (int) v->num;
                        std::string prefix;
                        if (auto v = req.get("prefix"); v && v->type == JVal::STR) prefix = v->str;
                        g_req_split.clear();
                        g_req_split_after = "causal_chain";
                        if (auto v = req.get("split"); v && v->type == JVal::ARR)
                            for (auto & grp : v->arr) {
                                if (grp.type != JVal::ARR) continue;
                                std::vector<std::string> ks;
                                for (auto & e : grp.arr) if (e.type == JVal::STR) ks.push_back(e.str);
                                if (!ks.empty()) g_req_split.push_back(ks);
                            }
                        if (auto v = req.get("split_after"); v && v->type == JVal::STR) g_req_split_after = v->str;
                        const bool keep = req.get("keep") && req.get("keep")->truthy();
                        const bool was_loaded = rmodel != nullptr;
                        std::string err;
                        double unload_ms = 0, load_ms = 0;
                        if (!reasoner_up(err, unload_ms, load_ms)) {
                            resp = "{\"error\":\"" + json_escape(err) + "\"" + id_field + "}";
                        } else {
                            if (want_stream) lw.reset(new LineWriter(c));
                            const int n_p = (int) rp.size();
                            std::vector<Out> outs(n_p);
                            double pre = 0;
                            ReasonStats rs;
                            for (int a = 0; a < n_p; a += reason_streams) {
                                const int b = std::min(n_p, a + reason_streams);
                                std::vector<std::string> sp(rp.begin() + a, rp.begin() + b);
                                std::vector<int> gm;
                                for (int k = a; k < b; ++k) gm.push_back(k);
                                const double off = ms_since(t0);
                                double pre_g = 0;
                                ReasonStats rs_g;
                                auto o = run_reason(rctx, sp, prefix, schema.empty() ? nullptr : &schema, max_new, pre_g, lw.get(), rs_g,
                                                    n_p, gm.data());
                                if (a == 0) rs = rs_g; else { rs.cached_tokens += rs_g.cached_tokens; rs.cache_ms += rs_g.cache_ms; }
                                pre += pre_g;
                                for (size_t k = 0; k < o.size(); ++k) {
                                    if (a > 0) { o[k].ttft_ms += off; o[k].ms += off; }
                                    outs[a + k] = std::move(o[k]);
                                }
                            }
                            t_reason = clk::now();
                            release_after = !keep;
                            resp = "{\"outputs\":[";
                            for (int i = 0; i < n_p; ++i) {
                                char num[200];
                                snprintf(num, sizeof num, "\",\"tokens\":%d,\"ttft_ms\":%.1f,\"ms\":%.1f,\"stop\":\"%s\",\"forced\":%d}",
                                         outs[i].tokens, outs[i].ttft_ms, outs[i].ms, outs[i].stop.c_str(), outs[i].forced);
                                resp += (i ? ",{\"text\":\"" : "{\"text\":\"") + json_escape(outs[i].text) + num;
                            }
                            char tail[512];
                            snprintf(tail, sizeof tail,
                                     "],\"prefill_ms\":%.1f,\"swap_ms\":%.1f,\"total_ms\":%.1f,\"reason\":{\"swapped\":%s,\"unload_ms\":%.1f,"
                                     "\"load_ms\":%.1f,\"cache\":\"%s\",\"cached_tokens\":%d,\"cache_ms\":%.1f,\"kept\":%s,\"streams\":%d}",
                                     pre, unload_ms + load_ms, ms_since(t0), was_loaded ? "false" : "true", unload_ms, load_ms,
                                     rs.cache.c_str(), rs.cached_tokens, rs.cache_ms, keep ? "true" : "false", reason_streams);
                            resp += tail + id_field + "}";
                        }
                    }
                }
                if (handled) {
                } else if (prompts.empty() || (agents && layouts.size() == 1 && (int) prompts.size() > max_streams) || (!agents && prompts.size() != 1)) {
                    resp = "{\"error\":\"bad request\"" + id_field + "}";
                } else {
                    // per-stream options (agents only)
                    std::vector<StreamOpt> opts;
                    if (agents && (g_trie || g_json_abort || g_role_draft)) {
                        opts.resize(prompts.size());
                        // request draft tables, cached by text set; cleared between requests only (pointers)
                        static std::map<std::string, htpd::NgramTable> req_tables;
                        if (req_tables.size() >= 16) req_tables.clear();
                        const JVal * labels = req.get("labels");
                        const JVal * drafts = req.get("draft");
                        for (size_t i = 0; i < prompts.size(); ++i) {
                            const JVal * li = labels && labels->type == JVal::ARR && i < labels->arr.size() ? &labels->arr[i] : nullptr;
                            // request labels win; otherwise the enum lists the prompt itself states
                            Labels req_l = htpd::labels_from_json(li);
                            const bool from_req = !req_l.empty();
                            opts[i].labels = from_req ? req_l
                                                      : htpd::labels_from_prompt(prompts[i], {"pattern", "status", "likely_cause", "action"});
                            if (g_trie >= 1 && from_req) opts[i].trie_labels = req_l;
                            else if (g_trie >= 2)
                                for (auto & k : g_trie_keys)
                                    if (opts[i].labels.count(k)) opts[i].trie_labels[k] = opts[i].labels[k];
                            if (g_role_draft) {
                                const JVal * di = drafts && drafts->type == JVal::ARR && i < drafts->arr.size() ? &drafts->arr[i] : nullptr;
                                std::vector<std::string> texts;
                                if (di && di->type == JVal::STR && !di->str.empty()) texts.push_back(di->str);
                                if (di && di->type == JVal::ARR) for (auto & e : di->arr) if (e.type == JVal::STR && !e.str.empty()) texts.push_back(e.str);
                                if (!texts.empty()) {
                                    std::string key;
                                    for (auto & t : texts) { key += t; key += '\x1e'; }
                                    auto it = req_tables.find(key);
                                    if (it == req_tables.end()) {
                                        std::vector<std::vector<int32_t>> seqs;
                                        for (auto & t : texts) { auto v = tokenize(t); seqs.emplace_back(v.begin(), v.end()); }
                                        it = req_tables.emplace(key, htpd::NgramTable()).first;
                                        it->second.build(seqs);
                                    }
                                    opts[i].table = &it->second;
                                } else {
                                    for (auto & ft : g_file_tables)
                                        if (prompts[i].find(ft.first) != std::string::npos) { opts[i].table = &ft.second; break; }
                                }
                            }
                        }
                    }
                    double pre = 0, swap_ms = 0;
                    if (rmodel) swap_ms += reasoner_down(agents ? "agents request" : "synth request");  // v8
                    auto use = [&](int li) {
                        if (cur_layout == li) return;
                        auto ts = clk::now();
                        llama_free(ctx);
                        ctx = make_ctx(li);
                        cur_layout = li;
                        swap_ms += ms_since(ts);
                        if (!ctx) { fprintf(stderr, "htpd: context swap failed\n"); exit(1); }
                    };
                    // plan: (layout, prompt indices) groups; one group unless --agent-layouts forces a split
                    std::vector<std::pair<int, std::vector<int>>> plan;
                    const int n_p = (int) prompts.size();
                    std::vector<int> all(n_p);
                    for (int i = 0; i < n_p; ++i) all[i] = i;
                    if (!agents) plan.push_back({-1, all});
                    else if (layouts.size() == 1) plan.push_back({0, all});
                    else {
                        std::vector<int> len(n_p);
                        for (int i = 0; i < n_p; ++i) len[i] = (int) tokenize(prompts[i]).size();
                        auto fits = [&](int li, const std::vector<int> & ids) {
                            if ((int) ids.size() > layouts[li].streams) return false;
                            for (int i : ids) if (len[i] + headroom > layouts[li].cells) return false;
                            return true;
                        };
                        int pl = cur_layout >= 0 && fits(cur_layout, all) ? cur_layout : -1;
                        for (int li = 0; pl < 0 && li < (int) layouts.size(); ++li) if (fits(li, all)) pl = li;
                        if (pl >= 0) plan.push_back({pl, all});
                        else {
                            std::vector<std::vector<int>> by(layouts.size());
                            for (int i = 0; i < n_p; ++i) {
                                int li = (int) layouts.size() - 1;
                                for (int k = 0; k < (int) layouts.size(); ++k) if (fits(k, {i})) { li = k; break; }
                                by[li].push_back(i);
                            }
                            // the current layout's group first (no swap), then the others in order
                            std::vector<int> order;
                            if (cur_layout >= 0) order.push_back(cur_layout);
                            for (int k = 0; k < (int) layouts.size(); ++k) if (k != cur_layout) order.push_back(k);
                            for (int k : order)
                                for (size_t a = 0; a < by[k].size(); a += (size_t) layouts[k].streams)
                                    plan.push_back({k, std::vector<int>(by[k].begin() + a, by[k].begin() + std::min(by[k].size(), a + (size_t) layouts[k].streams))});
                            fprintf(stderr, "htpd: request of %d prompts split into %zu batches by prompt length\n", n_p, plan.size());
                        }
                    }
                    // HTPD_SPEC=0 turns prompt-lookup speculation off for the synthesizer
                    const char * spec_env = getenv("HTPD_SPEC");
                    bool spec = !agents && (spec_env == nullptr || atoi(spec_env) != 0);
                    if (want_stream) lw.reset(new LineWriter(c));
                    std::vector<Out> outs(n_p);
                    for (auto & g : plan) {
                        use(g.first);
                        if (g_lora) {  // v8: attach/detach on the synth context; agent contexts are never touched
                            if (g.first < 0) {
                                if (lora_s != 0.0f) { llama_adapter_lora * ad = g_lora; llama_set_adapters_lora(ctx, &ad, 1, &lora_s); }
                                else llama_set_adapters_lora(ctx, nullptr, 0, nullptr);
                                static std::vector<float> seen;  // one prefix-cache tag per distinct scale
                                g_kv_tag = 0;
                                if (lora_s != 0.0f) {
                                    auto it = std::find(seen.begin(), seen.end(), lora_s);
                                    if (it == seen.end()) { seen.push_back(lora_s); it = seen.end() - 1; }
                                    g_kv_tag = (int) (it - seen.begin()) + 1;
                                }
                            } else g_kv_tag = 0;
                        }
                        const double off = ms_since(t0);  // a later sub-batch's times count from the request
                        double pre_g = 0;
                        std::vector<Out> o;
                        if (spec) o = run_single_spec(ctx, prompts[0], pre_g, lw.get());
                        else if ((int) g.second.size() == n_p) o = run_batch(ctx, prompts, agents, pre_g, opts, want_lp, lw.get());
                        else {
                            std::vector<std::string> sp;
                            std::vector<StreamOpt> so;
                            for (int i : g.second) { sp.push_back(prompts[i]); if (!opts.empty()) so.push_back(opts[i]); }
                            o = run_batch(ctx, sp, agents, pre_g, so, want_lp, lw.get(), n_p, g.second.data());
                        }
                        pre += pre_g;
                        for (size_t k = 0; k < o.size(); ++k) {
                            if (plan.size() > 1) { o[k].ttft_ms += off; o[k].ms += off; }
                            outs[g.second[k]] = std::move(o[k]);
                        }
                    }
                    const bool trie_any = std::any_of(opts.begin(), opts.end(), [](auto & o) { return !o.trie_labels.empty(); });
                    resp = "{\"outputs\":[";
                    for (size_t i = 0; i < outs.size(); ++i) {
                        char num[160];
                        snprintf(num, sizeof num, "\",\"tokens\":%d,\"ttft_ms\":%.1f,\"ms\":%.1f,\"stop\":\"%s\"",
                                 outs[i].tokens, outs[i].ttft_ms, outs[i].ms, outs[i].stop.c_str());
                        resp += (i ? ",{\"text\":\"" : "{\"text\":\"") + json_escape(outs[i].text) + num;
                        // v7 optional fields, only when the feature is on (v6 responses stay byte-identical)
                        if (outs[i].stop == "abort") resp += ",\"abort_why\":\"" + json_escape(outs[i].abort_why) + "\"";
                        if (trie_any) resp += ",\"forced\":" + std::to_string(outs[i].forced);
                        if (want_lp) {
                            resp += ",\"logprobs\":[";
                            for (size_t j = 0; j < outs[i].lp.size(); ++j) {
                                char lp[48];
                                snprintf(lp, sizeof lp, "\",\"lp\":%.4f}", outs[i].lp[j].second);
                                resp += (j ? ",{\"tok\":\"" : "{\"tok\":\"") + json_escape(outs[i].lp[j].first) + lp;
                            }
                            resp += "]";
                        }
                        resp += "}";
                    }
                    char tail[96];
                    snprintf(tail, sizeof tail, "],\"prefill_ms\":%.1f,\"swap_ms\":%.1f,\"total_ms\":%.1f", pre, swap_ms, ms_since(t0));
                    resp += tail;
                    if (g_lora) { char ls[48]; snprintf(ls, sizeof ls, ",\"lora_scale\":%g", (double) lora_s); resp += ls; }  // v8
                    resp += id_field + "}";
                }
                resp += "\n";
                if (lw) {
                    // the final result line goes through the same queue, so it is always the last line
                    lw->push(std::move(resp));
                    lw->finish();
                    fprintf(stderr, "htpd: streamed %zu progress lines, %zu bytes, %d send errors" "\n", lw->lines - 1, lw->bytes, (int) lw->broken);
                } else {
                    (void) !write(c, resp.data(), resp.size());
                }
                if (release_after) reasoner_down("request without keep");  // after the answer is out

            }
        }
        close(c);
    }
}
