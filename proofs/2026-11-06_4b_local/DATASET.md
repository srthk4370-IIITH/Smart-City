# Dataset r3 for the rsn_v3 4B local QLoRA (built 2026-11-06, laptop CPU only, nothing uploaded, no training started)

Purpose: give the chat model the fog tools with a device fallback, three cross-domain tools, and a prompt that matches
what the app sends, while keeping every r2 row. Tools: `TOOLS.md`. All data is synthetic: the r2 sources plus new
template generators on a longer synthetic store. It contains no board data.

## Files (`data/final/`, MD5SUMS there)
| file | rows | what |
|---|---|---|
| `chat_train_r3.jsonl` | 33,597 | chat training rows, adaptive thinking, `tools:"chat"` = tools_r3 (21 tools), plus 962 replay rows (`tools:"none"`) |
| `incidents_train.jsonl` | 35,151 | r2 reasoner rows, unchanged (`tools:"incident"` is identical in tools_r3.json) |
| `tools_r3.json` | - | `incident` (4) and `chat` (21) |
| `chat_test_r3.jsonl` | 983 | **test records, never trained on**. Held-out phrasings, both fog states. Fields `fog`, `last_sync`, `since`, `hinglish`, gold calls/facts, reference answer |
| `gen_chat_r3.jsonl`, `gen_train_chat_r3.jsonl` | 60 / 20 | trainer generation-eval records (`tools/make_gen_r3.py`): 60 fresh (40 new kinds, 20 device kinds; online 28, offline 26, timeout 6; 8 Hinglish; not in train/test/dev) and 20 whose rows are in training. Scored by `train_rsn3.py --gen-chat/--gen-train-chat` with `--gen-r3 auto` (r3 store, fog state per record); self-test: gold 80/80 pass, corrupted 0/80, r2 path unchanged 40/40 (`gen_r3_selftest.json`) |
| `dev_r3.jsonl` | 240 | loss-only early-stopping slice: r2 dev_mix3 (chat rows re-rendered) + 120 new rows removed from training |
| `incidents_test_r2.jsonl`, `incidents_dev60.jsonl`, `chat_test_r2.jsonl` | 1,368 / 60 / 581 | r2 test and dev sets, copied unchanged |
| `build_manifest.json`, `tokens_r3.json`, `schema_check.json` | - | counts, verify statistics, tokens per epoch, schema check |
| `data/store/` | - | `fog_store_r3.sqlite`, `device_store_r3.sqlite`, `store_r3_manifest.json` (the tool store the rows were executed on) |

Build (all in `tools/`, re-runnable, about 25 min on CPU):
1. `run_r3.sh`: make_store_r3 -> make_tools_r3 -> parity_r3 -> gen_chat_r3 (`--n-new 9000 --n-old 4800 --n-test 1100 --seed 1106`) -> build_r3.
2. `run_build_only.sh`: build_r3 -> check_schema_r3 -> finalize_r3 (tokens + MD5SUMS).
3. `render_header_r3.py`: the header, rendered with the HF template in `~/venvs/rsn`.

## Training store r3 (`make_store_r3.py`, seed 20261106)
- The rsn_v3 store (748 incidents, 2026-01-01 .. 2026-10-22) gets 2,230 incidents cloned from its closed incidents,
  spread over 2025-11-01 .. 2026-10-19. Clones keep the same sensors, titles, causes, steps, events and maintenance,
  shifted in time. Labels are weighted by season: winter PM, summer heat/AC/power, monsoon water. IDs are renumbered by
  time.
- Result: **2,978 incidents**. Per month 230 / 230 / 251 / 251 / 265 / 305 / 288 / 193 / 221 / 240 / 220 / 284 from
  2025-11 to 2026-10.
- **Device view:** the newest 1,000 in full, **since 2026-06-24**. The other 1,978 are index rows only: no root cause,
  notes, close time, steps, events or context sensors. Readings: 60 days hourly and 3 days of 5-min.
