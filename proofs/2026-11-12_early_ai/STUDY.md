# Early provisional AI: per-shape gate study (ROADMAP §2, FEATURES `ai_early_k` / `ai_early_shapes`)

**Update 2026-11-27: the full rerun with today's models (v5 reasoner, agt3 agents) is complete. No shape clears any k,
so keep `ai_early_k` off. See "v5 rerun (2026-11-27)" at the end.**

**Status (2026-11-12 run): PARTIAL. Not enough data for a decision. Keep `ai_early_k` OFF (the app default).**
The run had 15 min of GPU time (2026-11-12 12:46-13:01 UTC). Then WSL restarted and the r4 top-up took the GPU
(about 2.5 days). Of 440 event groups, 31 are done (192 rows). Resume with one command, shown below.

## Method (app-faithful)
- **Events.** `proofs/2026-10-28_master/gate_study/eval3e.jsonl` has 440 real-history events (4 roles × 6 shapes:
  spike, step, trend, flatline, noisy, fault). Each event is rendered after k = 3, 4, 5, 6, 7, 8 abnormal readings,
  with every other random draw identical, and has teacher gold per k. This is the truncatable test set. The reasoner
  test sets (`incidents_test_r2`, dev/RWH) are pre-rendered text, so their windows cannot be cut at k readings.
- **Harness.** `harness/eas_test.go` is a Go test. It runs in a scratch copy of `app/backend` (`~/early_ai`), and the
  repo backend is unchanged. Per row it:
  1. feeds the row's 12 h history into a real `Engine` as a measured device feed, at the row's IST time of day;
  2. reads the gate state the engine reaches;
  3. if the rules flag the sensor, builds the candidate the early path would (`Early`), then runs the app's own
     `buildIncident` and Mode-3 `analyse`: the domain agents (B50 GGUF, `ft_B50_q4_0`) through an htpd-protocol shim
     (`harness/htpd_shim.py`, which applies the htpd json/"action" stop rules, `HTPD_AGENT_MAX_NEW=160`), then reasoner
     v3 (`rsn_v3_4b_r3_q4_0.gguf`, md5 931f9dd7…) through `llamaServerLLM`, plus policy, gate and severity guard.
- **Models and settings.** Both models run on llama-cuda-b11815 llama-server with greedy decoding. Profile:
  `post_rules=all`, `solo_rerun=runaway`, `reasoner=v3`.
- **Stand-in sensor.** The app's sensor bank has one live sensor per role/metric, so each event replays on the bank
  sensor of the same role and metric whose range holds every reading. For example, an AQ-VN90 pm25 event runs on
  AQ-KN00-00.
- **Deviations from the board:**
  - No htpd forced schema or split decoding. Title, severity and label are decoded before the split point, so they are
    unaffected; the checklist can differ slightly.
  - No htpd agent label constraint.
- **Metrics** (`harness/analyze.py`, written to `raw/summary.json`). Each early run is paired with the k = 8 run of
  the same event (the current gate):
  - **flip:** the displayed severity or the label differs from k = 8;
  - **severity accuracy:** compared with the k = 8 teacher status;
  - **sensor-fault vs process call;**
  - **checklist Jaccard.**
- **Clear rule.** A shape clears k when, for k and every larger k:
  - the paired accuracy drop is ≤ 5 pp and not significant (losses − wins < 2√(losses + wins));
  - the flip rate is ≤ 15 %;
  - at least 8 pairs exist.

## Results so far (31 groups, about 5 per shape; 64 AI runs; 26.5 s per run, 2 parallel)
| shape | groups | gated at k=8 | pairs per k | flip rate k3-k7 | min clear k |
|---|---|---|---|---|---|
| spike | 4 | 2 | 1-3 | 0.5 at k3 | – (n too small) |
| step | 8 | 2 | 1-2 | 0 | – (n too small) |
| trend | 4 | 3 | 1-3 | 0 | – (n too small) |
| flatline | 7 | 0 | 0 | – | – (no gated rows) |
| noisy | 2 | 2 | 1-2 | 1.0 at k3 | – (n too small) |
| fault | 6 | 1 | 1 | 1.0 at k3 | – (n too small) |
| **ALL** | 31 | 10 | 6-9 | k3 0.50, k4 0.43, k5 0.38, k6 0.44, k7 0.22 | **none** |

Early signals, not conclusions:
1. **Early verdicts flip often.** Pooled, 22-50 % of early reports change severity or label by k = 8. Even k = 7
   flips 2 of 9.
2. **Many events never pass the gate.** About 40 % of the rows are gated (the rules flag them). Flatline (stuck) events
   replayed on the bank sensors were almost never flagged (2 of 44 rows). This needs a look: it may be the stand-in
   replay or a real gate gap.
