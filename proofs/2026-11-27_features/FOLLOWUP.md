# Follow-up 2026-11-27 (evening): early look, report rejections, heat, prefetch

## 1. Early look (owner: "show early AI with a badge, proper reading in N minutes, the full reading independent")
Deployed 2026-11-27 20:04 IST with `ai_early_k=3`, `ai_early_shapes=spike,step,trend,flatline,noisy,fault,limit` (owner: k=3 so a single random spike never calls the AI):
- Badge **"Early look"** on the incident, with "Full reading in ~N min, made independently of this one" (`/api/incidents`
  `full_eta_s` from the Watching-strip ETA). Android: "Early look: new warning" etc.; the full reading notifies again.
- **Independence** (the full reading is made as if the early look never happened):
  - severity, "severity final", severity reason, agents and retrieved matches of the early look are dropped when the gate
    adopts the incident (`fastpath.go`); the early look stays only in the revision history;
  - the reasoner's RE-CHECK list leaves out the early look (`buildV3Input`);
  - retrieval never stores an early look, and a query never matches its own incident (`retrieval.go`).
- An early look the gate never confirms closes itself after persist_readings + cooldown (100 min of sensor time):
  "early look not confirmed" (`closeUnconfirmedEarlyLocked`). Fast-path (critical) incidents are not touched.
- Tests: `TestEarlyLookIndependentOfFullReading`, `TestEarlyLookUnconfirmedCloses` (+ the existing early-AI tests).

## 2. Reasoner report rejections (repairs built and deployed)
- Laptop study (v5, 1,102 runs): 210 rejected (19 %). Board, all stored incidents since October: 43 of 568 (7.6 %), 8 of
  them "connection refused" (htpd down), so about 6 % are model output.
- Most are **format slips that throw away a sound diagnosis** (the report is rebuilt from the agent template, which the
  paper measured at 25 % both-correct vs 75 % for the reasoner):

| reason | study | board |
|---|---|---|
| warning checklist has no inspect/review step (or it is not first) | 68 | 15 |
| title over 80 characters | – | 19 |
| checklist / evidence list empty | 59 | – |
| confidence missing | 29 | – |
| critical / normal / sensor_fault first action not the policy one | 42 | 4 |
| agent_check verdict word not in the list ("rejected", "revised", "supported" ...) | 38 | – |
| evidence id written as `S1-E3`, `S1.card` | ~25 | 5 |
| number not in the input (real invention) | 2 | 1 |

- Built (`backend/reportrepair.go`, owner OK): repair instead of reject where the fix is mechanical: move the policy
  action first (or add the domain's inspect action), drop an agent_check with an unknown verdict or sensor ref,
  normalise `S1-E3` ids and drop unknown ids when known ones remain, fill empty evidence from the observations' own ids.
  Long titles were already shortened (sweep fix). Still rejected: invented numbers, actuation language, bad JSON,
  unknown labels/actions, missing confidence, empty title. Each repair is logged. Reach: in the study, 156 of 210 rejected
  reports (74 %) had only repairable errors (an upper bound: an id list with no known id is still rejected); on the
  board, all but about 3 of the 35 model rejections were of a repaired kind (or the title length fixed earlier). Script: `proofs/2026-11-12_early_ai/harness/rejections.py`.

## 3. Reasoner on corroborated heat (fixed at the input)
- Cause: the prompt showed S1 with a +2.0 C step and S2 (AC room temp) only as "now 33.5 C, trend +0.9 C/h"; nothing said
  both rose ~10 C together, so the reasoner sometimes read S1 as a jump.
- Fix: an **AGREE** fact line (`reportfix.go agreeLines`, used by the v4 prompt) when two independent indoor temperature
  sensors in the same area both rose >= 1 C over the last 6 readings.
- Laptop GPU A/B on the exact board prompts of feature runs 2 and 3 (`heat_ab/`, rsn_v3_4b_v5 Q4_0, greedy + seeds):

| prompt | critical (correct) | sensor_fault / warning |
|---|---|---|
| original | 27 / 32 | 5 |
| + AGREE (first wording) | 31 / 31 (+1 valid tool call) | 0 |
| + AGREE (final wording) | 23 / 24 | 1 |
| memory without the rh "sensor offset" line | 13 / 16 (+1) | 2 |
| S2 min/max lines shown | 9 / 15 (+1) | 6 |

  The guard in `reportfix.go` stays as the backstop.

## 4. Agents during the gate wait (prefetch): status for discussion
- Shadow log: 3 comparisons (2 agree; 1 differed and would not have been reused). Live data adds 1-2 per batch.
- Gain if reused: ~3 s per agent, against a 20-50 min gate. Risk: the reused answer read 1-3 fewer readings, the same
  independence problem the owner ruled out for the early look.
- Decision: stays `agent_prefetch=shadow` (free evidence), reuse stays off.

## Deploy
- Build: edge-agent f74cb6b3, APK from `android/out` (2026-11-27 20:04 IST). Rollback: `adb install -r -d deploy/before_followup.apk`
  (2e31ae51) and restore `htpd_profile.before_followup.<ts>` on the board. Script: `deploy_followup.sh`.

## Board checks (feeder3: KH03 heat with AC off, KH98 pH critical, SB00 power factor; state backed up and restored)
| run | what happened |
|---|---|
| A (20:04-20:45) | pH: early look 20:25 on the fast-path incident, full reading 20:40 "made independently of the early look"; both critical. Power factor (0.81 below 0.85, pattern "stable") got **no** early look: a value past its limit with no trend shape belonged to no family. |
| fix | new family **limit** (warning/critical value with no trend shape); profile `ai_early_shapes=...,limit` |
| B (20:55-21:28) | Power factor: early look 21:20 (shape limit), full reading 21:25 independent, both warning. Heat: early look 21:15 (shape trend) joined the open pH fast-path incident (same building); the **AGREE line was in the board prompt**. That early-look report was rejected for broken JSON (not a repairable slip) and showed the agent report. |

Not seen on the board yet: the full heat reading with the AGREE line (in both runs the heat gate fired at the very end).
Files: `run_followup*.sh/.out`, `feeder3_followup*.out`, `incidents3_log_followup.jsonl`; board states kept as
`state_followup1127`, `state_followup1127b`.
