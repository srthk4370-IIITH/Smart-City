"""Patch a llama.cpp 620d2225 source copy for a vocabulary-pruned lm_head (qwen35 only).
GGUF: output.weight has n_keep < n_vocab rows, plus the int32 array "<arch>.output_keep_ids" (the token id of each row).
The graph computes n_keep logits; llama_context expands them into the full n_vocab logits row with -inf elsewhere, so
callers (htpd: greedy argmax + forcer) see the same API. Without the key/short tensor nothing changes."""
import sys, os
root = sys.argv[1]


def patch(rel, old, new):
    p = os.path.join(root, rel)
    s = open(p, encoding="utf-8").read()
    assert s.count(old) == 1, (rel, old[:70])
    open(p, "w", encoding="utf-8", newline="\n").write(s.replace(old, new))


patch("src/llama-model.h", "    struct ggml_tensor * output          = nullptr;\n",
      "    struct ggml_tensor * output          = nullptr;\n"
      "    std::vector<int32_t> output_keep_ids;            // pruned lm_head: token id of each output row (empty = full)\n")

patch("src/models/qwen35.cpp",
      """    output = create_tensor(tn(LLM_TENSOR_OUTPUT, "weight"), { n_embd, n_vocab }, TENSOR_NOT_REQUIRED);
""",
      """    {
        // pruned lm_head (htpd v8p): output.weight with n_keep < n_vocab rows + <arch>.output_keep_ids
        const std::string oname = tn(LLM_TENSOR_OUTPUT, "weight").str();
        const ggml_tensor * meta = ml.get_tensor_meta(oname.c_str());
        int64_t n_out = n_vocab;
        if (meta && meta->ne[1] < n_vocab) {
            std::vector<int32_t> ids;
            ml.get_arr(std::string(ml.get_arch_name()) + ".output_keep_ids", ids, true);
            GGML_ASSERT((int64_t) ids.size() == meta->ne[1]);
            for (int32_t id : ids) GGML_ASSERT(id >= 0 && id < n_vocab);
            output_keep_ids = std::move(ids);
            n_out = meta->ne[1];
            LLAMA_LOG_INFO("%s: pruned lm_head: %lld of %lld tokens\\n", __func__, (long long) n_out, (long long) n_vocab);
        }
        output = create_tensor(tn(LLM_TENSOR_OUTPUT, "weight"), { n_embd, n_out }, TENSOR_NOT_REQUIRED);
    }
""")

patch("src/llama-context.cpp",
      """            if (n_outputs) {
                GGML_ASSERT( n_outputs_prev + n_outputs <= n_outputs_all);
                GGML_ASSERT((n_outputs_prev + n_outputs)*n_vocab <= (int64_t) logits.size);
                ggml_backend_tensor_get_async(backend_res, t_logits, logits_out, 0, n_outputs*n_vocab*sizeof(float));
            }""",
      """            if (n_outputs) {
                GGML_ASSERT( n_outputs_prev + n_outputs <= n_outputs_all);
                GGML_ASSERT((n_outputs_prev + n_outputs)*n_vocab <= (int64_t) logits.size);
                const auto & keep = model.output_keep_ids;
                if (keep.empty()) {
                    ggml_backend_tensor_get_async(backend_res, t_logits, logits_out, 0, n_outputs*n_vocab*sizeof(float));
                } else {
                    // pruned lm_head: n_keep logits per output, expanded to n_vocab with -inf for the dropped tokens
                    const int64_t n_keep = (int64_t) keep.size();
                    GGML_ASSERT(t_logits->ne[0] == n_keep);
                    std::vector<float> tmp((size_t) (n_outputs*n_keep));
                    ggml_backend_sched_synchronize(sched.get());
                    ggml_backend_tensor_get(t_logits, tmp.data(), 0, tmp.size()*sizeof(float));
                    for (int64_t o = 0; o < n_outputs; ++o) {
                        float * row = logits_out + o*n_vocab;
                        std::fill(row, row + n_vocab, -INFINITY);
                        const float * src = tmp.data() + o*n_keep;
                        for (int64_t j = 0; j < n_keep; ++j) row[keep[j]] = src[j];
                    }
                }
            }""")
patch("src/llama-context.cpp", '#include "llama-context.h"\n', '#include "llama-context.h"\n#include <cmath>\n')
print("patched", root)
