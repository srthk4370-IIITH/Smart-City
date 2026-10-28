# 3g / v2.1 (track A): continued SFT from v2

## Data
- Training file: `~/smartcity_runs/agents_v21/data/train_v21.jsonl`, 9,922 rows, 50.4% v2 replay. Manifest: `train_v21.manifest.json`.
- Scripts are in `Code/smart-city-edge-agent/training/v2/topup3f/`:
  - `gen_v21.py`: new train-month rows, same generator and teacher, new seeds;
  - `build_v21.py`: assembly, consistency filters and de-duplication;
  - `master_v21.sh`: training plus the checkpoint screen.
- Every row is SFT on teacher gold. The prompt is de-duplicated against dev3f, the 1,148-row test and rw5 dev/test.

### Sources

| source | rows |
|---|---|
| v2 train replay (sft_v2/train.jsonl, all families incl. HVAC/occupancy) | 5,000 |
| 3e pool, weakness-prioritised (power status, erratic, water cause, compound > exp/stages > calm/routine) | 1,500 |
| v21_weak (new seed: stages, status, erratic, water causes, compound, exp, calm, faults) | 1,300 |
| v21_aug: unseen-sensor augmentation | 800 |
| REALWORLD §5 rows: rw5_train 512 + v21_rw5 510 (glitch, chatter, gaps, recovery, holiday, CO2 floor, daily cycle, HVAC, acidic/low pH) | 1,022 |
| 3e realworld_train | 300 |

How v21_aug is built:
- Each seen-sensor history is rescaled, a ∈ [0.6, 1.7] on a log-uniform draw, and offset by ±10% of its median.
- This happens before the event is injected and before the teacher labels the row, so the label follows the new values.
- A row is kept only if it stays inside the metric's physical lo..hi.
- pf, pH and rh are not augmented.
- Unit changes are not done, because they would need new prompt text, which amounts to a new label rule.

### Consistency rules (rows dropped, never relabelled)
- **C1 invisible_event:** an event-labelled row whose post-onset amplitude is below 3 noise units (diag_data visibility). It addresses the event/stable confusion.
- **C2 short_flatline:** a flatline label whose post-onset flat run is shorter than 6 readings.
- **C3 flat_gradual:** a gradual label whose post-onset part is a flat run of at least 80% of d.
- **C4:** the 3e generator flagged the row learnable=false (the same visibility rule).

Drop counts:

| source | C1 | C3 | C4 |
|---|---|---|---|
| v2 replay | 1,403 of 35,946 | 8 | – |
| pool3e | – | 7 | 762 |
| v21_weak | – | 1 | 213 |
| v21_aug | – | – | 147 |
| rw5_train | 5 | – | – |
| v21_rw5 | 6 | – | – |
| rw3e | – | – | 32 |

## Training
- `train_3e.py` (SFT rows only) from `agents_v2/adapter` (r = 32).
- 1 epoch, LR 8e-6 cosine, 5% warm-up, grad-accum 16, a checkpoint every 100 steps.
- Output: `~/smartcity_runs/agents_v21/run1`.

## Selection
- Each checkpoint is converted to a GGUF LoRA and screened on dev3f and rw5dev with the LoRA-scaling method (fidelity in `../2026-10-23_v2t3f/RESULTS_TABLES.md`, section 3f-L).
- The winner gets the merged Q4_0 build and is then confirmed on the 1,148-row test and rw5test.

## Results: checkpoint screen (LoRA-scaling, rules on, vs v2 + rules)
- Training finished at 621/621 (2026-10-25 00:55 UTC). The run was interrupted twice by Claude Code's background-shell memory reaper and resumed from checkpoint-200.
- The "learning_rate 0.0" in train.log is a logging bug in the metrics line. The real schedule is in stats.jsonl and trainer_state: cosine, 6.49e-6 at step 200.

dev3f (2,010 rows):

| ckpt | ALL p | ALL s | 1.5 h s | compound s | notes |
|---|---|---|---|---|---|
| 621 | 83.9→85.7 | 86.7→88.3 | 85.9→89.7 | 86.6→80.4 (0/6) | – |
| 500 | 83.9→85.8 | 86.7→88.4 | 85.9→89.7 | 86.6→80.4 (0/6) | 3 h p 84.3 |
| 400 | 83.9→85.8 | 86.7→88.3 | 85.9→89.4 | 86.6→81.4 (0/5) | – |

Weakness slices for ckpt 500 on dev, with rules on:

| slice | pattern | status | cause |
|---|---|---|---|
| water_cause | 51.9→92.6 | 48.1→88.9 | – |
| unseen_sepoct | 74.2→81.2 | 74.2→80.3 | – |
| seen_unseen | 80.2→81.6 | 83.8→85.2 | – |
| erratic (n=26) | 42.3→53.8 | 46.2→53.8 | – |
| role_power | 74.8→77.7 | 81.4→84.3 | 72.8→77.0 |
| role_water | 79.9→83.7 | 80.1→83.7 | – |

- **Regression:** compound rows read gradual_decrease as flatline/sensor_fault, or escalate gradual/step to critical. That is −5 to −6 pts on compound (n=97), which the rules don't fix.
- **rw5dev (313):** ALL p 79.6→81.2, s 90.4→91.1. Without rules, v2.1 lifts §5 a lot: status 62.0→67.7, glitch 40→67, acidic 0→33, co2_floor 40→50. With rules on, these are mostly already covered, and a few slices are down 1 row each.
- **Mix screen (dev subset of 558 rows: compound, water cause, erratic, sepoct, 1.5 h):**
  - v2·0.3 + v21_500·0.7: compound p 86.6→86.6, s 87.6→85.6 (1/3), and it keeps most of the gains (ALL p 78.0→81.4);
  - v2·0.5 + v21·0.5 was not finished (the GPU went to reasoner training).
- **Owner decision (2026-10-25 12:15):** skip the screen. The FINAL checkpoint (621) is merged to Q4_0 (v2 recipe) and judged on the board.
