# Chat sweep: deploy27 (4B, NPU) vs deploy30 (2B, CPU)

| set | run | answers | errors/busy | router <1 s | median s | model answers | model mean s | model max s |
|---|---|---|---|---|---|---|---|---|
| s1 | d27 4B | 40 | 0 | 34 | 0.2 | 5 | 9.2 | 9.6 |
| s1 | d30 2B | 40 | 0 | 35 | 0.2 | 5 | 10.9 | 14.3 |
| heldout | d27 4B | 40 | 0 | 35 | 0.2 | 5 | 12.4 | 17.2 |
| heldout | d30 2B | 40 | 0 | 35 | 0.2 | 5 | 8.4 | 11.5 |
| blind | d27 4B | 40 | 0 | 38 | 0.2 | 2 | 10.1 | 10.7 |
| blind | d30 2B | 40 | 0 | 38 | 0.2 | 2 | 13.4 | 18.7 |
| blind2 | d27 4B | 40 | 0 | 35 | 0.2 | 5 | 11.4 | 14.9 |
| blind2 | d30 2B | 40 | 0 | 35 | 0.2 | 5 | 21.4 | 62.9 |

## Questions that reached a model in either run

**[s1] How many sensor faults were there this week?**
- 4B d27 (9.3 s): 0 sensors were confirmed faulty this week.
- 2B d30 (14.3 s, qwen3.5-2b rsn_v3 (cpu)): 12 sensors were flagged as faulty by the AI this week, for example SR-AQ-KH03-03 CO2 bias.

**[s1] When was the CO2 sensor in KH level 3 last replaced?**
- 4B d27 (9.6 s): No sensor replacements are recorded in the device store for this year.
- 2B d30 (11.5 s, qwen3.5-2b rsn_v3 (cpu)): No incidents involved SR-AQ-KH03-03/co2, so I can't help. I searched for incidents at KH03 and found 10, but none involved this sensor.

**[s1] Abhi koi critical alert hai kya?**
- 4B d27 (8.8 s): 0 critical incidents last 24h.
- 2B d30 (9.2 s, qwen3.5-2b rsn_v3 (cpu)): 48 incidents wait for an operator decision: water 1 critical, air quality 34 critical, hvac 8 warning, weather 5 warning. The latest pending is INC-0660 (critical, water).

