# Domain-agent improvement plan (2026-10-25): research only, nothing trained or run

Scope: the Llama 3.2 3B LoRA domain agent, Q4_0 on the NPU (htpd). The live model is **mixA50** (v2 + 0.5·(c49 − v2)) with post-rules on.
Constraints: no retrain from base; only top-ups, merges or small training; RTX 4050 6 GB; accuracy comes before latency.
I read the evidence on the laptop. I made no GPU, board or WSL calls, and changed no code.

## 1. Why v2.1 regressed on the board

**Evidence: per-row board diff, mixA50 → v2.1, host400 with rules on.**
- Diff method: `samples.jsonl`, pattern or status flipped.
- Result: **13 losses against 4 wins.**
- 8 of the 13 losses are **"→ flatline/sensor_fault"**, almost all on compound rows:
  - 3 are gradual_decrease/warning;
  - the others are step_increase/critical, step_decrease/normal and similar cases.
- 7 of the 13 losses are on **water, unseen or unseen_sepoct**. In that slice, unseen_sepoct pattern fell from 73.9 to 47.8.
- Compound pattern fell from 86.1 to 66.7 (n = 36).
- The rest are single rows:
  - oscillation → erratic;
  - erratic → stable;
  - dip → stable;
  - one empty answer.
- The model collapsed toward flatline/sensor_fault. Most of the regressions come from this one shift; they are not spread evenly over the slices.

**Root causes, most likely first:**
1. **The host screen showed the problem and it was overruled.**
   - dev3f compound status went 86.6 → 80.4, with 0 wins and 6 losses at every checkpoint (400, 500 and 621). That is the board failure, seen early.
   - The safe mix (v2·0.3 + v21·0.7) kept compound flat on the 558-row subset. It was screened only partly, and then the owner skipped the screen and the final checkpoint went to the board.
2. **The screen compared against the wrong baseline.**
   - v2.1 was trained from the **v2** adapter, and every dev number is "vs v2 + rules", but the deployed model is mixA50.
   - Some of the "gains" are things mixA50 already had. Because v2.1 does not start from mixA50, it also gives up c49's contribution.
3. **The gains fell where the post-rules already work.**
   - The large v2.1 gains (water_cause 52 → 93, the rw5 status slices) are status and cause fields, which the track-B rules already repair: water_cause, rel_level, limit, glitch and floor.
   - With rules on, the net gain was only ALL status +1.6 on dev.
   - The losses are pattern errors, and no rule repairs pattern errors. So the net on the board is negative.
4. **The data mix moved the flatline/sensor_fault prior. Hypotheses, ranked:**
   - (a) **C1 dropped 1,403 low-amplitude event rows from v2 replay, and nothing balanced that.** Small declines were left mostly as non-event examples. This filter is not symmetric: C2/C3 removed only 9 "flat gradual" rows.
   - (b) **The new 4,922 rows are heavy in faults and water.**
     - 870 of them are sensor_fault (17.7%, against 15.2% in replay).
     - 1,682 are water rows, against 904 in replay.
     - The weak buckets add `zero_stop` and `stuck_flow`, plus rw5 gap, stuck and recovery cases.
     - Together these teach "flat-looking water → flatline/sensor_fault". The 7 water rows among the losses fit this.
   - (c) **v21_aug rescales history by a ∈ [0.6, 1.7] but keeps the printed decimals.** When a < 1, slow declines on coarse metrics print as longer flat runs in SERIES and E8. This is untested; check it as described below.
5. **LR and epochs are not the cause.** Checkpoints 400, 500 and 621 are almost identical on dev, so the shift is driven by the data, not by over-training.
6. **Quantisation and runtime are not the cause either.** Host Q4_0 matches the board on 207/208 rows, so the host proxy is sound.

**Check, read-only, about 30 min CPU, when WSL is free:**
- On `train_v21.jsonl` against v2 replay, compute the label shares for flatline and sensor_fault on water/compound rows.
- Compute the share of gradual_decrease rows whose SERIES has a flat run of 6 or more, split by source (aug vs others).
- If the flatline-like share of the new rows is more than 1.5× the replay share, that confirms 4(b) and 4(c).

