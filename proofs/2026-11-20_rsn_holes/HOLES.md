# Reasoner holes (rsn_v3_4b_p2 Q4_0, host CUDA, think=adaptive, greedy), 2026-11-20
Raw: res/p2/*.jsonl (harness, subsets in sub/), res/probe.jsonl (20 hand-written chat Qs + 6 follow-ups, stub tool results in probe.py), bad.json (failures), score.py. Subsets are small (seeded), English only; real_agent/fog/dev_p2/unseen_metric only 10 rows each (time box).
Speed: ~48 tok/s decode on laptop GPU; chat replay 2.3-2.8 s mean (p90 3.3); reports 8-13 s mean (p90 11-17); probe first turns 25-34 s when it thinks long, later 1-6 s.

## Scores (my scorer; no official scorer for chat)
| set | n | result |
|---|---|---|
| test_campus_chat | 40 | tool sequence == gold 34/40 (85%); hallucinated number/INC id 0; >3 sentences 0; no-call-when-needed 0 |
| dev_chat | 30 | tool sequence == gold 28/30 (93%); hallucinated 0 |
| test_campus_inc (reports) | 30 | JSON valid 100%, severity == gold 24/30 (80%); wrong sensor_fault 1 |
| dev_inc | 23 | severity 17/23 (74%) |
| test_real_agent | 10 | severity 8/10 |
| test_unseen_metric | 10 | severity 8/10 |
| dev_p2 (new families) | 10 | severity 5/10 (my quick check) |
| test_fog (chat on fog results) | 10 | 3/10 EMPTY final answer; 0 non-empty unparsed-by-me ones judged only by eye |

## Ranked holes
| # | hole | freq | example | training data to fix |
|---|---|---|---|---|
| 1 | Severity under-/over-call in reports, esp. normal vs warning and critical vs warning, sensor_fault vs warning | 20-26% wrong on inc sets (6/30, 6/23), 5/10 p2 | dev_inc-00074 gold normal, said warning "Occupancy load, 2 rooms"; test_campus_inc-00194 gold warning, said critical (pump dry-run); test_campus_inc-00290 gold sensor_fault, said warning | contrastive pairs per family: same title pattern, 3 severities, with the deciding second-evidence line; hard-negative "benign expected pattern" (occupancy load, rain-filled tank, maintenance) = normal |
| 2 | EMPTY final answer after tool result (fog/co-occurrence results; also probe follow-up "same for KH01?") | 3/10 fog, 1/26 probe | chat-test-r4-x-00078 final ""; probe "is that the same for KH01?" -> what_if call then empty | multi-turn fog/analytics rows where the final is always a 1-3 sentence quote; include empty/long result payloads |
| 3 | Wrong args / invented ids in tool calls | 3/26 probe | "power spike in BLK2" -> get_incident INC-0740 (id not in question or any result), should find_incidents(node BLK2) first; "forecast CO2 crosses 1000" -> what_if driver occ +100% (made-up change) | two-hop rows: find_incidents/recent_incidents -> get_incident with id taken from the result; forbid ids not seen; forecast phrased questions -> what_if/trend with current-trend args |
| 4 | Faulty-meter vs empty-room: no occupancy cross-check, and misread trend | 1/1 probe | KH03 CO2 "is falling" while data 1200,1980,1890; used only get_sensor_history | chat rows "is sensor X faulty or is room empty" -> history + occupancy/co_occurring call then evidence-based verdict (both ways) |
| 5 | Result misquoted or wrong metric: answers a different metric from the tool | 2/26 probe | "which room is hottest?" -> rank_readings metric room_temp (not in enum) and then wrote CO2 values 2150/1480 as temperature; no AC follow-up (needs rank + linked_equipment) | rows where result metric != asked metric must say so; 2-call chain hottest room -> AC serves |
| 6 | Not following requested format/length | 3/26 probe | "list open incidents, one word each" -> full titles; "2 line summary for the manager" -> one-line list of incidents; "make that shorter, 8 words" -> 12 words | format-instruction SFT: bullets, N words, N lines, manager summary, "in exactly one sentence" across tools/no-tools |
| 7 | Follow-up/context bleed and unknown-entity lookups | 3/26 probe; 6/40 campus_chat call mismatches are unknown ZZ-nnn room -> get_site_tree instead of site_status | "and what about the water one?" -> answered air-quality INC-1042 (ignored water filter result); "status of sensor ZZ99-temp" -> site_status then "KH03 is critical" (unrelated node, no 'no such sensor'); dev_chat-00041 | rows with not-found tool results must say not found and not substitute; follow-ups referring to previous answer with a different filter; also dev_chat-00025 AC-serving loops linked_equipment x3 |
| 8 | Canned refusal misfire after a valid tool result | 1/26 probe | "is PM2.5 in KH01 working?" -> get_sensor_history then "The device can't tell that: it stores sensor readings..." | rows where a tool result has data and the answer is a short status; keep refusals only for no-tool-possible questions |
| 9 | Causal story invented beyond evidence | 1/26 probe | BLK2 spike answer says AC tripping caused the power spike (result only listed co-occurring INC-1043 on KH03) | "co-occurs != causes" hedge rows; require cause text from tool field |
| 10 | Units/term slips; injection answer mushy | minor | "2150 µmol/mol" instead of ppm; "ignore previous rules" -> "That contradicts what the device sees" | unit-faithful quoting; crisp injection refusal |
Checked and OK (not holes in this sample): no sensor_fault on flat/step in 1/30 test_campus_inc (1 wrong); no "data gaps / no judgement" titles (0 matches); 0 hallucinated numbers or INC ids in 70 chat replays; out-of-scope (cricket) and read-only (switch off AC) refusals correct; severity JSON validity 100%; late-batched-critical and severity-drop cases not isolated by this sample (needs targeted set).

## Tool use
Chat replays (70 rows, test_campus_chat+dev_chat): needed-but-missing call 0/70; unneeded call when gold has none 0/70; exact tool sequence 62/70 (89%): 8 mismatches = 7 wrong-tool (unknown room ZZ-nnn: get_site_tree vs site_status, 6 of them) + 1 loop (linked_equipment x3 instead of linked_equipment+site_status = chain-of-2 failure). Numbers/ids misquoted vs results: 0/70.
Reports (test_campus_inc 30): tool calls only 2 total (reports mostly decide from prompt; fine, but second-evidence lookups are rare, relevant to hole 1).
Probe (26, stub results): missing call 0; unneeded call 0 (no-tool for follow-up "shorter" is correct); wrong tool/args 4 (forecast what_if misuse, room_temp metric, INC-0740 invented id, site_status for sensor); needed second call missed 3 (faulty-vs-empty occupancy check, hottest room -> AC, forecast without trend); result ignored/misquoted 3 (hottest = CO2 numbers, "water one" answered air-quality, ZZ99 -> KH03 critical); empty after tool 1. Note probe tool results are my stubs (some artefacts: count_incidents ignoring severity).
Fix data: 2-call chain rows (rank->AC, sensor->occupancy, find->get_incident), not-found tool results, args validated against enums (metric, preset), final always quotes the result.
