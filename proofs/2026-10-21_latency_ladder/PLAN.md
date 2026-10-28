# v2 latency ladder: redo the v1 steps, get back to v1 speed without losing accuracy (2026-10-21/22)

Paper study only. The QIDK was busy with an eval and was not touched. No app code was changed: the proposed code is in
`patches/` (made in a scratch copy; the backend patch builds, `go vet` is clean and the related tests pass; the htpd
patch passes `g++ -fsyntax-only` against llama.cpp 620d2225; both `git apply --check` clean on the current tree).
Every number below is reproducible from the scripts in this folder. Rule: accuracy first. A lever ships only if its
outputs are within the HTP run-to-run floor and host400 accuracy is unchanged.

## 0. Targets, stated like for like

The "v1 13-agent incident 14.7 s" figure is the **agents-only htpd harness** number. It comes from
`2026-10-16_htpd_ab/RESULTS.md`, row v6, rep 2. It is not a full incident.

| what | v1 | v2 now | source |
|---|---|---|---|
| htpd harness, 13 agents, agents only (rep 2 of the same prompts) | 14.7 s (one batch, 13 x 768) | **15.3 s** (10 + 3, ABAB S10r1/r2) | `2026-10-21_htpd_v7_ab/run_one_batch.log` |
| chaos through the app, agents + synthesizer | **20.7 / 20.6 / 20.8 s**, 12 / 10 / 11 agents, no HVAC agents, run after the scenarios phase (htpd warm) | **25.5-34.4 s, median 28.4**, 13-14 agents incl. 2-3 HVAC, `--only chaos` | `evidence.json` |
| single-agent Mode 3 incident | median 3.8 s | **early alert median 3.35 s** (n=35), refinements 2.06 s; cold first incident 5.6-6.4 s | `evidence.json` |

- **Single agent: already at or below v1.** Only the cold first incident after an htpd start is slow.
  Those are the 3 slowest early alerts, each the first incident of its run, decoding at 17 tok/s against a median of 35.
- **Harness: 0.6 s short** of 14.7 s.
- **Full chaos incident: 5-14 s short** of v1's 20.7 s.
  - No lossless lever brings a full 13-agent incident to 14.7 s.
  - Prefill alone is ~7 s, one decode sweep ~6-8 s, and the synthesizer ~3-6 s.
  - The realistic target is **comparable to 20.7 s with more agents**.

## 1. The v1 ladder, mapped to v2

