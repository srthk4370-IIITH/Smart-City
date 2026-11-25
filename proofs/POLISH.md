# Polish list (owner, after execution)
- 2026-11-19 (owner): when the AI analysis times out for lack of fresh readings (e.g. rare-cadence pH fast path, INC-0009/INC-0018), do NOT just stop: run a base AI analysis on the past readings available (history window, last readings, context sensors) and give an AI verdict marked "limited data". AI reasoning on every alert is the core of the project.
- 2026-11-19 (owner): rare-cadence sensors (pH) -> AI on past readings when fresh readings stall: POLISH (not now).
- 2026-11-19 (owner): near-zero flat meter (3 W standby repeating) -> sensor_fault: leave to the new reasoner for now; discuss rule ("idle or stuck" warning + second-evidence) in polish.
- 2026-11-19: reasoner "data gaps / insufficient data" verdicts with 1/48 missing -> re-check after p2 reasoner deploy.
- 2026-11-19: agent tool calls = 0 on board so far; verify tool path in real incidents (and call recall ~40%).
- 2026-11-19: fog upload server (owner adds later).

## Production audit decisions (owner 2026-11-19; details proofs/2026-11-19_prod_audit/FINDINGS.md) — polish list
- Security core hardening: demo/inject off by default + watermark when on; release APK not debuggable; read token for chat/export; fog ingest fails closed; JSON content-type + custom header on writes.
- Robustness, all: recover() in tick/handlers; hard watchdog cap regardless of active; bounded critical-first persisted queue; fsync + write-error checks; compaction lock fix, never archive open incidents; rotation caps + disk-free in /api/health.
- Alerts: re-notify unacked criticals 15/30/60 min then backup contact; red banner if no channel; Ack / "I'm on it" always allowed; decide on the rules report for criticals.
- Reboot blindness: BOTH: persist bank + episode flags to state/ every 5 min (restore if <2 h), then backfill the gap from the campus API if reachable; failed incident re-hosts its sensor and reruns (no duplicate); per-sensor "warming up, N min".
- ALL findings of this audit round go into ONE final polish deploy (owner 2026-11-19).
- UX: site tree = BOTANICAL tree graphic (trunk = campus, labelled boughs = buildings, branches = floors/rooms, leaves = sensors coloured by status, per-room leaf cluster + count); arrow glyph bug (phase1.css:38).
- UX: plain words for the operator (no S1.E4/etype/(api)), ids in a "Technical details" fold; rename Engineering view.
- UX: undo/reopen (10 min) + safe dismiss (critical needs 2nd confirm; unconfirmed dismissals out of AI memory).
- UX: one time format with zone + "updated N min ago"; dark theme >=12px text, >=44px targets; reasons on disabled buttons + Retry; persistent critical banners.
- PDF/print only through the QR report (device stays edge-only). Assign/notes/due and shift handover: to discuss. Fog: still to add (owner).
- No shift/handover feature (owner). Chat app: voice input/output to look into.
- Next: 30-min hands-on test of the whole app + chat as a non-technical first-time user after the p2 deploy; findings -> discuss -> this list.

## Model decisions (owner 2026-11-19, after hands-on; details 2026-11-19_prod_audit/HANDS_ON.md)
- Chat: BOTH, router first: fix template bugs (sensor lookup, stale-sensor list, context bleed, forecast tool,
  answer format + language), route open questions (why/should/summarise/compare) to the reasoner with tool results;
  chat fine-tune top-up later if still weak.
- Short/rare events: run the agent + reasoner on the last 4 h window when a fast-path critical has not reached the
  8-reading gate after 15 min (or 2 cadences for slow sensors, e.g. hourly pH).
- Reasoner quality ("data gaps" titles on complete data, unexplained severity drop at 3 h): reasoner top-up p3 later
  (heavier p2 weight, more steps, gate vs p2).
- Swallowed events: a new abnormal event on a sensor with an open incident re-runs the AI and escalates that incident
  (new revision, severity raised, operator notified); incidents judged fine auto-close after 2 h with nothing new.
