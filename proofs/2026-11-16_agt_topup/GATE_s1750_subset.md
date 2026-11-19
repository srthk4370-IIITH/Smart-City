# GATE_agt: agt_v3 snap_1750 (same subsets) vs B50 -> **FAIL**

Strict gate (V3_DESIGN.md 5.4 + owner brief): every check must pass, otherwise B50 stays. Host GPU Q4_0, greedy, device prompts + prefill + app stop rule; B50 on its v2 prompts of the same windows. Raw samples: `/home/hp_srthk4370/smartcity_runs/agt_topup/gate/samples_s1750`.

| check | pass | detail |
|---|---|---|
| JSON validity 100 % (all sets) | yes | 1164/1164 |
| dev: every v3 row paired with a B50 row | yes | 400/400 paired |
| dev: net (pattern+status+cause wins - losses) > 0 | **NO** | net -223 over 400 pairs |
| dev: severity-weighted status net >= 0 | **NO** | -86 |
| dev: no Holm-worse slice (exact sign test, alpha 0.05) | **NO** | worse: ALL.cause 84.0->63.5 (18/100), ALL.pattern 84.2->63.7 (12/94), ALL.status 84.5->69.8 (23/82), age_other.cause 89.9->63.5 (5/47), age_other.pattern 90.6->67.3 (4/41), age_other.status 88.7->72.3 (11/37), calm_or_routine.cause 75.6->56.3 (4/27), calm_or_routine.pattern 74.0->49.6 (4/33), fam_fault.cause 95.2->66.1 (1/19), fam_fault.pattern 98.4->71.0 (0/17), fam_fault.status 95.2->66.1 (1/19), gold_pat_flatline.cause 100.0->74.5 (0/13), gold_pat_flatline.pattern 96.1->64.7 (0/16), gold_pat_step_increase.cause 88.9->47.2 (0/15), gold_pat_step_increase.pattern 88.9->44.4 (0/16), gold_status_normal.cause 82.8->61.3 (5/45), gold_status_normal.pattern 80.1->57.0 (5/48), gold_status_sensor_fault.cause 94.1->65.9 (2/26), gold_status_sensor_fault.pattern 96.5->70.6 (0/22), gold_status_sensor_fault.status 94.1->64.7 (1/26), role_water.cause 79.8->51.1 (5/32), role_water.pattern 85.1->52.1 (2/33), role_water.status 83.0->59.6 (6/28), role_weather.cause 90.9->63.6 (0/12), seen_seen.cause 86.9->64.6 (11/62), seen_seen.pattern 87.8->65.5 (4/55), seen_seen.status 88.6->72.9 (13/49), seen_unseen_sepoct.cause 84.8->52.2 (0/15), seen_unseen_sepoct.pattern 84.8->43.5 (0/19), seen_unseen_sepoct.status 87.0->60.9 (0/12), sensor_fault.cause 93.8->68.8 (2/22), sensor_fault.pattern 96.2->70.0 (0/21), sensor_fault.status 93.8->67.5 (1/22), set_testrest.cause 85.6->62.7 (8/54), set_testrest.pattern 85.6->64.7 (7/49), set_weak.cause 77.8->57.0 (9/37), set_weak.pattern 78.5->57.0 (4/33), set_weak.status 79.3->57.8 (4/33), stage_40min.status 79.2->51.4 (3/23), stage_early.status 79.2->51.4 (3/23) |
| dev: calm/routine status not worse | **NO** | B50 82.4 -> v3 72.3 (n 119) |
| dev: power status >= 78 | **NO** | 57.4 (n 101) |
| dev: water status >= 80 | **NO** | 59.6 (n 94) |
| dev: no domain status > 1 pt below B50 | **NO** | air_quality 91.2->75.8; hvac 89.4->72.3; occupancy 100.0->100.0; power 68.3->57.4; water 83.0->59.6; weather 97.7->88.6 |
| dev: critical recall >= 85 | **NO** | 63.6 (n 44; B50 86.4) |
| dev: calm false alarms <= 8 % | **NO** | 26.1 % of 111 calm normal rows (B50 18.3 %) |
| dev: stage_40min pattern >= B50 | **NO** | B50 72.2 -> v3 50.0 (n 72) |
| dev: stage_1.5h pattern >= B50 | **NO** | B50 88.2 -> v3 78.4 (n 51) |
| dev: stage_3h pattern >= B50 | **NO** | B50 80.0 -> v3 65.0 (n 40) |
| dev: young k=3-7 pattern >= B50 | **NO** | B50 - -> v3 - (n 0) |
| E1: net >= 0 | **NO** | net -62 over 184 stories |
| E1: safety 16/16 | **NO** | 8/18 correct |
| rename agreement >= noise floor | yes | orig vs renamed 96.7 (n 60); noise floor 96.7 (n 60) |
| unseen_metric: status >= 85 | yes | 89.0 (n 100) |
| unseen_metric: pattern >= 80 | yes | 86.0 (n 100) |
| unseen_metric: dq >= 90 | yes | 97.0 (n 100) |
| unseen_layout: status >= 85 and >= B50 | yes | 85.0 (n 100; B50 82.2) |
| test_campus (real held-out): status >= B50 | yes | B50 81.9 -> v3 97.6 (n 83) |
| calm-looking fault recall >= 85 | yes | 97.9 (n 97) |
| fault precision >= 90 | **NO** | 88.7 of 239 sensor_fault calls are real faults |
| false 'broken sensor' calls <= 3 % | **NO** | 4.9 % of 551 non-fault windows called sensor_fault |

