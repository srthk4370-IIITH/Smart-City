# RQ1 on the board: measured cost of escalation (2026-11-26)

**Source:** every incident the board ran on the deployed stack (htpd_v7, agent agt3, reasoner rsn_v3_4b_v5_q4_0): INC-0001 to INC-0016, of which 14 used the v5 reasoner. INC-0004 was a policy-rejected fallback and is excluded. The data is read-only from `/api/incidents` and `state/htpd.log`.

- **Raw data:** `results/board_incidents.json`.
- **Script:** `board_collect.py`.
- **Test incidents:** INC-0013 to INC-0016 came from test pushes into the live app via `/api/ingest`. They are marked `test_incident`.

## Per-incident cost by number of primary sensors (medians)

| Flagged sensors | n | Total wall (s) | NPU agents, sum (s) | Slowest agent (s) | Reasoner (s) | Reasoner TTFT (s) | Reasoner tokens | NPU calls |
|---|---|---|---|---|---|---|---|---|
| 1 | 7 | 18.2 | 3.1 | 3.1 | 12.0 | 1.6 | 340 | 2 |
| 2 | 5 | 19.2 | 5.4 | 4.9 | 21.3 | 2.4 | 521 | 10 |
| 3 | 2 | 36.8 | 12.3 | 4.1 | 25.7 | 3.6 | 540 | 20 |

**Model swap and prefill** (htpd.log, 24 swaps, medians):

| Step | Time |
|---|---|
| Reasoner swap in (agent model out) | 2.83 s |
| Agent model back in | 2.30 s |
| Reasoner prefill | 1.45 s |

**Cheap-arm cost on the board** (agents plus template, no reasoner) is about the agent stage: 3.1 s at N=1 and 5.4 s at N=2.

**Escalation adds:** swap in 2.8 s, plus reasoner 12–26 s, plus swap back 2.3 s off the critical path. The full path therefore costs about 5–6× the cheap path at N=1–2 on the board, against 1.6–3.7× on the host proxy. The ratio is higher on the board because of the swap and the slower NPU decode. Reasoner latency can be larger than the total wall time in a row: refinement passes re-run the reasoner after the first report.

## Finding: the deployed app escalates every incident

`reason.go:1004` sends single-domain incidents to the reasoner too: "reasoner v3 owns the wording of every report", an owner decision from 2026-10-27. `isolatedReport` is only the preliminary report and the fallback. The board data confirms this: all 7 N=1 incidents have a reasoner report.

So the deployed policy is **always escalate**. The "2 or more domains" short-circuit (RQ3, the Set A 15.5% routing rate) describes the pre-v3 policy. The paper should present it as a candidate trigger, with "always" as the deployed baseline.

## Set C on the board (done 2026-11-26, stopped-app harness)

The sweep could not be driven through the live app (wall-clock sensors, slow re-arm, few drivable sensors), so it ran on a standalone htpd with the app stopped (`setc_board.sh` forced run, `lab_serve.sh` + `board_drive.py` adaptive run), one NPU client, each case started at <= 55 C. Full table: RESULTS.md "Set C on the board".

| N flagged | agents s | reasoner s, forced (live today) | valid, forced | reasoner s, adaptive | valid, adaptive |
|---|---|---|---|---|---|
| 1 | 10.2 | 24.9 | 5/10 | 30.1 | 9/10 |
| 2 | 24.3 | 40.5 | 3/10 | 36.9 | 10/10 |
| 4 | 44.3 | 44.1 | 1/10 | 45.2 | 10/10 |
| 8 | 78.6 | 43.7 | 4/10 | 46.5 | 10/10 |
| 12 | 123.1 | 47.2 | 7/10 | 52.8 | 9/10 |

- **Forced decoding loops:** 29 of the 30 invalid forced reports hit the token limit while repeating a sentence.
- **Adaptive:** 48 of 50 valid, one call each, about the same reasoner time.
- **Cost at large N is the agents:** about 10 s per flagged sensor; the reasoner grows only from 30 to 53 s.
- **Overflow (> 8192 tokens):** stop `ctx`, empty report, template fallback, no crash.
- **Caveat:** cold start and heating to 79-85 C per case make these upper-bound costs.

## Sets B + D reasoner on the board (2026-11-26)

218 cases, same prompts as the host full arm, adaptive thinking (details: RESULTS.md "Sets B + D reasoner on the board").

- **Accuracy matches the host:** Set B both-correct 73.9 % board vs 75.2 % host (McNemar p = 0.88); raw 73.2 % on both.
- **Valid reports:** 208/218 board, 212/218 host.
- **False alarms on normal windows:** 50 % board, 10 % with the skip rule.
- **Reasoner time:** median 34 s on B (host 12 s).

## Side effects (restored)

- **Trigger rules** were changed temporarily (fast_cooldown, fast_readings, abnormal_of_window) and are restored to the saved `results/rules_before_board.json` values (verified).
- **Test incidents** INC-0013 to INC-0016 are in the app history and the local fog outbox (fog relay down, so nothing was uploaded). Cleared afterwards; see the main session note.
