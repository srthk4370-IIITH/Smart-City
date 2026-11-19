# agt_v3 top-up v2: plan (automated, owner-approved 2026-11-17)

Goal: continue from s0300 (v1 top-up winner, deployed, real val .808) with ~300 more steps on a mix that adds (1) a tool protocol, (2) dynamic window lengths,
(3) tonight's board failures as hard cases, (4) the weak classes of the v1 selection, while ~58 % replay of the v1 mix keeps current accuracy.
Nothing here deploys to the board; the pipeline ends with a winner file (FINAL_K2) or "s0300 stays".

## Pipeline (auto_v2.sh, detached, log ~/detached/agt_v2.log, registry lines "STAGE x")
0 start -> 1 generate (CPU, nice, 3 procs, gen_run.py) -> 2 mix (build_mix_v2.py) -> 3 checks (check_data_v2.py = v1 real-rows exception + checks_v2.py; FAILED file on
any failure) -> 4 push (push_v2.sh: private dataset agt3-topup2-data, run dataset agt3-topup2-run seeded with the s0300 adapter, private kernel agt3-topup2-train, T4x2,
budget 6 h / cap 8 h, snapshots every 50 steps, patience 3, LR 1e-4, 1 pass ~298 steps) -> 5 pull (poll; re-push up to 3 sessions if the kernel stopped early) ->
6 wait until `~/smartcity_runs/rsn3_4b_v3ft/status.json` says done (the reasoner fine-tune is never paused or touched) -> 7 select_v2.sh (waits for the GPU lock and
>= 21 GB free on C:; exports merged Q4_0 with the shared imatrix on CPU; host eval of six sets; no-harm vs s0300) -> 8 winner file or "s0300 stays".

## Data (counts in mix_manifest.json; real numbers of the run are in STATUS / the final report)
| family | rows | what it teaches | source |
|---|---|---|---|
| tool_* (history, neighbors, card, card+neighbors) | ~24 % of the new rows, 1 row per assistant turn | PROTOCOL.md: when to call, how to use the result | gen_tools.py, simulator truth |
| dyn_* | ~800 | windows 1.5 h (18 pts) / 3 h (36) / 4 h (48) / 12 h (144) for event, stable, fault, occupancy, routine rows | gen_agt families, forced n |
| hard_standby | 280 | 3 W on a kW card (rendered with the app's effDec, 4 decimals): stable/normal, dq ok, never flatline/stuck | custom, teacher label |
| hard_leak | 280 | early part of a slow leak ramp (6-22 pts old): gradual_decrease and warning, not stable/normal | target_amp on tank cards |
| hard_night | 240 | presence 22:00-06:00 = off_hours_presence (warning), not sensor_fault; flapping stays the fault contrast | gen_occ_row |
| hard_plateau | 300 | lone plateau (throttling) / lone step inside the card limits = real event; sensor_fault needs a 2nd evidence kind | gen_event_row, status != sensor_fault enforced |
| hard_limits | 360 | card-edited limits (jitter up to +-45 %), status follows the CARD in the prompt | wide_jit + gen_event_row |
| hard_ph | 180 | rare cadence (one fresh reading per 30-120 min, held between, GAPS line): dq insufficient/suspect, status from the readings that exist | GAPS rows like dq_edge |
| weak_* | 560 | power/water events + faults, calm texture rows that must stay `stable` (the v1 confusion stable->oscillation 12x) | gen_agt families |
| replay | ~5550 (58 %) | v1 mix rows that fit the board context, weak v1 classes x1.4-1.5 (power, water, real_fault, real_longrange, zero_stop) | v1 mixdata |

Extras from the v1 lessons (item 4): v1 REAL VAL per role: power .66 status, water .70, hvac .82, air_quality .92, occupancy 1.0; confusions warning->normal 21,
critical->normal 13, normal->warning/critical 10+10, sensor_fault->normal/critical 7+5; patterns stable->oscillation 12, erratic->oscillation 5,
gradual->exponential 5. v1 real families weakest: real_fault .54, real_longrange .38, real_zero_stop 0, real_water_fill .5. Hence: weak_* (power, water, calm texture),
hard_limits (warning/critical vs card limits), replay weights above. v1 lessons also applied: keep C: >= 20 GB (export failed once at 20338 MB: select waits for space),
one NPU/GPU client at a time (selection waits for the GPU lock), unseen_metric and jittered cards stay in the replay (independence), selection on the deployed Q4_0 form.

## Decisions and limits worth knowing
* Board context: EVERY turn <= 904 prompt tokens (+240 new +136 headroom = 1280). 3789 of the 7500 v1 real rows (12 h windows) and 663 of 2500 synthetic rows exceed it and are
  NOT replayed (they could never run on the board). 12 h windows are therefore rare among the new rows (~5 %); 1.5 h / 3 h / 4 h dominate. If the app wants 12 h agent
  windows, the card text or the evidence must be shortened first.
* Tool results are the compact board-budget forms in PROTOCOL.md (a full 72-value 12 h series + 10 E lines does not fit behind a ~700-token first prompt). The model needs
  the app side of the protocol before a v2 model is deployed.
* Prefill `{"` for generation 1 (so the model may call); final answers keep `{"pattern": "`.
* The Go builder prints no GAPS line today (gaps are interpolated); hard_ph and the gap tool rows use the Python GAPS line. For rare-cadence sensors the app must emit
  that line, otherwise the model sees a smooth interpolated series and cannot know the cadence (app to-do).
* Teacher texts are the v1 templates (some imprecise phrases, e.g. "over 3 h" in an early leak); status/pattern/cause/dq are the training targets that matter.
* Replay real windows go to Kaggle under the same owner exception as v1 (private dataset, md5-pinned REAL_APPROVED.json, REAL_EXCEPTION.log, AGENT_REGISTRY.md).

## Selection (select_v2.py)
Sets: REAL VAL 400, synthetic slice 120, unseen_metric 100 (v1 sets, refs = the s0300 samples already on disk) + hard_val (dev split, tonight's cases),
tool_t2 (final turns with gold call + result forced = what the app does after a correct call), tool_t1 (turn 1 free: call_ok on gold-call rows, direct_ok = no spurious
call on direct rows). Harm (reject): any field worse than s0300 with sign-test p < .05 on val/syn/unk/hard/t2, direct_ok worse with p < .05 or < 92 %, or a composite
score below s0300 minus tolerance (val .012, syn .025, unk .03). Winner: best val + .35 hard + .35 t2 + .30 t1 among harm-free snapshots whose mean (hard, t2, t1) beats
s0300 by >= .02; else s0300 stays. Snapshots below step 100 are skipped.

## Stop / resume
`touch proofs/2026-11-17_agt_topup_v2/STOP` stops after the current stage. Re-running `bash proofs/detach.sh agt_v2 proofs/2026-11-17_agt_topup_v2/auto_v2.sh` resumes
(generation is cached, the mix is rebuilt deterministically; push continues the lineage; select skips scored snapshots). FAILED holds the reason of a failed stage.
