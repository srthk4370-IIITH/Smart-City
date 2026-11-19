# htpd v9h: reasoner KV pool + M2 chained static prefix (built 2026-11-12, NOT on the board)

## What changed (htpd only; ggml-hexagon and the deployed libs untouched)
`v9h.patch` = diff against v9f (`proofs/2026-10-31_night/v9f/htpd_v9f.cpp`). Every change is env-gated. Without the
new env, v9h runs v9f's code paths, and the host shows bit-identical logits (h0 below).

| env | effect |
|---|---|
| `HTPD_REASON_POOL=N` | The split-spec + unified-KV reasoner context gets N cells in total (v9f: streams x `--reason-ctx` + 256). `--reason-ctx` stays the per-stream cap. `POOL=12544` + `reason_ctx=8192` is today's allocation (3x4096+256), and one chat stream may use 8192. Ignored without unified KV |
| (always) | A `llama_decode` returning 1 (no free KV cell, i.e. the pool is exhausted) ends the request with stop `ctx`, not `error` |
| `HTPD_REASON_CHAIN=1` | **M2.** A static `prefix` that is in neither memory nor on disk is built on the longest known static state that is a prefix of it (memory, or the disk files' token headers, which are scanned once per process). If another known key shares a head of >= `HTPD_REASON_CHAIN_MIN` (1024) tokens with it, and no known prefix reaches within `HTPD_REASON_CHAIN_SLACK` (256) of that head, the state at the end of the head is saved once as a **base** (disk + memory, LRU-touched on every use). For r3 the base is header + "...Device time: 2026-11-15 ", about 4.6k tokens, so each new hour prefills only about 380-490 tokens. Cache kinds: `chain-base`, `chain-mem`, `chain-disk` |
| `HTPD_REASON_MEM_STATIC` | Static states kept in memory: default 2, or 3 with the chain. A base is evicted last |

There is no app change: the app's NPU keep-warm already sends `prefix` = the hour's r3 prefix. The state file naming
is unchanged, so files are compatible with v9f both ways.

## Build
- Board: `build_v9h.sh` (WSL, NDK r26d, flags and libs of v9f, nice). `htpd` md5 **7296d50264c77585c6c7e32180a5f313**.
  Source `htpd_v9h.cpp` md5 9023b92e51eb10f8408348924f26e128 (= `Code/smart-city-edge-agent/app/htpd/htpd.cpp`). One
  pre-existing warning (`n_act`). Log: `build.log`.
- Host: `~/v9host/htpd_v9h` (md5 2ea9da0a), built with `proofs/2026-10-30_spec_split/v9work/build_host.sh`.

## Host test (WSL CPU, `host_run.sh` -> `host_test_v9h.py`; raw: `host/host_results_ERC.json`, `host/htpd_*.log`, `host/run.log`)
- Model: rsn_v3 2B r2 Q4_0 (qwen35 hybrid, the same architecture and tokenizer as the 4B r3). The 4B did not fit next
  to the other jobs.
- Prompt: the exact r3 chat prefix (chat_header_r3.txt + time/fog line + chat_system_r3.txt + user turn) = **4,998
  tokens**.
- Greedy decoding, 48 new tokens, split-spec on (`HTPD_REASON_SPLIT_SPEC=8`), 3 streams, CPU -t 6, nice.
- Per-pick logits trace (`HTPD_REASON_TRACE`: picked token, top-1/2 logits, FNV hash of all logits).

**E: equivalence.** Hours 10/11/12/20 on 2026-11-15, two questions. All configs use `--reason-ctx 8192`, because at
4096 the r3 prefix alone overflows (test C).

| config | h10 | h11 | h12 | h20 |
|---|---|---|---|---|
| f = v9f (pool 24832), cache / prefill s | saved 101.7 | saved 118.6 | saved 104.1 | saved 101.6 |
| h0 = v9h, no env | saved 105.9 | saved 102.0 | saved 218.1* | saved 82.6 |
| hp = v9h POOL=12544 | saved 95.5 | saved 106.7 | - | - |
| **hc = v9h POOL + CHAIN** | saved 102.2 | **chain-base** 95.3 (base 4,618 built) | **chain-mem 7.6** (wall 12.3 s) | **chain-base** 87.2 (base 4,617: hour "2x" vs "1x") |

\* host CPU contention (another job), not a code effect.

- **h0 vs f:** 4/4 requests have the same text and the same picks, and every step's logits are **bit-identical** (hash
  match on 172/172 steps). No regression without the env.
- **hp vs f:** 2/2 bit-identical. The pool size alone does not change the numerics.
- **hc vs f:** 4/4 have the same text and the same picked tokens at every step.
  - h10 (no chain) is bit-identical.
  - The chained ones differ by at most **0.33 in the top-1 logit**. Splitting the prefill at the base boundary
    changes the CPU float accumulation, the same class of effect as v9f's own prefix/turn split.
  - The model sees the same tokens.
- **R, restart (new process, same disk dir), hour 13:** `chain-disk`. The base was found by the disk scan. Prefill
  10.2 s vs 99.5 s for v9f (31 s wall incl. the model loads). Same text and picks as v9f (max top-1 diff 0.31).
- **Speed-up of a new hour's prefix:** prefill 7.6 s (memory base) / 10.2 s (disk base) vs ~100 s full, i.e. **9.8-13x**.
  On the board's NPU (425-545 tok/s) the expected first-of-hour cost is ~4 s swap + ~1-1.5 s, vs 4 + 10-13 s.

**C: context.** Prompt = r3 prefix + ~2.1k tokens of history + question (~7.1k tokens), 32 new tokens.

| config | result |
|---|---|
| f4 = v9f `--reason-ctx 4096` (the live per-stream cap) | **stop `ctx` after 1 token**: the blocker reproduced |
| h8 = v9h `--reason-ctx 8192` + POOL=12544 (n_ctx 12544, the same cells as live) | **32 tokens, stop `max`**: fits |
| hx = v9h POOL=6144 (pool smaller than the prompt) | prefill `rc 1` -> **stop `ctx`** (v9f would report `error`) |

## Not done / limits
- **M3** (pre-build the next hour at HH:50) needs an APK change (the app knows the next hour's prefix, htpd does not).
  It is not built. With M2, a pre-build would cost only ~1.5 s of NPU time. M1 keep-warm already pays the hourly
  rebuild while the chat page is open.
- **Not tested on the host** (the board will show them):
  - NPU numerics: the chained split on HTP fp16 may differ more than 0.33 in the logits. The board A/B compares answers.
  - HTP buffer mapping: the pool keeps the live 12,544 cells, so the expected mapping is the same.
  - Board RAM: +1 static state in memory (~130 MB with r3), plus one base file on disk per day.
- Board A/B plan + rollback: `proofs/2026-11-06_4b_local/board/DEPLOY_R3.md` section 0b ("htpd v9h is BUILT", V0-V4).
