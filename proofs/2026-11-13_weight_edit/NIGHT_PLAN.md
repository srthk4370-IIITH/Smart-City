# Night plan 2026-11-13 -> 11-14 morning (owner away; owner decisions via AskUserQuestion 19:20 IST)

Deliverables by morning:
1. agt_v3 domain agents: trained, selected, gated (fault precision etc.), everything agreed included (V3_DESIGN 4.2/5.1/5.4). GPU PRIORITY.
2. r3-2800 neuron-edited reasoner, merged ONCE into board Q4_0 GGUF, real-tested vs r3-2800 Q4_0.
3. Reasoner plan: fine-tune vs top-up vs full retrain (decided from edit + agent results), dataset ready (incl. agt_v3 outputs). NO training start until owner asks.

Neuron targets (r3-2800 only): no-think-easy; evidence over agent; severity not copied from agent; critical recall / no under-grading;
sensor fault vs real event; chat tool choice (co_occurring_incidents / fog_search); anything else surgery can improve (cross-domain flow).

Method: we_neuron.py profile tables -> Claude picks neurons + factors (judgment) -> script tests one tweak at a time (greedy keep if target
improves, others not worse, NLL <= +0.01) -> merge kept tweaks once (edit_weights: scale down_proj columns, base + LoRA A) -> Q4_0 -> real test.
Rules: GPU_LOCK one job; agents first; scripts for long/mindless work; LF endings; no board/APK/commits; real data local.

Owner clarifications (19:30 IST):
- agt_v3 quota: continue training (laptop or later Kaggle) ONLY if I judge it will improve (selection scores still rising).
- agt_v3 gate fails: FIX it (neuron surgery on the agent, then agents take priority over the reasoner; or top-up training; whatever improves). Goal: a perfect agent tomorrow, or a clear way to it.
- Reasoner deliverable: Q4_0 GGUF staged in Code/models_stage (md5, host test vs r3-2800), NOT deployed.
- Trade-offs allowed iff aligned with the project goal: better cross-domain reasoning with a little sensor-fault loss is OK; any rise in hallucination (invented numbers/ids, ungrounded claims) is NOT: then tone the edit down but keep accuracy.
- Owner 19:40: run things in parallel where possible (GPU: one model job at a time, 6 GB; CPU: exports/merges/Q4_0 quantize, data building, scoring; Kaggle: agent training while quota lasts). Be time + token efficient; 30-min checks short.
- Owner 21:40: neuron surgery for EACH department (domain): agt_v3 per-domain weaknesses (power, water, air quality, hvac, occupancy, weather) after its gate/dev scores, AND every reasoner target. Deliver the best models by any means possible.
- Owner 22:35: reasoner training PLAN + DATASET only after (1) agt_v3 done and (2) COMPLETE neuron surgery of every agreed target (agents per department + reasoner all targets).
- agt_v3 seq 6 (step 1500->, 2.75 h) launched 17:19 UTC; pull manually after ~20:10 UTC (runner in gate phase), then select new snaps; gate on snap_1500 running.

Method for EVERY target (owner 23:20): not just mute. Per target: profile -> deep look (specificity, harm/help) -> choose per neuron:
dial (0.2-0.7), flip, boost helpers (x1.5-2), REWIRE (add a desired-logit push to the output column of highly selective
detector neurons; effect scales with firing so it stays conditional). Rule from trust: never rewire detectors whose firing is also
right in protected cases (e.g. agent-normal detector fires on calm too) -> dial them instead. Extra care for cross-domain targets.
Targets checklist (reasoner r3-2800): [ ] no-think-easy  [ ] evidence over agent  [ ] severity not copied (under-grade flips)
[ ] critical recall  [ ] sensor fault vs real event  [ ] chat tool choice  [ ] cross-domain (linked sensors / flow / shared cause)
Agents (agt_v3, per department): [ ] calm false alarms (water, power, all)  [ ] power over-grading  [ ] AQ fault<->normal  [ ] others from gate
- Owner 23:50: agent gate ONLY after Kaggle seq 6 (gate the best snapshot once). Now: agent profile -> neuron surgery (agents + reasoner). Small gate optional.
  After seq 6 ends (~20:10 UTC): bash agt/pull.sh --once; bash agt/select.sh (scores new snaps); then bash agt/gate.sh <best snap> (or restart runner).
