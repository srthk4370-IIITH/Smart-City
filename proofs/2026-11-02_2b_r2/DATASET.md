# rsn_v3 2B r2 dataset (built 2026-11-02, laptop CPU only, nothing uploaded, no training started)

Why each part exists: see `DIAG.md`. All data is synthetic: the round-1 simulator/generators plus new template generators.
The `real_agent` incident family (28 % of the generator rows, as in r1) is simulator sensor data (sft_v2) with recorded outputs
of our own earlier agent models; it contains no real board sensor data. No RWH, RWH-2, round-1 dev, chat dev v3 or board item
is in training (exact-prompt dedup, below).

## Files (`data/final/`, MD5SUMS there)
| file | rows | what |
|---|---|---|
| `incidents_train.jsonl` | 35,151 | reasoner report rows (thinking off, app system prompt) |
| `chat_train.jsonl` | 20,973 | 20,011 chat rows (adaptive thinking) + 962 general replay rows (r1, base-model answers) |
| `tools_r2.json` | - | `incident` (4 tools), `chat` (15 tools, tools_v4), **`chat9`** (the app's current 9-tool chat header, byte-identical render) |
| `incidents_test_r2.jsonl` | 1,368 | **test**, never trained on (field `slice`) |
| `chat_test_r2.jsonl` | 581 | **test** records for `chat3_eval.py`/`verify_chat` (fields `hinglish`, `chat9_ok`) |
| `dev_mix3.jsonl`, `incidents_dev60.jsonl` | 120 / 60 | loss-only dev slices (same as r1, for the trainer's early stopping) |
Total training tokens (Qwen tokenizer, 800-row samples): incidents ~86 M (mean 2,439), chat ~72 M (mean 3,411) = ~157 M, about
2x r1. At r1's effective ~490 tok/s one epoch is ~3.5-4 days on the 4050 (early stopping on dev usually ends sooner).

Build (all scripts in `tools/`, re-runnable): `make_data.sh` RUN_ID=r2x SEED=47 POOL=70000 TARGET=30000 SKIP_CHAT=1 RWH2=0 ->
`gen_heat_r2.py --mix-into build/r2x/data` -> `gen_incident_extras.sh` (targeted + heat_r2b) -> `run_test_inc.sh` ->
`gen_chat_v3.py --n 14000 --n-dev 700 --seed 404` -> `build_chat_r2.py` -> `run_inc.sh` / `run_inc_gate.sh` (assemble, verify,
Go gate) -> `finalize_r2.sh`.

## Incidents (train 35,151)
| source | rows | notes |
|---|---|---|
| round-1 generator, new seed 47 (`build/r2x`) | 30,000 | 40 families, weak families x3, +tool / +inject x3, 600 borderline rows; compact gold; verify.py 30000/30000 |
| heat_r2 (r1 add-on, seed 2611) | 192 | heatwave vs weather-sensor-fault pairs |
| heat_r2b (new, seed 2711) | 960 | 480 pairs of the same generator; 240 more rows held out as test |
| **targeted r2** (`tools/gen_r2_targeted.py`, seed 5101) | 3,999 | contrastive pairs for the diagnosed board/gate errors (below) |

Targeted classes (train rows): room temperature **fault** (one-sample jump / stuck / spikes while the AC's own room sensor stays
ordinary) 680 vs **real AC failure** (AC units drop to 0, both room sensors climb) 680; pH **single bad reading** 690 (sensor_fault,
check_sensor first) vs **held** excursion beyond the limit 689 (critical/warning, inspect_water_system first, manual test last);
CO2 **real rise with people** 630 (critical / warning / *normal below 1000 ppm*) vs **bias step in an empty room** 630. The domain
agent is wrong in 1,832 of them (46 %) and the gold corrects it in agent_checks. 1,437 are refinements (`refine-1.5h` / `refine-3h`)
with app-style RE-CHECK lines `HH:MM <severity>: <earlier title>`; in about half the earlier revision is wrong and the gold
re-judges on the current evidence. Building codes vary over 18 codes, floors 0-6, sensor numbers 1-9.

Class balance (all incident train rows): severity critical 6,584 / warning 11,610 / normal 9,407 / sensor_fault 7,550; labels:
normal_operation 6,965, sensor_fault 7,550, occupancy_driven_load 4,665, unknown 2,859, water_quality_issue 2,382,
hvac_or_thermal_issue 2,097, water_supply_issue 1,561, air_pollution_event 1,549, power_quality_issue 1,526, weather_driven 1,354,
power_load_anomaly 1,218, water_leak_or_overuse 1,095, ventilation_issue 330. Flagged roles: air_quality 15,562, water 9,405,
power 7,525, hvac 2,232, weather 2,021, occupancy 1,336. Modes: early 32,954, **refine-1.5h 1,462, refine-3h 735** (r1: 431 / 0).
Outdoor CONTEXT line 3,041 (r1 633). Tool turns 4,255.

Checks on every incident row (train and test): round-1 `verify.py check_incident` (schema, enums, grounded numbers/times/ids,
units, direction words, severity floors) and the **app's own Go validator** `checkReportV3For` (+ weatherOnlyIncident, with tool
turns in the known text; `tools/r2_gate_test.go` on a copy of app/backend): train 35,151/35,151, test 1,368/1,368 pass.

## Chat (train 20,011 + 962 replay)
| source | rows |
|---|---|
| r1 rows (teacher-distilled 1,326, reference 6,593, template 630; verified in r1) | 8,549 |
| new questions (gen_chat_v3 seed 404, train phrasings only): hard -> gold calls + reference answer + short plan think (verified); easy -> gold calls + reference answer with an **empty** think (verified) | 11,462 |
| ... of which Hinglish / code-switched rewrites of the question (same gold, re-verified), e.g. "was temperature at SR-AQ-VN02-01 better kal than today jaldi", "kitne saare wind incidents were there since midnight na" | 1,498 |
Header: 3,139 rows use the app's current **9-tool** header (`chat9`, only questions the 9 tools answer), 16,872 the 15-tool header.
Easy 11,110 / hard 8,901; 1 / 2 / 3 user turns: 11,138 / 5,760 / 3,113 (follow-ups up to 2 earlier exchanges, as `chat.go`).
54 question kinds incl. refusals (`refuse_close`, `actuation`, `refuse_personal`, `offtopic`), prompt-injection questions
(`injected`), unanswerable / offline-docs / old-data cases, typos and casual prefixes/suffixes. Every tool call has schema-valid
args (verify_chat executes them on the training store). Questions that occur in chat dev v3 (the gate set) are excluded.
With the trainer fix, the first labelled token of every easy row is `\n` then `</think>` (checked on 408 sampled easy rows).

## Test set r2 (separate, built before any training)
Incidents `incidents_test_r2.jsonl` (1,368):
| slice | rows | severity c / w / n / f |
|---|---|---|
| `gen_heldout`: round-1 generator on the HELD-OUT split (held-out nodes and real-agent rows, like RWH), seed 6161, 37 families equally weighted | 640 | 85 / 199 / 224 / 132 |
| `targeted`: the app-story classes (room-temp fault vs AC failure, pH single vs held, CO2 real vs bias vs drift, refinements), seed 5202 | 280 | 86 / 42 / 12 / 140 |
| `targeted_novel_names`: same, building codes never seen in training (QX, ZR, EL, WD, FY, UV) | 160 | 45 / 27 / 8 / 80 |
| `heat`: heatwave vs weather-sensor-fault (heat_r2b dev 240 + heat_r2 dev 48), split by pair | 288 | 96 / 48 / 0 / 144 |
Chat `chat_test_r2.jsonl` (581): held-out question phrasings only (blind style: the last 2 templates of every kind, never used in
training), 54 kinds, 223 hard, 85 rewritten to Hinglish, 302 answerable with the 9-tool header (`chat9_ok`). 119 candidates were
dropped for overlapping chat dev v3 or training.
RWH (150), RWH-2 (150), round-1 dev (120) and chat dev v3 (300) stay the gate sets: 0 of their prompts are in training (exact
user-prompt dedup; for chat the whole user side of the session and the last question, normalised).

## Trainer change (needed for this data; no run started)
`kaggle/train_rsn3.py`: segment tokenization at prompt/target boundaries (env `RSN3_SEG_TOKENIZE`, default 1; cache files get
a `_seg` suffix). Incident rows tokenize identically (50/50 checked); backup of the r1 version: `tools/train_rsn3.r1_backup.py`.

## Before training (not done, waiting for the owner)
- `laptop_train.sh` hard-codes `--tools tools_v4.json`: point it at `data/final/tools_r2.json` (the `chat9` rows need it).
- `laptop_chain.sh`: step markers in `kaggle/chain/` are not per run (r1's train_2b/export_2b are marked done) and the export is
  skipped when `models_stage/rsn_v3_2b_q4_0.gguf` exists (r1's file): give r2 its own markers and GGUF name before starting.
  `train_ctl.sh` still points at `rsn3_2b_r1`. The r1 chain watch was stopped (kaggle/chain/STOP set; no trainer running).
- Gate additions: run `chat3_eval.py` on `chat_test_r2.jsonl` also with the 9-tool header (`chat9_ok` rows), and score
  `incidents_test_r2.jsonl` per slice.
- Recommended app change (not made): send the 15-tool chat header when `chat_think=adaptive`.

## Known limits
- Chat device time is fixed at 2026-10-22 12:00 (the tool store is built around it); time words are covered, other dates are not.
- Hinglish is a rule-based code-switch of English templates (word swaps + fillers), not native Hindi sentences.
- The base incident generator uses the campus building set; name variety comes from the targeted rows (18 codes) and is
  measured on the `targeted_novel_names` test slice.
