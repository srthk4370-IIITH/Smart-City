# 2026-11-04: eval-day chat split (2B chat, 4B reports)

**This is for the evaluation only.** On the chat gate, the fine-tuned Qwen3.5-2B rsn_v3 r2 scored better than the 4B: chat dev v3 pass rate 0.737 vs 0.477 (`proofs/2026-10-29_rsn_v3/kaggle/gate/g2b_r2/GATE.md`). On reports it was worse (RWH severity 0.793 vs 0.919, check recall 0.405 vs 0.848). So the Campus Assistant chat runs on the 2B, and incident reports and the domain agents stay on the 4B and the 3B on the NPU. The 4B keeps training and remains the general model on the device.

## What runs where (final)

| job | model | engine |
|---|---|---|
| domain agents | ft_B50 3B Q4_0 | Hexagon V75 NPU (htpd, resident) |
| incident reports (cross-domain reasoner) | Qwen3.5-4B rsn_v1 Q4_0 | NPU (htpd, swapped in per incident) |
| chat (Campus Assistant), model questions | Qwen3.5-2B rsn_v3 r2 Q4_0 | **CPU, 5 threads** (llama-server, `chatgpu/`) |
| chat, router questions (~90%) | none (deterministic router) | CPU, <1 s |

## Steps and results

1. **Server build.** The Docker toolchain image pull stalled at about 10 MB/min. `gpu/native_build.sh` built llama-server in 3 min instead, with NDK r29, upstream 338fce6, OpenCL on and Hexagon off. It ships its own libs to `/data/local/tmp/chatgpu/lib`, so the NPU libs are untouched.
2. **Stage 1** (`gpu/STAGE.md`): the 2B ran on the GPU next to the live app.
   - fastcheck with the 2B resident: fast alert 5.8 s, AI report 28.0 s, valid. The baseline is 5.6 s and 28 s.
   - no guard kills
3. **Flag sweep** (`gpu/tune/TUNE.md`): 5 warm questions per config, greedy decoding, and every config gave text identical to config A.
   - The GPU tops out at about 10 t/s (`-t 6`): the hybrid model's recurrent ops run on the CPU and sync with the GPU every layer.
   - **CPU only: about 25 t/s** at 5 or 6 threads. 8 threads is slower because the little cores join.
   - `-cms 0 -ub 128`: a warm question re-prefills about 130 tokens instead of about 520.
   - MTP and n-gram speculative decoding did not help, so they were rejected.
4. **App fixes** (APK split2, then split3, split4, split5):
   - GPU chat timeout cut from 2 min to 60 s.
   - **Keep-warm for a hybrid model.** llama-server can only resume a Qwen3.5 prompt from a checkpoint, which sits about one micro-batch before the end of each prompt. The hourly time line in the prompt comes right after the 15-tool header. Before the fix, every new question re-prefilled about 3,100 tokens (11.8–14 s on the GPU). The keep-warm now sends the header alone, then the hour's prefix, every 30 s, at about 4 tokens per ping once warm. A new question then re-prefills about 290 tokens (1.7 s on the GPU).
   - The badge follows the profile key `chat_device` (`qwen3.5-2b rsn_v3 (cpu|gpu)`).
5. **Deploys:** deploy32 (split7, chat UI names the engine) is the final one. deploy31 (split6) added the repeated-tool-call guard and the header pre-warm after a server (re)start.
   - deploy28 (split2, GPU), deploy29 (split3, GPU) and deploy30 (split5, CPU)
   - each one ran chaos 2 and fastcheck before the split was turned on, and fastcheck again with the 2B resident
   - the status of each is in its `deployNN/STATUS.md`

## Fallback during the evaluation

- `bash proofs/2026-11-04_split/split_off.sh` (WSL), about 10 s, no app restart. It removes `chat_url`, `chat_think` and `chat_device` from htpd_profile, which the app reads on every call, so chat goes back to the 4B on the NPU. It also stops the 2B server.
- `split_on.sh` turns the split back on in about 45 s. It adds the profile keys only after the server is healthy and has finished its header pre-warm, so the first answer is warm (rehearsal: 5.7 s; `fallback_rehearsal.txt`).
- If the 2B server fails a call, the app falls back to the 4B for that call and skips the 2B for 60 s.
- Full revert to the pre-split APK e0ccda2b: `deploy28/known_good/` (app.apk + htpd_profile).

## Sweep and demo

- d30 sweep vs d27: `CMP_d27_d30.md`: 160/160 answered, 0 errors, router 143/160 with a median of 0.2 s.
- Demo questions: `DEMO.md`.