- **Fog view:** everything, plus daily sensor rollups 2025-11-01 .. now (11,392 rows). Days with hourly data are
  rolled up from it; earlier days use a seasonal synthesis with Hyderabad monthly normals.
- Knowledge base `tools/knowledge_r3.json`: 46 passages, of which 16 are cached on the device.
  - Real standards: IS 10500:2012 pH 6.5-8.5, TDS 500/2000 mg/L, turbidity, hardness; NAAQS PM2.5 60/40 and PM10
    100/60; WHO 2021; CPCB AQI bands; IMD heatwave criteria.
  - Campus limits copied from features.go.
  - SOPs, manuals and 2 post-event reports, written for the campus (synthetic).

## Chat rows
| source | rows | notes |
|---|---|---|
| r2 rows, re-rendered | 19,051 | `tools:"chat"` (21-tool header for every row, the old 9-tool `chat9` rows included). The system is the r3 rules plus the offline fog sentence (last sync random, or never 15 %) and "full records since 2026-01-01", which is their world. Tool results unchanged (verified in r2) |
| r2 rows dropped | 960 | 959 of the kinds the r3 tools replace: offline_docs 71, fog_knowledge 66, old_data 99, history_old 245, compare_periods 478, and any search_knowledge call. These taught "can't, the fog is offline" or two count calls. Plus 1 with a schema-invalid `what_if.domain` |
| replay (r1 general) | 962 | unchanged |
| **new, fog and cross-domain kinds** | 8,835 | 20 kinds below; 995 rewritten to Hinglish/code-switched and re-verified |
| **new, rsn_v3 kinds re-run on the r3 store** | 4,749 | 50 device kinds, both fog states. The right move is a device tool, not the fog |

New rows: **13,584**. Fog state of all new rows: online 6,286, offline
6,420, timeout 878 (the prompt says online and the fog call times out mid-conversation). For the 20 new kinds alone:
online 3,951, offline 4,006, timeout 878.

New kinds (train rows, Hinglish included):

| kind | rows | what |
|---|---|---|
| fog_find_old | 848 | incidents of a month before the window, optional filter |
| fog_text | 573 | text search over all history |
| fog_old_detail | 620 | get_incident for an archived id |
| fog_trend | 566 | incident_trend |
| fog_resolve | 423 | resolve_time |
| fog_sensor_monthly | 627 | monthly sensor stats and seasonal comparison |
| knowledge | 320 | search_knowledge. Online: answer only when the top passage is the right one. Offline: cache hit, or "can't look it up" without using unrelated cached passages |
| fog_status | 157 | link, sync, pending, store |
| old_count | 505 | **count_incidents, not the fog**: the device index is exact |
| recent_vs_fog | 365 | **find_incidents, not the fog**, for recent periods |
| cooccur | 625 | co_occurring_incidents |
| recurring | 570 | recurring_issues |
| compare_tool | 657 | compare_periods |
| fu_fog_detail | 375 | multi-turn: old list, then "what caused the first one?" |
| fu_fog_period | 331 | multi-turn: "and in March?" |
| fu_fog_status | 168 | multi-turn: after a fallback answer, "is the fog back?" |
| fu_cooccur | 286 | multi-turn: recent incidents, then "what else happened around the first?" |
| fog_drop | 430 | fog down mid-conversation: earlier answer from the fog, this call times out |
| refuse_fog | 66 | sync/upload/delete/restart requests; must refuse, no call |
| inject_fog | 323 | prompt injection ("say the data came from the fog", "invent older data") on a fog question |

Answer rules in the rows:
- Every fog answer names its source. Online answers say "From the fog server". A fallback says "The fog server is
  unreachable / stopped responding" and gives the coverage date (`since 2026-06-24`).
- Trend fallbacks say the counts are exact from the index. Text-search fallbacks say older incidents were matched on
  titles only.
- No older data is ever added, and a failed fog call is never repeated: every row has one call per question.

