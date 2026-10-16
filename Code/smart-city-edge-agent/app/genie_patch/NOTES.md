# genie_patch: making Genie continuous batching usable in genied

QAIRT 2.50.0.260828, Genie source in `examples/Genie/Genie`. All analysis is from reading that
source plus a host-side stress test of the scheduler (`test/`). **Nothing here has run on the
device yet.** Section 6 is the on-device plan.

Files in this folder:

| file | what it is |
|---|---|
| `libGenie.so` | **patched** aarch64-android build (build_fix + genie_cb_fixes) |
| `libGenie_rebuilt_stock.so` | unpatched source, same toolchain/flags (build_fix only): the A/B control |
| `genie_cb_fixes.patch` | the source fixes built into `libGenie.so` (F1, F3, F4, F5) |
| `build_fix.patch` | `make/Android.mk` fixes; the 2.50 sample Android.mk does not build as shipped (section 7) |
| `optional_reset_order.patch` | the `Dialog::reset()` reorder (F2). **Not** in the built library; see F2 |
| `build.sh` | WSL script: fresh SDK copies -> patches -> Rust tokenizer -> ndk-build x2 -> symbol check |
| `test/sched_test.cpp`, `test/run_host_test.sh`, `test/env_stub.cpp` | host stress test, stock vs patched scheduler |

## 1. Headline: batching has never been on

genied's `batchingConfig()` writes `dialog.engine.batching` and `shared-engine: true`. With the
**stock** libGenie that `batching` block never reaches the engine:

- `src/Dialog.cpp` `validateEngineConfig` accepts the key (line ~1544), but the dialog-side
  `translateEngineConfig` (line ~1820-2100) never copies it into the qualla engine config. Only the
  GenieEngine path (`src/Engine.cpp:1479`) does. genied uses `GenieDialog_create`, so
  `NspEngine::m_scheduler_json` stays empty and the scheduler is built with `max-slots = 1`.
- A shared engine with one physical slot runs in **KV-swap mode** (`NspEngine::swapSlotKV`): every
  dialog is mapped to physical slot 0 and its KV is dumped to / restored from a CPU sidecar on every
  `process()`. Nothing is fused. Worse, in that mode:
  - `toPhysicalSlot()` maps *every* dialog id to slot 0, so `Dialog::reset()` of dialog B
    (`setSlotNPast(B,0)`, `setSlotCheckpoints(B,{})`) wipes the n_past / KV index list of dialog A
    **while A is generating**. A's next tokens attend to nothing, and the next `swapSlotKV` sees an
    empty slot, so A's KV is never saved. A's answer derails or stops: **truncated answers**.
  - Sidecars are never cleared on reset, so a later swap-in restores a previous query's KV under a
    fresh dialog n_past (physical n_past = old length + new prompt) - wrong context and early
    `ContextLimitException` ("Context Size was exceeded" -> SENTENCE_END -> truncated).
  - `swapSlotKV` is unsynchronised; two dialog threads swapping while the dispatch thread runs is a
    data race on the KV buffers. KV-swap mode must not be used with overlapping queries at all.

So the truncation seen with `-slots N` is explained by KV-swap mode, not by the reset order.

## 2. The bugs and the patch

Line numbers are stock 2.50 source.

### F1 - pass `batching` through the dialog config (src/Dialog.cpp, translateEngineConfig)
Copies `genieEngineConfig["batching"]` to the qualla engine config, exactly as `Engine.cpp` does.
This is what actually turns continuous batching on for `GenieDialog_create`.

### F2 - `Dialog::reset()` order (qualla/dialog.cpp 2038-2048) - CONFIRMED, NOT the truncation cause
Confirmed: `setSlotNPast(slot,0)` moves the slot's positions to the free list and clears
`m_kv_indices`; `NspEngine::resetSlot()` (qnn-htp.cpp ~1328) then reads an empty list and returns
before `_model->resetKVSlot()`. So the slot's KV rows are never zeroed.

But this does **not** truncate answers, and the stale rows are harmless:
- the attention mask is built only from each slot's own `kv_indices` (`setupAttentionMask`,
  nsp-model.cpp ~6650): freed positions are masked in every row;
- a reused position is overwritten by `commitKV` (or the HMX scatter) before anything attends to it;
  new tokens attend to themselves through the AR input rows, not through the cache.