- Owner 23:55: agent profile + tweak tests ONLY on the final best snapshot (after seq 6 selection). Reasoner 'round 1' = first batch of reasoner surgery tests; rounds continue over all targets; one merge at the end.

Owner 04:15 IST, next 8-10 h:
1. After agent snapshot scoring: finish reasoner neuron surgery (all targets) -> best edited reasoner (merge once, Q4_0, real test).
2. Agent: best snapshot -> per-department surgery -> gate.
   - Gate PASS: keep improving it; then decide reasoner route (retrain / top-up / fine-tune) and BUILD the full reasoner dataset (using agt_v3 real outputs).
   - Gate FAIL: stop reasoner work after surgery; work only on fixing the agent (surgery / top-up / data) until it passes.
3. Reasoner dataset only once the agent model is done.

Owner 2026-11-15 21:50 IST (approved, with changes):
- NO separate reasoner evaluation step (no C1 real Q4_0 test); go straight to improving; only quick probes, full gate only when the model is finished.
- Reasoner route: FINE-TUNE from best edited r3-2800 with a BIGGER dataset (approved 7,990 + agt_v3 real outputs/mistakes + extra weak-type rows incl. cross-floor flow).
- Deploy: WAIT and deploy everything new together (agt_v3 + new reasoner + app) later; board keeps current build.
- App work (Go builders/parity): LATER.
- Agents: neuron surgery (small valid gains) in GPU gaps while the reasoner trains; agent gate on snap_1750 running.
- Owner 21:55: dataset v2 -> fine-tune starts automatically if all checks pass (log summary+examples). agt_v3 windows: synthetic + cleaned real (laptop only). Power fails -> top-up + smallest possible re-gate. Reasoner surgery: tool choice only; fault/event + cross-domain + flow -> training rows.
- Owner: if B50 beats agt_v3 on any gate slice, find out WHY before discarding (numbers + proper reason): prompt format (each model must get its own prompt: B50 v2 prompt, agt_v3 card prompt - gate already pairs them), gold differences (v3 teacher vs v2 gold), card/jitter effects, independence trade-offs, Q4_0 quant. Report per slice.
- 2026-11-15 17:20 UTC: dataset v2 pipeline running (rsn_v2_s1 agent outputs on CPU 33 s/window -> ~18 h; s2 builds+checks, writes READY). WHEN THE AGENT GATE FREES THE GPU: touch proofs/2026-11-13_v3_data/rsn/data/final_v2/work/agent_out.jsonl.STOP, wait for s1 exit, re-run v2_agent_run.py resumable with GPU (-ngl 99, CUDA visible, GPU_LOCK held) to finish the windows in ~40 min; s2 then builds; fine-tune starts on r3_edit_C1 when READY.
- Owner 2026-11-16 01:30 IST: reasoner strict gate must take <= 4 h. Build it only AFTER the fine-tune is running. Fast gate: stratified fixed subsets of every suite (keep the 73 easy-think fails, every reasoning type, every fog state, safety cases), r3-2800 reused from cached gate_r3 results on the same items (run r3-2800 only on small r4 + site-chat slices), BASE_V4=0, shorter cool gap; ~3.5-3.9 h; paired comparisons; report noise per slice.

