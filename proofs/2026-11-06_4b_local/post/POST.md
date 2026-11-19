# Post-training chain of the 4B r3 run (rsn3_4b_r3): export + gate, unattended

When the live Qwen3.5-4B r3 run ends, `post_chain.sh` exports the best checkpoint to a Q4_0 GGUF and gates it against
rsn_v1 on the host GPU. Nobody has to touch it. It never touches the board: deployment is the owner's decision.

## Launch (once, any time before training ends)

```powershell
powershell -ExecutionPolicy Bypass -File C:\Users\hp\Desktop\qidk\proofs\2026-11-06_4b_local\post\start_post.ps1
```
This runs `wsl bash /mnt/c/Users/hp/Desktop/qidk/proofs/detach.sh post_4b /mnt/c/Users/hp/Desktop/qidk/proofs/2026-11-06_4b_local/post/post_chain.sh`
plus a hidden keepalive `wsl.exe` (`keepalive.sh post_4b 720`, as in `baton/start_auto.ps1`), so WSL's 15 s idle timeout
does not kill it while it waits. Log: `~/detached/post_4b.log`. Status lines: `[post_4b]` in
`proofs/2026-10-29_rsn_v3/kaggle/STATUS.md`. A status line is written only when the waiting reason changes.

- **Stop:** `wsl touch /mnt/c/Users/hp/Desktop/qidk/proofs/2026-11-06_4b_local/post/STOP`. Waits see it within 30 s. Export
  checks it between phases. The gate kills its llama-server and exits.
- **Resume:** remove `post/STOP` and launch again. Finished steps are skipped (markers in `post/markers/`), and the gate
  result files are resumable.
- Only one instance can run (`post/post.pid`).

## Steps (in order)

| step | what | output | duration |
|---|---|---|---|
| wait | Every 10 min, checks four conditions. (1) Training finished: `chain/train.done`, or `status.json` stopped `after_epoch1`/`early_stop`, or `done: true`. (2) The laptop holds the baton: `baton/BATON` holder=laptop or no BATON file, and no `<run>/BATON_AT_KAGGLE`. (3) Nothing touches the run dir: no `train_rsn3.py ... rsn3_4b_r3`, no live chain_4b pid, no `to_kaggle.sh`/`from_kaggle.sh`. (4) `best.json` exists | `markers/wait.done` | until training ends (epoch 1 ~100-120 h busy, or early stop) |
| pick | Reads `best.json` "top" sorted by gen dev score, newest step first on ties, and takes the first `ckpt_best_XXXX` that has an adapter. It never falls back silently to ckpt_epoch1/latest. The two adapter files are copied with an md5 check to `~/smartcity_runs/rsn3_4b_r3_post/` | `pick.json` (step, score, md5, best.json, gen_eval at that step) | seconds |
| export | `export_4b.sh`: `kaggle/local/merge_any.py`, the same streaming merge and scale convention as `export_gguf.sh`: W' = W + (lora_alpha/r)·B@A = 2.0 for r32/a64. The adapter config is checked: r32/a64, no rslora/dora. Then `convert_hf_to_gguf.py --outtype bf16` and `llama-quantize Q4_0 4`, the rsn_v1 recipe | `Code/models_stage/rsn_v3_4b_r3_q4_0.gguf` + `.md5`; logs + `export.json` in `post/export_r3/` | ~20-40 min |
| gate | `gate_4b.sh` (below) | `post/gate_r3/GATE.md` + `gate.json` | verdict ~3 h after the GGUF; all informational suites ~12-14 h |

### Export safety (the 2026-10-31 crash)
The 4B import of 2026-10-31 ran merge + bf16 convert inside WSL. That grew `ext4.vhdx` on C: by ~16 GB, C: filled, and
WSL crashed in the middle of the convert (`gguf/rsn_v3_4b_1/convert.log` stops at 94 %). WSL frees vhdx space only after
an owner compact. So:

- **The big intermediates live on NTFS:** `C:\Users\hp\AppData\Local\Temp\post_4b_rsn_v3_4b_r3` holds the merged HF dir
  (~8.8 GB) and the bf16 GGUF (~8.7 GB). Deleting them really frees C:, and the vhdx does not grow.
- **Before each phase:** C: free must be >= 20 GB plus what that phase still writes (merge needs ~40 GB free;
  2026-11-06: 62 GB). Windows available RAM must be >= 2 GB and WSL MemAvailable >= 2.5 GB (7 GB cap). The script waits
  up to 24 h with a status line every hour, and never deletes anything to make room.
- **Low RAM:** the merge streams one shard at a time with a <= 1 GiB write buffer (as the 2B and rsn_v1 exports). All
  steps run at `nice -n 15`, `OMP_NUM_THREADS=4`, `MALLOC_ARENA_MAX=2`.
- **Writes:** the GGUF is written as `.part`, then md5, then `mv`, then `md5sum -c`. The script refuses to overwrite a
  staged GGUF it did not make.

### Gate (`gate_4b.sh`, host RTX 4050, llama-server CUDA `~/llama-cuda-b11815`)
- **One GPU job.** The gate waits for an idle GPU: < 800 MiB used, no trainer or llama-server, no `PAUSE_GPU`, and
  `GPU_LOCK` free. It then holds `GPU_LOCK` (`post_4b gate ...`) for the whole gate and runs one llama-server at a time.