## 2. Why the leak and AC stories fail

The prompts do carry time of day:
- WINDOW start → end in IST;
- the off-hours flag in E6 (occupancy) and E8 (HVAC);
- E8 also gives the day.

The AC prompt carries what the AC case needs:
- E1: room vs setpoint band;
- E4: trend and last-hour slope;
- E5: AC on N/N, mode;
- E8: usual-on and off-hours.

Water level carries slope (E4) and the 12 h slow drift (E9). So the signal is there. The failures have three other causes.

| story | what happened (`sim_results.json`) | root cause |
|---|---|---|
| slow_tank_leak | mixA50 said **critical / tank_overflow_risk** (the level sat above the node's high mark of 186.5). v2.1 said **warning / possible_leak**, which is the right idea. In both runs the **post-rule `rel_level` + `water_cause` overwrote the answer to normal/tank_draining** (`repairs` field). | **The label definition, not the model.** The teacher (`routine_rule`, mirrored in `postrules.go` `routineV2` and in `rules.go`) says a gradual_decrease is `possible_leak` only off-hours, and `tank_draining`/normal in the daytime. A daytime leak cannot be detected by definition, and the rule removes a correct model answer. **Story flaw:** the level was injected at 300 − 6i into a node whose marks are about 186. The engine rule saw a spike, and the model saw "past the high mark", so this was a step plus a drain, not a slow leak. |
| ac_fails_hot_day | mixA50: **stuck_on**, "kept running at night/weekend". v2.1: **stable/normal**, "steady at 30.0 C inside the band around 26" (wrong: the band tops out at 28), and "cool mode, so no cooling is expected" (a corrupted fan-mode template). The app's own HVAC rule said **no_cooling_effect/critical**. | **The model, not the features or the teacher.** Python `classify_hvac` labels this window too_hot/warning (above band for less than 1 h) or no_cooling_effect (after 1 h). The HVAC teacher is fully deterministic and mirrored in Go (`hvac_v2.go`). **Distribution shift:** +4.2 C/h, stepped (one ingest is held across several 5-min buckets), on top of 34 replay points from another time of day. The board scores HVAC at 98.5% on in-distribution rows. |
| time-of-day claims | "Night-time water activity" and "night/weekend" at about 13–14 h sim time. | The observations copy teacher templates without checking E6/E8. It is a text hallucination; the label fields can still be right. |
| co2_glitch (aside) | "Level down from 450 to 928 ppm" | Direction and number contradict each other in the observation text. |

**Caveat:** the sim does not save the exact prompts. The step/replay mix and the off-hours flag are therefore inferred from the outputs and the code. Logging the prompts is P0 below.

## 3. Methods ranked: expected gain, risk and cost on an RTX 4050 6 GB

| rank | method | gain | risk | cost | verdict |
|---|---|---|---|---|---|
| 1 | **Deterministic fixes**: post-rules plus a claim verifier | High on safety stories (leak, AC) | Low; Go unit tests; affects no model weights | 3–5 h CPU | **Do first** |
| 2 | **Task-vector re-mix** (no training): mixA50 + β·(v21 − v2), β ∈ {0.2, 0.35, 0.5}; plus **TIES/DARE** on the c49 and v21 deltas with v2 as base | +0.5–1.5 pattern on unseen/erratic while keeping compound; most v21 status gains are redundant with rules | Low | ~1 h GPU per candidate (LoRA-scaling screen), 3–4 candidates | Do |
| 3 | **Targeted small SFT from mixA50** (`mix_to_lora.py`), heavy replay | +2–5 on HVAC stories and gradual_decrease vs flatline | Medium: three top-ups so far each traded slices | 5–7 h GPU + 2 h eval | Do only after 1–2 and the new eval |
| 4 | **Tiny classifier** (MiniRocket or GBM on the E1–E10 numbers) as a pattern second opinion or tie-break on flatline vs gradual | Medium on compound/unseen pattern | Medium: a Go port is needed, and it is a new component to prove | 1–2 days CPU | Optional, after 3 |
| 5 | **Prompt/feature changes** (for example a "usual drain/h" line or an explicit "daytime" token) | Real for the leak case | High: any new line is out of distribution without retraining. Put the signal in the rules or the reasoner instead | — | Not via the prompt now |
| 6 | **DPO/ORPO on hard pairs** | Low | High: 3e run1 lost 13 of 75 compound rows; run2c49 was gate-neutral; anchor repair (mixRep50) gave no win | 4–6 h | No |
| 7 | **Grammar / trie** | ≈0 accuracy (track-B: no host gain, one unexplained loss) | — | 0 (the trie already exists) | Keep the trie for off-label safety only |

Literature behind the ranking:
- **WiSE-FT** (Wortsman et al., CVPR 2022, arXiv 2109.01903) and **task arithmetic** (Ilharco et al., ICLR 2023, arXiv 2212.04089): scaling deltas keeps the wins and limits forgetting, with no training. This is already shown here by mixA50.
- **TIES-Merging** (Yadav et al., NeurIPS 2023, arXiv 2306.01708): trims small values and resolves sign conflicts. The c49 and v21 deltas conflict on the status prior, which is the case TIES is built for.
- **DARE** (Yu et al., ICML 2024, arXiv 2311.03099): drops and rescales delta weights. Merge in delta space (BA), not on A and B separately. The `mix_to_lora.py` form applies.
- **Model Stock** (Jang et al., ECCV 2024, arXiv 2403.19522): checkpoints from one trajectory give little soup diversity. This matches soup3 being no better than mixA50.
- **LoRA Learns Less and Forgets Less** (Biderman et al., TMLR 2024, arXiv 2405.09673): a low-LR, low-rank top-up with replay is the right SFT shape.
- **Likelihood displacement in DPO** (Razin et al., ICLR 2025, arXiv 2410.08847) and **ORPO** (Hong et al., EMNLP 2024, arXiv 2403.07691): single-token-swap pairs move mass to neighbouring labels. This is exactly the 3e and c49 failure, so preference training ranks low.
- **Mix data or merge models?** (Aakanksha et al., 2024, arXiv 2410.10801): merging separately trained deltas often beats one mixed run.
- **MiniRocket** (Dempster et al., KDD 2021, arXiv 2012.08791): a strong, CPU-cheap time-series classifier.

## 4. Eval protocol that predicts the board

- **E0: story capture (P0, about 2 h).**
  - `sim.py` saves, for each agent call:
    - the exact prompt;
    - the window end;
    - the off-hours flag;
    - the rule finding.
  - The Python teacher (`teacher_v2` / `hvac.classify_hvac`) labels each captured window: this is the **story gold**.
  - A story where the teacher gold disagrees with the intended label is a **label-definition gap** (like the leak) and goes to the rules backlog, not to training.
- **E1: fixed story suite on the host proxy** (screen on host, Q4_0 CPU/CUDA = board 207/208).
  - The 6 existing stories, fixed so they are realistic:
    - the leak starts at the node's own level;
    - the AC fault rises +1–2 C/h in 5-min steps, without replay mixing.
  - About 20 new stories, each run daytime and night, on a seen and an unseen node, with 3 seeds (about 240 calls):
    - leak at night;
    - daytime leak with no refill for 3 h;
    - fill valve stuck (overflow);
    - AC not cooling at 14:00 on a weekday, occupied;
    - AC running in an empty room at night;
    - AC stuck off during working hours;
    - slow AC recovery;
    - load growth at 11:00 vs a normal evening shutdown;
    - weekend or holiday low load;
    - CO2 stuck at 400 for 3 h;
    - CO2 drift;
    - slow pH drift;
    - refill step then drain (compound);
    - step then gradual decrease on power;
    - gap then recovery;
    - chatter at a limit;
    - single glitch;
    - stuck flow at 0 while the tank level moves;
    - an unseen sensor at 0.6× and 1.7× scale.
  - Score pattern, status and cause against the story gold, plus **claim checks**:
    - time-of-day words vs the flag;
    - direction words vs the numbers;
    - "inside band" vs E1.
- **E2: paired host screen, reference = mixA50 + rules** (never v2).
  - Sets: dev3f (2,010) + rw5dev (313), LoRA-scaling for screening, then the merged Q4_0 for the gate.
  - Fixed slices: compound, water unseen/sepoct, gradual_decrease-vs-flatline rows, HVAC.
  - Gates:
    - net "→ flatline/sensor_fault on gold-event rows" must be ≤ 0;
    - no fixed slice may lose more than 1 row net.
- **E3: final host confirmation.**
  - host400 (= board proxy), test 1,148 and rw5test, merged Q4_0, McNemar vs mixA50.
  - Only one winner goes to the **board**: host400 + the E1 suite (one NPU client, safe transfer).

## 5. Ranked plan

| # | what | cost | expected gain | risk | go/no-go test |
|---|---|---|---|---|---|
| P0 | **Build the eval** (E0/E1 above): prompt capture, realistic stories, teacher story gold, claim checker, mixA50 baseline row | 3–4 h CPU + one host-proxy run of about 1 h | Makes every later decision board-predictive | none | Baseline recorded. The suite reproduces today's leak/AC failures on mixA50 and v2.1 |
| P1 | **Rule fixes** (Go, mirrored in Python for scoring): (a) `rel_level`/`water_cause` must not **downgrade** a model `possible_leak`/warning to normal when E9 shows a slow drift, or when the window drop exceeds the node's usual drain with no refill; add a daytime-leak routine, same rule in `routine_rule` (label-definition change, documented). (b) HVAC: when Go `classify_hvac` gives an event pattern with warning or above and the model says stable or normal, use the teacher's pattern/status/cause (same as the Python teacher, so exact). (c) Claim verifier: remove or rewrite observations whose night/weekend/off-hours claim contradicts the flag, or whose direction word contradicts from→to. | 4–5 h | Leak and AC stories fixed on both models. Story status +10–20 pts on safety stories. host400 unchanged | Low. (a) can raise false leak alarms on routine drains | host400 + test + rw5test with rules: 0 net losses; real_routine/water_fill slices unchanged; E1 leak and AC stories pass; Go tests pass |
| P2 | **Re-mix without training**: mixA50 + β(v21 − v2), β ∈ {0.2, 0.35, 0.5}; TIES (density 0.2–0.3) and DARE (p 0.9) on {c49 − v2, v21 − v2}, base v2 | ~4 h GPU (screen) + 1.5 h merge/eval of the winner | +0.5–1.5 pattern (unseen, erratic), compound flat | Low | E2 gates vs mixA50 + rules, and no story regression in E1. Otherwise keep mixA50 |
| P3 | **Small SFT from mixA50**: r 16–32, LR 3–5e-6, ≤ 300 steps, **≥ 3:1 replay** stratified to the v2 label distribution, **C1-dropped rows put back**. New data, about 1.5k rows: HVAC story-like windows (fast rises, stepped ingest, too_hot/no_cooling with AC on, cool mode, daytime) and clear gradual_decrease rows with flat-run look-alikes; no extra zero_stop/stuck_flow; no v21_aug. Then WiSE-interpolate the result with mixA50 (α 0.5–0.7). | 6–8 h GPU (user-started session with a stop prompt) + 2 h eval | +2–5 on HVAC stories and compound pattern | Medium | E2 gates (flatline drift ≤ 0) + E1 ≥ P1/P2 on every story class, then E3 |
| P4 | **Optional tiny classifier**: MiniRocket/GBM on the 48-point window + E-stats, trained on teacher labels (CPU, minutes). Used only to veto `flatline` when the classifier is ≥ 0.9 sure it is gradual or step, as a post-rule | 1–2 days (Go port) | Compound/unseen pattern +2–4 | Medium | Same gates; veto precision ≥ 95% on dev3f |
| — | Drop: DPO/ORPO, more grammar, prompt-format changes (they need a retrain to be in distribution) | — | — | — | — |

**Order:** P0 → P1 (ship the rules on mixA50 if the gates pass) → P2 → P3 only if P2 leaves the HVAC/compound story gaps open → P4 optional.
**Never deploy** a candidate that has not passed E2 vs mixA50 + rules and the E1 story suite on the host proxy.

## Status (execution, proofs/2026-10-25_domain_plan)
- **P0 (in progress, CPU):** E1 story suite built (`scripts/e1_stories.py`, 184 rows, 23 stories x day/night x seen/unseen x 3 seeds,
  teacher story gold); E2 gate script (`scripts/e2.py`, ref = mixA50 + live rules, flat-drift gate). E2 check: v2.1 vs mixA50 on dev
  = flat +4, compound -5, gradual_decrease -4 -> FAIL (reproduces the board rejection). Host-proxy E1 run for mixA50 / v2.1: running.
- **P1 (code done, gate PASS on stored outputs):** (a) daytime long-drain leak routine + E9 keep-leak guard (Go `postrules.go`,
  teacher `routine_rule`, Python mirror `scripts/p1_rules.py`); (b) `hvac_rule` (Go `claimcheck.go`); (c) claim verifier = flags
  only (`AgentCall.claim_flags`). Go parity 6,446 rows 0 mismatches; go test ./... pass. E2 mixA50+P1 vs mixA50+rules:
  4 sets PASS under the new label definition (dev s +7 net, test +3; flat 0); old gold differs only on the 5 relabelled rows.
- **P1 DEPLOYED (2026-10-25 22:15 IST):** edge-agent cf0da165, HANDBOOK 2.52. Board proof (board_p1/sim_p1_*.json): daytime 4 h tank drain
  normal -> warning/possible_leak by post-rule; AC no-cooling stable/normal -> no_cooling_effect/critical by hvac_rule. refine 10/10, chaos 30/34 (thermal).
- **P0 done:** E1 mixA50 baseline (159/184 host rows; CPU runs killed by memory pressure): rules all-3 71%, safety 6/14; +P1 75%, 12/14.
- **P2 ready (waits for GPU):** B20/B35/B50 runtime LoRA on mixA50 Q4; TIES d0.2/0.3 (rank-128 relative LoRA, SVD energy 0.87-0.9);
  DARE p0.9 dropped (rank-128 keeps 28% of its energy, so it collapses to ~B35). scripts/p2_screen.sh + p2_score.sh.
- **P3 ready (waits for GPU):** train_p3.jsonl 4,800 rows (sha e56cfac9): new 1,200 = HVAC story 450 (fast/stepped no-cooling) + HVAC events 200
  + gradual_decrease with flat runs 400 + daytime leak 150; replay 3,600 v2-train rows (C1 rows kept, 13 old-definition day drains dropped).
  scripts/p3_train.sh: from m50_adapter, LR 4e-6, ~300 steps, then WiSE a 0.5/0.7 screen on E1 + dev3f.

## Gate revision (2026-10-28) - the E2 slice gate above is INVALID
- Permutation test (diag.py, 1,000 swaps of paired rows = two EQUAL models): the old rule "flat drift <= 0 and no fixed slice net loss > 1 row"
  fails equal models 71-82% of the time on dev3f (38-64% on E1). It rejected B50/T30 on noise.
- **New sound gate (scripts/gate2.py):** vs mixA50 + P1 rules (new leak gold), dev3f total net (pattern+status+cause wins - losses) > 0,
  severity-weighted net (x3 on gold warning/critical/sensor_fault rows) >= 0, no fixed slice significantly worse (exact sign test, Holm 0.05);
  E1 net >= 0, safety stories not lower, no Holm-worse slice. Bootstrap 95% CI of the total net is reported alongside.
- Under it: T30 PASS (dev +8, sev +48, E1 0), B50 PASS (dev +1, sev +61, E1 +4); both CIs include 0. P3W06 FAIL (dev -42, CI -73..-14, HVAC Holm-worse).
- **P3 root cause:** replay = raw v2-train gold pulled the model back to v2 (34 of 67 P3 losses are mixA50's gains over v2; P3 sided with v2 on
  49/108 mixA50-vs-v2 decisions). **P3b:** replay only rows mixA50 itself answers right (scripts/p3b_queue.sh: filter, train, WiSE 0.5/0.7/1.0,
  gate2 over P3b + T30 + B50, merge winner to Q4_0, LoRA-vs-Q4 parity on fid200, stage in Code/models_stage with md5).