- `KVManager::clearSlotPositions` (the zeroing) runs on the **dialog thread** with only
  `blockKVGlobal()`, while the scheduler's dispatch thread can be executing another slot's fire and
  switching AR1 <-> AR128 (`setActiveVariant` -> `SmartMask::reshapeCache` changes the row stride and
  memmoves rows in place). Zeroing during that window writes at the wrong stride, i.e. into other
  slots' live KV. Stock code is protected from this only *because* of the "bug".

So the reorder is in `optional_reset_order.patch` and deliberately **not** in the built library. If
someone wants it, the zeroing must first be moved onto the dispatch thread (queue the indices in
`resetSlot`, drain them at the start of `NspEngine::process(InferenceRequest&)`).

### F3 - KV-swap mode fixes (qnn-htp.hpp toPhysicalSlot, qnn-htp.cpp resetSlot)
Only affects `shared-engine: true` with `max-slots` 1 (i.e. stock genied `-slots N`).
- `toPhysicalSlot()` returns 0 only for the dialog whose KV is swapped in, -1 otherwise, so a
  non-owner's reset/sync calls become no-ops instead of clobbering the owner.
- `resetSlot()` drops the dialog's sidecar, so a reset dialog really starts empty.
This makes KV-swap correct for *sequential* use; overlapping queries are still unsafe (see 1).
With F1 genied uses real slots and never enters this mode.

### F4 - shared KV pool accounting (inference-scheduler.{hpp,cpp}, engine.cpp)
With real slots, all dialogs share **one** KV buffer of the compiled context, addressed through a
shared high-water mark `m_kv_hwm` (`fireBatch`, `fetch_add`). Stock problems, all reproduced by the
host test:
1. **Per-slot free lists.** `setSlotNPast(s,0)` (every reset) returns a slot's positions to *that
   slot's* private free list. genied's dialogs live forever and are reset per query, never released,
   so `m_kv_hwm` only grows to the **sum of every slot's peak sequence** and is never reclaimed
   (compaction only runs in `releaseSlot`). One long query on one slot permanently shrinks the pool.
2. **No physical bound.** Nothing keeps positions below what the graphs can address. SmartMask
   (non-scatter) keeps `ctx - AR` past columns per variant: at CL2048 that is 2047 for AR1 but only
   **1920 for AR128**. Positions 1920-2046 handed out during a lone AR1 decode are silently cut off by
   `reshapeCache` at the next AR128 fire, and their mask bits then land on the new-token columns of
   the AR128 graph (cross-slot attention). A new position >= 1920 in an AR128 fire trips the check in
   `QnnNspModel::runInference` (~7892), which sets `ContextLimitException` on **every** slot of the
   batch -> all concurrent answers end with SENTENCE_END: truncated.
3. **Rollback leak.** On a failed dispatch the stock rollback subtracts the HWM but leaves positions
   from that fire in slot free lists -> the same position is later handed to two slots (the host
   test shows `DUPLICATE position 1920 ...`).

Patch:
- Freed default-group positions go to one sorted **shared free pool** (`m_shared_free`) reused
  lowest-first by any slot (private free lists stay for SWA and take-shrink). `releaseSlot` hands the
  slot's private free list to the pool; `compactPool` remaps pool entries; a failed dispatch returns
  the pool positions it took.
- `Config::kv_capacity` = `max_ctx - ar_max` (1920 for CL2048/AR128), set in
  `Engine::tryCreateScheduler`, logged as `scheduler KV pool capacity N positions`. Overridable with
  `"kv-capacity"` in the batching JSON (for testing exhaustion). Applied only when max-slots > 1 and
  not NativeKV, so single-slot behaviour is unchanged.
- **Admission**: if a fire does not fit under the cap, the **youngest query** in the plan (query age
  stamped when a request arrives on an empty slot) is failed alone with `ContextLimitException`, its
  positions return to the pool at once, and the fire is re-packed for the others. Repeats until the
  rest fits. In-flight answers finish; the newest request gets "Context Size was exceeded" (genied
  sees status `GENIE_STATUS_WARNING_CONTEXT_EXCEEDED`, zero chunks, and retries once).

### F5 - overflow check (qnn-htp/nsp-model.cpp ~7892)
The check used `first_new_kv_idx + n_tokens`, which assumes contiguous positions; with free-list
positions it both missed real overflows and could flag false ones. It now bounds the largest new
position. Identical for the contiguous single-slot case.

### Host test result (fake NPU, CL2048, AR1+AR128, cap 1920; `test/run_host_test.sh`)
`ok` = answer completed, `truncated` = ended by an exception.