- **Watchdog.** It pauses the server (SIGSTOP) at >= 92 C or Windows available < 1.2 GB. It resumes at <= 88 C and
  >= 1.8 GB. Temperature is parsed with `| head -1 | cut -d. -f1 | tr -dc 0-9`. run_v3.py's own `gpu_cool` gets
  HEAT_HI/LO = 92/88.
- **Retries.** Each step is tried up to 4 times, because a long pause can time a client out.

Steps, gate inputs first:
1. `rep`: RWH 150 + round-1 dev 120 (round-1 incident prompt) + P0, with `eval/run_v3.py --tag rsn_v3_4b_r3`, ctx 8192
   (= eval_gguf.sh).
2. `rwh2`: RWH-2 150 (`run_suite.py`). rsn_v1's RWH-2 is cached in `eval/results/ft612` (150/150).
3. `dev3`: chat dev v3 (300) **with the prompt the app sends this model** (`chat_think=adaptive` + `chat_prompt=r3`).
   `chat_r3_eval.py --mode dev3` uses:
   - the 21-tool `tools_r3.json` header (= backend `chat_header_r3.txt`);
   - the r2 system re-rendered to the r3 system exactly as `build_r3.py` re-rendered every r2 row (offline fog line,
     seeded last sync, "full records since 2026-01-01");
   - an open `<think>` capped at 128 tokens, as the app does;
   - ctx 12288.
4. `score1` -> `GATE.md` + `gate.json` with the **verdict**, under the same rule as `kaggle/gate/g2b_r2/GATE.md`:
   - RWH and RWH-2: every report metric >= rsn_v1, schema_err <=;
   - dev: within 1 item;
   - chat dev v3 pass rate > rsn_v1.
   rsn_v1's chat dev v3 is its cached result (`kaggle/gate/rsn_v1_chatdev3_3059c98f8956.jsonl`) with its own trained
   mode (empty think), the same baseline both 2B gates used. Its incident results (ft612) were made with the identical
   incident prompt, so they are reused.
5. `r3new` / `r3v1`: `chat_test_r3` (983 held out). Each record runs in its fog state (online/offline/timeout) on
   `ToolsR3` and is scored by the r3 verifier: the trainer's `--gen-r3` path, with the build_r3 defaults. rsn_v1 runs
   the same r3 prompt with empty think. It never saw the r3 header or the fog tools, so GATE.md marks its column
   **out of distribution**. Reported per fog state, group (new/device), Hinglish, hard and kind.
6. `t2new` / `t2v1`: `incidents_test_r2` (1,368), scored per slice (gen_heldout, heat, targeted, targeted_novel_names).
   Gold is the row's own report. rsn_v1 is cached as `eval/results/ft612/test_r2.jsonl`.
7. `score2`: final GATE.md / gate.json with the informational sections, plus `MD5SUMS`.

Exit codes: 0 PASS, 1 FAIL, 2 incomplete. PASS and FAIL both finish the chain. The final status line names the GGUF, its
md5 and the verdict.

## Files

| file | role |
|---|---|
| `post_chain.sh` | the chain (wait, pick, export, gate) |
| `export_4b.sh` | merge -> bf16 GGUF -> Q4_0, with the disk/RAM guards |
| `gate_4b.sh` | host-GPU gate |
| `chat_r3_eval.py` | chat eval with the r3 app prompt (`--mode dev3` or `r3test`, `--think 1` or `0`), resumable |
| `gate_score_4b.py` | gate verdict + informational tables (reuses `kaggle/local/gate_score.py`) |
| `start_post.ps1` | Windows launcher + keepalive |
| `test/` | dry runs (below) |

## Dry runs done 2026-11-06 (CPU only, no GPU, the live run untouched)

- **Syntax:** `bash -n` on every script, run in WSL.
- **`test/t_gate_score.sh`:** feeding the g2b_r2 inputs to `gate_score_4b.py` reproduces the g2b_r2 GATE.md check table
  exactly (19 rows, FAIL, rc 1). Per-slice test_r2 scoring ran on g2b_r2's 628 items, and the chat slice tables were
  built.
- **`test/t_chat_mock.sh`:** `chat_r3_eval.py` ran against `test/mock_server.py`, a CPU stand-in for `/completion` that
  replays gold calls and then the reference answer. Results:
  - 40 `chat_test_r3` records (every 25th; online, offline and timeout): 37/40 pass. The 3 failures are a mock artifact:
    three `fu_fog_status` records share the same last question, so the mock answered them with the first record's
    reference.
  - empty think: 10/10;
  - chat dev v3 re-rendered to r3: 30/30.
- **`test/t_export_tiny.sh`:** the full `post_chain.sh` ran wait -> pick -> export on a tiny real-config Qwen3.5 and a
  fake finished run. The gate step was pre-marked, and every path was redirected into the scratch dir. Results:
  - pick skipped the missing top checkpoint and took the next one;
  - merge: 25/25 LoRA modules, 0 mismatches against W + 2·B@A, and all 66 other tensors identical;
  - the GGUF has arch qwen35 with 70 tensors (Q4_0/Q8_0/F32);
  - md5 OK, and the NTFS work dir was removed;
  - a second launch skipped every step.
- **`test/t_wait.sh`:** the chain waits while training is not finished, while Kaggle holds the baton, and while
  `BATON_AT_KAGGLE` exists, and it stops cleanly on STOP.
- **Not run:** the GPU gate itself (the live run owns the GPU) and a real 4B merge (8.8 GB).
