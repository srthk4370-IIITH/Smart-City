# Label audit of real-agent incident rows (2026-11-13)

**Question.** In every `real_agent:*` incident row (agent line = a real model's output on a real window), is the gold
severity / label visible in the evidence lines that are actually in the prompt?

**Answer.** Mostly yes, but not everywhere. 657 of 12,715 audited real-agent rows (5.2 %; files overlap: r4 replay re-uses r3 rows) carry a gold the prompt does not
support. In the r3 training set **217 of the 1,577 `sensor_fault` rows (13.8 %) taught a fault the evidence does not show**,
plus 188 `normal` rows whose current value is physically impossible on the v3 card and 45 warning rows with no visible
limit crossing: 450 of 8,681 real-agent rows (5.2 %) in r3 train. The headline hole of the holes study ("r3 catches 0 of 13
faulty AQ sensors called normal") is mostly a label artefact: 9 of those 13 are one PM10 window with no visible fault.

CPU only, deterministic, nothing trained/uploaded/committed. Real data stays on the laptop (the audit files carry ids,
labels and reasons, no series).

## Where the gold comes from
`2026-10-25_reasoner_final/pipeline/gen_incidents.py real_case()/real_label()` copies the gold of the agent-window
dataset: `data/real_pool.jsonl` (3,281 real agent outputs) <- `real_pool.py` <- `Code/smart-city-edge-agent/data/sft_v2/test.jsonl`
(v2 teacher gold `status` / `fault_kind`, set by the fault **injector**, not by what survives into the window statistics).
A weak injected fault (e.g. `noise_increase` on an already noisy outdoor PM10) can leave E1-E10 inside the normal range of
that sensor; the gold still says `sensor_fault`.

## Method (`scripts/audit.py`)
- Parse S1 from each prompt (header, LIMITS/TANK, quality, S1.E1-E10); join to the pool row for `fault_kind`.
- Thresholds are **data-driven**: per (role, metric), the 97.5th / 99th percentile of each feature over the 1,765 gold-normal
  pool windows (`thresholds.json`): noise (absolute and relative to the mean), largest 5-min change / mean, flat-run and
  plateau fraction, E9 shift/drift strength, E10 excursion size, trend x r2; HVAC: flat minutes, step, missing fraction;
  occupancy: state-change rate.
- Absolute signatures from the **v3 cards** (`core/cards.py`): impossible bounds, `max_step` (a 5-min change above it is never
  a process event), saturation at the sensor ceiling, drop to 0 and back on a non-zero metric, missing >= 25 %, whole-degree
  readings, room below band with the AC off.
- **sensor_fault** supported = a signature of its fault_kind (stuck/quantised: flat or plateau; noise: noise/step/excursions;
  dropout: zeros/missing/steps; bias/drift: E9 shift/drift, impossible, below band with AC off; saturation: ceiling/plateau)
  beyond the normal p97.5, or any strong signature (absolute or > p99).
- **warning / critical** supported = E2/E3 beyond the LIMITS line (critical needs the critical limit); TANK high level; rate-rule
  metrics (power kW, flow, level): a visible change (range/mean >= 0.35, E9 >= 4x, E10 >= 5x, long plateau); HVAC: out of band
  >= 30 min, short cycling, AC off while usually on, AC running in a vacant / usually-off room, room beyond 30/34 C.
- **normal** unsupported only when the current value is impossible on the card, above the critical limit, or saturated /
  missing / quantised. Single zero or impossible *glitches* stay normal (v3 rule: one glitch = dq suspect, status by process).
- Control on the pool itself (`pool_audit.jsonl`): 492/554 faults, 1,707/1,765 normals, 640/681 warnings, 281/281 criticals pass.

## Results (`audit.jsonl`, `summary.json`, `summary_numbers.json`)
| file | real-agent rows | unsupported | sensor_fault unsup. / all | normal unsup. | warning unsup. | windows behind the unsupported rows |
|---|---|---|---|---|---|---|
| r3 train (`incidents_train.jsonl`) | 8,681 | **450** | **217 / 1,577** | 188 | 45 | 41 |
| test_r2 | 187 | 14 | 9 / 48 | 0 | 5 | 4 |
| rwh | 38 | 2 | 2 / 11 | 0 | 0 | 1 |
| rwh2 | 44 | 2 | 2 / 7 | 0 | 0 | 2 |
| dev (round 1) | 102 | 6 | 3 / 18 | 1 | 2 | 6 |
| dev_r3 / dev60 | 20 / 20 | 1 / 1 | 0 | 0 | 1 | 1 |
| r1 train | 1,769 | 95 | 37 / 302 | 40 | 18 | 48 |
| r4 replay (never trained) | 1,854 | 86 | 45 / 329 | 31 | 10 | 36 |

r3 train, unsupported faults by sensor/kind: water flow quantised 45, HVAC drift 38, AQ RH stuck 34, flow noise 26, power kW
stuck 24, PM2.5 noise 18, tank level stuck 14, HVAC bias 7, PM2.5 stuck 6, flow stuck 5. In 197 of the 217 the real agent also
said `sensor_fault` (so r3 learnt "agent says fault -> fault" without evidence); in 20 it said warning.
The 188 `normal` rows: indoor CO2 currently below the v3 card bound 350 ppm (145 of them below 300 ppm, the r3 system-prompt
bound). Under the v3 trust rule these are data faults ("drift below outdoor CO2").

Criticals: 0 unsupported anywhere.

### The 13 "AQ faulty sensor called normal" rows of the holes study
| window (pool id) | fault_kind | rows | evidence | verdict |
|---|---|---|---|---|
| test-air_quality-00176, AQ-AN00-00 PM10 | noise | 9 (rwh 2, test_r2 7) | last 64.6, noise 3.54, flat 2, E9 none, E10 none: all inside normal PM10 | **unsupported**: r3 "normal" is correct |
| test-air_quality-00141, AQ-AN00-00 PM10 | dropout | 2 | drops to 0.0 and back (+E5 0.94 x mean), E10 7.3x | supported (real miss) |
| test-air_quality-00506, AQ-AN00-00 PM10 | noise | 2 | E10 excursion 9.9x, noise 7.2 > p97.5 | supported (real miss) |

## Exclusion / relabel list (`exclusions.jsonl`, 657 rows: id, file, pool_id, gold, action, new_gold, reason)
| action | rows | rule |
|---|---|---|
| `relabel` -> normal | 12 | gold sensor_fault not visible and the agent said normal (the agent was right) |
| `drop_r3_replay__relabel_v4` -> sensor_fault | 260 | gold normal, current value impossible on the v3 card: dropped from r3-format replay; in v4 renders the card makes it a data fault |
| `drop` | 385 | gold not visible and the agent claim cannot be judged from the prompt (agent said fault / warning) |

**Rule for all new data (rsn v3 fine-tune):** a gold fault or severity must be visible in the prompt's evidence lines or card.
Otherwise relabel to what the evidence supports, set `needs_more_data`, or drop. The new builders enforce it in `verify`.

## r3-2800 re-scored on the cleaned golds (same outputs, `eval/results/rsn_v3_4b_r3`)
| suite | severity ok, original gold | severity ok, cleaned gold (dropped rows) |
|---|---|---|
| test_r2 real-agent | 176 / 187 (94.1 %) | 176 / 180 (97.8 %) (7 dropped) |
| rwh | 35 / 38 | 37 / 38 |
| rwh2 | 44 / 44 | 42 / 42 (2 dropped) |
| dev | 42 / 46 | 40 / 44 (2 dropped) |

## Files
`scripts/audit.py` (rules), `scripts/summarize.py`, `scripts/holes_x.py` (holes cross-check), `thresholds.json`,
`audit.jsonl` (12,715 rows), `pool_audit.jsonl` (3,281 pool windows), `exclusions.jsonl`, `summary.json`, `summary_numbers.json`.
Limits of the audit: the rules are heuristics over the rendered E-lines (no raw series), so a borderline window can go either
way; the percentile control says about 11 % of pool faults are invisible by these rules, which is the right order for weakly
injected faults.