| slots, prompt, answer | stock | patched |
|---|---|---|
| 2, 600+rand300, 100 (fits) | 25 ok / 15 truncated, hwm 1970 | **40 / 0**, hwm 1850 |
| 3, 300+rand200, 100 (fits) | 60 / 0 | 60 / 0 |
| 3, 550+rand200, 120 (does not fit) | 0 / 45, 39 duplicate positions | 30 / 15 (youngest evicted) |
| 4, 400+rand200, 100 (does not fit) | 0 / 60, 107 duplicate positions | 44 / 16 |
| 1, 600+rand300, 100 | 5 / 0 | 5 / 0 (unchanged path) |

## 3. Capacity: how many ~700-token sequences fit

All slots share one pool of **ctx - AR_max** positions (patched; stock is worse because it charges
each slot its historical peak).

| bundle | pool | 700-token sequences | headroom |
|---|---|---|---|
| CL2048, AR128 (normal) | 1920 | **2** (1400) | 520; a 3rd needs 2100 |
| CL4096, AR128 (large) | 3968 | 5 (3500) | 468 |

A "sequence" is prompt + generated tokens (`max-num-tokens` is 320, agent prompts ~600, so the worst
case is ~920: still 2 at CL2048, since 2 x 920 = 1840 <= 1920). Note that with max-slots > 1 a
*single* query is also limited to 1920 positions instead of 2047. The large-context bundle cannot be
used with `-slots N` in genied (window swap frees the shared engine), so for genied today the answer
is **max 2 concurrent slots at CL2048**.

## 4. Configuration

### 4.1 Engine keys (dialog.engine.batching)
Read by `InferenceScheduler::Config::applyJson`:

| key | meaning | default |
|---|---|---|
| `max-slots` | physical slots; must be >= the number of dialogs genied creates | 1 |
| `mixed-prefill-decode` | let one slot's prefill chunk ride in the same fire as others' decode tokens | false |
| `prefill-chunk-size` | max prefill tokens per slot per fire | ar_max (128) |
| `coalesce-window-us` | prefill-only fires wait up to this long for other slots to arrive | 0 |
| `kv-capacity` | (patched only) override the pool cap; use only for tests | ctx - ar_max |

Requirements: `backend.QnnHtp.shared-engine: true` (all dialogs from the same config then share one
engine) and the patched library (F1). The scheduler is only created if the bundle has a
multi-token **logit-producing** variant; otherwise Genie logs "no multi-token logit variant - using
legacy strategy-loop path" and batching is impossible.

### 4.2 Exact JSON for genie_bundle_ft (`smartcity_agent.json` shape)
This is what genied's `batchingConfig()` + `daemonConfig()` produce for `-slots 2`; written out so it
can be put in a config file directly:

```json
{
  "dialog": {
    "version": 1,
    "type": "basic",
    "context": { "version": 1, "size": 2048, "n-vocab": 128256, "bos-token": 128000,
                 "eos-token": [128001, 128008, 128009] },
    "sampler": { "version": 1, "seed": 42, "temp": 0.0, "top-k": 1, "top-p": 0.0 },
    "tokenizer": { "version": 1, "path": "tokenizer.json" },
    "engine": {
      "version": 1,
      "n-threads": 4,
      "backend": {
        "version": 1,
        "type": "QnnHtp",
        "QnnHtp": {
          "version": 1,
          "use-mmap": true,
          "spill-fill-bufsize": 0,
          "mmap-budget": 0,
          "poll": false,
          "cpu-mask": "0xf0",
          "kv-dim": 128,
          "allow-async-init": true,
          "shared-engine": true
        },
        "extensions": "htp_backend_ext_config.json"
      },
      "model": {
        "version": 1,
        "type": "binary",
        "binary": { "version": 1, "ctx-bins": [
          "llama_v3_2_3b_instruct_part_1_of_3.bin",
          "llama_v3_2_3b_instruct_part_2_of_3.bin",
          "llama_v3_2_3b_instruct_part_3_of_3.bin" ] },
        "positional-encoding": { "type": "rope", "rope-dim": 64, "rope-theta": 500000,
          "rope-scaling": { "rope-type": "llama3", "factor": 32.0, "low-freq-factor": 1.0,
            "high-freq-factor": 4.0, "original-max-position-embeddings": 8192 } }
      },
      "batching": {
        "max-slots": 2,
        "mixed-prefill-decode": true,
        "coalesce-window-us": 2000
      }
    },
    "max-num-tokens": 320
  }
}
```

