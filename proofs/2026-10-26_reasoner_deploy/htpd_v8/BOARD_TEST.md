# htpd v8 (reasoner slot): board test, to run only AFTER reasoner training is finished and the owner says go

Built 2026-10-26, CPU only. The board was not touched and no model was loaded.

- **Binary:** `htpd`, Android arm64, md5 in `htpd.md5`.
- **Source:** `Code/smart-city-edge-agent/app/htpd/htpd.cpp` + `reason_logic.h`. The protocol is in the file header, under "v8 reasoner additions".
- **Build:** `app/htpd/build_htpd_wsl.sh`. It uses the same flags, headers and `build-snapdragon/bin` libraries as `build_htpd.sh` (llama.cpp 620d2225).
  - Only the toolchain differs: WSL NDK r26d instead of the r29 docker image. Docker Desktop was not running.
  - htpd uses only the llama C API and links libc++ statically. Its NEEDED list is the same as the deployed htpd_v8.
  - If the owner wants an exact-toolchain rebuild: `build_htpd.sh Code/smart-city-edge-agent/app/htpd <out>`, with Docker running.
- **Host evidence:**
  - `forcer_gold_test.txt`: the forcer accepts all 6,046 gold answers byte for byte. 39.6% of the answer bytes are forced.
  - `go_test.txt`: `go test ./...` passes.

**Board name.** Push the binary as `htpd_v8r`. The board already has a different `bin/htpd_v8` (the 2026-10-22 LoRA build), and it must not be overwritten.

**Safety rules, for every step.**
- One NPU client at a time.
- Stop the app and every htpd, then **wait for them to exit**.
- Big files go up as `.part`, are checked, then `mv`'d, with the app stopped.
- **Never reboot.** If the board drops, stop and collect logs (`proofs/2026-10-22_board_crash/ROOT_CAUSE.md`).

## 0. Preconditions
- Training is finished, and the reasoner is merged and converted to GGUF Q4_0 on the host.
  - Call it `qwen35_reasoner_q4_0.gguf`, about 2.6 GB.
  - It has passed the host harness (`run_host_harness.sh`) and the host gate.
- The host has `md5sum <gguf> > <gguf>.md5`.
- `adb devices` shows the board, and nothing else is using it.

## 1. Stop everything and record the current htpd command line
```sh
A=adb
$A shell 'P=$(pgrep -f "[b]in/htpd" | head -1); [ -n "$P" ] && { tr "\0" " " < /proc/$P/cmdline; echo; tr "\0" "\n" < /proc/$P/environ | grep -E "^(HTPD|GGML|LD_LIBRARY|ADSP)"; }' > htpd_cmdline_before.txt
$A shell 'am force-stop com.iiith.smartcityedge; pkill -x edge-agent; pkill -f "[b]in/htpd";
          for i in $(seq 1 60); do pgrep -f "[b]in/htpd" >/dev/null || break; sleep 1; done;
          pgrep -fl "[b]in/htpd|genied|edge-agent" && echo "STILL RUNNING - STOP HERE"; sleep 10'
$A shell 'sync; echo 3 > /proc/sys/vm/drop_caches; echo 1 > /proc/sys/vm/compact_memory; grep -E "MemAvailable|MemFree" /proc/meminfo'
```

## 2. Push the binary and the reasoner (app stopped)
```sh
$A push htpd /data/local/tmp/llama.cpp/bin/htpd_v8r.part
$A shell 'cd /data/local/tmp/llama.cpp/bin && md5sum htpd_v8r.part'        # small file: on-board md5 is fine
# must equal htpd.md5, then:
$A shell 'cd /data/local/tmp/llama.cpp/bin && mv htpd_v8r.part htpd_v8r && chmod 755 htpd_v8r'
# the 2.6 GB GGUF: .part + size check + host md5 sidecar (HANDBOOK: no on-board md5sum of multi-GB files)
$A push qwen35_reasoner_q4_0.gguf /data/local/tmp/gpu/qwen35_reasoner_q4_0.gguf.part
$A push qwen35_reasoner_q4_0.gguf.md5 /data/local/tmp/gpu/qwen35_reasoner_q4_0.gguf.md5
$A shell 'stat -c %s /data/local/tmp/gpu/qwen35_reasoner_q4_0.gguf.part'   # must equal the host size
$A shell 'mv /data/local/tmp/gpu/qwen35_reasoner_q4_0.gguf.part /data/local/tmp/gpu/qwen35_reasoner_q4_0.gguf'
$A shell 'df -h /data; sync; echo 3 > /proc/sys/vm/drop_caches'
```

## 3. v7 reference outputs (htpd_v7 alone, app stopped)
```sh
$A pull /data/local/tmp/smart_city_edge/htpd_warmup.jsonl agents_requests.jsonl
```
1. Start `htpd_v7` exactly as in `htpd_cmdline_before.txt` (same env, args and `LD_LIBRARY_PATH`/`ADSP_LIBRARY_PATH`), with `nohup ... > /data/local/tmp/htpd_v7_ref.log 2>&1 &`.
2. Wait for `htpd: ready` in that log.
3. Run `adb forward tcp:8091 tcp:8091`, then `python3 -I probe_v8.py v7_ref.jsonl --agents agents_requests.jsonl --v7 1`.
4. Stop it with the step 1 stop block. **Wait for exit.**

