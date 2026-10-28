# Reasoner on the Adreno 750 GPU, domain agents on the NPU: research (2026-10-28)

## 1. How the QIDK GPU works for LLM decode
- **Hardware.** The Adreno 750 shares LPDDR5X with the NPU and CPU. The theoretical peak is 68 GB/s; large copies reach ~62 GB/s.
- **Decode is bandwidth bound.**
  - One engine alone reaches ~40-45 GB/s in decode; the GPU reaches 43.3 GB/s.
  - The GPU and NPU decoding concurrently reach 59.5 GB/s in total. Each engine therefore slows down when both run (HeteroInfer, arXiv 2501.14794).
- **Runtime.** llama.cpp OpenCL is Qualcomm's own backend.
  - Q4_0 is the primary type.
  - Weights are image/texture backed and flattened into separate arrays (SoA).
  - The kernels use subgroup GEMV.
  - The kernel program cache avoids JIT on later runs (IWOCL 2026, Wang et al.).
- **Our tree is stale.** The tree on the board (620d222, Oct 16) is the one where "OpenCL matmuls do not batch" (HANDBOOK 2.37). Upstream 338fce65 adds:
  - GATED_DELTA_NET + SSM_CONV OpenCL ops, which Qwen3.5 needs, so nothing falls back to the CPU;
  - multi-column GEMV for 2-4 rows (`GGML_OPENCL_Q40_MC3`, `Q6K_MC3`; byte-identical, opt-in). These are made for MTP and split verify batches;
  - DP4A dense prefill (`GGML_OPENCL_Q4_0_DENSE_DP4A`, on by default only on X2 Elite);
  - large-buffer support (`GGML_OPENCL_ADRENO_USE_LARGE_BUFFER`);
  - flash-decoding / FA kernels with a DK=256 path (Qwen3.5 head dim). Some of this is still in the Qualcomm fork only.
- **Not public.** Qualcomm's fastest Qwen3.5 path is an "internal ILA path" (inline assembly). It is not public yet; it will come via QPM or a vendor extension.

## 2. Latency deduction (per incident, after the agents finish)
| step | NPU today (split-3) | NPU split-6 (queued A/B) | reasoner on GPU (estimate) |
|---|---|---|---|
| model swap | 3.6 s | 3.6 s | **0** (resident) |
| prefill | 2.0 s (1,317-token static prefix from the disk cache) | 2.0 s | 1-1.7 s, **if** the static + sensor part is prefilled on the GPU **while the NPU agents run**, leaving only the ~300-token agent-findings tail; ~6 s without that overlap (old pp 177 t/s) |
| decode | ~18 s | ~11 s (6-row HMX steps ≈ 3-row cost) | ~18 s: 2.45 GB/token at ≤43 GB/s gives ≤17.5 t/s per stream; split-3 only pays off with mc3 (≈1.2× the cost of 1 row, unmeasured) |
| **total** | **~24 s** | **~17 s** | **~19-20 s** |
| agents' model reload before the next incident | 3-4 s | 3-4 s | **0** |
| next incident's agents during this report | wait | wait | **run concurrently** (both engines slow ~25-35% from shared bandwidth) |

- **Single report:** the GPU is about the same as NPU split-6.
- **Bursts and multiple incidents:** the GPU wins clearly, with no swaps or reloads and agents and reasoner running in parallel.
- **Combining both:** split-6 on the NPU and the GPU reasoner are alternatives for the reasoner. The HMX 6-row trick exists only on the NPU.

## 3. The gate: memory safety
- **Why it rebooted before.** kgsl (GPU) and rpcmem (NPU) buffers are unmovable and must fit the 7.26 GB Normal zone. Genie 3.1 GB + a second 3B on the GPU rebooted the board (HANDBOOK 2.37).
- **Footprint now.** B50 on the NPU is ~2.6-2.8 GB. The reasoner on the GPU is 2.45 GB, or ~2.0 GB with the pruned lm_head. That leaves ~4.6-5.2 GB in the zone.
- **Guard proven since 10-16.** llama runs at oom_score_adj 1000 (it dies first), with a MemAvailable kill guard and one rung at a time; no reboot since.

## 4. Plan
1. **Queued (safe, GPU alone, app stopped).** `gpu_bench.sh` runs after split6 when the board connects:
   - old vs new tree, default vs MC3, MC3+DP4A and MC3+FA;
   - pp1/2/3/4/6/8 step cost, pp512 and tg64;
   - kgsl and Normal-zone telemetry.
2. **Owner gate: coexistence memory test.**
   - htpd agents-only (B50 on the NPU, idle) + llama-bench reasoner on the GPU;
   - oom_score_adj 1000, abort below 1 GB Normal free, no app;
   - pass = 3 cycles with Normal free ≥ 1.5 GB.
3. **If the GPU numbers hold (tg ≥ 14 t/s, 3-row ≤ 1.3×).**
   - htpd: reasoner context on the OpenCL device (no swap);
   - Go: send the reasoner prefix (static + sensors) at incident start, then append the agents' findings;
   - board A/B vs split-6 on the 30 RWH prompts plus an app chaos run.
4. **Lower bound on decode.** Per stream, nothing beats ~17-20 t/s on this SoC (bandwidth). Only parallel streams (split-N), fewer bytes per token (pruned lm_head, −16% of decode bytes) or fewer output tokens cut decode further.

Sources: IWOCL 2026 "Advancing OpenCL-Based LLM Inference in Llama.cpp on Qualcomm Adreno GPUs"; arXiv 2501.14794 (HeteroInfer); llama.cpp PR #10693 and docs/backend/OPENCL.md; llama.cpp 338fce65 `ggml-opencl.cpp`; HANDBOOK 2.37.