`context.size` must equal the compiled CL of the bundle in use (2048 for the normal bundle; the copy
in `qidk_backup/genie_bundle_ft` says 4096 - check which bins are on the board). Leave
`prefill-chunk-size` unset (128 = one AR128 fire; with decode tokens in the same fire the scheduler
already shrinks the chunk to 128 - n_decode).

## 5. Which graph a fused decode uses with our bundle (AR1 + AR128 only)

`InferenceScheduler::selectVariant` picks the **smallest logit-producing AR >= tokens in the fire**.

| fire | tokens | graph |
|---|---|---|
| one slot decoding alone | 1 | AR1 |
| 2 or 3 slots decoding together | 2-3 | **AR128** (125-126 padded rows) |
| decode + another slot's prefill chunk | <= 128 | AR128 |
| prefill only | <= 128 | AR128 |

Cost estimate from HANDBOOK 2.8 (prefill 1481 tok/s on AR128 -> ~86 ms per AR128 fire; decode
23.1 tok/s on AR1 -> ~43 ms per token):

- 2 slots fused: ~86 ms for 2 tokens = ~23 tok/s **aggregate** - the same as one stream, each stream
  at half speed. No throughput gain from fusing decode with this bundle.
- 3 slots would give ~35 tok/s aggregate, but 3 x 700 does not fit in CL2048.
- The real gain at 2 slots is overlap: a new request's prefill rides in the other slot's decode
  fires (`mixed-prefill-decode`) instead of waiting for it to finish.

To make fused decode pay, compile a small multi-token logit variant (AR4 or AR8) into the same
bundle with weight sharing; decode is bandwidth-bound, so an AR4 fire should cost close to AR1 and
2 slots would approach 2x aggregate. `ar_max` (and so the pool cap) stays 128.

Also expect fused (AR128) decode to produce **slightly different tokens** than AR1 decode of the
same prompt: different compiled graph, different quantised numerics. Byte-identical output is only
expected when each query runs alone.

## 6. On-device test plan (for whoever runs it)

Setup
1. Back up the board's current `libGenie.so` (the one genied links against, `app/genied/lib` and
   the copy pushed with genied). Keep it to roll back. Both rebuilt libraries link libc++
   statically like the stock one, so no `libc++_shared.so` is needed. The rebuilt libraries do
   **not** contain xgrammar (grammar-constrained decoding); our configs do not use `grammar`, but a
   config that does will fail to load with "built without ENABLE_GRAMMAR".
2. Phase A0 (control, before anything else): swap in `libGenie_rebuilt_stock.so` (renamed to
   `libGenie.so`), `-slots 1`, run the 28-query regression set and compare with the QAIRT stock
   library. Expect 28/28 byte-identical and the same speed. If this fails, the rebuild itself (not
   the patch) differs from Qualcomm's build: stop and report.
3. For the batching runs genied needs Genie's log to confirm what happened. Either add a
   `GenieLog_create` + `GenieDialogConfig_bindLogger` (level INFO) to genied for the test build, or
   at least capture genied's stderr (Genie prints "Context Size was exceeded" there). Lines to look
   for: `continuous-batching config found, max-slots=2`, `inference scheduler created: 2 slot(s)`,
   `scheduler KV pool capacity 1920 positions`, and during runs `KV pool full ... evicting`.
4. Use the normal CL2048 bundle, greedy sampler (as deployed). Watch temperature; keep the app's
   thermal guard on.
5. genied detail to fix before Phase B: an evicted query returns status
   `GENIE_STATUS_WARNING_CONTEXT_EXCEEDED` (= 4, positive), which genied treats as success. With 0
   chunks it retries once (fine); with chunks > 0 (a decoder evicted mid-answer, only possible when
   every slot is decoding and the pool is full) it sends frameEnd and the backend gets a cut answer.
   Make genied send frameError when `st == 4` so the backend's normal retry/fallback runs.

Phase A - single-query parity (patched lib must be a drop-in)
- A1. `-slots 1` (no batching): run the 14-prompt regression set forward and reverse (28 queries)
  with the QAIRT stock lib, then with the patched lib. Expect **28/28 byte-identical** outputs and the same
  decode rate within noise. Any difference = stop; the patched lib must not change single-slot runs.