## 4. v8 standalone (htpd_v8r alone, app stopped)
1. Start it with the same command line, with the binary changed to `htpd_v8r` and these additions:
   `--reasoner-model /data/local/tmp/gpu/qwen35_reasoner_q4_0.gguf` and env `HTPD_REASON_IDLE_MS=60000`.
   Log to `/data/local/tmp/htpd_v8r_test.log`.
2. Wait for `htpd: ready` and `v8 reasoner slot` in the log. Then run:
   ```sh
   python3 -I probe_v8.py v8_probe.jsonl --agents agents_requests.jsonl
   python3 -I -c "import probe_v8 as p; print('v7 == v8 agents:', p.compare_outputs('v7_ref.jsonl','v8_probe.jsonl'))"
   ```
3. Watch the board in a second shell during the first reason request:
   `adb shell 'while sleep 2; do grep MemAvailable /proc/meminfo; done'`.
   If MemAvailable falls under 800 MB, run the stop block at once.

**Pass criteria.** Write them into RESULTS.md with the raw files.
- **v7 regression.** The agents outputs are identical to v7 (`compare_outputs` True), before and after the swap.
- **Swap.** The log shows `reasoner loaded in X ms (agents' model unloaded in Y ms)` and later `agents' model back in Z ms`.
  - Expected: X ≈ 2 s, Z ≈ 2 s (PLAN §3).
  - There are never two models: the agents' model is freed before the reasoner load.
- **Prefix cache.**
  - First reason request: `cache` is `saved`, and `PATH.prefix_<hash>.state` (≈ 100 MB) appears next to the GGUF.
  - Later requests: `mem`.
  - After a release and a new reason request: `disk`, and `cached_tokens` ≈ 1,317.
- **Placement.** In the log, after the reasoner context is created: the `graph splits` count, and no CPU-fallback warnings for GATED_DELTA_NET/SSM_CONV.
  - If splits > 2, rerun once with `GGML_SCHED_DEBUG=2` and keep that log.
- **Forcing.**
  - `reason_schema` outputs parse as JSON with stop `json`.
  - `forced` ≈ 35-45% of `tokens`.
  - `reason_free` (no schema) gives the same field values on these fixtures. If not, record the diffs: the forcer keeps the model's choice except where the layout deviates.
  - Also record the decode tok/s of both.
- **Correctness vs host.** Run the same fixtures on the host llama-server CPU (`run_host_harness.sh`), then diff (like v2's 207/208).
- **Memory.** MemAvailable stays above 800 MB throughout.

Then stop htpd_v8r with the stop block and **wait for exit**.

## 5. Through the app
1. Edit `/data/local/tmp/smart_city_edge/htpd_profile` with the app stopped: keep the existing lines and add
   ```
   bin=/data/local/tmp/llama.cpp/bin/htpd_v8r
   reasoner=v3
   reasoner_engine=htpd
   reasoner_model=/data/local/tmp/gpu/qwen35_reasoner_q4_0.gguf
   ```
   - Optional: `reasoner_force=0` turns forced tokens off (A/B).
   - Optional: `env=... HTPD_REASON_IDLE_MS=20000`.
2. Start the app. The supervisor starts `htpd_v8r --reasoner-model ...`.
   - The backend probes `{"kind":"caps"}` before every reasoner call and refuses an htpd without the slot.
3. Run 30 incidents through the app with random inputs, faults and stress (`app/tools/stress_app.py`).
4. Collect:
   - `state/htpd.log`, the `reason stream ...` and `reasoner loaded/unloaded` lines;
   - the incident reports: `source` badge `device:qwen3.5-4b`, gate pass rate, latency p50/p90 (target p50 ≤ 20 s including the swap);
   - the agent-wave latency right after a swap. Expect about +2 s, because the agents' prefix KV cache survives the reload but the page cache may not.

## 6. Rollback
1. With the app stopped (step 1 block), remove the four lines from `htpd_profile` and start the app.
2. The supervisor sees the changed args and starts `htpd_v7` again.
3. The `.state` files next to the GGUF can be deleted at any time.

## Not in this build
**MTP speculative decoding.** It is documented here and not built.

What the tree supports:
- llama.cpp 620d2225 has everything for it:
  - `LLAMA_CONTEXT_TYPE_MTP` and `load_mtp`;
  - `common_speculative` `draft-mtp`, which supports qwen35 with one MTP head;
  - partial recurrent rollback with `n_rs_seq` snapshots, where qwen35 is in `llm_arch_supports_rs_rollback`.

Why it is not built:
- It needs `libcommon` (not in `build-snapdragon/bin`) or a port of `common_speculative_impl_draft_mtp`, about 600 lines. That port uses the staging API in `src/llama-ext.h` (`llama_set_embeddings_nextn`, `llama_get_embeddings_nextn_ith`, `llama_batch_ext_*`).
- It needs a second (MTP) context on the same model, loaded with `load_mtp=true`. That adds more DSP-mapped memory.
- It needs `n_rs_seq ≥ k` recurrent snapshots, each about 50 MB per sequence, on the HTP backend. Those snapshot ops are not yet verified on HTP.
- The MTP head is not LoRA-tuned, so its acceptance has to be measured on the host first.

Steps:
1. Host acceptance test: `llama-server --spec-type draft-mtp` against the merged GGUF.
2. Board test of `n_rs_seq` rollback with the prompt-lookup drafts already in htpd.
3. Port the MTP driver.