3. **Accuracy against teacher gold is low at every k,** including k = 8 (0.2-0.33). The gold is the teacher's
   agent-level status at the original node, so it is a weak target here. Flip versus k = 8 is the metric that counts.

## Recommendation (provisional)
- `ai_early_k`: **leave unset (off).** No shape has evidence to clear any k.
- `ai_early_shapes`: **leave empty.**
- If one must be tried before the full run, only `step` and `trend` show 0 flips. That rests on 1-3 pairs each, which
  is not enough. Do not enable without the full run.

## Resume (one command; waits for GPU_LOCK to be free, skips finished rows)
```
wsl.exe -e bash /mnt/c/Users/hp/Desktop/qidk/proofs/2026-11-12_early_ai/harness/start.sh
```
- `start.sh` rebuilds `~/early_ai` if it is missing, starts `harness/run.sh` detached with a hidden keepalive (80 h),
  and logs to `raw/run.log`.
- `run.sh` waits until `GPU_LOCK` is absent, the GPU has < 800 MiB used, and no llama-server or `train_` process is
  running. Then it takes the lock, runs at most `EAS_HOURS` (default 5.5 h), and releases the lock and its servers on
  exit.
- Guards: GPU 92/88 C pause/resume; Windows free RAM < 500 MB pause.
- Expected size: about 1,050 AI runs at about 256 per hour, so the full study takes about 4-4.5 h.
- After it finishes, run `python3 harness/analyze.py` and update this file.

## Files
- `harness/`: `eas_test.go`, `htpd_shim.py`, `run.sh`, `start.sh`, `analyze.py`
- `raw/`: `rows_s0.jsonl` and `rows_s1.jsonl` (one JSON per row: gate state, agents, report severity, label, checklist,
  validity, latency), `run.log`, `summary.json`

## v5 rerun (2026-11-27)

**Status: COMPLETE (440 of 440 event groups, 2,640 rows, 1,102 AI runs). No shape clears any k. Keep `ai_early_k` OFF and
`ai_early_shapes` empty.**

### Method diff vs the 2026-11-12 run
- **Models (md5 = board `/data/local/tmp/gpu`):** reasoner `rsn_v3_4b_v5_q4_0.gguf` (afdae452…, `Code/models_stage`); agents
  `agt3_s0450_q4_0.gguf` (996777a4…, `~/smartcity_runs/agt_topup_k2b/post/s0450/`), the model the board's `htpd_profile`
  names (`model=`, `agents=agt_v3`). Old run: rsn_v3_4b_r3 + ft_B50.
- **Profile** (`raw_v5/htpd_profile_used`): `post_rules=all`, `solo_rerun=runaway`, `reasoner=v3`, plus the board lines
  `reasoner_prompt=v4`, `reasoner_think=adaptive`, `agents=agt_v3`, `agent_tools=1`, `agent_ctx=1280`. The agent lines are
  needed, because agt3 is trained on the v3 prompt and the tool-call protocol. Board `agent_version` = v2, as before.
- **Shim** `harness/htpd_shim_v5.py`: `HTPD_AGENT_MAX_NEW=240` (board env) and the Llama 3.2 prefill marker
  (`<|end_header_id|>\n\n`, as in htpd v9h `prefill_of`). The old shim only knew the ChatML marker.
- **Backend:** a fresh copy of the working tree of `app/backend` (branch htpd-window-ux @ 5516ac1, with the uncommitted
  `batchsplit.go` / `reason.go` edits present on 2026-11-27 07:25 UTC), built as `~/early_ai/eas.test`. `harness/eas_test.go`
  is unchanged. The repo was not modified.
- **Serving:** llama-cuda-b11815. Reasoner `-c 16384 -np 2` (8,192 per slot = board `reason_ctx`). Agents `-c 4096 -np 2`,
  because the 6 GB GPU has to hold both models (5.8 GB used). Greedy decoding. 2 shards. Median 23.4 s and p90 27.6 s per AI run.
- **Guards** (`harness/run_v5.sh`): no pause/SIGSTOP. Temperatures are only logged (83-90 C, never 92 C), and 92 C would have
  stopped the run cleanly. The known-stale `GPU_LOCK` line from 2026-10-31 was saved and restored.
- **Still not on the board:** no htpd split decoding (`reasoner_split=3`), no `HTPD_JSON_ABORT`, and no agent label trie. With
  `reasoner_think=adaptive` the board also runs the reasoner without forced schema, so the report path matches more
  closely than in the old run.
