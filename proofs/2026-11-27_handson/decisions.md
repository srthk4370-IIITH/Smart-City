# Owner decisions on findings.md (2026-11-27/28 night review, one item at a time)

| # | Finding | Decision |
|---|---|---|
| 1 | Start-up catch-up shows "no data" 1-5 min | Fast catch-up (big replay steps) + "catching up" banner |
| 2 | API speed OK | Keep, no change |
| 3 | Bad input handled | Add the cases to API tests |
| 4 | API hygiene (200 empty / 400 on wrong method) | Unknown sensor 404, wrong method 405 + Allow |
| 5 | CSV export works | Add "Download CSV" button on History |
| 6 | Voice tiny.en 2.3-3.0 s, accurate | Keep tiny.en |
| 7 | Silence -> "you" | Server-side no-speech filter |
| 8 | Voice guards | Keep |
| 9 | Voice "in" -> "and" | Add campus vocabulary prompt to whisper |
| 10 | Fog outbox never drains (127.0.0.1:8092 refused) | Fog server IS part of the deployment: make delivery work (find why 8092 is down / wire the real fog endpoint), plus back-off and "fog offline since" status |
| 11 | Supabase sync not visible | Expose queue/sent/last_ok/last_error in /api/prod/status + Health line |
| 12 | Disk leftovers | Delete old backups only (incidents.jsonl.bak_20261021_1555, today's 5 state-backup tgz, htpd.log.root_old); keep run states |
| 13 | Chat router fast answers OK | Keep + router regression tests |
| 14 | Chat context sticks to last sensor | Carry context only for true follow-ups |
| 15 | PF "what to do" answer has no actions | Add per-metric action knowledge |
| 16 | Answer starts with the missing sensor | Lead with the answer |
| 17 | Chat LLM 4-11 s | Keep |
| 18 | Chat safety OK | Keep + safety test set |
| 19 | Chat doesn't know "early look" | Add knowledge entry |
| 20 | Time window ignored | Parse time ranges in router, "nothing new since X" |
| 21 | Unknown incident id answered as another | "No such incident (latest is X)", never carried forward |
| 22 | "hi"/"?" refused | Friendly hello + 3 example questions |
| 23 | Chat bursts heat NPU to 90 C | Leave as is (guard handles it) |
| 24 | Multi-part question half answered | Route multi-part questions to the LLM |
| 25 | Bottom nav see-through, hides handover buttons | Opaque nav + bottom padding |
| 26 | Two identical sun icons | Sun/moon theme toggle + gear for settings |
| 27 | Sensors help text stale | Text from the real data source, collapsed by default |
| 28 | "Since" card with all zeros | Hide when all counts are 0 |
| 29 | Map tree unreadable | Make it look better + leaf labels on zoom + sensor search |
| 30 | History page OK | Keep |
| 31 | Chat silence handled | Keep + countdown and live level bar |
| 32 | First mic test missed | Keep 8 s window; the transcript not being written (upload refused) is a MAJOR bug: must fix (see voice CSRF item) |
| 33 | "Stop reading" on empty chat | Show only while speaking |
| 34 | Placeholder clipped | Shorter placeholder |
| 35 | Chat suggestions static | Context-aware suggestions (open incidents first) |
| 36 | Fast path 2 readings | Keep 2 readings |
| 37 | "AI is writing the report now" when idle | Show real ETA; "writing now" only while NPU runs it |
| 38 | Stale "8 readings" text | Build from live gate rule |
| 39 | Fast-path title = pattern name | Value + limit title |
| 40 | Two "ANALYSING" chips | Merge to one |
| 41 | Incident id gap after restore | Keep the id counter with the state |
| 42 | Recursive read lock -> freeze | Fix now (done in code: inner RLock removed; deploy pending) |
| 43 | Panic leaves engine/workflow lock held | Defer unlock |
| 44 | htpd restart pile-up | Single shared restart |
| 45 | Supabase queue rewrites whole file per row | Save once per flush |
| 46 | Supabase queue stall / wrong-row delete | Row ids + park after N failures |
| 47 | Logs/archives never rotate | Add to rotateStateFiles |
| 48 | SMTP no deadline | Add deadline |
| 49 | NPU keeps running after chat client leaves | Cancel htpd call on disconnect |
| 50 | SSE no write deadline | 10 s write deadline per message |
| 51 | Retrieval index only grows | Prune archived incidents |
| 52 | Chat sessions >100 dropped at restart | Owner: accept loss; asked whether fog should store chats -> see #52b |
| 52b | Chats to fog? | No fog; archive overflow locally in chats_archive.json (rotated 90 days / 5 MB) |
| 53 | supabase_seen.json grows | Prune entries for incidents closed > 30 days |
| 54 | Code checks OK (limits, timeouts, caps, lock order) | Keep (no options needed) |
| 55 | Duplicate pH incident (fast path + early look) | No early look after a fast-path incident this episode + combined test |
| 56 | Fast-path short-window AI correct | Keep |
| 57 | Agents over-call sensor_fault on fast real rises | Rule-side corroboration check now; agent top-up later |
| 58 | Dead 12 h "more data" re-run | Skip when the prompt can't fit |
| 59 | Early looks merged across buildings | Apply the building/domain/link rule to early-look candidates |
| 60 | Early look card stays "analysing" | "Early look ready · full reading in ~N min", actionable |
| 61 | Gate view accurate | Keep |
| 62 | Card body (agent) contradicts AI report | Lead with AI report; agent view as "overruled" note |
| 63 | Relative time stale on open sheet | Refresh every 30 s |
| 64 | Card extras (next check, checklist) OK | Keep |
| 65 | Chat incident questions OK | Keep + regression tests |
| 66 | "Explain in simple words" returns title only | Send to LLM |
| 67 | "Sensor fault or real?" unclear | Explicit verdict from the final report (+ overruled agent note) |
| 68 | Chat ignores floor (KH 3 -> KH 98) | Building + level matching |
| 69 | "Happened before?" doesn't check history | Route to find_incidents + get_action_history |
| 70 | Early-look report invented a flow event | Guard against event claims on normal sensors |
| 71 | Ack flow with identity OK | Keep |
| 72 | Relative time on re-render | Covered by #63 |
| 73 | "Detected" uses AI time | Use incident opening time |
| 74 | Full reading independent of early look | Keep |
| 75 | Android notification | Keep |
| 76 | Heat early look lost in power incident | Covered by #59 |
| 77 | Batch held 25 min by a normal-again spike | Only abnormal-now sensors hold; critical member goes out at once |
| 78 | Fast path only before maturity | Fast path any time (2 critical readings, no open incident) |
| 79 | One-reading spike no AI (k=3) | Keep |
| 80 | TDS flatline needs 80 min | Keep 80 min; exactly-constant value faults at 30 min |
| 81 | Dust incident report good | Keep |
| 82 | Beyond-critical reading lowered to warning silently | Stays critical while the reading is beyond the critical limit; AI view shown as a note |
| 83 | Dust checklist generic | Outdoor-specific first steps |
| 84 | Watching "AI now" during hold | Real wait + reason, "abnormal for 8 readings (4 needed)" |
| 85 | Home hero | Owner: could be better -> see #85b |
| 86 | Sheet re-opens on resume | Banner instead of sheet |
| 87 | Resources fine | Keep + track over time on health page |
| 85b | Home hero redesign | "Do this next" card (worst open item + I'm on it/Open), "Also open" list, live readings line, "all other areas normal" |
| 88 | Board heat 92-95 C per AI run | Thermal budget scheduler (urgent never waits) |
| 89 | Board RTC 25 min ahead | Document only |
| 90 | Chat misses live critical readings | List all critical/warning from live state |
| 91 | Stale value shown as fine | Flag readings older than ~3 missed readings |
| 92 | Chat can't explain AI waits; "[unverified id removed]" shown | Gate-status chat tool + clean the marker |
| 93 | AGREE line works on board | Keep |
| 94 | Heat guard blanks good titles | Limit guard to temperature/room sentences |
| 95 | Late reading flipped pH verdict | #77 + "returned to normal at HH:MM after N abnormal readings" fact line |
| 96 | pH in two incidents | Covered by #55 |
| 97 | Auto-opened sheets steal taps (accidental ack) | Banner instead of auto-open + 1 s tap guard |
| 98 | "stepped up -2.40" | Up/down from the sign |
| 99 | Full readings held 16-26 min | Re-run the scenario on the board after #77 |
| 100 | "Since you last looked: 0 new" wrong | Fix counting (created/changed vs last-looked, live updates) |
| 101 | Incident cards + filters | Keep |
| 102 | Handover repeats the place | Keep + dedupe place |
| 103 | Search placeholder cut | Shorter placeholder |
| 104 | Prefetch evidence thin | Prefetch sensors that mature inside an open batch; reuse stays off |
| 105 | Three stale rules | One rule: stale after 3 missed readings, everywhere, counted as no data |
| 106 | Data health vs gate on the glitch | Covered by #77 |
| 107 | Impossible CO2 shows as fault status | Keep |
| 108 | Campus API / MQTT retry noise | Back off + "offline since" status |
| 109 | Impossible value never alerts | Count sensor_fault readings toward the gate regardless of pattern |
| 110 | "Critical right now" for recovered sensors | Count current readings vs limits |
| 111 | Stopped feed flagged after 25 min | Covered by #105 |
| 112 | Critical hidden under a warning group | Group by site tree / same sensor only, worst first, never collapse critical |
| 113 | Voice upload refused (CSRF JSON-only) | Allow audio/wav on /api/chat/voice + Origin-header test |
| 114 | Board mic heard the owner | Keep |
| 115 | Raw server error shown for voice | Friendly message, raw error to log |
| 116 | Reconnecting flash on wake | 5 s delay + refresh on wake |
| 117 | Typed chat in UI | Keep |
| 118 | "Fog server" jargon | Plain wording, only when relevant |
| 119 | Voice error note stays | Clear status notes on send |
| 120 | Full-screen "No data" after restart | Banner over the dashboard; full screen only when no data ever |
| 121 | Order of work | Fix all, test, deploy (owner OK given), re-run tonight's scenario |
- 2026-11-28 04:30: deleted (owner #12): 5 state-backup tgz, incidents.jsonl.bak_20261021_1555, htpd.log.root_old
