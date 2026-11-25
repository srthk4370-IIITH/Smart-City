# NEW model failures: chat_en (39 rows, 15 fail) and tool_chain (20 rows, 12 fail)
Scored with gate_score_big.score_chat (exec'd unmodified). Note argeq checks only id/node/metric/domain/severity/link/direction/analysis + time preset; window_min and limit are NOT checked.

## Causes
| cause | chat_en | tool_chain | example ids (suffix) |
|---|---|---|---|
| node arg drops word "building" (KH vs "KH building"); checker strict (gold uses display name) | 5 | 0 | pus_chat-00152,-00109,-00133,-00066,-00193 |
| node arg truncated: "air sensor 03" vs gold "room of air sensor 03" (2 of 4 also too long: dumps site list) | 4 | 0 | pus_chat-00166,-00017,-00008,-00092 |
| wrong tool: history instead of current_levels(metric,location) for "any problem with sensor" | 2 | 0 | t_status-00000,-00001 |
| wrong tool: list_sensors / fog_search_history / search_knowledge / faulty_sensors instead of gold | 2 | 2 | n_sensor-00001, nd_empty-00000; forecast-00001, vs_empty-00002 |
| extra calls (nocall row got incident tools; one_word row extra get_incident; cooccur extra linked_equipment / duplicate co_occurring) | 2 | 2 | G-nocall-00001, one_word-00000; cooccur-00000,-00002 |
| chain missing 2nd call (no get_incident / no occ history of gateway sensor / no linked_equipment) | 0 | 3 | find_get-00000, vs_empty-00001, k_linked-00002 |
| empty final answer after chain (nonempty=0) | 0 | 3 | find_get-00000, k_linked-00000,-00001 |
| wrong arg in chain call: linked_equipment node/direction (SR-AQ-KH03-03 out vs KH-03-AQ03 in), metric vs domain filter, wrong metric (pm25 vs co2) | 0 | 4 | k_linked-00001, p_domain-00000, find_get-00000, vs_empty-00000 |
| co_occurring_incidents missing window_min=120 (not scored, but trained gold has it) | 0 | 1 | cooccur-00002 |
| checker issue: grounded fails on reasonable not-found answer | 0 | 1 | get_missing-00000 |

## Regressions vs p2
- p2 ok, new fail: nd_empty-00000 (p2 used find_incidents; new used fog_search_history, no limit)
- new ok, p2 fail: pus_chat-00102, pus_chat-00088, t_status-00002, shorter-00002, n_sensor-00000, find_get-00002, cooccur-00001, get_missing-00001

## Per-row (new fails)
| id | slice/sub | question | failed | gold | model |
|---|---|---|---|---|---|
| pus_chat-00152 | chat site_old | Why is KH building amber? | args | site_status{node:"KH building"} | site_status{node:"KH"} |
| pus_chat-00109 | site_old | How many occupancy sensors in KN building? | args | nodes_under{KN building,sensor,occ} | node:"KN" |
| pus_chat-00133 | site_old | Why is VN building amber? | args | site_status{VN building} | VN |
| pus_chat-00066 | site_old | count the CO2 sensors in KN building | args | nodes_under{KN building,co2} | KN |
| pus_chat-00193 | site_old | Status of VN building? | args | site_status{VN building} | VN |
| pus_chat-00166 | site_old | List the sensors in room of air sensor 03. | args | get_site_tree{"room of air sensor 03",depth1} | node:"air sensor 03" |
| pus_chat-00017 | site_old | What sensors are in room of air sensor 03? | args | same | air sensor 03 |
| pus_chat-00008 | site_old | same | args,short | same | air sensor 03; answer lists all buildings |
| pus_chat-00092 | site_old | same | args,short | same | air sensor 03; long list |
| t_status-00000 | short_status | CO2 at KH03: any problem with the sensor? | calls,args | current_levels{co2,KH03} | get_sensor_history{SR-AQ-KH03-01,co2,last_24h} |
| t_status-00001 | short_status | PM2.5 at KH03: any problem? | calls,args | current_levels{pm25,KH03} | get_sensor_history{pm25,last_24h} |
| G-nocall-00001 | nocall | hello, which location should I check first? | calls,args | (no call) | open_incidents{air_quality}; get_incident{INC-0084} |
| one_word-00000 | fmt_one_word | one word each: the incidents to handle first | calls,args,fmt | open_incidents{} | open_incidents + get_incident{INC-0084}; sentence answer |
| n_sensor-00001 | unknown_sensor | Any temperature data for QQ45? | calls,args | current_levels{temp,QQ45} | list_sensors{QQ45} (answer fine) |
| nd_empty-00000 | find_empty | Sensor fault occupancy incidents today? | calls,args | find_incidents{today,occupancy,[sensor_fault],limit3} | fog_search_history{same filters} |
| find_get-00000 | tool_chain find_get | Story of the latest power incident in VN | nonempty,calls,args | find_incidents{last_30d,limit3,domain power,node VN}; get_incident{INC-0747} | nodes_under; recent_incidents; find_incidents{metric power_kw}; no final |
| vs_empty-00000 | faulty_vs_empty | Faulty meter or empty room SR-AQ-KH03-03 | args,extra | hist co2 30d; hist SR-OC-GW-KH95-01 occ 30d | hist pm25 24h; hist co2 24h |
| vs_empty-00001 | faulty_vs_empty | broken or vacant SR-AQ-KH03-01? | calls,args,extra | hist co2 24h; hist occ gateway | only co2 hist |
| vs_empty-00002 | faulty_vs_empty | Faulty meter or empty room SR-AQ-KH03-01? | calls,args,extra | hist co2 7d; hist occ 7d | faulty_sensors{30d} |
| k_linked-00000 | rank_linked | Hottest room 24h, then check its AC | nonempty,calls,args | rank_readings{temp,air_quality,last_24h,1}; linked_equipment{KH-03-AQ03,serves,in} | rank_readings; current_levels x2; no final |
| k_linked-00001 | rank_linked | Most humid room in KH 24h, check AC | nonempty,args | rank_readings; linked_equipment{KH-03-AQ03,in} | rank_readings ok; linked_equipment{SR-AQ-KH03-03,out}; no final |
| k_linked-00002 | rank_linked | AC ok in most humid room in KH today? | nonempty,calls,args | rank_readings; linked_equipment | rank_readings only; no final |
| cooccur-00000 | cooccur | Did AC or power trip cause INC-0741? | calls,args,extra | get_incident; co_occurring{window120} | + linked_equipment{SR-EM-VN01-02} |
| cooccur-00002 | cooccur | Linked incidents for INC-0746? cause? | calls,args,extra | get_incident; co_occurring{INC-0746,120} | get_incident; co_occ(no window); co_occ{INC-0744} x2 |
| forecast-00001 | forecast | Estimate time temp at SR-AQ-VN02-01 hits 30 | calls,args | get_sensor_history{temp,last_24h} | search_knowledge{"temperature trend forecast"} |
| get_missing-00000 | get_missing | Cause of INC-5038? | grounded | get_incident{INC-5038} | get_incident ok; answer reasonable (checker issue) |
| p_domain-00000 | followup_domain | ok and power? | args | count_incidents{last_7d,domain power} | count_incidents{metric power_kw} (domain arg missing; follow-up context partly kept) |
