# Early provisional AI: per-shape gate study (ROADMAP §2, FEATURES `ai_early_k` / `ai_early_shapes`)

**Status: PARTIAL. Not enough data for a decision. Keep `ai_early_k` OFF (the app default).**
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
