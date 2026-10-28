// Host micro-benchmark of the two grammar paths htpd_grammar_v9.patch adds (llama.cpp 620d222, vocab only):
//   accept path : llama_sampler_apply on ONE candidate (the greedy token) + llama_sampler_accept
//   reject path : llama_sampler_apply on the FULL vocabulary (128,256 candidates) - only when greedy is off-grammar
// It walks a real v2 answer token by token through the role grammar and times both paths at every position.
//   g++ -O2 -std=c++17 bench_grammar.cpp -I$L/include -I$L/ggml/include -L$L/build-host/bin -lllama -lggml -lggml-base \
//       -Wl,-rpath,$L/build-host/bin -o bench_grammar
//   ./bench_grammar model.gguf agent_v2_power.gbnf 'continuation text after the prefill'
#include "llama.h"

#include <chrono>
#include <cmath>
#include <cstdio>
#include <fstream>
#include <sstream>
#include <string>
#include <vector>

using clk = std::chrono::steady_clock;
static double us(clk::time_point a) { return std::chrono::duration<double, std::micro>(clk::now() - a).count(); }

int main(int argc, char ** argv) {
    if (argc < 4) { fprintf(stderr, "usage: %s model.gguf grammar.gbnf text\n", argv[0]); return 1; }
    llama_backend_init();
    auto mp = llama_model_default_params();
    mp.vocab_only = true;
    llama_model * model = llama_model_load_from_file(argv[1], mp);
    if (!model) return 1;
    const llama_vocab * vocab = llama_model_get_vocab(model);
    std::ifstream f(argv[2]);
    std::stringstream ss; ss << f.rdbuf();
    const std::string gbnf = ss.str(), text = argv[3];
    std::vector<llama_token> toks(text.size() + 8);
    int n = llama_tokenize(vocab, text.c_str(), (int) text.size(), toks.data(), (int) toks.size(), false, false);
    toks.resize(n);
    const int nv = llama_vocab_n_tokens(vocab);
    auto t0 = clk::now();
    llama_sampler * proto = llama_sampler_init_grammar(vocab, gbnf.c_str(), "root");
    double parse_us = us(t0);
    if (!proto) { fprintf(stderr, "grammar parse failed\n"); return 1; }
    t0 = clk::now();
    llama_sampler * g = llama_sampler_clone(proto);
    double clone_us = us(t0);
    std::vector<llama_token_data> cand(nv);
    double acc_us = 0, full_us = 0, full_max = 0;
    int ok = 0, allowed_sum = 0;
    for (int i = 0; i < n; ++i) {
        // reject path: full-vocabulary mask at this position (state before token i)
        for (int j = 0; j < nv; ++j) cand[j] = {j, 0.0f, 0.0f};
        llama_token_data_array a = {cand.data(), (size_t) nv, -1, false};
        auto t1 = clk::now();
        llama_sampler_apply(g, &a);
        double d = us(t1);
        full_us += d; full_max = std::max(full_max, d);
        int allowed = 0;
        for (size_t j = 0; j < a.size; ++j) allowed += std::isfinite(a.data[j].logit);
        allowed_sum += allowed;
        // accept path: one candidate (the real next token) + accept
        llama_token_data one = {toks[i], 0.0f, 0.0f};
        llama_token_data_array a1 = {&one, 1, -1, false};
        t1 = clk::now();
        llama_sampler_apply(g, &a1);
        bool on = std::isfinite(a1.data[0].logit);
        if (on) llama_sampler_accept(g, toks[i]);
        acc_us += us(t1);
        ok += on;
        if (!on) { fprintf(stderr, "token %d off-grammar: '%s'\n", i, text.c_str()); break; }
    }
    printf("{\"tokens\": %d, \"on_grammar\": %d, \"parse_us\": %.1f, \"clone_us\": %.1f, \"accept_path_us_per_token\": %.2f, "
           "\"full_mask_us_mean\": %.1f, \"full_mask_us_max\": %.1f, \"allowed_mean\": %.1f, \"n_vocab\": %d}\n",
           n, ok, parse_us, clone_us, acc_us / n, full_us / n, full_max, (double) allowed_sum / n, nv);
    llama_sampler_free(g); llama_sampler_free(proto);
    llama_model_free(model);
    return 0;
}
