# GATE_agt: agt_v3 topup snap_0075 (7fa44fd489047170eead7ec8d7e7a406) vs B50 -> **FAIL**

Strict gate (V3_DESIGN.md 5.4 + owner brief): every check must pass, otherwise B50 stays. Host GPU Q4_0, greedy, device prompts + prefill + app stop rule; B50 on its v2 prompts of the same windows. Raw samples: `/home/hp_srthk4370/smartcity_runs/agt_topup/gate/samples_cand`.

| check | pass | detail |
|---|---|---|
| JSON validity 100 % (all sets) | yes | 1164/1164 |
| dev: every v3 row paired with a B50 row | yes | 400/400 paired |
| dev: net (pattern+status+cause wins - losses) > 0 | **NO** | net -189 over 400 pairs |
| dev: severity-weighted status net >= 0 | **NO** | -69 |
| dev: no Holm-worse slice (exact sign test, alpha 0.05) | **NO** | worse: ALL.cause 84.0->67.5 (24/90), ALL.pattern 84.2->66.2 (18/90), ALL.status 84.5->71.8 (28/79), age_other.cause 89.9->66.7 (5/42), age_other.pattern 90.6->67.9 (4/40), age_other.status 88.7->73.6 (11/35), fam_fault.cause 95.2->64.5 (1/20), fam_fault.pattern 98.4->69.3 (0/18), fam_fault.status 95.2->64.5 (1/20), fam_hvac.pattern 95.7->68.1 (0/13), gold_pat_erratic.cause 76.0->28.0 (0/12), gold_pat_erratic.pattern 76.0->12.0 (0/16), gold_pat_erratic.status 76.0->28.0 (0/12), gold_pat_flatline.cause 100.0->74.5 (0/13), gold_pat_flatline.pattern 96.1->68.6 (0/14), gold_status_normal.cause 82.8->66.7 (11/41), gold_status_normal.pattern 80.1->61.8 (11/45), gold_status_sensor_fault.cause 94.1->56.5 (1/33), gold_status_sensor_fault.pattern 96.5->64.7 (0/27), gold_status_sensor_fault.status 94.1->56.5 (1/33), role_hvac.pattern 95.7->68.1 (0/13), role_water.cause 79.8->53.2 (5/30), role_water.pattern 85.1->57.5 (3/29), seen_seen.cause 86.9->73.4 (14/45), seen_seen.pattern 87.8->72.0 (7/43), seen_seen.status 88.6->77.3 (13/39), seen_unseen_sepoct.cause 84.8->47.8 (0/17), seen_unseen_sepoct.pattern 84.8->41.3 (0/20), seen_unseen_sepoct.status 87.0->54.4 (1/16), sensor_fault.cause 93.8->60.0 (1/28), sensor_fault.pattern 96.2->62.5 (0/27), sensor_fault.status 93.8->60.0 (1/28), set_testrest.cause 85.6->67.7 (11/47), set_testrest.pattern 85.6->69.2 (9/42), set_weak.pattern 78.5->58.5 (6/33), set_weak.status 79.3->59.3 (6/33) |
| dev: calm/routine status not worse | **NO** | B50 82.4 -> v3 74.8 (n 119) |
| dev: power status >= 78 | **NO** | 60.4 (n 101) |
| dev: water status >= 80 | **NO** | 63.8 (n 94) |
| dev: no domain status > 1 pt below B50 | **NO** | air_quality 91.2->76.9; hvac 89.4->66.0; occupancy 100.0->95.7; power 68.3->60.4; water 83.0->63.8; weather 97.7->97.7 |
| dev: critical recall >= 85 | **NO** | 68.2 (n 44; B50 86.4) |
| dev: calm false alarms <= 8 % | **NO** | 22.5 % of 111 calm normal rows (B50 18.3 %) |
| dev: stage_40min pattern >= B50 | **NO** | B50 72.2 -> v3 59.7 (n 72) |
| dev: stage_1.5h pattern >= B50 | **NO** | B50 88.2 -> v3 72.5 (n 51) |
| dev: stage_3h pattern >= B50 | **NO** | B50 80.0 -> v3 67.5 (n 40) |
| dev: young k=3-7 pattern >= B50 | **NO** | B50 - -> v3 - (n 0) |
| E1: net >= 0 | **NO** | net -45 over 184 stories |
| E1: safety 16/16 | **NO** | 10/18 correct |
| rename agreement >= noise floor | **NO** | orig vs renamed 95.0 (n 60); noise floor 98.3 (n 60) |
| unseen_metric: status >= 85 | yes | 89.0 (n 100) |
| unseen_metric: pattern >= 80 | yes | 85.0 (n 100) |
| unseen_metric: dq >= 90 | yes | 94.0 (n 100) |
| unseen_layout: status >= 85 and >= B50 | yes | 88.0 (n 100; B50 82.2) |
| test_campus (real held-out): status >= B50 | yes | B50 81.9 -> v3 95.2 (n 83) |
| calm-looking fault recall >= 85 | yes | 91.8 (n 97) |
| fault precision >= 90 | yes | 95.6 of 204 sensor_fault calls are real faults |
| false 'broken sensor' calls <= 3 % | yes | 1.6 % of 551 non-fault windows called sensor_fault |

