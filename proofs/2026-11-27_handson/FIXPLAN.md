# Fix plan for decisions.md (5 parallel workstreams)

App: `Code/smart-city-edge-agent/app` (Go backend in `backend/`, package main; PWA in `device/web/`; Android in `android/`).
Item numbers = rows in `decisions.md` (read the matching finding in `findings.md` for details).

Rules for every workstream:
- Edit only the files you own (list below). If you truly need a change in another stream's file, keep it to a few lines,
  re-read the file right before editing (others edit in parallel), and say so in your report.
- LF line endings. No git commit, no deploy, no adb/board access, no network calls.
- Tests: `wsl.exe bash -lc 'bash /mnt/c/Users/hp/AppData/Local/Temp/claude/5cb597a87cde10fb/125df7ac-c9eb-46de-b63b-ce87f4c7e8ce/scratchpad/gt.sh "<regex>"'`
  (runs go vet + go test -run regex). Add tests for every behaviour fix. Other streams edit in parallel, so a failure
  in a file you don't own may be transient: re-run once before reporting it.
- Keep changes minimal and readable; comment the "why" with "night sweep 2026-11-27 #<item>".

## Shared API contract (backend adds, frontend consumes)
- `/api/status` -> `gate.watching[]` gains `held_by` (string, sensor key holding the batch, "" if none) and `eta_s`
  includes the batch hold (time until the batch can close); `gate.batch.waiting_for` = []string of sensor keys.
- `/api/live` and `/api/health` sensor entries gain `now_status` = status of the CURRENT reading vs card limits
  (normal|warning|critical|sensor_fault|no_data). Home "right now" counts use `now_status`.
- `/api/incidents` rows gain `ai_eta_s` (seconds until the next AI run for this incident: early look or full reading;
  -1 unknown) and `ai_running` (bool, true only while the NPU runs this incident). Keep `full_eta_s`.
- `/api/incidents` rows gain `opened_unix` (incident opening wall time) for "detected" (#73).
- `/api/prod/status` gains `supabase: {queued, sent, last_ok_unix, last_error}` and `campus_link/mqtt/fog` gain
  `offline_since_unix`.
- Staleness: one rule (#105): a sensor is stale after 3 missed readings (3 x reading interval); exported helper
  `sensorStale(lastUnix, nowUnix int64) bool` in the engine stream, used by health, data health and chat.

## Workstreams and file ownership
A. Engine/gate (engine.go, batchsplit.go, earlyai.go, fastpath.go, gateview.go, dataquality.go, domainhealth.go,
   health/data-health files, workflow.go, rules/flatline code, store id counter):
   #1 fast catch-up (+ status field `catching_up {done,total}`), #38 live gate rule in fast-path text, #41 id counter
   with state, #43 defer unlocks (Tick, workflowTick), #55 no early look after a fast-path incident in the episode,
   #59 group early-look candidates with relatedSensors, #77 only abnormal-now sensors hold a batch + critical member
   leaves at once, #78 fast path any time (2 critical readings, no open incident), #80 exactly-constant value faults at
   30 min (keep 80 min otherwise), #84 gate `held_by`/real eta, #95 provide "returned to normal at HH:MM after N
   abnormal readings" fact (expose a helper the reasoner stream calls), #105 one stale rule, #109 count sensor_fault
   readings toward the gate regardless of pattern, #110 `now_status`, `ai_eta_s`/`ai_running`/`opened_unix` (server.go
   incident list lines only).
B. Reasoner/report (reasoner_v3.go, reasoner_v4.go, reportfix.go, reportrepair.go, reason.go, title.go,
   severity*.go, polish_severity.go, agent prompt/"more data" code, evidence text builder):
   #37 timeline text: "writing the full report" only when the NPU runs it, #39 value + limit rules title, #57 rule-side
   corroboration before trusting an agent's sensor_fault on a fast rise, #58 skip the "more data" re-run when the prompt
   can't fit, #70 guard removing event claims about sensors that rule+agent call normal, #82 reading beyond its critical
   limit keeps the incident critical (AI view as note + timeline line), #94 heat guard only on temperature/room
   sentences, #95 add the "returned to normal" fact line to the prompt (helper from A), #98 "stepped up/down" from sign.
C. Chat backend (chat*.go and the chat knowledge/router files):
   #13 #18 #65 router + safety regression tests, #14 context only for true follow-ups, #15 per-metric action knowledge,
   #16 lead with the answer, #19 early-look knowledge entry, #20 time ranges, #21 unknown incident id, #22 greeting/help,
   #24 multi-part -> LLM, #66 "explain in simple words" -> LLM, #67 explicit real/fault verdict from the final report,
   #68 building + level matching, #69 history questions -> find_incidents/get_action_history, #90 all critical/warning
   from live state, #91 stale readings flagged (use sensorStale), #92 gate-status tool + remove "[unverified id
   removed]" from user text, #118 plain wording, #52b archive overflow sessions locally (chats_archive.json, rotated
   90 days / 5 MB, never uploaded).
