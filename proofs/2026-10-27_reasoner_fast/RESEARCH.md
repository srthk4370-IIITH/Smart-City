# Reasoner latency on the QIDK NPU: ranked levers (2026-10-27)

Scope: rsn_v1 (Qwen3.5-4B Q4_0 with the LoRA merged) running in htpd_v8r on the Hexagon V75 HTP (llama.cpp 620d2225).
Rule: accuracy comes first. The SPEC §9 contract is frozen, and the owner rejected the §10 output cuts.
Every number below was **measured on the board** unless it is marked *est*.
Raw data is in `raw/` and `bench/`, the scripts are in `scripts/`, and RESULTS.md has the A/B tables.

## 0. Where the 29 s goes (INC-0362, board log)

| part | time | evidence |
|---|---|---|
| swap: agents' model unload + reasoner load | 0.15 + 3.4-4.2 s | `htpd: reasoner loaded in 3597 ms` |
| prefill of the prompt after the cached 1,317-token static prefix | 1.9 s | `prefill 1912 ms, cache disk (1317 tokens, 134 ms)` |
| decode: 424 tokens (116 forced) in 307 steps | 25.5 s (83 ms/step) | `reason stream 0` |
| agents' model reload (on the next agents request, or after 20 s idle) | 2.5-2.9 s | `agents' model back in 2529 ms` |

- The "4.9 s prefill" was the **first** request after boot. It prefills the static prefix and saves its state (2.1 s). Every later request restores the prefix from disk in 134 ms, so the prefix cache **is** hit.
- **Decode is 87% of the reasoner time.** Speeding up decode is the only lever bigger than about 2 s.

## 1. Decode is at the memory-bandwidth roof

`GGML_HEXAGON_PROFILE=1` per-op profile of single-token decode (`scripts/prof_agg.py`, `raw/prof_err.txt`, 23 decode graphs):

- One token takes **60 ms on the HTP** (797 ops in one op-batch, so one RPC per token).
- The matmuls take 51 ms of that and read 2.6 GB of weights at about 52 GB/s:

  | weight | time per token | share |
  |---|---|---|
  | ffn gate+up | 16.3 ms | 27% |
  | lm_head (tied Q6_K `token_embd`, 497 MB) | 9.6 ms | 16% |
  | ffn_down | 8.5 ms | 14% |
  | GDN qkv/gate/out | 11 ms | 18% |

- GATED_DELTA_NET itself takes 3.0 ms (5%), and ROPE (IMROPE) 0.2 ms (0.4%). Neither is a bottleneck.
- **Env knobs** (llama-bench tg32; `raw/prof/tg_*.md`, rerun with the env actually applied):

  | knob | tok/s | vs base | verdict |
  |---|---|---|---|
  | base | 14.72 | — | — |
  | `GGML_HEXAGON_OPPOLL=1` (poll for completions) | **15.65** | **+6%** | **adopted**; in htpd A/B2 27.8 → 25.8 s |
  | NHVX=2 | 10.86 | −26% | no |
  | POWER_MODE=sustained_high_performance | 14.30 | −3% | no |
  | OPFUSION=0 | 13.81 | −6% | no |

Batch cost per decode call (llama-bench, `raw/bench_server/llama_bench.md`):

| tokens in the batch | 1 | 2 | 3 | 4 | 6 | 8 | 16 | 64 |
|---|---|---|---|---|---|---|---|---|
| ms per call | 66 | 82 | 113 | 133 | 106 | 109 | 120 | 171 |

- Batches of 2-4 tokens run the HVX matmul, which is not weight-stationary across the batch rows.
- From 5 tokens up (`HTP_MM_HMX_MIN_NROWS` = 4), the HMX path is used. It has a fixed cost of about 106 ms.
- So **verifying k draft tokens costs 1.25× (k=1) to 1.6-1.8× (k≥5) a plain step.** A speculative scheme only wins if it keeps more tokens per step than that ratio.

## 2. Ranked levers

| # | lever | measured effect | accuracy | verdict |
|---|---|---|---|---|
| 1 | **Single-domain incidents through the reasoner**, deterministic report as fallback only (owner) | +30 s per single-domain incident (was 0.9 s). The title and severity stream after about 7 s | the reasoner owns the wording | **done (Go)**, see RESULTS §3 |
| 2 | **Gate repair: trim over-long lists** (evidence > 6, and so on) instead of rejecting the report | two of two 3 h refinements on the board had been thrown away for 7 evidence ids | keeps the reasoner's report; within the §3 limits | **done (Go)** |
| 3 | **Stream severity with the title** (2nd key, provisional until the gate accepts) | severity shown about 0.5 s after the title, about 7 s into the reasoner instead of about 30 s | provisional flag kept | **done (Go)** |
| 4 | Prompt-lookup (n-gram) speculative decoding in htpd (`HTPD_REASON_SPEC`, htpd_v8s) | see RESULTS §2 (board A/B). Offline simulation on 3 real outputs: 1.2-1.4 tokens per step | lossless by construction (greedy + forcer verify); outputs can differ only by batch numerics, as forced batches already do | **built**; on or off decided by the A/B |
| 5 | MTP self-speculation (base MTP head; the merge kept blk.32 `nextn`, so it **works** with the merged weights) | llama-server on the HTP: acceptance **72-78% (K=2)** and **63-67% (K=3)**, but decode is **1-20% slower** (32.3 → 32.7 s at K=2, → 38.8 s at K=3) | lossless | **rejected as is**. Each MTP draft runs the full 248k-vocab Q6_K lm_head (about 10 ms) plus CPU sampling. With pp2/pp3 verify costs it cannot pay off. It would need a reduced-vocab draft head in a ported htpd MTP driver (*est* −20-25% decode at K=1, about 600 lines of work) |
| 6 | lm_head Q6_K → Q4_0 (untied `output.weight`, `scripts/add_output_q4_0.py`) | **measured: 27.8 → 26.7 s (−4%)** | moved 1 RWH label away from gold | **not adopted** |
| 6b | **Vocabulary-pruned lm_head** (32,864 kept tokens: corpus + ASCII ≤ 4 chars + specials; Q6_K rows copied bit-exactly; `libllama_p.so` expands to n_vocab with −inf; htpd_v8p) | 1 request ran (34 s, warm-up); HTP model buffer 2448 → 1988 MB; *est* −8 ms/token (−12%) | lossless whenever the argmax is in the kept set; the corpus answers use only 1,321 distinct tokens | **on hold**: the board rebooted during the 2nd request (02:11, 90-94 °C, cause unknown). Retry only on the owner's go |
| 6c | OPPOLL=1 | **27.8 → 25.8 s (−7%)**; agents identical | lossless (host-side wait only) | **adopted, live** |
| 7 | HTP small-batch matmul (HVX multi-row, weight-stationary for m=2-4) | *est* pp2-4 → about 70 ms, which would make forced batches and K=1 drafts nearly free (−15-25% decode) | lossless | needs a DSP kernel rebuild (Hexagon SDK in the docker image; Docker is not running). Proposed |
| 8 | Keep the reasoner resident / two models | — | — | **rejected on paper**: two resident models rebooted the board (HANDBOOK 2.27/2.37). One Hexagon PD maps about 3.5 GB; 2.45 GB reasoner + 2.8 GB agents do not fit one session, and two sessions are the reboot class (ROOT_CAUSE 2026-10-22). Not tested |
| 9 | Preload the reasoner during the agents' run / overlap the agents and the reasoner | — | — | impossible with one model per process (#8). Already minimal: the swap starts the moment the last agent answers. With `keep`, queued reports share one swap |
| 10 | Quant type | Q4_0 is the only type on the tiled HMX/HVX fast path. Q4_K_M is +6.6% bytes ([PLAN §4 #8](../2026-10-26_reasoner_deploy/PLAN.md)) | — | keep Q4_0 |
| 11 | Threads / ubatch / graph reuse / op offload | one graph per token, 2 splits; only OPPOLL helps (§1) | — | nothing left |
| 12 | Smaller draft model (Qwen3.5-0.8B) | — | — | rejected: a second model in the session is #8. Its draft cost (about 0.5 GB of weights per token, about 12 ms) plus pp2+ verify (≥ 82 ms) is no better than MTP |
| 13 | Prefix cache | already hit: 134 ms restore from disk (first request after boot: 2.1 s save) | — | done (v8r) |

## 2b. What made the Llama agents fast, and whether it transfers (HANDBOOK 2.37/2.47, proofs/2026-10-21_latency_ladder)

| Llama/htpd trick | effect on the agents | reasoner (Qwen3.5 hybrid) |
|---|---|---|
| Batched decode across streams (10 agents in one weight sweep) | 13 agents 68 → 23 s | **applied as split decoding (htpd_v8x).** The answer head is decoded once, then the state is copied to 3 sequences that decode field groups in parallel. Board A/B in RESULTS §6 |
| System-prefix KV cache (`HTPD_PREFIX_CACHE`, synth prefix cache) | prefill 8.7 → 6.8 s | already applied: whole-state prefix cache (disk 134 ms) |
| n-gram / role drafts (`HTPD_DRAFT`, K8) | 22 → 16.4 s; role drafts rejected (accuracy) | measured and rejected: needs recurrent snapshots, which double prefill, and only 17-26% of drafts are kept (§2 #4) |
| JSON abort / max_new caps | bounds runaways | n/a: the forced schema closes the answer (`stop json` on every board output); max_new 700 |
| `GGML_HEXAGON_HMX_PIPE_ALL=1`, legacy prefill | 28-31 → 24 s | already in the env (inherited) |
| Parked finished streams | — | inherent: finished split streams leave the batch |
| Genie / QNN instead of llama.cpp | Genie Llama-3B w4a16 decodes at 19.2 tok/s (HANDBOOK §5), the same as llama.cpp HTP at about 19 tok/s | **not feasible for Qwen3.5.** AI Hub lists Qwen3.5 as "not supported on any chipset"; Qualcomm's own Qwen3.5 assets ship for GenieX's **llama.cpp** runtime at q4_0, the path we already use. No Gated-DeltaNet QNN op is documented |
| Two-stage report (instant deterministic report, then the reasoner's) | — | **applied (fast3)**: preliminary report 1-7 s after the event; the reasoner's replaces it at 29-46 s |

## 2c. Deep round 2 (owner: "can be improved significantly"), ranked by measured or estimated gain

| # | idea | finding | gain | status |
|---|---|---|---|---|
| 1 | Split decoding (parallel field groups after the head) | measured | **−8…−15%** | **live (fast4)** |
| 2 | Weight-stationary HVX matmul for 2-4 rows (DSP kernel) | forced rows add about 15 ms/step (84 vs 66-70 ms), about 4.7 s per report. Split and MTP lose because 2-4 row steps cost 82-133 ms. A kernel that streams the weights once for m ≤ 4 makes all three cheap | *est* −15-20% alone; with split/MTP up to about −40% | needs the Hexagon SDK toolchain (docker image ghcr.io/snapdragon-toolchain/arm64-android, several GB, Docker Desktop not running, laptop RAM tight). **Proposed; needs a go** |
| 3 | Newer ggml-hexagon than 620d222 | upstream has moved the HMX/HVX matmul choice to the DSP and unified the weight layout on x4x2 (PR #20693); Q4_1 matmul, PAD and SOLVE_TRI ops. No PR found that targets small-batch decode | unknown, likely small | same toolchain as #2; benchmark-only A/B when the image is available |
| 4 | Pruned lm_head (32,864 tokens) | 16% of decode is the lm_head | *est* −12% | built; on hold after the 02:11 reboot |
| 5 | Compact output keys / positional layout (round-3 training change) | key and punctuation tokens are already **forced**, so they cost no decode steps, only extra rows in the step that carries them. Row-cost model on the 30 RWH outputs: keyed 18.0 s, short keys 18.0 s, positional 17.4 s of model decode (`scripts/sim_forced_rows.py`) | about −0-3% | **not worth a retrain**. The steps are the model-chosen value tokens (about 310), which only a shorter answer can cut (rejected by the owner) |
| 6 | Reasoner on the Adreno GPU (OpenCL) beside the NPU agents | kgsl and rpcmem buffers are both unmovable; 2.6 GB + 2.8 GB in the 7.26 GB Normal zone is the reboot class (HANDBOOK 2.27/2.37). Llama-3B OpenCL decodes at 22 tok/s on this board (PLAN §3), not 2× | removes the 3.5 s swap, no decode gain | **rejected on paper (memory safety)** |
| 7 | Other runtimes (MNN, MLC/OpenCL, ExecuTorch-QNN, Genie/QNN, PowerServe) | none of them runs Qwen3.5's Gated DeltaNet on the Hexagon NPU. Qualcomm's own Qwen3.5 assets ship for **GenieX's llama.cpp runtime at q4_0**, our path. Genie Llama-3B w4a16 = 19.2 tok/s = llama.cpp HTP (HANDBOOK §5) | none | rejected |
| 8 | Physical bound | 2.45 GB of weights per token at the measured about 52 GB/s gives 47 ms of pure matmul. We are at 60 ms on the HTP (66-70 ms wall). Even a perfect kernel gives about 20 tok/s for a 4B Q4 model on 8 Gen 3; **2× (28 tok/s) per stream is not reachable by kernels alone**. Only fewer sequential steps (split, speculation with cheap verify) or fewer model tokens get there | — | — |
| 9 | LoRA unmerged? lm_head on CPU? mmap? | merged (one GGUF); the lm_head runs on HTP (`output` duplicated to HTP0, 2448 MiB buffer); load 3.3-3.9 s from page cache | — | nothing to fix |

## 3. Sources
- Leviathan, Kalman, Matias, *Fast Inference from Transformers via Speculative Decoding*, ICML 2023 (arXiv:2211.17192). This is the lossless greedy verification used in #4 and #5.
- Saxena, *Prompt Lookup Decoding* (github.com/apoorvumang/prompt-lookup-decoding). The n-gram draft from the prompt; llama.cpp `examples/lookup` (PR #4484).
- arXiv:2601.11580, *Speculative Decoding: Performance or Illusion?*. It finds that n-gram drafting only helps when the output reuses prompt spans.
- llama.cpp MTP speculative decoding (`--spec-type draft-mtp`, PR #22673). The tree used here has `common_speculative` draft-mtp and `n_rs_seq` recurrent rollback for qwen35 (`src/llama-memory-recurrent.cpp`, `llm_arch_supports_rs_rollback`).
- Victor M., *Speculative decoding in llama.cpp — MTP vs the others* (HF space): upstream acceptance of about 72-82% for Qwen MTP heads on GPUs. Our 72-78% at K=2 matches it, but on the HTP the draft cost dominates.
- ggml-hexagon sources (620d2225): `HTP_MM_HMX_MIN_NROWS = 4` (matmul-ops.h), `HTP_GDN_MIN_TOKENS = 8`, and the GDN HMX path requires K==1 snapshots (`ggml-hexagon.cpp:5411`).
- Qualcomm AI Hub, Qwen3.5-2B model page (aihub.qualcomm.com/models/qwen3_5_2b); huggingface.co/qualcomm/Qwen3.5-0.8B (GenieX llama.cpp q4_0 asset); Qualcomm developer blog, *GenieX developer preview* (2026-06).
- proofs/2026-10-22_board_crash/ROOT_CAUSE.md and HANDBOOK 2.27/2.37: one Hexagon PD maps about 3.5 GB, and two resident models rebooted the board.