| # | v1 step (HANDBOOK) | v1 measured effect | v2 | why |
|---|---|---|---|---|
| 1 | Fine-tuned short answers (2.7, 5) | 150-240 -> ~84 tokens, ~2x per call | done | v2 mean 86.7 tokens |
| 2 | Stop at end of JSON (5) | stops when the object closes | done | htpd `Scanner` stops on object close / `action` |
| 3 | Output cap 200 (5) | bounds runaways | done, tighter | v7: `HTPD_AGENT_MAX_NEW=160`, `HTPD_JSON_ABORT=2`. A runaway batch drops from 21 s to ~9 s |
| 4 | `action` derived, not generated (2.8) | +3.7 pts on action | done | `ActionOfRole` (2.41) |
| 5 | `action` trim (2.18, 2.21) | -199 ms per call | done in htpd | every agent stop is `action` in the v7 logs; the synthesizer is correctly not trimmed (2.21) |
| 6 | Genie threads, cpu-mask, poll (2.8, 5) | +1.6% / +7% | n/a | Genie-only knobs. htpd's Hexagon power mode defaults to burst; OPPOLL was slower (`2026-10-16_htp_bringup/knob_sweep.txt`) |
| 7 | `allow-async-init` (2.10) | -65 ms per call | n/a | htpd loads once |
| 8 | Persistent process, genied (2.24) | 3.64 -> 2.54 s per call | done | htpd is resident |
| 9 | genie-app batching (2.13, 2.17) | -1 s per incident | superseded | htpd batches all agents |
| 10 | LADE, grammar, continuous batching (2.14, 2.16, 2.25) | rejected | n/a | htpd uses verified n-gram drafting instead (lossless) |
| 11 | Context 4096 -> 2048 (2.22) | -721 ms per call (KV bandwidth) | **redo as a layout** | Per-stream KV is read only up to the cells in use, so the allocated size costs nothing per step. The v2 equivalent is the layout: 10 x 1280 forces 13 agents into 10 + 3 -> **L1** |
| 12 | Two context windows (2.32) | big synth prompts fit | done | agent/synth context swap. Measured ~0.05-0.1 s (app overhead beyond htpd's own time: agents median 9 ms, synth 47-118 ms) -> **not a lever** |
| 13 | Inter-call gap 600 -> 250 -> 0 ms for the daemon (2.20, 2.24) | -333 ms per incident | **redo** | In htpd mode `daemonUp()` asks about genied, so `Run` still sleeps 250 ms before the synthesizer, solo re-runs and back-to-back calls. INC-0025: residual 282 ms -> **L6** |
| 14 | Exact-prompt cache, deterministic context (5) | reruns 0 ms | done | same code |
| 15 | Batch window closes after 1 reading (2.29) | -4 s, before the analysis | done | gate unchanged; not inside `total_ms` |
| 16 | Leaner synth prompt + word limits (5) | synth 11 -> 7-8 s | done | same `synthPrompt`. 4 sensors = 810 tokens |
| 17 | Skip the synthesizer when related domains are steady (5, step 4) | single-domain incidents make 0 synth calls | done | v2 single-agent incidents end "deterministic (related domains verified steady)" |
| 18 | Thermal pacing (2.35) | 88 C -> wait for 82 C, at most 15 s | applies, bites harder | v2 chaos ends at 84-95 C. v1's first two chaos rounds ended at 72 / 67 C -> **L4** |
| 19 | FA_STREAMS, HMX_PIPE_ALL, NEON argmax (2.37) | 13 agents 28-31 -> 24 s; 30.3 -> 27.7 s | done | `htpdclient.go` env, binary |
| 20 | Verified drafting, k <= 4 (2.37); `DRAFT_K=8` (2.42) | 13 agents 22 -> 16.4 s | done, but see note | `k = max(1, min(K, 32/streams - 1))`. K matters only at 5 or fewer streams. At 8 streams k = 3 for both K=4 and K=8, so 2.42's "-5.6% on batches of 8" cannot come from K: it is drift |
| 21 | Prefix cache (2.37) + synth prefix cache (v7) | prefill 8.7 -> 6.8 s (13 agents) | done; **add a cap** | The v2 system turn names the window ("a 4.5-hour window"), so there are up to 17 entries per role at ~34 MB each, never evicted -> **L9** |
| 22 | Legacy prefill (2.37) | the equal-ubatch order changed 30% of outputs | done (kept) | do not retry |
| 23 | **13 agents in ONE batch** (13 x 768, 2.37) | this is v1's 14.7 s | **not achieved** | 14 x 1024 was tried with the 32-row cap (k = 1 at 13 streams): +0.4 s in the exact-draft harness -> **L1**, re-test with novel prompts and 64 rows |
| 24 | Rejected in v1: synth speculation, 8-bit KV, thread/ubatch/power knobs, unified KV | - | do not retry | 2.37 |

## 2. Where v2 incident time goes

### 2a. Prompt tokens (`prompt_tokens.py` -> `prompt_tokens.json`; Llama 3.2 tokenizer, parity fixtures)

| role | 4 h total / uncached | 8 h | 12 h |
|---|---|---|---|
| air quality | 685 / 385 | 665 / 365 | 727 / 427 |
| power | 666 / 366 | 776 / 476 | 882 / 582 |
| water | 709 / 401 | 796 / 488 | 892 / 584 |
| weather | 663 / 376 | 783 / 496 | - |
| occupancy | 458 / 196 | 477 / 215 | 490 / 228 |
| **HVAC** | **806 / 458** | **939 / 591** | **1017 / 669** |

- The cached system turn is 262-348 tokens per role.
- The schema hint sits inside it, so it is cached. The user turn starts at `NODE:`.
- Prefix coverage is therefore complete. What remains to prefill is each window's own data.
- v1 prompts were ~597 tokens (~336 uncached).
- Synthesizer, 2 domains / 4 sensors: 810 tokens.
- Chaos synthesizer, ~18-20 sensors: an estimated **2.4-2.8k tokens** (2.32: it does not fit 2048). This is measured in step 4.1.

### 2b. Chaos (13-14 agents), v2 now (`evidence.json`; per-phase numbers are estimates until step 4.1 measures them)

| phase | estimate | basis |
|---|---|---|
| batch 1: 10 agents, 4 h, prefill | ~5-5.5 s | ~400 uncached tokens x 10 x ~1.35 ms (A/B fit, NOTES.md); HVAC adds most |
| batch 1 decode (k=2) | ~6-9 s | A/B exact-draft decode is 8.3 s for 10 + 3. The app's novel prompts accept fewer drafts: single stream 35 tok/s in the app vs 96 tok/s in the harness |
| batch 2: 3-4 agents (prefill + decode, k=8) | ~4-6 s | B4 is 4.3 s in the harness; novel prompts are slower |
| solo re-run of an invalid answer | 0 or ~2.5-3.5 s | **5 of 9** chaos incidents. Water `acidic_condition` was invalid again when run alone (the kept answer is still invalid) |
| call gap before the synthesizer | 0.25 s | `genie.go` (L6) |
| thermal pacing before the synthesizer / solo re-run | 0-15 s | NPU >= 88 C; boards ended at 84-95 C |
| synthesizer (swap ~0.1 s + prefill ~2-2.5 s + 100-150 tokens) | 3-9 s | 2-domain: 2.65-3.0 s for 52-71 tokens |
| **total** | **25.5-34.4 s** | measured |

**Cold start.**
- Round 1 of each chaos run is the slow one: 30.8, 34.4, 32.5 s.
- Later rounds: 25.5-29.7 s.
- Round 1 comes after a fresh htpd, so the prefix cache is empty (one system-turn prefill per role, run one after another) and there are no recent answers to draft from.
- Round 1 also always has the 14-agent composition: the stress RNG is seeded, so the two effects are confounded. Step 4.1 separates them.

**v2 vs v1 (+~8 s median), in order:**
1. the second batch;
2. cold rounds;
3. solo re-runs;
4. heat;
5. HVAC agents with longer prompts.

### 2c. Single agent (early alert)
- TTFT 0.4-0.7 s, then ~92 tokens at a median 35 tok/s, about 3.35 s in all.
- Refinements decode at 62 tok/s: the previous answer is in htpd's recent-output memory, so drafts hit.
- The three slowest early alerts (5.6, 5.6, 6.4 s at 17 tok/s) are each **the first incident of a run** (INC-0642, INC-0682, INC-0693): the cold-start case.

### 2d. Measurement problems found in the existing A/B data (read before trusting older numbers)
1. **Rep-2 artefact.**
   - `ab_v2.py` (and the v1 `ab.py`) records rep 2 of the *same* prompts, so the drafts copy the exact earlier answer.
   - B1 decodes at 96.5 tok/s there, against 35 in the app.
   - So every decode-side lever was measured where it cannot show: role drafts, K, rows, one batch.
   - `ab_ladder.py` adds "novel" workloads (warm-up with different prompts).
2. **No cooling in `run_ab.sh`.**
   - The temperature read returned 0 seven times ("board 0"), so cooling never ran.
   - B13 climbs monotonically: 14.55 -> 15.72 -> 16.34 -> 16.90 -> 16.76 -> 17.09 -> 17.58 s over the arms.
   - The rejections of role drafts (A1) and of one batch at 14 x 1024 (A6) are therefore confounded by heat.
   - LOGITS_READ (A2) is a real rejection: 3 runaways in B4.
   - The ABAB run (`run_abab.sh`, cooled to 49 C) is the trustworthy one.
3. K=8 vs K=4 at 8 streams: identical k. See row 20 above.

## 3. Levers, ranked

Savings are for a warm 13-14-agent chaos incident unless noted. "Identity" = exact text match against L7 within
the HTP floor (21-24/25 = 84-96%), plus host400 accuracy.

| rank | lever | expected saving | output risk | implementation |
|---|---|---|---|---|
| **L1** | **One batch for 4 h chaos**: layouts `14x1024,10x1280` + `HTPD_DRAFT_ROWS=64` (k: 13 streams 1 -> 3, 10 streams 2 -> 5) | **-3 to -5 s chaos**; harness B13 15.3 -> ~13.5-14.5 s | batch composition and rows change -> noise floor; verified drafts; 4 h prompts <= 888 + 160 fit 1024 (layout headroom 136); >= 8 h prompts go to 10 x 1280 automatically | `patches/htpd_v8.patch` (`HTPD_DRAFT_ROWS`, plus a guard that keeps draft KV inside the slice); profile `agents=14 agent_ctx=1024 layouts=14x1024,10x1280` (no backend change: `htpdMaxBatch` reads the profile) |
| **L2** | **Warm-up after every htpd (re)start**: one 4 h prompt per role + one synth prompt | **cold first incident: -3 to -6 s** (chaos round 1 30.8-34.4 vs 25.5-29.7); cold single agent 5.6-6.4 -> ~3.5 s; 0 when warm | none: the prefix KV is the same bytes; drafts are verified. Outputs discarded, never cached | `patches/backend_latency.patch` (`htpdWarmup`, run after `start()`); file from `make_warmup.py` -> `/data/local/tmp/smart_city_edge/htpd_warmup.jsonl` |
| **L3** | Solo re-run only for runaways / unparseable answers (`solo_rerun=runaway`) | -2.5 to -3.5 s on 5/9 chaos incidents | **behaviour change, USER DECISION**: an off-label answer (complete JSON, stop `action`) is no longer re-run. Here the re-run never fixed one | `patches/backend_latency.patch` (`reason.go`, profile key, default off) |
| **L4** | Thermal: heatsink + fan; measure pacing waits | 0-15 s per hot incident, plus slower steps when hot | none | hardware. Pacing (88 -> 82 C) is a safety rule: changing it is a USER DECISION, not proposed |
| **L5** | Role draft tables `HTPD_ROLE_DRAFT=1` (already in v7) | single -0.5 to -1 s (replay: 26.4 -> 18.3 steps); batch 2 -0.3 s; ~0 at 10+ streams | verified; A1 36/36 identical on normal workloads, 2 runaways in the flaky RUN2 batch -> needs host400 | profile env only |
| **L6** | Call gap 250 ms -> 0 in htpd mode | **-0.25 s per multi-domain incident**, also before each solo re-run | none (no process teardown with htpd) | `patches/backend_latency.patch` (`genie.go`) |
| **L7** | Dynamic draft rows `HTPD_DRAFT_DYN=1`: pad to the longest proposed draft, not to k | single -0.3 to -0.8 s, synth -0.3 to -1 s (if the step cost falls with rows: `ksweep` first) | row count changes the matmul shape: identity + host400 | `patches/htpd_v8.patch` |
| **L8** | `--ubatch-synth 1024` (htpd's default; the backend passes 512) | chaos synth -0.1 to -0.3 s | ubatch can change numerics: identity on S2/SC | profile key `ubatch_synth` (backend patch) |
| **L9** | Prefix-cache LRU cap `HTPD_PREFIX_CACHE_MAX=24` | 0 s; avoids up to ~3.5 GB of host memory over a long run (each OOM restart = a cold start) | none | `patches/htpd_v8.patch` |
| fix | `htpdKill` matches comm `htpd` exactly; the live binary is `htpd_v7`, so a stalled daemon was never killed or restarted | robustness | none | `patches/backend_latency.patch` |

**Expected outcome**
- With L1 + L2 + L5 + L6 + L7 + L8 passing:
  - harness B13 ~13.5-14.5 s, at or below 14.7;
  - warm chaos ~22-24 s, or **~20-21 s with L3**, comparable to v1's 20.7 s with 2-3 more agents;
  - cold chaos ~25 s instead of 31-34 s;
  - single agent ~2.7-3.0 s median, cold ~3.5 s.
- These are estimates. Step 4.1 replaces them with measurements.

**Not levers:**
- context swap (~0.1 s);
- synthesizer skip (already done);
- more prefix coverage (already the whole system turn);
- trimming more output (every field after `action` is gone already; the fields before it are read by `policy.go`);
- 8-bit/unified KV, ubatch for agents, power mode (2.37).

## 4. Device plan (after the eval; ~3 h of board time in 4 sittings; laptop load stays light)

Before each sitting:
- the board is idle and on DC power;
- the app runs the current build;
- the NSP is below 50-55 C.

The scripts cool between arms by reading the hottest `nsp*` zone. A failed read falls back to a fixed 180 s wait, never to "cool".

**4.1 Baseline breakdown through the app (~30 min).**

Run the live L7 profile, with no backend patch and no warm-up file.
```
bash run_app_ab.sh L7 profiles/L7.txt -
cp app_L7/warm/chaos_prompts.jsonl app_L7/warm/synth_prompts.jsonl .   # real chaos workloads for ab_ladder CR / SC
```
This gives, per incident:
- batch walls and prefill;
- solo re-runs;
- synthesizer ms and prompt tokens;
- residual (gap + thermal pacing, with `thermal_pacing.txt` from `agent.log`);
- `htpd.log` draft steps per batch (`../2026-10-21_v2_research/latency/parse_htpd_log.py`).

`cold/` = the first round after a restart.

**4.2 htpd direct, env only, v7 binary (~75 min).**
```
bash run_ladder.sh envA     # L7 / RD (L5) / O14 (L1 without rows) / US (L8), ABAB x2
bash run_ladder.sh ksweep   # single-stream ms per step at K = 1, 4, 8, 16 (rows 2..17) -> decides L7
```
Workloads (`ab_ladder.py`):
- COLD13: a fresh htpd, i.e. the cold penalty;
- N1, N4, N13, NM10: novel prompts;
- C13: chaos-like with HVAC;
- CR: real chaos;
- S2, SC: synthesizer;
- B13: continuity with the earlier numbers.

Each arm reports:
- prefill, swap, per-batch time and first progress;
- steps per batch and ms per step (from the htpd log);
- identity against `L7r<rep>`.

**4.3 htpd v8 (~50 min).**

Build the binary once. This is one source file in the existing Docker toolchain, about 1-2 min of CPU:
```
git apply proofs/2026-10-21_latency_ladder/patches/htpd_v8.patch      # only when the user says go
bash Code/smart-city-edge-agent/app/htpd/build_htpd.sh Code/smart-city-edge-agent/app/htpd /c/Users/hp/gpu_work/htpd_v8
adb push /c/Users/hp/gpu_work/htpd_v8/bin/htpd /data/local/tmp/llama.cpp/bin/htpd_v8
bash run_ladder.sh v8       # V8 (all off, must equal v7) / R64 / O14R64 (L1) / DYN (L7), ABAB x2
```

**4.4 Accuracy gate for each winner (~12 min each).**
```
bash run_ladder.sh acc L7 ; bash run_ladder.sh acc O14R64 ; bash run_ladder.sh acc RD ; ...
```
Compare with `acc_L7` on the same day: pattern, status, cause, JSON, policy, plus paired McNemar per row.

Accept a lever only if all of these hold:
- identity is within the floor;
- the host400 metrics do not drop beyond noise (paired p > 0.05 and no metric worse by more than 1 point);
- JSON and policy stay at 100%.

**4.5 Through the app with the winners (~40 min).**

Do this after the user approves applying `backend_latency.patch` (L2 / L6 / fix) and an APK build and install.
```
py -3 make_warmup.py
bash run_app_ab.sh CAND profiles/candidate.txt htpd_warmup.jsonl    # edit candidate.txt to the winners first
bash run_app_ab.sh L7b profiles/L7.txt -                             # same sitting, for the comparison
```
Report:
- cold and warm chaos totals with their breakdown;
- the Mode 3 single-agent median;
- the stress checks (including every agent passed policy).

Save `app_*` and `logs/` plus a manifest here (collect-proofs rule).

**Decisions to ask the user (AskUserQuestion), with the 4.1 numbers in hand:**
1. L3 solo-re-run policy (behaviour change).
2. Heatsink/fan for the board (L4).
3. Whether to apply the patches and rebuild the APK.

## 5. Recommended order to implement
1. **Now, no device needed:** L6 (gap) + the `htpdKill` fix. Zero output risk; ship with the next APK.
2. **After 4.1/4.2:** L2 warm-up. Zero output risk and the biggest win for demos and first incidents. It needs only the backend patch plus a pushed file.
3. **After 4.3/4.4:** L1 (one batch + 64 rows). This is the main lever for the 13-agent case. It needs an htpd v8 build and the accuracy gate.
4. L5 role drafts, L7 dynamic rows, L8 synth ubatch: each only if 4.4 passes. They are small.
5. L9 cache cap: ship with v8 (robustness).
6. L3 and L4: user decisions.

## Files
| file | what |
|---|---|
| `evidence_from_proofs.py` -> `evidence.json` | every number in sections 0-2 from existing proofs |
| `prompt_tokens.py` -> `prompt_tokens.json` | v2 prompt tokens per role and window, cached vs uncached |
| `ab_ladder.py` | htpd-direct harness: novel / chaos / synth / cold workloads, log-derived steps and ms per step, identity |
| `run_ladder.sh` | device arms (envA, ksweep, v8, acc), ABAB with cooling, never two htpd binaries at once |
| `app_breakdown.py` | through-the-app per-phase breakdown, exports the real chaos and synthesizer prompts |
| `run_app_ab.sh`, `profiles/*.txt` | app arms (cold + warm, v1 method), profile saved and restored |
| `make_warmup.py` -> `htpd_warmup.jsonl` (`_all` = 4/8/12 h) | warm-up requests for L2 |
| `patches/htpd_v8.patch` | `HTPD_DRAFT_ROWS`, `HTPD_DRAFT_DYN`, draft-KV slice guard, `HTPD_PREFIX_CACHE_MAX`, rows and decode ms in the log (all off by default = v7) |
| `patches/backend_latency.patch` | gap 0 in htpd mode, `htpdKill` for `htpd_*`, `htpdWarmup`, `ubatch_synth` and `solo_rerun` profile keys |
