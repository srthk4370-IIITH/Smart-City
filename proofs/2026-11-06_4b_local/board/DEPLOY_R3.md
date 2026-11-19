# Deploy rsn_v3 4B r3 to the QIDK (planned for 2026-11-15)

Prepared 2026-11-09 without the board and without the laptop GPU. Nothing in this folder has run on the board yet.
Today the board runs deploy32: split7 APK `9e82675a`. Chat goes to the 2B on llama-server (CPU), and reports and agents
run on the NPU (rsn_v1 4B + ft_B50 3B, htpd_v9f).

After this deploy, the r3 4B is the **single general model** (owner): chat and reports both run on the NPU through htpd,
and the 2B split is retired.

## 0. What is ready

| item | file | status |
|---|---|---|
| r3 APK | `board/SmartCityEdge.r3.apk` + `.md5` (`build_r3.sh`, `go_test.txt`, `build.log`) | built 2026-11-09 (md5 in the .md5 file) |
| model | `Code/models_stage/rsn_v3_4b_r3_q4_0.gguf` (final) or `rsn_v3_4b_r3_s2000_q4_0.gguf` (mid gate) + `.md5` | **TBD by the gate** (`post/gate_r3/GATE.md`, or the mid gate) |
| laptop fog | `go test -run TestFogServe` (`backend/fog_serve_test.go`, opt-in) | ready |

**What changed in the APK since split7** (backend only; the chat UI and web assets are unchanged):
- r3 chat: the 21-tool header, the r3 system and the fog line (`chat_fog.go`, `chat_header_r3.txt`,
  `chat_system_r3.txt`). They are on only with `chat_prompt=r3` + `chat_think=adaptive`.
- 2026-11-09 gating, so that a profile without `chat_prompt=r3` behaves exactly as deploy32:
  - the archive index is read only with r3;
  - `search_knowledge` is the old offline stub without r3;
  - `fog_*`, `co_occurring_incidents`, `recurring_issues` and `compare_periods` are unknown tools without r3.
  - Test: `TestChatR3OffIsDeploy32`.
- New profile key **`reason_ctx`** -> `htpd --reason-ctx N`. Unset means 4096, as today (`TestHtpdReasonCtx`).
  **r3 needs `reason_ctx=8192`:**
  - the static prefix alone is about 5,070 tokens;
  - training rows are p99 6,377 and max 7,229 tokens;
  - with 4096 cells per stream, every r3 model question would overflow.
- The badge says `qwen3.5-4b rsn_v3` when `reasoner_model` names `rsn_v3_4b`. The live rsn_v1 path keeps `qwen3.5-4b`.
- `FogHandler` takes a clock (`fogHandlerAt`) so that a laptop fog can follow the board's replay sim clock.

## 0b. BLOCKER: the htpd reasoner context (decide on Nov 15 with test T0 before Stage C)

**Where the setting lives:**

| setting | what it is |
|---|---|
| htpd `--reason-ctx` | cells per reasoner stream. Default **4096** (`htpd_v9f.cpp` l.952/1984). The live APK never passes it (`htpdclient.go` args), so the board runs 4096 |
| stream count | `reasoner_split=3` in htpd_profile -> `reasonerStreams()` = 3 groups -> `--reason-streams 3` (`reasoner_v3.go` l.1340-1374; values 3, 3r, 2, 4, 6) |
| context allocation | the live env has `HTPD_REASON_SPLIT_SPEC=8` with KVU on by default, i.e. a split-spec context with **one unified KV pool** of `streams x reason_ctx + 256` cells (l.2291-2294). Live: 3 x 4096 + 256 = **12,544 cells** |
| per-stream cap | `per_seq = g_reason_ctx_stream` = reason_ctx (l.1400). A single chat stream can use at most 4096 cells today |
| new in the r3 APK | profile key **`reason_ctx`** -> `--reason-ctx N` (`htpdReasonCtx`). Unset keeps today's behaviour |

