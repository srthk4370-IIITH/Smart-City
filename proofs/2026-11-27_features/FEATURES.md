# Features and fixes, 2026-11-27 (owner answers after the night sweep)

Owner decisions are recorded in `questions.md` (answered section). Code is in `Code/smart-city-edge-agent/app`.

## What was built

| # | Feature | Where | Switch |
|---|---|---|---|
| 1 | **Batch split by site-tree distance.** Same building = related; different buildings = separate incidents unless the same domain or a site link. The split log shows the tree distance against the diameter. | `backend/batchsplit.go` | `batch_split=0` = old single batch |
| 2 | **Auto-close after 3 days open** with nobody working a step (outcome "no action needed", note "auto: open 3 days with no decision"). | `backend/workflow.go` | `stale_close_days=N` (0 = never) |
| 3 | **Board clock without the laptop:** the HTTP `Date` header of every trusted reply (campus, heartbeat, fog, Supabase), plus the clock of phones viewing the dashboard (median, ignored when network time is in use, at most 7 days of change, 2 agreeing viewers unless the app clock is unset). | `backend/clocknet.go`, `clockviewer.go`, `app.js clockHelp` | — |
| 4 | **Report wording guards (instead of a top-up):** "stop the AC" when the AC units read 0; "ventilate" for an outdoor dust event; "sensor jump" when two temperature sensors rose together. Each rewrite is a logged repair. | `backend/reportfix.go` | — |
| 5 | **Watching strip** on Home: each sensor on its way to an AI check ("3 of 4 abnormal readings, AI in ~5 min"), the open batch, and the incident being analysed ("Domain agents 2 of 3 · ready in ~30 s"). | `backend/gateview.go` (`/api/status` gate + progress), `app.js renderWatch` | — |
| 6 | **Chat streaming:** tool look-ups appear as steps and the answer appears word by word as a draft. The checked final answer replaces it. Thinking text and tool-call text are never shown. | `backend/chatstream.go`, `chat/chat.js` | — |
| 7 | **Agents during the gate wait (shadow mode):** when a batch opens, the opener's agent runs while the NPU idles. At close the real agent still runs, and both answers are compared in `state/prefetch_shadow.jsonl`. Reuse (`=1`) only after the shadow log shows agreement. | `backend/prefetch.go` | `agent_prefetch=shadow` (deployed) / `1` / absent |
| 8 | **Incident cards:** a mini chart of the 4 h window, the building and floor, a building filter, and a **Shift handover** text (copy/share). | `/api/incidents` place + spark, `app.js` | — |
| 9 | **History page:** 24 h / 7 d / 30 d / 90 d; Timeline, Heatmap, Breakdown and List modes; filters; KPIs against the previous period; recurring sensors. | `backend/history.go`, `web/history.js/css` | — |
| 10 | **Android notifications:** "I'm on it" and "Open" buttons, a Warnings channel, sensor-fault labels, grouping, building and floor in the text. | `android/.../EdgeService.java`, `IncidentActionReceiver.java` | — |
| 11 | **Early AI on strong warnings:** NOT enabled. The per-shape study is being rerun with reasoner v5 (`proofs/2026-11-12_early_ai`, raw_v5); it is enabled only for shapes that clear. | `earlyai.go` (existing) | `ai_early_k`, `ai_early_shapes` |

## Verification

(filled in below after the board run)