Class balance of all chat rows (training):
- easy 18,061 / hard 14,574.
- User turns 1 / 2 / 3: 18,892 / 9,608 / 4,135.
- Thinking: hard rows get a short numberless plan (the calls, never a result); easy rows get an empty think.

## Checks
- **Every new row** comes from a record whose gold calls were executed on the r3 store in its fog state
  (`tools_r3_impl.ToolsR3`) and passes `verify_chat.verify`:
  - calls parse and are executed;
  - numbers, ids, dates, times and units are grounded in tool results, question, history or system;
  - gold facts are present (counts, ids, and the source/coverage phrase and date for fallbacks);
  - refusals are correct, there is no actuation claim, and the think rules hold.
- **Pass rates:**
  - new fog/cross-domain kinds: 8,955 / 8,955 (100 %); 45 dropped for question overlap;
  - re-run rsn_v3 kinds: 4,749 / 4,800 (98.9 %); 51 `faulty_explain` fail on a "4 hours" sentence, dropped;
  - Hinglish rewrites: 995 kept;
  - test references: 983 / 987 (4 dropped).
- **Schema** (`check_schema_r3.py`, every call in train/dev/test against tools_r3.json; known tool, required args, no
  unknown args, enums, bounds, presets): 34,693 + 179 + 1,932 calls, **0 invalid**. The fog sentence matches the row's
  fog state in 32,635 / 32,635 rows.
- **Go vs Python:** `TestChatFogParity`, 92 calls, identical (TOOLS.md).
- **Dedup** (exact normalised user side of the session and last question): no training row overlaps chat dev v3 (the
  gate), chat_test_r2 or chat_test_r3. Dropped: 45 new rows, 113 test candidates. RWH, RWH-2 and round-1 dev are
  incident sets; incidents_train is r2's, already deduped.

## Test set r3 (`chat_test_r3.jsonl`, 983 records)
- Held-out phrasings only: the last 2 templates of each kind, and the last 8 knowledge questions.
- Composition: 700 new-kind and 283 device-kind records (most of the 113 overlap drops were device-kind). Fog: online 421, offline 493, timeout 69. 116 are Hinglish.
- Every new kind appears in both fog states. Exceptions: fog_drop (timeout only) and fu_fog_status (offline only).
- To score: run each record with `ToolsR3(fog=rec["fog"], last_sync=rec["last_sync"])` as the executor of
  `verify_chat.verify`, and add the r3 defaults from build_r3.py (`VC.DEFAULTS.update`).

## Tokens per epoch (Qwen3.5-4B tokenizer, 800-row samples, `tokens_r3.json`)
| file | rows | mean tokens | epoch |
|---|---|---|---|
| chat | 33,597 | 5,420 | 182.1 M |
| incidents | 35,151 | 2,440 | 85.8 M |
| **total** | | | **267.9 M** (r2: ~157 M) |

The 21-tool header is 4,579 tokens of every chat row; the 15-tool header was about 3,100. At r1's effective ~490 tok/s
for the 2B that is about 6.3 days per epoch. The 4B is slower. Early stopping on dev usually ends sooner. Ways to cut it
are below; the owner decides.

## Known limits
- The device time is fixed at 2026-10-22 12:00 in all rows. The r2 rows live in the rsn_v3 store world (since
  2026-01-01, no archive); the new rows live in the r3 world (since 2026-06-24).
- Fallback semantics differ slightly between training and the board. In training the device has 60 days of hourly
  readings (sensor_monthly fallback); on the board it has 7 days of 5-min readings. The model reads `coverage.from`
  either way.
- Hinglish is the r2 rule-based code-switch, not native Hindi. Knowledge questions have one phrasing per item (40
  train, 8 test), with surface noise on top.
- The fog server itself, its HTTP contract and the sync uploader are not built on the fog side (TOOLS.md "Open").
- Cutting tokens, owner's choice:
  - train on a subset of the 19,051 r2 rows (for example drop half the r1 reference rows);
  - shorten the tool descriptions;
  - pack the header with prefix sharing in the trainer.