D. Infra (auth.go, voice.go, server.go except A's incident-list lines, supabase_sync.go, prod_*.go, htpd*.go,
   genie*.go, hardening.go, retrieval.go, store.go, prefetch.go, campus/mqtt client files, polish_events.go, alert/smtp):
   #113 allow audio/wav on /api/chat/voice (same-origin check stays) + Origin-header test, #7 whisper no-speech filter,
   #9 whisper campus vocabulary prompt, #3 bad-input API tests, #4 404 unknown sensor / 405 wrong method,
   #10 fog delivery: find why fog_url 127.0.0.1:8092 is unreachable (read the fog code, docs under the repo, deploy
   scripts) and make delivery work as designed + back-off + offline_since, #108 campus/MQTT back-off + offline_since,
   #11 Supabase status, #44 single shared htpd restart, #45 Supabase save once per flush, #46 row ids + park after N,
   #47 rotate htpd.log/genied.log/prefetch_shadow.jsonl/chats_archive.json, #48 SMTP deadline, #49 cancel htpd call on
   client disconnect, #50 SSE write deadline, #51 prune retrieval index on archive, #53 prune supabase_seen.json,
   #87 resource history (RSS, mem, temps) for the health page, #88 thermal budget (space non-urgent NPU work > 80 C,
   never delay alerts), #104 prefetch sensors that mature inside an open batch (reuse stays off).
E. Frontend (device/web/** incl. chat/, android/**):
   #5 History CSV button, #25 opaque bottom nav + padding, #26 sun/moon + gear, #27 Sensors help from real source,
   collapsed, #28 hide zero "since" card, #29 map: nicer look + leaf labels on zoom + sensor search, #31 voice countdown +
   level bar, #33 Stop reading only while speaking, #34 shorter chat placeholder, #35 context-aware chat suggestions,
   #37 fast-path sheet text from `ai_eta_s`/`ai_running`, #40 one chip, #60 "Early look ready · full reading in ~N min"
   + actionable, #62 card leads with the AI report when it differs from the agent (agent view as "overruled" note),
   #63 refresh relative times every 30 s, #73 "detected" = `opened_unix`, #84 Watching real wait + reason + wording,
   #85b Home "Do this next" card (see decisions.md), #86 banner instead of re-opening a sheet on resume, #97 no
   auto-open over the current screen (banner) + 1 s tap guard on new sheets, #100 fix "since you last looked" counts,
   #102 handover place dedupe, #103 shorter search placeholder, #110 "right now" from `now_status`, #112 grouping by site
   tree / same sensor only, worst first, never collapse critical, #115 friendly voice error, #116 5 s reconnect banner
   delay + refresh on wake, #119 clear notes on send, #120 "no data" banner over the dashboard (full screen only when
   no data ever), #1 "catching up" banner from `catching_up`. Bump sw.js CACHE. Check `node --check` on changed JS.