- **Analysis:** the same `harness/analyze.py`, which now takes the raw dir as an argument
  (`python3 harness/analyze.py raw_v5`). The clear rule is unchanged.

### Results (pairs = groups where both the k run and the k = 8 run gave a valid model report)
| shape | k8 reports | k=3 pairs | k=3 flip | k=3 Δsev pp | k=3 Δcls pp | flip k4 / k5 / k6 / k7 | min clear k |
|---|---|---|---|---|---|---|---|
| spike | 31 | 20 | 0.60 | -15.0 | +10.0 | 0.64 / 0.54 / 0.50 / 0.52 | none |
| step | 43 | 25 | 0.72 | -4.0 | +12.0 | 0.70 / 0.65 / 0.59 / 0.76 | none |
| trend | 35 | 22 | 0.68 | +9.1 | +22.7 | 0.72 / 0.44 / 0.72 / 0.61 | none |
| flatline | 16 | 12 | 0.58 | -33.3 | -33.3 | 0.55 / 0.44 / 0.46 / 0.64 | none |
| noisy | 18 | 13 | 0.62 | -23.1 | -30.8 | 0.67 / 0.56 / 0.50 / 0.60 | none |
| fault | 11 | 10 | 0.40 | -30.0 | -30.0 | 0.33 / 0.33 / 0.22 / 0.43 | none |
| **ALL** | 154 | 102 | 0.63 | -11.8 | -1.0 | 0.64 / 0.52 / 0.56 / 0.62 | **none** |

Full per-k table (accuracies, wins/losses, checklist Jaccard): `raw_v5/summary.json`, or run `analyze.py raw_v5`.

### Findings
1. **The flip rule fails everywhere, by a wide margin.** The best cell is fault at k6 (0.22, 9 pairs). Every other cell
   is between 0.33 and 0.76, against a limit of 0.15. Even k = 7, one reading before the gate, flips 52-76 % on the
   shapes with the most data. A verdict that changes this often between k and k + 1 is not stable enough to show as a
   provisional alert.
2. **Accuracy drops at k = 3 for 5 of 6 shapes.** Flatline, noisy and fault lose 23-33 pp. Trend is the exception: early
   runs score higher against the teacher gold (+9 pp severity, +23 pp sensor-fault-vs-process). Its k = 8 accuracy is only
   0.29, and it still flips 68 %, so it does not clear.
3. **Early runs can fire on events the gate never reports** (rows gated at k = 3 whose k = 8 row is not gated): fault 11 of
   25, noisy 7 of 21, spike 8 of 42, flatline 2 of 22, step 1 of 44, trend 1 of 32. For fault and noisy this would add
   provisional alerts that the full gate later drops.
4. **19 % of AI runs ended with the reasoner report rejected** (210 of 1,102, rules fallback; excluded from pairs). Top
   reasons: a warning checklist without inspect/review (60), missing evidence, confidence or checklist (26), a wrong
   critical first action (18), and agent verdict "rejected" (14). This is a separate reasoner-validity issue worth a look.
5. **Data is adequate for k = 3 on spike, step and trend (20-25 pairs) and thin for flatline, noisy and fault (10-13
   pairs).** With flip rates of 0.4-0.7, no plausible sampling error brings any shape under 0.15.
6. **Caveat, not measured:** run-to-run nondeterminism of the host servers (parallel slots, prompt cache) could explain
   part of the flip rate. A k = 8 self-repeat (`raw_v5_repeat8/input_k8.jsonl`, 190 rows, `harness/run_v5_repeat.sh` with
   `EAS_RAW` / `EAS_DATA_IN`) was started but was stopped before any row ran: the session reaped it under low memory. It
   gives the noise floor and can be rerun. Even so, the accuracy losses on flatline, noisy and fault do not depend on that
   floor.

### Recommendation
- `ai_early_k`: **keep unset (off).**
- `ai_early_shapes`: **keep empty.**
- To revisit, an early path needs a stability fix first, not a different k: for example, show the provisional verdict
  only when a k and k + 1 run agree, or only the rules report early. Then rerun this study (about 3.7 h on the laptop GPU).

### v5 files
- `harness/run_v5.sh`, `harness/run_v5_repeat.sh`, `harness/htpd_shim_v5.py`, `harness/analyze.py` (now takes a raw-dir argument)
- `raw_v5/rows_s0.jsonl`, `raw_v5/rows_s1.jsonl` (2,640 rows), `raw_v5/summary.json`, `raw_v5/run.log`,
  `raw_v5/htpd_profile_used`, `raw_v5/gate_dry_all.jsonl` (gating-only dry run over all rows, no AI)
- `raw_v5_repeat8/input_k8.jsonl` (repeat input, not run)