Dev overall (B50 -> v3): pattern 84.2 -> 63.7; status 84.5 -> 69.8; cause 84.0 -> 63.5; dq - -> 85.0

Slices down > 1 pt (not significant, for the record): ALL.cause 84.0->63.5, ALL.pattern 84.2->63.7, ALL.status 84.5->69.8, age_other.cause 89.9->63.5, age_other.pattern 90.6->67.3, age_other.status 88.7->72.3, calm_or_routine.cause 75.6->56.3, calm_or_routine.pattern 74.0->49.6, calm_or_routine.status 82.3->72.3, exp_vs_gradual.pattern 80.0->70.0, exp_vs_gradual.status 70.0->60.0, fam_event.cause 72.0->58.0, fam_event.pattern 74.1->61.5, fam_event.status 75.5->60.1, fam_fault.cause 95.2->66.1, fam_fault.pattern 98.4->71.0, fam_fault.status 95.2->66.1, fam_hvac.cause 95.7->74.5, fam_hvac.pattern 95.7->72.3, fam_hvac.status 89.4->72.3, fam_occupancy.cause 100.0->87.0, fam_occupancy.pattern 100.0->87.0, fam_routine.cause 85.7->50.0, fam_routine.pattern 82.1->60.7, fam_routine.status 89.3->60.7, fam_stable.cause 67.7->51.6, fam_stable.pattern 67.7->48.4, fam_stable.status 71.0->67.7, gold_pat_erratic.cause 76.0->48.0, gold_pat_erratic.pattern 76.0->40.0, gold_pat_erratic.status 76.0->48.0, gold_pat_exponential_increase.cause 88.0->76.0, gold_pat_exponential_increase.status 80.0->72.0, gold_pat_flatline.cause 100.0->74.5, gold_pat_flatline.pattern 96.1->64.7, gold_pat_flatline.status 96.1->74.5, gold_pat_gradual_decrease.cause 85.2->77.8, gold_pat_gradual_decrease.pattern 92.6->88.9, gold_pat_gradual_decrease.status 88.9->81.5, gold_pat_gradual_increase.status 88.9->83.3

**Also required before agt_v3 replaces B50 (owner 2026-11-13, run after this gate):** through the reasoner: the 315 real incidents (cleaned labels) + test_real_agent through the reasoner with agt_v3 outputs vs B50 outputs: report severity and label not worse; board fit + latency (Q4_0 on the QIDK): 10 agents fit ctx 1408, output p95 <= 230 tokens, agent wall time measured and reported (accuracy first; fails only if it breaks the app); post-gate weight edit (V3_DESIGN 5.1): edit only if a failure direction exists and the full gate still passes

Not automated here (need the reasoner / one-time sets): design 5.4 items 7 (315 real-agent incidents through r3-2800) and 8 (untouched eval_test, once at the end).
