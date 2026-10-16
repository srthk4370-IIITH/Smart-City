// Host-side stress test of qualla::InferenceScheduler KV-pool bookkeeping.
//
// Builds against either the stock or the patched inference-scheduler.cpp (see
// build_and_test.sh). A fake dispatch function stands in for the NPU: it checks
// every physical KV position a fire touches and fulfils the promises. N dialog
// threads run genied's pattern: reset (setSlotNPast 0) -> PREFILL prompt ->
// DECODE token by token (syncKV after each) -> markSlotIdle, forever reusing the
// same slot, like genied's long-lived dialogs.
//
// Reported per run: max HWM, fires, failures (ContextLimit), invariant errors.

#include <atomic>
#include <cstdio>
#include <cstdlib>
#include <mutex>
#include <random>
#include <set>
#include <thread>
#include <vector>

#include "Exception.hpp"
#include "inference-scheduler.hpp"

using namespace qualla;

namespace {
std::atomic<uint32_t> g_max_pos{0};
std::atomic<uint64_t> g_fires{0}, g_fused{0}, g_bad{0};
uint32_t g_cap = 0;  // positions must stay below this (0 = do not check)
}  // namespace

int main(int argc, char** argv) {
  const int slots      = argc > 1 ? atoi(argv[1]) : 2;
  const int prompt     = argc > 2 ? atoi(argv[2]) : 600;
  const int answer     = argc > 3 ? atoi(argv[3]) : 100;
  const int queries    = argc > 4 ? atoi(argv[4]) : 20;
  const int jitter     = argc > 5 ? atoi(argv[5]) : 300;  // random extra prompt tokens
  const uint32_t ctx   = 2048;
  const uint32_t armax = 128;
  g_cap                = ctx - armax;

  InferenceScheduler::Config cfg;
  cfg.max_slots            = static_cast<uint32_t>(slots);
  cfg.ar_max               = armax;
  cfg.mixed_prefill_decode = true;
  cfg.coalesce_window      = std::chrono::microseconds(2000);
  cfg.variants.supported[ctx] = {{1, false}, {128, false}};
  cfg.variants.logit_variants = {{1, (int)ctx}, {128, (int)ctx}};
  cfg.variants.max_ctx_size   = (int)ctx;
#ifdef PATCHED
  cfg.kv_capacity = ctx - armax;
#endif

  auto dispatch = [](InferenceRequest& req) -> bool {
    g_fires++;
    if (req.slots.size() > 1) g_fused++;
    std::set<uint32_t> seen;
    for (auto& s : req.slots) {
      for (size_t k = 0; k < s.kv_indices.size(); ++k) {
        const uint32_t p = s.kv_indices[k];
        uint32_t cur     = g_max_pos.load();
        while (p > cur && !g_max_pos.compare_exchange_weak(cur, p)) {
        }
        if (!seen.insert(p).second) {
          fprintf(stderr, "DUPLICATE position %u across slots in one fire\n", p);
          g_bad++;
        }
      }
      // what the real runInference does at a fused (AR128) fire
      const uint32_t past_dim = req.ctx_size - req.ar_size;
      for (size_t k = s.n_past; k < s.kv_indices.size(); ++k) {
        if (req.ar_size > 1 && s.kv_indices[k] >= past_dim) {
          try {
            s.promise->set_exception(std::make_exception_ptr(
                genie::ContextLimitException("KV position exceeds compiled ctx")));
          } catch (...) {
          }
          return false;  // stock: whole batch fails
        }
      }
    }
    for (auto& s : req.slots) {
      if (!s.is_final_chunk) continue;  // like runInference: only final chunks resolve
      try {
        s.promise->set_value(Tensor{});
      } catch (...) {
      }
    }
    return true;
  };

  InferenceScheduler sched(dispatch, cfg);
  std::vector<int32_t> slot(slots);
  for (int i = 0; i < slots; ++i) slot[i] = sched.acquireSlot();

  std::atomic<int> ok{0}, truncated{0};
  std::atomic<uint32_t> max_hwm{0};
  std::vector<std::thread> th;
  for (int d = 0; d < slots; ++d) {
    th.emplace_back([&, d] {
      std::mt19937 rng(1234 + d);
      const int32_t s = slot[d];
      for (int q = 0; q < queries; ++q) {
        sched.markSlotIdle(s);
        sched.setSlotNPast(s, 0);  // Dialog::reset
        const int p = prompt + (jitter ? static_cast<int>(rng() % jitter) : 0);
        uint32_t n_past = 0;
        bool failed     = false;
        try {
          std::vector<int32_t> toks(p, 7);
          sched.enqueue(s, toks, {}, SlotPhase::PREFILL, false).get();
          n_past += p;
          sched.setSlotNPast(s, n_past);  // syncKV
          for (int t = 0; t < answer; ++t) {
            sched.enqueue(s, {7}, {}, SlotPhase::DECODE, true).get();
            n_past += 1;
            sched.setSlotNPast(s, n_past);
            uint32_t h = sched.getKVHwm(), c = max_hwm.load();
            while (h > c && !max_hwm.compare_exchange_weak(c, h)) {
            }
          }
        } catch (const std::exception& e) {
          failed = true;
        }
        sched.markSlotIdle(s);
        (failed ? truncated : ok)++;
      }
    });
  }
  for (auto& t : th) t.join();
  printf(
      "slots=%d prompt=%d+rand%d answer=%d queries/slot=%d | ok=%d truncated=%d | "
      "fires=%llu fused=%llu max_hwm=%u max_pos=%u cap=%u invariant_errors=%llu\n",
      slots, prompt, jitter, answer, queries, ok.load(), truncated.load(),
      (unsigned long long)g_fires.load(), (unsigned long long)g_fused.load(), max_hwm.load(),
      g_max_pos.load(), g_cap, (unsigned long long)g_bad.load());
  return g_bad.load() ? 1 : 0;
}
