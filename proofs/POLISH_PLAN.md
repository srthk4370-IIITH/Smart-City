# Polish plan: one pass, one final deploy (owner 2026-11-20)

Decisions: proofs/POLISH.md. Evidence: proofs/2026-11-19_prod_audit/{FINDINGS,HANDS_ON}.md.
Board now: agent agt3_s0450, reasoner rsn_v3_4b_p2, APK phase1l, incidents + chats cleared (state/cleared_20261119).

Order = what unblocks what. GPU work runs detached in parallel with code work.

## 0. Start at once (GPU, detached, ~6-8 h)
- Reasoner p3 top-up (data gaps titles, severity drops, flat/step without 2nd evidence, late batch criticals):
  heavier p2 weight, more steps, from p2; gate vs p2 on dev_p2 + r3/r4. Chat rows from the hands-on questions
  (incl. Hindi, follow-ups, forecasts, 2-line summaries) go in the same data so the chat top-up is the same run.

## 1. Engine and AI flow (backend)
1. Short/rare events: AI on the last 4 h window when the fast-path critical has not reached the gate after 15 min
   (2 cadences for slow sensors).
2. Swallowed events: a new abnormal event re-runs the AI and escalates the open incident; fine incidents auto-close
   after 2 h with nothing new (reopenable); new alarm on a sensor with an open incident joins it.
3. Reboot: persist bank + episode flags every 5 min, restore < 2 h, then campus backfill; failed incident re-hosts;
   per-sensor "warming up"; boot record + restart counter.
4. Severity change explained at every refine; a drop from critical needs the rules to agree.
5. Playbook per metric + indoor/outdoor.
6. Event mode (one incident per zone above N alarms in 10 min).
7. Maintenance snooze (reason + expiry, criticals still notify).
8. Deploy-check incidents tagged "system check", hidden, auto-closed.

## 2. Chat router (backend)
Sensor lookup bug, stale-sensor list, context bleed, forecast tool, answer format + language, open questions to the
reasoner with tool results, plain words, "I'm on it" vocabulary, 30-day archive + Clear history.

## 3. Production hardening (backend + android)
Security core (demo off in production, release APK, read token for chat/export, fog ingest fails closed, CSRF
header); robustness (recover, watchdog hard cap, bounded persisted queue, fsync, compaction lock, never archive
open incidents, rotation caps, disk alarm); alerts (re-notify 15/30/60 min, backup contact, no-channel banner,
act on the rules report for criticals); undo/reopen + safe dismiss.

## 4. UI (web)
One honest headline; layout bugs + compact titles; plain words + Technical details fold; real time only with zone;
tooltips; disabled-button reasons + Retry; persistent critical banners; dark-theme sizes; Map: botanical tree first,
Site admin collapsed.

## 5. New features
Voice (push-to-talk, on-device speech-to-text, read aloud only for spoken questions); QR self-contained report +
static viewer site; fog minimal: laptop relay keeps raw readings on campus; Supabase cloud (reports, decisions, board health only) for store + backup + fleet view + alerts + chat KB + QR viewer; board independent when offline; API model later.

## 6. Relay
MQTT reachable from Windows again; fog "not configured" logged once.

## 7. Final
Full go test + APK build; reasoner p3 deploy if its gate passes; one APK deploy; 30-min hands-on re-run of the
same checklist (UI, 10 chat questions, injected events) on the board; push to GitHub main.

Rough size: code 3-5 days of focused work (1-4 in parallel with the GPU top-up), features 2-3 days, final test 1 day.