**Why r3 cannot run at the default:**
- r3 chat is one stream with a static prefix of about 5,070 tokens (the header alone is 4,579).
- Rows reach 7,229 tokens (p99 6,377) once the history, the tool rounds and the answer are added.
- So the chat stream needs about **8192 cells**.

**Memory risk:**
- On 2026-10-28, sp6 (6 streams x 4096 = 24,576 cells, htpd v8x) died at the first request with
  `HTP0 buffer mapping failed size 427401216` (HANDBOOK 2.54). That is about 17.4 KB per cell, so the buffer that
  failed is the reasoner KV of 24,576 cells, which the NPU session could not map.
- `reason_ctx=8192` with split-3 allocates 3 x 8192 + 256 = **24,832 cells (about 432 MB)**. That is more than the
  allocation that failed, so it is **expected to fail**.
- If the reasoner fails to load, the reports fall back to the deterministic path and the agents keep running (htpd
  reloads the agents' model). It does not crash the app, but no AI reports are made until it is reverted.

| option | cells (est. KV) | fits? | cost |
|---|---|---|---|
| today: split-3 @4096 | 12,544 (~218 MB) | yes (live) | r3 chat does not fit |
| split-3 @8192 | 24,832 (~432 MB) | **expected no** (>= the sp6 failure) | none, if it maps |
| split-2 @8192 (`reasoner_split=2`) | 16,640 (~289 MB) | unknown (between OK and failed) | reports lose one parallel group; report time must be measured |
| split-1 @8192 (`reasoner_split` unset) | 8,448 (~147 MB) | very likely | no split decoding for reports (split-3 gave 25.7 -> 23.7 s, and the v9 drafts work best inside the split): expect slower reports, measure with fastcheck |
| **htpd v9h pool (recommended code fix)** | 12,544 (~218 MB, the same as today) | yes (same allocation as live) | needs an htpd build + board A/B (below) |
| chat on CPU llama-server (today's split engine, r3 4B) | NPU unchanged at 4096 | yes | ~+3 GB RAM; slow CPU prefill (below) |

**htpd v9h pool patch:**
- At l.2294, when `HTPD_REASON_POOL=N` is set and KVU is on, use `cp.n_ctx = N` instead of
  `streams*reason_ctx+256`. The per-stream cap stays `--reason-ctx`.
- With `HTPD_REASON_POOL=12544` and `reason_ctx=8192`, the KV allocation is byte-for-byte today's. One chat stream may
  then use up to 8192 cells of the shared pool.
- A split-3 report uses about 1.3k + 2.5k + 3x300 cells, well under the pool.
- Add one guard: when the pool is exhausted, stop with "ctx" instead of a failed decode.
- No APK change: the env goes on the profile `env=` line. Bundle it with M2 (the chained prefix, LATENCY below) in
  one htpd v9h build (the free v9g slot), built in WSL like v9f.
- Board A/B before use: fastcheck x2 + RWH q10-q15 must match v9f (identical text at 4096).

**htpd v9h is BUILT (2026-11-12, not on the board): `proofs/2026-11-12_htpd_v9h/`** (README there = HOST_TEST.md).
- Board binary `htpd` md5 **7296d50264c77585c6c7e32180a5f313** (source `htpd_v9h.cpp` 9023b92e, `v9h.patch` vs v9f,
  `build_v9h.sh`: same NDK r26d flags and the same deployed libs as v9f; ggml-hexagon untouched).
- Everything is env-gated. Without new env v9h runs v9f's code paths (host: bit-identical logits, HOST_TEST.md).
  - `HTPD_REASON_POOL=12544`: the unified split-spec pool gets 12,544 cells whatever `--reason-ctx` is.
  - `HTPD_REASON_CHAIN=1`: M2 chained prefix (below, section M2), memory static states 2 -> 3.
  - A decode that finds no free KV cell now ends with stop `ctx`, not `error`.
- **Board A/B plan (Nov 15, after Stage A, before Stage C; one NPU client, app stopped for every push):**
  1. **V0 push:** `$A push htpd $BIN/htpd_v9h.part`, md5 = 7296d502..., `mv`. Profile `bin=$BIN/htpd_v9h`, env unchanged,
     no `reason_ctx`. fastcheck x2: rc=0, report text identical to the v9f fastcheck of Stage A (same sim seed), report
     time within +-1 s. RWH q10-q15 (`bench`) identical to v9f. Fail -> rollback.
  2. **V1 pool (T0 by code):** add `HTPD_REASON_POOL=12544` to `env=` and `reason_ctx=8192` to the profile (htpd restarts by
     itself). `grep -E 'buffer mapping failed|split-spec reasoner context|v9h:' $W/state/htpd.log` must show
     `n_ctx 12544, kv unified` and no mapping failure. fastcheck x2 + RWH q10-q15 identical to V0 (no stream reaches
     4096 cells there). `tele` + htpd VmRSS within +-30 MB of V0.
  3. **V2 context 8192 (after Stage C, r3 GGUF):** a chat with 3 earlier exchanges + a long question, i.e. > 4,096
     prompt tokens (the r3 prefix alone is ~5,070). The htpd log line `reason stream 0: ... stop eog` (never `ctx`), and
     the answer is sensible. Then a split report (fastcheck) right after: rc=0 (the pool is shared, the chat state is
     dropped per request).
  4. **V3 M2 chain + latency:** append `HTPD_REASON_CHAIN=1 HTPD_REASON_DISK_KEEP=6` to `env=`. Chat page closed, then
     per step one question, recording the `cache` kind (htpd log `cache ...`) and total seconds:
     a. first question (new prefix): `saved`, ~4 + 10-13 s (as today);
     b. the same question again: warm, `mem`/`turn`;
     c. next sim hour (or flip `fog_url` on/off to change the prefix): `chain-base` once (the base = header + date is
        built, ~same cost as a), log line `prefix chain: base of N tokens`, N ~4.6k;
     d. the hour after: **`chain-mem`, first-of-hour target <= 4 + 2 s** (was 4 + 10-13 s);
     e. force a reasoner swap (fastcheck), then a new hour: `chain-disk` (base from disk, ~0.4 s + ~490 tokens);
     f. the warm / first-question / follow-up latency table of section 6 step 12 with r3: warm question unchanged.
  5. **V4 RAM / HTP:** `tele`, `cat /proc/$(pidof htpd_v9h)/status | grep VmRSS` (+ up to ~130 MB for the 3rd static
     state), `ls -la /data/local/tmp/gpu/*.prefix_*.state` (<= 6 files, ~130 MB each with r3), no
     `buffer mapping failed`, MemAvailable >= 1.5 GB during chat + incident.
  6. **Rollback (1 min):** profile `bin=$BIN/htpd_v9f`, remove `HTPD_REASON_POOL`, `HTPD_REASON_CHAIN` from `env=`
     (keep `reason_ctx` only if T0 showed split-3 @8192 maps, else remove it or use split-2/1 / F-CPU as above). htpd
     restarts by itself; fastcheck once. The state files are compatible both ways (same file naming).
  - Save `deployR3/V0..V4.md` with log lines, fastcheck output, `tele`, latency per step.

**Fallback F-CPU (no htpd change):** chat runs on the r3 4B through llama-server on the CPU (`chat_url`, as in the
2B split), and reports stay on the NPU at 4096/split-3.
- Changes:
  - in `chat_gpu.sh`: `M=/data/local/tmp/gpu/$M`;
  - push `board/warm_r3.json` (md5 b388df6a: the r3 21-tool header, the same format as warm.json) as `$S/warm.json`;
  - profile keys `chat_url`, `chat_device=cpu`, `chat_think=adaptive`, `chat_prompt=r3`.
- `-c 8192` is already set.
- Costs:
  - about +2.6 GB of GGUF and +0.3 GB of KV in RAM, because the 4B is loaded twice (NPU + CPU). The guard kills below
    700 MB free.
  - a one-time header pre-warm of 5k tokens at 4B CPU speed: about 1-2 min at server start. `split_on.sh` waits for it.
  - per question, about 290 tokens are re-prefilled (keep-warm checkpoint) plus 4B CPU decode, roughly 10-12 t/s
    against the 2B's 25 (est.).
- The APK's 60 s chat timeout falls back to htpd, which then overflows at 4096. Accept this, or set no fallback.

**T0, test first on Nov 15** (after Stage A, before pushing anything else; it works with today's rsn_v1, because the
r3 4B has the same architecture and the same KV size):
1. App stopped. Add `reason_ctx=8192` to the profile and start the app.
2. Run fastcheck once: it forces a reasoner load with the split-3 context.
3. Run `grep -E 'buffer mapping failed|split-spec reasoner context|reasoner model load failed' $W/state/htpd.log`.
4. **Maps (n_ctx 24832 and a valid AI report):** keep it. Record `tele` and htpd VmRSS, and run fastcheck once more.
5. **Fails:** remove `reason_ctx` (htpd restarts by itself), run fastcheck to confirm the report is back, then:
   - try `reasoner_split=2` + `reason_ctx=8192`, and run fastcheck. Report time must stay within +3 s of today's 28 s,
     or the owner decides.
   - If that fails too, use `reasoner_split` unset + `reason_ctx=8192`. Measure the report time; the owner decides.
   - If neither is acceptable, use **F-CPU** for Nov 15 and v9h afterwards.
6. Save `T0.md` with the htpd log lines, fastcheck output and `tele` for each try.

## 1. Preflight (laptop, WSL)

```bash
P=/mnt/c/Users/hp/Desktop/qidk/proofs/2026-11-06_4b_local/board; I=$P/deployR3; mkdir -p $I/known_good
A=/mnt/c/Users/hp/Desktop/qidk/Code/platform-tools/adb.exe; W=/data/local/tmp/smart_city_edge; S=/data/local/tmp/chatgpu
M=rsn_v3_4b_r3_q4_0.gguf            # or rsn_v3_4b_r3_s2000_q4_0.gguf: whichever the gate passed
G=/mnt/c/Users/hp/Desktop/qidk/Code/models_stage/$M
sh_(){ "$A" shell "$@" | tr -d '\r'; }
tele(){ sh_ "echo avail=\$(awk '/MemAvailable/ {print int(\$2/1024)}' /proc/meminfo)MB t=\$(cat /sys/class/thermal/thermal_zone*/temp | sort -rn | head -1 | cut -c1-2)C"; }
(cd $P && md5sum -c SmartCityEdge.r3.apk.md5)           # APK unchanged since the build
(cd $(dirname $G) && md5sum -c $M.md5)                  # GGUF matches the export
grep -m1 -i verdict /mnt/c/Users/hp/Desktop/qidk/proofs/2026-11-06_4b_local/post/gate_r3/GATE.md   # must be PASS (or the owner's call)
"$A" devices; tele; sh_ "df -h /data | tail -1"          # need >= 6 GB free on /data (GGUF ~2.6 GB + .part + prefix states)
```

- Check that no other laptop job uses adb: one NPU client at a time, and no sweep or bench running.
- Touch `proofs/2026-10-31_night/PAUSE` as deploy32 did.
- Board temperature must be < 60 C before starting.

## 2. Snapshot known_good (rollback material)

```bash
"$A" pull "$(sh_ "pm path com.iiith.smartcityedge" | sed "s/^package://")" "$(wslpath -w $I/known_good/app.apk)"
"$A" pull $W/htpd_profile "$(wslpath -w $I/known_good/htpd_profile)"
md5sum $I/known_good/app.apk     # expect 9e82675a... (split7)
```

The known_good profile should hold `reasoner_model=/data/local/tmp/gpu/qwen35_reasoner_q4_0.gguf`, `chat_think=adaptive`,
`chat_url=http://127.0.0.1:8090` and `chat_device=cpu`.

## 3. Stage A: APK alone, profile unchanged (proves "install is safe")

1. Stop the app with `stop_app` from `proofs/2026-11-04_split/deploy32_split7.sh`. It stops chat_gpu.sh, force-stops
   the app, kills edge-agent and htpd, waits for exit, then waits 30 s. Expect `STOPPED`.
2. Install and start: `"$A" install -r -d "$(wslpath -w $P/SmartCityEdge.r3.apk)"`, then `start_app`, which waits for
   `htpd: ready in`.
3. Checks:
   - `chaos2.py chaos 2 150` must give rc=0, then run `fastcheck.py` (both in `proofs/2026-10-27_reasoner_fast/scripts`,
     `python3 -I`);
   - `chatcheck2.py` with 3 demo questions: the 2B still answers with the `(cpu)` badge.
4. Targets:
   - fast alert <= 6.0 s, AI report <= 32 s (deploy32: 5.6 s / 28.0 s);
   - chat the same as deploy32.
5. On failure: install `known_good/app.apk`, push the profile back and stop. Do not continue.

## 4. Stage B: push the model (app stopped)

```bash
# stop_app again (expect STOPPED); then:
m=$(cut -c1-32 $G.md5)
"$A" push "$(wslpath -w $G)" /data/local/tmp/gpu/$M.part
[ "$(sh_ "md5sum /data/local/tmp/gpu/$M.part" | cut -c1-32)" = "$m" ] && sh_ "mv -f /data/local/tmp/gpu/$M.part /data/local/tmp/gpu/$M" && echo PUSHED
sh_ "md5sum /data/local/tmp/gpu/$M"   # again after mv
```

Keep `qwen35_reasoner_q4_0.gguf` (rsn_v1) and `rsn_v3_2b_r2_q4_0.gguf` on the board until the owner signs off. They are
the rollback.

## 5. Stage C: switch the profile (app still stopped)

1. **Retire the 2B split** with `bash proofs/2026-11-04_split/split_off.sh`. It removes `chat_url`, `chat_think` and
   `chat_device` and stops llama-server.
2. **Write the r3 keys** (edit on the board through .part + mv, as split_off does):

```bash
sh_ "grep -vE '^(reasoner_model|chat_think|chat_prompt|reason_ctx|fog_url|fog_token|fog_timeout_ms)=' $W/htpd_profile > $W/htpd_profile.part && \
     printf 'reasoner_model=/data/local/tmp/gpu/$M\nchat_think=adaptive\nchat_prompt=r3\nreason_ctx=8192\n'   # + reasoner_split as chosen in T0 >> $W/htpd_profile.part && \
     mv -f $W/htpd_profile.part $W/htpd_profile"
"$A" pull $W/htpd_profile "$(wslpath -w $I/htpd_profile.r3)"
```

- The `env=` line stays as it is. Optionally append `HTPD_REASON_DISK_KEEP=6` to it, so that the hourly chat prefix
  states cannot push the report's static-prefix state out of the 4-file LRU.
- Then `start_app`.
  - `state/htpd_args` must contain `reasoner=/data/local/tmp/gpu/$M --reason-ctx 8192`.
  - The htpd log must show the reasoner context (`n_ctx` about 3 x 8192 + 256, kv unified).
- `fog_url` stays **unset**: offline fallback is the default and what the board runs.

## 6. Board test plan (save everything under `board/deployR3/`)

| # | test | how | pass |
|---|---|---|---|
| 1 | fastcheck + chaos 2 on r3 (reports are now r3) | `chaos2.py chaos 2 150`, `fastcheck.py` x2 | rc=0. Fast alert <= 6.0 s. AI report <= 32 s, valid. Label/severity sane on the fastcheck incident |
| 2 | chat smoke | `chatcheck2.py` with the 6 deploy32 questions (Section "Sweep and demo", DEMO.md) | 6/6 answered. Badge `qwen3.5-4b rsn_v3` on model answers. "Close all" refused |
| 3 | prefix cache | `grep 'reason 1 streams' $W/state/htpd.log` after the first chat, then a 2nd and 3rd question | 1st of the hour: `cache saved (~5070 tokens, X ms)`. Then `mem`/`disk`/`turn`. Record X (estimate 10-13 s) |
| 4 | 160-question sweep | `cd proofs/2026-11-01_chat; bash run_sweep.sh 40_r3`, then `python3 -I sweep.py questions_heldout.json sweep41_heldout_r3.jsonl`, `... questions_blind.json sweep42_blind_r3.jsonl`, `... questions_blind2.json sweep43_blind2_r3.jsonl` | 160/160 answered, 0 errors. Router answers unchanged (~143, median 0.2 s). Model answers: compare side by side with `CMP_d27_d30.md` (d30 2B / d27 4B) |
| 5 | fog offline (default) | fog_url unset. Ask: "How many water incidents were there in March?", "What is the drinking-water pH limit?", "Has this AC failed before this year?", "Is the fog server reachable?" | Answers state the device fallback (`source:device_fallback`, coverage). There are no invented fog numbers, and counts include the archive index |
| 6 | fog online | Laptop: pull `$W/state/incidents.jsonl` + `incidents.archive.jsonl`. Read sim_time from `/api/status`. Then `SCE_FOG_SERVE=127.0.0.1:8091 SCE_FOG_STORE=incidents.jsonl,incidents.archive.jsonl SCE_FOG_NOW=<sim_time> go test -run TestFogServe -count=1 -timeout 0 .` (WSL, backend dir, nice). Then `"$A" reverse tcp:8091 tcp:8091` and add `fog_url=http://127.0.0.1:8091` to the profile (read per call, no restart). Same 4 questions | `fog_status` is reachable, and the answers carry fog results (`source` fog). The first question pays one new prefix (the fog line changed): record it |
| 7 | fog timeout | Stop the laptop fog. Run `nc -lk 8092` (accepts, never answers), `adb reverse tcp:8092 tcp:8092`, set `fog_url=http://127.0.0.1:8092` and `fog_timeout_ms=2000` | The first fog call adds <= 2.5 s and falls back. Calls within the next 30 s add 0 s. The answer discloses the fallback |
| 8 | fog error | Point `fog_url` at a closed port (`http://127.0.0.1:8093`) | Immediate fallback, no added wait |
| 9 | back to default | Remove `fog_url`/`fog_timeout_ms`, `adb reverse --remove-all`, stop nc and the laptop fog | Next answer offline again (one prefix rebuild) |
| 10 | RAM / heat | `tele` before/after each stage, `sh_ "dumpsys meminfo | head -40"`, htpd RSS (`cat /proc/$(pidof htpd_v9f)/status | grep VmRSS`), `ls -la /data/local/tmp/gpu/*.prefix_*.state` | MemAvailable >= 1.5 GB during chat + incident. Peak < 100 C, no thermal kill. Prefix state files <= 6 per model |
| 11 | coexistence | A chat question 12 s into a fastcheck incident (as deploy32) | fastcheck rc=0. The chat waits for the NPU (no error) |
| 12 | latency table | from the sweep + htpd log: warm / same-hour cold / first-of-hour; think tokens per answer | see targets below |

**Latency targets:**
- router answers: median <= 0.5 s.
- model answers, warm (page open): mean <= 12 s. Today: 4B 9.2-12.4 s, 2B 8.4-13.4 s.
- same-hour cold (reasoner swapped out): <= warm + 5 s.
- first question of an hour: <= 20 s (estimate 15-18 s, see `LATENCY` below). Over 20 s -> mitigation M2 is required
  before the evaluation.
- fastcheck: 6.0 s / 32 s.

**Proofs to save** (`board/deployR3/`):
- `STATUS.md` (one line per step, as deployNN);
- `deploy.log`;
- `known_good/`, `htpd_profile.r3`;
- `chaos_*.txt`, `fastcheck_*.txt`;
- sweep jsonl + inc/status/sensor snapshots (in `proofs/2026-11-01_chat`, tag `_r3`);
- `htpd_r3.log` (pulled `state/htpd.log`), `htpd_args`;
- `tele.txt`, `fog_online.txt` / `fog_timeout.txt` / `fog_offline.txt` (question, answer, tools, source, seconds);
- `latency.json` (per question: engine, cache kind, cached tokens, prefill ms, decode steps, think tokens, total s);
- a `CMP_d32_r3.md` side-by-side of the model answers.

## 7. Rollback

- **Fast, profile only (about 1 min, APK stays):** push `known_good/htpd_profile` back through .part + mv, then
  `bash proofs/2026-11-04_split/split_on.sh`.
  - This restores rsn_v1 on the NPU and 2B chat on the CPU.
  - htpd restarts by itself, because `reasoner=` and `--reason-ctx` change its args.
  - **Never** run split_on.sh with `chat_prompt=r3` still in the profile: the 2B would get the 21-tool prompt it was
    not trained on. The known_good profile has no `chat_prompt`.
- **Chat only back to rsn_v1, reports stay r3:** this is not supported. One reasoner model serves both. Use the fast
  rollback.
- **Full:** `stop_app`, `"$A" install -r -d known_good/app.apk`, push `known_good/htpd_profile`, `start_app`, then
  chaos 2 + fastcheck.

## LATENCY: the r3 header on the NPU

**Measured today** (board htpd logs, rsn_v1 4B, 9-tool chat prefix of 2,486 tokens):

| step | time |
|---|---|
| prefix build | 4.6-5.8 s (`cache saved (2486 tokens, 4574-5845 ms)`), i.e. 425-545 tok/s on the NPU; the 1,317-token report prefix runs at 545-585 tok/s |
| restore from disk | 0.21 s |
| restore from memory | 0.01 s |
| question suffix | 0.2-0.4 s |
| reasoner swap | 4.0 s |
| decode | 127.8 ms/step |

htpd caches a hybrid model's **whole state at the exact `prefix`** that the app sends: memory (2 static entries), disk
(LRU 4 per model), and the turn state of the last prompt. It does **not** have llama-server's
"checkpoint one micro-batch early" problem. The prefix key changes when the time line changes (hourly in IST), when
the fog line changes (online/offline/last sync), or when the "full records since" date moves.

**r3 estimate:**
- static prefix ≈ 4,579 (header) + about 90 (time/fog/device line) + about 400 (r3 system) ≈ **5,070 tokens**, 2.04x
  today.
- Prefill at 400-520 tok/s: the rate drops a little because the 8 attention layers grow with context.

| case | today (rsn_v1) | r3 (est.) |
|---|---|---|
| warm (page open, keep-warm holds the reasoner, prefix in memory) | ~0.3 s + decode | ~0.3 s + decode (+ think tokens) |
| same hour, reasoner swapped out | 4.0 + 0.2 s | 4.0 + ~0.4 s (disk state ~2x larger) |
| **first question of an hour / after a fog-line flip** | 4.0 + 5-6 s | **4.0 + 10-13 s** |
| new: adaptive think on hard questions | none | ~20-60 tokens x 128 ms = 2.5-8 s |
| new: fog timeout (fog_url set but down) | none | <= fog_timeout_ms (2 s) once per 30 s |
| reasoner KV (NPU-mapped, unified pool) | 12,544 cells (~218 MB) | split-3@8192 = 24,832 cells (~432 MB, **expected not to map**: section 0b). v9h pool = ~218 MB; split-2 ~289 MB; split-1 ~147 MB |
| reports, if T0 forces fewer streams | split-3 + drafts | split-2/1: slower reports (to measure; split-3 gave -2 s on 25.7 s) |

**Mitigations that keep the exact header:**
- **M1, keep-warm (already in the APK, no change).** The NPU keep-warm pings `chatStaticPrefix(now)+"Hi"`, which in
  r3 mode is the r3 prefix, every 2 s while the chat page is open. So the hourly rebuild is paid by a ping, not a
  question, when the page is open at the hour change. Measure it in test 3.
- **M2, htpd v9h "chained static prefix" (recommended; needs an htpd build + board A/B, owner OK).** This is the htpd
  form of the 2026-11-04 llama-server header fix.
  - In the restore block (`htpd_v9f.cpp` ~l.1322), when the best memory entry is a *static* key that is a strict
    prefix of `ptoks`, restore it, prefill only `[key, P)`, and save the `ptoks` state to memory and disk. Raise the
    static memory cap from 2 to 3.
  - The app sends one header-only warm after each reasoner load: `prefix` = `chatHeaderR3`, the constant 4,579 tokens,
    persisted on disk forever.
  - A new hour then costs about 490 tokens (about 1 s) instead of 5,070 tokens (10-13 s). First-of-hour drops to
    about 4 + 1.5 s.
  - v9g (`proofs/2026-11-04_split/v9g`, an unmodified copy of v9f) is the free slot.
  - **Built as htpd v9h (2026-11-12, `HTPD_REASON_CHAIN=1`), with no app change:** instead of a header-only warm,
    htpd finds the base itself. When a new prefix misses, the longest common head with any known static key (memory, or
    the token headers of the `.prefix_*.state` files on disk) of >= 1024 tokens becomes a base state (saved once, LRU-
    touched on every use). For r3 that is header + "...Device time: 2026-11-15 " (the hour digits differ). Then each
    new hour restores the base and prefills ~490 tokens. Cache kinds in the log: `chain-base` / `chain-mem` /
    `chain-disk`. One extra base per day (the date changes). Board A/B: section 0b, V3. Host proof:
    `proofs/2026-11-12_htpd_v9h/HOST_TEST.md`.
  - M3 (below) still needs the APK and is not built. With M2 on, a pre-build costs only ~1.5 s, and M1 keep-warm
    already pays the hourly rebuild while the chat page is open.
- **M3, hour-ahead pre-build (app, default off, owner OK).** The next hour's prefix is fully known in advance (time
  line HH+1:00, the fog line, the device date). At about HH:50, when no incident has been analysed for 10 min, the
  chat is idle and the board is < 80 C, send it once (`prefix` + "Hi", 1 token), so htpd writes it to disk.
  - Cost: about 4 + 12 s of NPU per hour off the user path. An alert in that window waits up to about 13 s, which is
    the same risk as today's keep-warm.
  - Needs `HTPD_REASON_DISK_KEEP=6`. With M2 it costs only about 1.5 s.
- **M4, router coverage.** The router answers about 89 % of the sweep in 0.2 s with no model. The new r3 question
  kinds can be routed with the same Go tools (`runLocalR3`, `fogTool`), so most of them never reach the 4B:
  - recurring issues;
  - compare this week vs last;
  - monthly trend;
  - "is the fog reachable".
  This is a follow-up after the sweep shows which ones reach the model.
- **M5, stable prefix.** Keep `fog_url` unset unless a real fog runs: every online/offline flip is a new 5,070-token
  prefix.
- Not done without the owner's OK: a shorter header or tool descriptions, or moving the time line after the header
  into the user turn. Both change the trained prompt.

## Open decisions for the owner

1. **Which GGUF:** the s2000 mid-gate export, or the final one after epoch 1. Use the gate verdict.
2. **The NPU context (section 0b) is the blocker.** r3 needs 8192 cells for the chat stream, and split-3 @8192 is
   expected not to map. Choose:
   - the htpd v9h pool patch (the same memory as today; needs a build + A/B);
   - fewer streams (split-2 or split-1, with slower reports);
   - or F-CPU chat on llama-server.
   T0 on Nov 15 decides which ones are possible.
3. **Retire the 2B now**, or keep its files on the board for the rollback. The recommendation is to keep the files
   with the split off.
4. **M2 (htpd v9h)** and **M3 (pre-build):** build and A/B them before the next evaluation if the first-of-hour time
   is over 20 s.
5. **Production fog:** the Supabase side and the uploader are not built. fog_url stays unset on the board.
6. The report path also changes to r3: one model serves both. If chat passes but reports fail on the board, the only
   option is a full rollback (rsn_v1 + 2B split).