QIDK deploy (owner 2026-11-16, board connected; START ONLY AFTER THE REASONER FINE-TUNE IS RUNNING; detached scripts; save tokens):
- Agents: agt_v3 if its gate passes (Go card builder + parser, byte parity), else B50 (B50 = rollback).
- Reasoner: r3_edit_C1 Q4_0 (export from C:/Users/hp/qidk_models/r3_edit_C1), r3-2800 = rollback; r3 prompt format until the new reasoner.
- App scope (build everything, all integrated): site tree + typed links + roll-up + grouping (adaptive window by link type) + suspect parent; map UI + tree picker + spec-card editor (site config on board); agt_v3 card prompts + new fields (evidence ids, data_quality, severity_reason) in UI; v4 reasoner prompts + 4 site chat tools behind a hidden switch (OFF until the new reasoner).
- Production features ON: MQTT ingest, time sync, heartbeat, alert delivery, fog uploader (local fog), auto warm-up. OFF: early provisional AI. OTA built, unused. Supabase NOT now (no data online).
- Procedure: DEPLOY_R3.md full (T0 ctx test with htpd v9h, APK alone, model push, profile switch, retire 2B split, 12-item test plan) with auto-rollback.
- Phasing: Phase 1 (models + site features + production features) when built + tested; Phase 2 (v4 reasoner prompts + site chat ON) when the new reasoner passes.
- Owner: app/board testing <= 30-60 min total (fast checks: fastcheck, chaos-lite, a few stories, site/map UI smoke); be fast.
- MQTT: broker (Mosquitto) on the laptop; board mqtt_url=tcp://<laptop-ip>:1883; mqtt_pub.py plays real-like sensors (ramp, backlog, broker drop); sliders keep working.
- Owner: live input = campus API http://10.2.203.214:9999 (synthetic 2026 replay; /verticals/all/latest every ~60 s, /temporal 12 h backfill on start, /nodes registry) ; SLIDERS REMOVED. Site tree + map auto-built from /nodes (building from name, floor/room from node code, x,y positions; links proposed by rules; editable). Board currently on no Wi-Fi: app shows a custom "No network / connect to Wi-Fi" page (with Wi-Fi settings shortcut + last-data age) whenever the API (and MQTT broker) is unreachable; resumes + backfills on reconnect. Values parsed from "421 ppm" strings, unit checked; created_at is UTC.
- Owner 2026-11-16: poll API every 5 s (if-changed). ADD: live data-health panel (last-seen age, stale/missing, API+MQTT link), faster first alert from the 12 h backfill (agent windows filled at start), daily summary report (reasoner, stored incidents), incident export CSV/JSON. Phase 1 LEAVES OUT: map floor-plan upload (use API x,y campus map). Spec-card editor: FULL editor now (all card fields, new sensor types, validated, saved in site config, agent uses at once).
- 2026-11-16 owner: agt_v3 gate FAIL = sim-to-real gap (golds agree 95.5%, prompts match; wins synthetic/independence, loses real dev/E1). Fix: laptop real-window top-up (background agent, proofs/2026-11-16_agt_topup, real val selection, small re-gate). Real data NOT on Kaggle. Dataset v2 agent runs PAUSED (STOP file); redo all 2,000 on GPU with the FINAL topped-up agent (CUDA server -ngl 99 instead of build-host -ngl 0), then v2 build -> reasoner fine-tune -> QIDK app work.
- Owner 2026-11-16 ~02:45 IST: ALLOWS real windows on Kaggle as a PRIVATE dataset for the agt_v3 top-up -> top-up trains on Kaggle; laptop builds the Phase 1 APK NOW (all decided features); B50 + r3_edit_C1 in the first deploy, agt_v3 swapped in after its re-gate passes (profile switch).
- 2026-11-16: top-up chain running (proofs/2026-11-16_agt_topup, ~202 steps, real val B50 .907 vs snap_1750 .686). Watch rules: (a) if real-val score still rising at the end -> extend training (30k real rows available); (b) the strict gate's absolute thresholds (power>=78, water>=80, crit recall>=85, calm FA<=8%) also fail for B50 -> if candidate >= B50 on paired slices AND no harm vs snap_1750, write ~/smartcity_runs/agt_topup/FINAL myself (log reason; absolute thresholds = info).

## Owner 2026-11-17: sensor_fault false alarms (proofs/2026-11-17_sensor_fault_check/FINDINGS.md)
- Done in app (phase1d): A clear all incidents (moved to state/cleared_20261117), B small-value resolution (effDec), C retrieval ignores unconfirmed sensor_fault.
- D -> reasoner fine-tune PART 2 (v2 top-up): sensor_fault only with a 2nd evidence kind (neighbour disagrees / physically impossible / DQ flag);
  else warning "possible sensor fault"; reasoner must not override a normal/warning agent to sensor_fault without it. Build rows for this.
- F (agent/reasoner training on level-shift / plateau real events): WAIT for owner.
