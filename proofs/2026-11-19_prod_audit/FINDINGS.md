# Production / UX / research audit (2026-11-19, 3 Sonnet read-only audits)

Paths: backend = Code/smart-city-edge-agent/app/backend, web = app/device/web, android = app/android.

## Production must-fix (ranked)
1. Engine state in memory only: after a reboot the board is blind ~50 min, alerts re-fire (engine.go). Persist bank + episode flags.
2. Restart mid-incident: running -> failed, cannot host promotion, duplicate incident opens (store.go:67, promote.go:33).
3. Store compaction vs append lost-update window; open incidents may be archived (store.go:112-191).
4. Watchdog cannot fail over when r.active is stuck (watchdog.go:49); pending queue in memory, unbounded (reason.go:300-316).
5. Demo/injection endpoints live in production, unwatermarked (server.go:758).
6. APK debuggable=true + cleartext (AndroidManifest.xml:20-21); adbd exposure check.
7. Auth: all GETs open on LAN; fog ingest open without token; no CSRF/content-type check; one shared token (auth.go:43, prod_fog.go:408, server.go:246).
8. Durability: no fsync/write-error check (store.go:116, rules_config.go:247, chat_fog.go:113); unbounded archive/daily/fog_rows; no disk alarm.
9. No recover() in tick loop/handlers (main.go:60-77); htpd restart-loop cap/backoff (htpdgate.go).
10. Notifications: no escalation for unacknowledged criticals; nothing reaches anyone if channel unconfigured (prod_alert.go).
11. Operator accountability: free-text name, last-write-wins, silent takeover, one-click dismiss of criticals, no undo/reopen; dismissals poison memory (workflow.go).
12. Sensor lifecycle: unknown/renamed sensors silently rejected, no hot reload, no gap re-baselining (sensors.go:44, dataquality.go:114).
13. Static thresholds: holidays/night/season (heatwave, monsoon) -> incident floods; no bounds/diff/revert on card/rule edits.
14. Event mode for mass alerts (fire/flood): group per zone, push the rules critical at once; thermal queue timeout (reason.go:295-327).
15. Clock: single source (campus Date header); 1970 clock if API down at boot (clocknet.go).
16. Fleet: per-board id/token, signed OTA + auto-rollback, /api/metrics + heartbeat (disk, heap, temp, htpd restarts, model version), backups of state/, support bundle.
17. Model side: AI-timeout banner + severity floor from rules; claim verifier on every chat answer; stale memory versioning; daily on-board self-test; prompt overflow counter.

## UI/UX (top)
- Site tree = nested list, "B8"/"BE" literal glyph bug (phase1.css:38); not a graphic; map dots unlabelled, colour-only, no keyboard.
- Internal ids/jargon shown (S1.E4, etype, "(api)"); tiny dark-theme text/targets (styles.css:604,696).
- Times inconsistent, no zone label; 6+ timers not gated on visibility.
- No export/print/share of a report; no assign/notes/due; toasts without actions for criticals.
- Disabled buttons without reason; interrupted incidents without Retry.
- Search incidents only; no sensors/map search; English only, no units setting.
- Offline: stale data without "updated N min ago".

## Feature ideas
QR-hashed report + separate viewer site (owner idea); shift handover view; push/SMS escalation with on-call; printable/PDF report; maintenance snooze; saved views per role; map/tree time slider replay; language/units; event mode.

## Research positioning (from search snippets, to verify)
Likely new: fully on-device multi-agent RCA on Hexagon NPU (10-stream htpd), per-sensor fine-tuned agents with tool calls, outcome memory, spec cards, edited reasoner. Comparables: Hitachi PHM 2025 HVAC multi-LLM, arXiv 2510.03859, SEMAS 2602.16738, AgenticTwin 2608.11679, TSAutoBox (VLDB26 ws), llm.npu 2407.05858, HeteroLLM 2501.14794, T-MAN 2511.11248, NPU stage study 2605.27435.
Metrics to report: per-severity P/R/F1 on a frozen blind set, false sensor_fault rate, grounding rate, stage latency p50/p95 (sensor-time vs compute), NPU tok/s and scaling, J/incident, 0 bytes out, 72 h soak, ablations (tools, memory, cards, fine-tune), cloud-LLM baseline.
Reviewer attacks: single site + synthetic/self-distilled labels, rules may do most of the work, 40-55 min gate, host vs device gap, no frozen test set, no cloud baseline.