- #4 Playbook per metric + indoor/outdoor (outdoor PM, pH sampling, tank level...); the reasoner checklist wins when present.
- #5 Demo/injection: off in production builds (no realism work).
- #6 Severity changes at refine: always show why (readings that changed) on the incident + notification; a drop from critical needs the rules to agree, else kept and flagged.
- #13 Old test chats: clear now (done with the incident clear) + sessions > 30 days auto-archive + "Clear history" button.
- #14 Voice: push-to-talk with on-device speech-to-text (Whisper tiny/base, English + Hindi, nothing leaves the board); answers read aloud (Android TTS) only when the question was spoken.
- #15/#16 Home: one honest headline = worst true state (critical > warning > data problems > starting up > all clear), decisions waiting part of it; "Got worse" only on a real status worsening.
- #17 Fine incidents auto-close after 2 h with nothing new (reopenable); new alarm on a sensor with an open incident joins it.
- #18/#19 Layout: area cards 1 column < 480 px, no horizontal overflow, header reflow; dotted titles compact on phones.
- #20 Header icons: tooltips only (tap/hover labels).
- #21 Map: botanical tree first; version/nodes/links, Save, Rebuild in a collapsed "Site admin" (Rebuild = confirm + backup); node kinds in plain words (ground, building, floor, room).
- #22/#23 Plain words everywhere: confidence only for AI reports ("Rules only - no AI yet"); ids/internal terms only in Technical details, incl. chat answers.
- #24 Operator sees real time only ("22:40 IST"); sensor time only in Technical details.
- #25 Record every boot (time, uptime before, temperature, memory, htpd state) in state/; "restarted N times this week" in Technical details + heartbeat; alert if > 2 a day.
- #26 Relay: MQTT broker reachable from Windows again; fog: log "not configured" once instead of every minute (until fog is added).
- #27 Demo scenarios: covered by #5 (demo off in production).
- #28 Deploy-check incidents tagged "system check", hidden from the operator list, auto-closed.
- #29 Earlier audit items: already decided above.
- #30 QR: self-contained, compressed + signed report in the QR (or a short link to a static viewer that decodes in the browser); nothing stored online; viewer prints/PDF; long reports over 2-3 codes or trimmed.
- #31 Event mode: > N alarms in 10 min -> one incident per building/zone, rules critical pushed at once, AI per zone afterwards (critical first), red "Event mode" banner.
- #32 Maintenance snooze per sensor/room: mandatory reason + expiry (max 72 h); criticals still notify; shown as "snoozed".
- #33 "Since you last looked": no.
- Next: ordered polish plan + fog discussion, then everything in ONE pass / one final deploy (owner 2026-11-20).

## Fog (owner 2026-11-20)
- Roles: long-term store + backup, knowledge base for chat, fleet view + alerts (+ hosts the QR viewer). Board fully independent when fog is down (bounded on-disk queue, resend later; chat says "deeper lookup unavailable" once).
- Storage: Supabase cloud, REPORTS ONLY (logged exception to "no data online"): incident reports, operator decisions, board health go to Supabase; raw readings stay on campus (board + laptop). Laptop = local fog relay for raw data.
- Bigger model via API: later.
- Scope: minimal fog in this polish pass, built on afterwards.