**[s1] shw me critcal alrts**
- 4B d27 (9.4 s): No critical incidents today.
- 2B d30 (13.4 s, qwen3.5-2b rsn_v3 (cpu)): Latest critical incidents: [INC-0564] Temperature critical: VN building, level 04, rooftop weather station; [INC-0545] PM2.5 199.8 ug/m3, critical: KN building, outdoor air station; [INC-0549] KH building, level 98: Water pH critical (9.61); [INC-0553] Power factor at 0.623 (SB00 substation, 11 kV f

**[s1] Are there any HVAC problems I should worry about?**
- 4B d27 (8.9 s): Open HVAC incidents: 15; worst status: warning.
- 2B d30 (6.2 s, qwen3.5-2b rsn_v3 (cpu)): 15 incidents involve hvac, worst status warning. Check [INC-0486] first.

**[heldout] Compare air quality and water incidents this week.**
- 4B d27 (17.2 s): 0 incidents involved PM2.5 at AQ-KN00-00 this week. 0 incidents involved PM10 at AQ-KN00-00 this week. 0 incidents involved CO2 at SR-AQ-KH03-03 this week.
- 2B d30 (11.5 s, qwen3.5-2b rsn_v3 (cpu)): This week: 48 air quality PM2.5 incidents, 0 water PM10 incidents.

**[heldout] Status of sensor ZZ-XX99-07?**
- 4B d27 (11.0 s): I don't see sensor ZZ-XX99-07 in the current sensor list.
- 2B d30 (3.0 s, qwen3.5-2b rsn_v3 (cpu)): No sensors exist at ZZ-XX99-07, so I can't tell what's there.

**[heldout] Has the KH level 2 AC unit 24 had repeated problems?**
- 4B d27 (10.9 s): The KH AC has not had repeated problems: room temperature incidents today: 0.
- 2B d30 (10.4 s, qwen3.5-2b rsn_v3 (cpu)): SR-AC-KH02-24 AC units on in the last 24 hours: 288 5-min points from 2026-10-15 18:15 to 2026-10-16 18:10.

**[heldout] How does today compare with yesterday in incident count?**
- 4B d27 (9.5 s): Today has 5 incidents; yesterday had 0.
- 2B d30 (6.4 s, qwen3.5-2b rsn_v3 (cpu)): Today has 24 incidents, while yesterday had 40 incidents. So today has fewer incidents than yesterday.

**[heldout] How many incidents this week were sensor faults and how many were real problems?**
- 4B d27 (13.6 s): 0 incidents were sensor faulty this week; 2 were real problems.
- 2B d30 (10.8 s, qwen3.5-2b rsn_v3 (cpu)): Sensor-fault incidents: 146 of 249 total.

**[blind] what was the root cause**
- 4B d27 (9.6 s): The root cause is room temperature stuck on due to schedule or control fault.
- 2B d30 (8.2 s, qwen3.5-2b rsn_v3 (cpu)): [INC-0620] Room temperature stuck on, warning (KH building, level 02) (warning, 2026-10-18 00:40): closed. An operator approved it. The device does not store operator names beyond what the steps record. Root cause: Room temperature stuck on due to schedule or control fault.

**[blind] Compare the number of incidents last week vs the week before.**
- 4B d27 (10.7 s): 5 incidents last week; 5 incidents the week before.
- 2B d30 (18.7 s, qwen3.5-2b rsn_v3 (cpu)): Last week: 260 total incidents (129 on 2026-10-14, 56 on 2026-10-13, 40 on 2026-10-15, 24 on 2026-10-16, 11 on 2026-10-17). Last

**[blind2] and an hour ago, was it the same?**
- 4B d27 (14.9 s): That node doesn't exist on this device; available nodes are AC-KH03, AQ-KN00-00, EM-CR-SB00-00, SR-AC-KH02-24, SR-AC-KH03-15, SR-AC-KH95-02, SR-AQ-KH03-03, SR-EM-KH04-01, SR-OC-GW-KH95-01, WE-VN04-00, WM-WD-KH98-00, WM-WF-KH98-40, WM-WL-KH98-00. (Note: the device could not run get_sensor_history: un
- 2B d30 (18.8 s, qwen3.5-2b rsn_v3 (cpu)): I can't help with what you asked for: the device has no temperature sensor, only AC units on and room temperature.

**[blind2] Show me everything critical from this morning.**
- 4B d27 (10.2 s): No critical incidents this morning.
- 2B d30 (7.6 s, qwen3.5-2b rsn_v3 (cpu)): No critical incidents were found in the time window.

**[blind2] pm25 sensr on KH lvl 3 kharab hai kya?**
- 4B d27 (10.0 s): No sensors are reported as critical, warning or sensor_fault at KH level 3.
- 2B d30 (62.9 s, qwen3.5-2b rsn_v3 (cpu)): I could not find an answer to that on the device.

**[blind2] Was there any power spike in the last 4 hours?**
- 4B d27 (10.5 s): No power incidents in the last 4 hours.
- 2B d30 (8.6 s, qwen3.5-2b rsn_v3 (cpu)): No readings were returned for that query, so I can't confirm or deny a spike. Please try again with different parameters.

**[blind2] Give me a quick status of the whole campus in two lines.**
- 4B d27 (11.4 s): Open incidents: air_quality 31 (worst critical); water 1 (worst critical); power 0; occupancy 0; weather 6 (worst critical); hvac 15 (worst warning).
- 2B d30 (8.9 s, qwen3.5-2b rsn_v3 (cpu)): Air quality: 45 open incidents, worst critical. Water: 1 open incident, worst critical. Power: 0 open incidents, worst normal. Occupancy: 0 open incidents, worst normal. Weather: 6 open incidents, worst critical. HVAC: 15 open incidents, worst warning.