Dev overall (B50 -> v3): pattern 84.2 -> 66.2; status 84.5 -> 71.8; cause 84.0 -> 67.5; dq - -> 88.8

Slices down > 1 pt (not significant, for the record): ALL.cause 84.0->67.5, ALL.pattern 84.2->66.2, ALL.status 84.5->71.8, age_other.cause 89.9->66.7, age_other.pattern 90.6->67.9, age_other.status 88.7->73.6, calm_or_routine.cause 75.6->62.2, calm_or_routine.pattern 74.0->57.1, calm_or_routine.status 82.3->74.8, exp_vs_gradual.pattern 80.0->70.0, fam_event.cause 72.0->65.0, fam_event.pattern 74.1->65.0, fam_event.status 75.5->71.3, fam_fault.cause 95.2->64.5, fam_fault.pattern 98.4->69.3, fam_fault.status 95.2->64.5, fam_hvac.cause 95.7->74.5, fam_hvac.pattern 95.7->68.1, fam_hvac.status 89.4->66.0, fam_occupancy.cause 100.0->95.7, fam_occupancy.status 100.0->95.7, fam_routine.cause 85.7->64.3, fam_routine.pattern 82.1->75.0, fam_routine.status 89.3->71.4, fam_stable.cause 67.7->45.2, fam_stable.pattern 67.7->45.2, fam_stable.status 71.0->58.1, gold_pat_erratic.cause 76.0->28.0, gold_pat_erratic.pattern 76.0->12.0, gold_pat_erratic.status 76.0->28.0, gold_pat_exponential_increase.cause 88.0->84.0, gold_pat_flatline.cause 100.0->74.5, gold_pat_flatline.pattern 96.1->68.6, gold_pat_flatline.status 96.1->74.5, gold_pat_gradual_decrease.pattern 92.6->88.9, gold_pat_gradual_decrease.status 88.9->85.2, gold_pat_gradual_increase.pattern 91.7->88.9, gold_pat_gradual_increase.status 88.9->83.3, gold_pat_spike.cause 72.0->68.0, gold_pat_spike.pattern 72.0->56.0

**Also required before agt_v3 replaces B50 (owner 2026-11-13, run after this gate):** through the reasoner: the 315 real incidents (cleaned labels) + test_real_agent through the reasoner with agt_v3 outputs vs B50 outputs: report severity and label not worse; board fit + latency (Q4_0 on the QIDK): 10 agents fit ctx 1408, output p95 <= 230 tokens, agent wall time measured and reported (accuracy first; fails only if it breaks the app); post-gate weight edit (V3_DESIGN 5.1): edit only if a failure direction exists and the full gate still passes

Not automated here (need the reasoner / one-time sets): design 5.4 items 7 (315 real-agent incidents through r3-2800) and 8 (untouched eval_test, once at the end).
