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
| 11 | **Early AI on strong warnings:** NOT enabled: the v5 study rerun shows no shape clears (flip 40–76 %, limit 15 %). | `earlyai.go` (existing) | | `earlyai.go` (existing) | `ai_early_k`, `ai_early_shapes` |

## Verification

The board was fed through `/api/ingest` by `feeder3.py`. The scenarios were a KH level 03 AC failure (heat, AC off), a critical pH at KH level 98, and a power-factor drop at the SB00 feeder. The state was backed up first and restored after every run; the sweep states are kept on the board as `state_feat1127_run1..4`. Final build: edge-agent 15ed1007, APK 2e31ae51. Rollback: `adb install -r -d deploy/before_features.apk`.

| Run | Build | What happened | Fix |
|---|---|---|---|
| 1 | first deploy | Heat (KH03) and SB00 power factor merged into one incident. The report invented "the PF dip is caused by the AC stopping". Cause: two **inferred** `outdoor-for` links in the auto site tree related the two sensors. | Cross-building relations use confirmed links only (`confirmedIndex`) |
| 2 | + confirmed links | **Split works:** separate incidents. The PF sensor still waited, mature, in the batch opened by the pH sensor, which was waiting for the young KH03 temperature. The reasoner called the corroborated heat a "sensor heating itself", and that report was then rejected for an invented number (template report shown). | A mature sensor unrelated to the open batch goes out at once (`releaseUnrelatedLocked`) |
| 3 | + early release | The PF incident went out **before** the heat incident. The corroborated-rise guard **fired** and overruled sensor_fault, but the title "Suspect … readings" and one contradicting sentence stayed. The PF report blamed "the AC load change": KH AC sensors were attached as context to the SB00 feeder. | Guard catches "suspect … readings" / "sensor problem" and removes those sentences; the context picker keeps non-weather context to the same building |
| 4 | final | PF: context is only SB00 power_kw, report clean. Heat: **critical**, "Room temperature 34.5 C, AC unit in error". pH: critical, 35.6 s. All correct. | — |

Other checks:
- **Watching strip** (screenshots in `ui/`): rows like "Water pH · KH-98 — 3 of 4 abnormal readings · AI in ~5 min" with progress bars, and "AI at work: INC-0015 domain agents · ready in ~30 s". `tele_run*.jsonl` holds the 20 s samples.
- **Chat streaming** (`chat_stream.jsonl`): first words after 2.6 s of a 4.0 s answer for an explanation question; the draft equals the final answer. The first version showed thinking text and the closing `</think>` tag; that is fixed and covered by a test.
- **Prefetch shadow:** 3 comparisons. 2 agree (power factor, 1 reading older, same rule finding). 1 differs (temperature, 2 readings older, the rule finding had changed, so the reuse rule would not have reused it). Too few to switch reuse on; it stays `agent_prefetch=shadow` and collects evidence.
- **Old incidents:** INC-0001..0011 auto-closed by the 3-day rule; INC-0012 dismissed "no action needed" (owner request).
- **History page** renders on the board with KPIs and charts. The severity chips were cut at phone width; fixed (wrap).
- Go: full `go vet` + `go test` pass. `TestChatGPUWarmHeaderOnly` failed once under parallel load and passes alone (timing-sensitive, pre-existing).

## Still open
- **Early AI: stays OFF.** The full v5 rerun (440 events, 1,102 AI runs, today's board models and backend) shows no shape clears at any k from 3 to 7. Early verdicts change by the full gate 40–76 % of the time (limit 15 %), and flatline, noisy and fault lose 23–33 pp severity accuracy. Details: `proofs/2026-11-12_early_ai/STUDY.md` "v5 rerun". Side finding: 19 % of the AI runs there had the reasoner report rejected, most often for a warning checklist without an inspect/review action.
- **Prefetch reuse:** needs about 20+ shadow comparisons with ≥ 95 % agreement when the rule finding is unchanged.
- **Reasoner judgement on corroborated heat:** it misjudged it in 2 of 4 runs ("sensor heating itself", "suspect readings"). The guard now corrects the wording and severity. If this keeps happening, it is a top-up case (owner: top-up only if the errors keep varying).
- **Viewer clock:** tested by unit tests only (the laptop reaches the board over loopback, which is ignored by design).