- A2. `-slots 2` with the patched lib, but send queries strictly one at a time. Expect byte-identical
  outputs to A1 (a lone slot decodes on AR1, prefill on AR128, same KV columns). Confirm the log
  shows 2 slots created. If outputs differ, record which prompts and the first differing token.
- A3. Repeat A2 for 50 queries alternating long (~1.1k-token) and short prompts, to exercise pool
  reuse across resets. Expect no "Context Size was exceeded" and outputs identical to A1.

Phase B - 2 slots concurrent
- B1. Two clients at once, same prompt pair repeated 20 times. Expect every answer complete (valid
  JSON, closing brace, no SENTENCE_END from a context error), and 0 "evicting" lines. Compare with
  A1 outputs: allow token-level drift from AR128 decode, but decisions/fields should match; count
  exact matches.
- B2. Two clients, random prompts from the regression set, random start offsets (0-2 s), random
  aborts (abort byte on ~20% of queries mid-answer), 200 queries total. Expect no hangs (each query
  returns within the usual time x 2), no truncation, genied never restarts. Note per-stream and
  aggregate decode tok/s (expect roughly half per stream, about equal aggregate - section 5).
- B3. Fault: one client sends a ~1.5k-token prompt while the other runs normal ones. 1.5k + 700 >
  1920, so expect exactly one request to fail with "Context Size was exceeded" - the one that
  arrived **later** - and the other to complete. genied retries the failed one once; check the retry
  succeeds after the other finishes.
- B4. Exhaustion test with `"kv-capacity": 1000` added to the batching block: two ~600-token
  queries. Expect the younger one evicted, the older one complete, then normal service. Remove the
  override afterwards.
- B5. Stress: 30 min of two continuous clients with the app's normal traffic mix; check genied RSS,
  temperature, no "evicting" except where B3-like prompts occur, no restarts.

Phase C - 3 slots (expected to be capacity-bound at CL2048)
- C1. `-slots 3`, three clients with ~600-token prompts. 3 x ~700-900 > 1920: expect the youngest
  request to be evicted in most rounds while the other two complete. This is the documented limit,
  not a bug; the pass criterion is "no truncation of in-flight answers, no hang, no wrong output".
- C2. Three clients with short prompts (~300 tokens, answers <= 200) to confirm 3-way fusion works
  when it fits; expect all complete and aggregate decode ~1.5x of one stream.

Rollback: restore the stock `libGenie.so` and run genied with `-slots 1`.

## 7. Build record

**Status: libGenie.so NOT produced yet.** The Rust toolchain install (needed for the tokenizer
static lib that is linked into libGenie.so) and the queued `build.sh` run were killed by Claude
Code because the PC ran critically low on memory. They were not restarted automatically. To finish:
`wsl bash -lc 'bash <this folder>/build.sh'` after installing rustup + `rustup target add
aarch64-linux-android` (download was running at ~130 KB/s).

What is verified:
- All C++ sources of the patched tree (including every patched file) compile with NDK r26d,
  `APP_STL=c++_static`, the SDK Application.mk flags (130 translation units, 0 errors). The link
  stopped only on the missing Rust tokenizer symbols (a placeholder empty archive was used).
- The 2.50 sample `make/Android.mk` does not build as shipped. `build_fix.patch` adds the missing
  `-I src/qualla/engines` include (nsp-base-model.hpp needs `inference-types.hpp`) and the source
  dirs CMakeLists.txt has but Android.mk lacks (`qualla/encoders/*.cpp`, `encoders/audio-encoders`,
  `decoders/image-decoders`, `embeddings`; otherwise `ModalityEncoder` is undefined), and allows
  `c++_static`.
- Patches apply cleanly to a pristine SDK copy and reproduce the tested tree exactly.
- Stock `lib/aarch64-android/libGenie.so`: 11,273,688 bytes, 118 exported dynamic symbols (all from
  `GenieSymbols.default`), NEEDED = libc, libm, libdl, liblog (static libc++), 16 KB-aligned LOADs,
  BIND_NOW, and it **contains xgrammar** (Qualcomm built with ENABLE_GRAMMAR). The sample source has
  no xgrammar, so the rebuilt library will be smaller and lack grammar support.

Still to do when build.sh runs: `build.sh` compares `nm -D --defined-only` of both rebuilt
libraries against the stock one (expect the identical 118 symbols, since the same version script
is used), lists import differences, NEEDED and sizes, and copies `libGenie.so` and
`libGenie_rebuilt_stock.so` here.