## Big reasoner run (owner 2026-11-20)
- Start from p2; data built so the top-up cannot break what works (replay of p2's own correct behaviour, low LR, regression slices).
- English only (no Hindi; English translations of Hindi rows allowed if needed).
- Agent rows: regenerate 4000+ windows with s0450 (tool rounds, cross-domain groups) before building.
- Compute: Kaggle, big if needed (up to ~20 h laptop-equivalent): to discuss separately.
- Gate: a different, small gate (to define; includes English chat).
- Holes first: 30-min laptop inspection (reports + chat) -> proofs/2026-11-20_rsn_holes/HOLES.md.
- Kaggle: exception extended to the reasoner run (private dataset, deleted after the run, logged).
- Supabase: owner creates the free project and pastes URL + anon key into a gitignored file; I build schema, RLS, sync, fleet page; service key never on the board.
- QR viewer: static page on Cloudflare Pages (wrangler), decodes in the browser, stores nothing.
- Voice STT: whisper.cpp tiny.en on the board CPU (never the NPU).
- Alerts: ntfy push (topic = secret), email as backup contact.
- Event mode: 5+ sensors alarming in one building within 10 min (editable in Cards & rules).
- Work order: engine/AI flow + chat router -> hardening -> UI -> voice/QR -> fog last. Compute for the big run: to discuss after the hole inspection.
- Big reasoner run must teach better tool use (owner 2026-11-20): when to call which tool (lookup, history, forecast/estimate, cards, site tree, 2-call chains), correct arguments, using results faithfully, no call when the answer is in context; weighted tool-call rows (agent v2 lesson: rows x4 + first-token weight) and a tool-use slice in the gate.
- No-regression rule for the big run (owner 2026-11-20): replay of p2's own verified-correct outputs on every existing family (r3, r4, real-agent, campus chat, fog, unseen layout/metric, taxonomy) + the old v1/v2 replay; gate = small but checks EVERY existing slice vs p2 (any slice drop > 0.03 = FAIL, JSON validity >= p2), plus the new holes + tool-use slices; keep-best checkpoint chosen on the regression slices too.
- Big run compute: Kaggle ~12-14 h, 1 epoch, from p2, LoRA, low LR, 2 sessions with checkpoint resume (owner 2026-11-20). Data ~14-18k rows: no-regression replay of every family + holes (proofs/2026-11-20_rsn_holes/HOLES.md) + tool chains + 4500 new s0450 agent rows; English only.
- Gate: run the proposed small gate (~45 min: 40 report rows all families, 30 new-family/severity, 40 English chat, 20 tool-chain probes) and REPORT scores to the owner; deploy decided together (no auto-deploy).
- Top-up training must include fog (owner 2026-11-20): fog tool use, faithful short answers from fog results, fog-down behaviour.
- AI call rule (owner 2026-11-20): call the AI when >= 4 of the last 8 readings are beyond the threshold (missing readings count as not abnormal), instead of 8 in a row; editable per site in Cards & rules (2-8, default 4); critical fast path unchanged.
- AI vs rules (owner 2026-11-20): if the value is inside its limits and only the trend triggered the rule warning, the AI's normal wins (shown 'Watching: rising trend, AI judged normal', no decision needed, auto-close if nothing new); a real limit crossing keeps the guard.
- Critical fast path (owner 2026-11-20): every critical fast-path alert runs the agent+reasoner on the real history that exists as soon as it opens ('Early AI on history', no 15-min wait; slow-cadence sensors use their real readings, nothing invented; if impossible a timeline line says why, once). The 8-reading gate re-runs the incident (promotion) and replaces it ('Full 8-reading analysis replaces the early one'); 1.5 h/3 h refines unchanged. 15-min wait stays for non-critical. Also: AI-normal wins on trend-only warnings, reasoner checklist -> steps, S-refs stripped from titles.
- Reviewer modes: settling experiment (ANSWER.md section D) to run AFTER the big-reasoner gate decision (owner 2026-11-20); slide-6 quote pending: owner to point to the other deck.
- Reviewer study (owner 2026-11-20): target = research paper; multi-domain real replay soon; slide-6 deck unknown (correct any 'same model' line to agent stage only).
- Research paper plan: RESEARCH_PAPER.md (owner 2026-11-20: escalation RQ accepted; injected-only labels for now; 4 RQ3 triggers; ceiling model later).

## Open items / state at 2026-11-20 14:50 IST (single list, so nothing is lost)
- Board: APK phase1t (all polish incl. 4-of-8 gate + spike fix, critical early AI on history, trend-only guard, report steps, clean titles, voice VAD, QR share fix, fog relay order), agent agt3_s0450, reasoner rsn_v3_4b_p2.
- Reasoner big top-up: Kaggle kernel srthk4370/rsn-big-train v2 running since 07:02 UTC (first run lost to a flag-join bug, fixed in kernel_big.py:150). after_kaggle.sh gates automatically, NO deploy; owner decides from gate/GATE.md.
- p2 finding: p2 likely re-trained on the stage-2 pack, not on its p2 families (trainer log/hashes; dataset zip agent) -> verify the big run's trainer log reads data/final_big/train_new.jsonl.
- Research paper: RESEARCH_PAPER.md (+ answer_rishit.md, questions_for_rishit.md, status.md, proofs/2026-11-20_reviewer_modes/ANSWER.md). Runs start right after the reasoner decision.
- Still open polish: styled "set new password" page (fleet reset uses a browser prompt); MQTT on the laptop relay down since the WSL restart; reasoner/chat fog-up answers (only fog-down rows trained); Home "warming up" headline wording check; old incidents INC-0001..0004 keep pre-fix reports (re-run on request); GitHub main push of all decided code still pending; QR viewer trust list must be updated if the board key changes.
- Website smart-city-esw.pages.dev: deploy with npx wrangler@3.114.0 (v4 makes Workers). Camera scan + real sign-in not yet tested by the owner.
- Dataset zip: Desktop/SmartCity_Training_Datasets_2026-11-20.zip (private: real rows).
- Rishit additions 2026-11-20 logged in RESEARCH_PAPER.md section 11 (both arms on every case + offline trigger eval, forced full path on ~50 single-domain, oracle + always/never baselines + cost-accuracy curve, family-level leakage, 30-case discordance pilot, scoping line). No reply to Rishit needed now (owner).
- Big gate 2026-11-21 ~02:50 IST: chat ok 0.513->0.615, tool_chain 0.25->0.40, new-family hyg 0.80->0.97, report_all ok 0.825->0.775 (2/40; real_agent 5/6->3/6), severity flat. Owner: keep p2 on board; laptop full-pool run (~35 h) from step 242, higher LR, extra weight on reports/severity/real-agent; gate again, then deploy the winner; research runs after.
- Laptop full run (owner 2026-11-21): real windows BEFORE the paper's held-out cutoff with verified-pipeline gold + the ~13k real-derived lineage rows as replay; ~1,200 steps (~45 h); additions: thin tools x200-300 each (aligned to the Go chat router's tool list), agentic multi-step loops, multi-domain incidents (2-5 domains, causal and coincidental), domain-reasoning rows per domain incl. severity contrasts. Laptop-usable rules: normal priority, CPU threads = cores-2, use available RAM; Windows free RAM < 1.5 GB -> drop WSL caches; < 1 GB -> ping Claude (alert file) to free RAM; < 500 MB -> stop training cleanly (resumable). No pause at 2 GB.
- Laptop run size cut to 800 steps (12.8k rows; all real/gen5 kept, replay/old pool reduced) for speed (owner 2026-11-21); speed test: no faster config fits 6 GB (35 s / 4 rows).
- Before deploying the laptop-run reasoner: the app's chat header must list forecast_crossing + data_health (chat_r6 menu, tools_v5.json) and Go must return the same result fields as the training twin (see proofs/2026-11-21_rsn_full/TOOLS_DIFF.md).
- Laptop run: keep 800 steps (owner 2026-11-21); if the gate is weak, top-up 800 more steps on the same dataset (unseen half first).
- RAM stop line lowered to 250 MB (owner 2026-11-21).
- Laptop run: --shared-prefix disabled (batch OOM -> CUDA allocator assert loop on 6 GB); 2026-11-21.
- 2026-11-22 16:02:09 owner: work while training -> .wslconfig memory 6->5GB, processors 8->6; run_full: 4 threads, nice 10, GPU SIGSTOP throttle (THROTTLE file, 350/150 ms)
