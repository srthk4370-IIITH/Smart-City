# r3 chat tools: fog with device fallback + cross-domain tools (2026-11-06)

Implementation: `Code/smart-city-edge-agent/app/backend/chat_fog.go` (+ wiring in `chat.go`), training twin
`tools/tools_r3_impl.py`. Schemas: `data/final/tools_r3.json` (`chat` = 21 tools, `incident` = the 4 reasoner tools,
unchanged). Prompt: `tools/chat_header_r3.txt` (4,579 tokens) + `tools/chat_system_r3.txt`, byte-identical to the
backend's embedded copies (`TestChatHeaderR3MatchesTraining`). The r3 prompt is sent only with the profile keys
`chat_think=adaptive` and `chat_prompt=r3`. Earlier models keep their own prompts.

## Design rules (from `2026-10-23_reasoner_research/DECISIONS.md`)
- **Device store:** the newest 1000 incidents in full (`store.go` retention) plus an **all-time index row** per archived
  incident. The index is `incidents.archive.jsonl` read back stripped to id, time, title, severity, label, flagged
  sensors (pattern/status/fault kind), approval, workflow, outcome and injected. Every chat tool counts over full records
  plus the index, so offline counts stay exact. Before this change, archived incidents were invisible to chat.
- **The backend decides the fallback.** A fog tool first calls `POST {fog_url}/v1/tool {"name","args"}` (profile
  `fog_url`, optional `fog_token`, `fog_timeout_ms` default 2000). If the fog URL is unset, the call times out, or it
  returns HTTP != 200 or bad JSON, the same query runs on the device store. The result then carries
  `"source":"device_fallback","fog":"unreachable"` and a coverage block. After a failure the fog is skipped for 30 s, so
  one answer never waits for two timeouts. A fog reply that contains `error` (bad arguments) is passed on as the
  answer, not treated as an outage.
- Online results carry `"source":"fog"`. Device tools keep `coverage.source:"device"`; their note reads
  `device store` when the fog is reachable and `device store, fog offline` when it is not.
- **Prompt line** (live): `The device is online: the fog server is reachable.` or `The device is offline: the fog server
  is unreachable (last sync YYYY-MM-DD HH:MM|never synced).`, followed by `Full incident records on the device since
  YYYY-MM-DD.` The state comes from the last fog contact (reachable = success within 3 min). A background
  `/v1/status` probe runs at most once a minute, from prompt builds and keep-warm. The last sync is kept in
  `state/fog_state.json`. The device-time hour is now floored in IST, because `Truncate(time.Hour)` gave XX:30. The
  r3 path only.
- All tools are read-only. Results are capped: at most 10 items, 8 groups, 5 passages.
- `FogHandler` (chat_fog.go) serves `/v1/tool` and `/v1/status` with the same code over a store that holds every
  incident in full. It runs on a fog box or laptop with this backend and a large `SCE_MAX_INCIDENTS`, and is used by the
  tests. It is not mounted on the board. The Supabase side (FOG_OPTIONS.md) is not built: whichever fog is chosen must
  answer this HTTP contract.

## Tools (old = rsn_v3 r2 header, 15 tools; new = 6; changed = 2)
| tool | status | args (* required) | online result | fallback result |
|---|---|---|---|---|
| count_incidents, find_incidents, sensor_faults, get_sensor_history, list_sensors, domain_health, get_action_history, rank_readings, current_levels, recent_incidents, open_incidents, faulty_sensors, what_if | old, device | unchanged | device store incl. the all-time index; note `device store` | same; note `device store, fog offline` |
| get_incident | **changed** | id* | full record on the device; for an archived id the fog's full record + `source:fog` | archived id: index row (no root cause, `steps: []`) + `source:device_fallback`, `fog:unreachable`, note "full record archived off the device ... index row only" |
| search_knowledge | **changed** (was a stub) | query*, k (1-5, def 3) | top-k passages of the fog knowledge base (46: IS 10500, NAAQS, WHO 2021, CPCB AQI, campus limits, SOPs, manuals, 2 post-event reports) | the 16-passage device cache (`fog_kb_cache.txt`: limits + key SOPs) + coverage `{passages:16, complete:false}`; `available:false` when nothing matches |
| fog_search_history | new, fog | time*, domain, metric, node, severity, label, text, limit (1-10, def 5) | `total`, newest-first items {id, time, title, severity, label, domains, outcome, root_cause}, coverage {from = first record, incidents = all, complete:true} | same query on full records + index rows (root_cause null for archived). Coverage {from = oldest full record, incidents = full records, complete = period starts inside the full window, index_from, counts_exact (false with `text`: archived incidents match on title/label only), note} |
| fog_analytics | new, fog | analysis* (incident_trend \| resolve_time \| sensor_monthly), time*, bucket (month\|week), group_by (label\|domain), domain, metric, node, severity, label | trend: zero-filled buckets, total, peak, mean_per_bucket. resolve: closed, mean_h, median_h, top 8 groups. sensor_monthly: months {month, mean (weighted by readings), min, max, days} | trend: the same counts from the index (`counts_exact:true`). resolve: only incidents with full records (close times are not in the index). sensor_monthly: only readings still on the device (board: 7 days of 5-min; training store: 60 days hourly). complete + note say so |
| fog_status | new, device | none | {fog:"reachable", last_sync, pending_uploads, device_store {full_incidents, since, index_rows, index_from}, fog_incidents, source:fog} | fog:"unreachable", last_sync (or null), pending_uploads = incidents newer than the last sync, source:device_fallback |
| co_occurring_incidents | new, local | id*, window_min (10-240, def 60), other_domains_only (def true) | anchor {id, time, title, domains}, total, items {id, time, title, severity, label, domains, offset_min (floor, signed)}, sorted by abs(offset) | same (device store + index) |
| recurring_issues | new, local | time*, min_count (2-50, def 3), by (sensor\|node), domain, metric | groups (keys with count >= min_count), top 8 {sensor\|node, count, first, last, top_label, outcomes{}, open} | same |
| compare_periods | new, local | period_a*, period_b* (time objects), domain, metric, node, severity, label | a/b {from, to, count, by_severity, top_labels (3)}, b_minus_a, change_pct (null when a = 0) | same |

Demo injections are excluded everywhere. Time objects work as in count_incidents: presets or from/to, with `to` exclusive.

### Examples (r3 training store, now 2026-10-22 12:00; device full records since 2026-06-24, index from 2025-11-01)
`fog_search_history {"time":{"from":"2026-01-01","to":"2026-02-01"},"domain":"water","limit":1}`
- online: `{"source":"fog","total":56,"items":[{"id":"INC-0710","time":"2026-01-31 10:13","title":"level gradual decrease: VN ...","severity":"warning","label":"water_supply_issue","domains":["water"],"outcome":"fixed_by_action","root_cause":"inflow stopped, tank level falling at VN ..."}],"coverage":{"from":"2025-11-01","to":"2026-10-22 12:00","incidents":2978,"complete":true}}`
- fallback: the same `total` (56: the index is exact) and `"root_cause":null`, with `{"source":"device_fallback","fog":"unreachable",...,"coverage":{"from":"2026-06-24","incidents":1000,"complete":false,"index_from":"2025-11-01","counts_exact":true,"note":"fog unreachable: full records for the last 1000 incidents on this device (since 2026-06-24); older incidents from the all-time index (no root cause or checklist)"}}`

`fog_analytics {"analysis":"resolve_time","time":{"preset":"this_year"},"group_by":"domain"}`
- online: `closed 2322, mean_h 14.6, median_h 14.5`. Fallback: `closed 848, mean_h 14.2`, only the full-record window, `complete:false`, note "fog unreachable: only incidents with full records on this device (since 2026-06-24)".

`search_knowledge {"query":"drinking water pH limit"}`
- online: SOP-WT-02 and KB-IS10500-PH ("pH value: acceptable range 6.5 to 8.5 ..."). Fallback: the same two passages from the cache. `{"query":"AC service contract"}` online gives DOC-AC-CONTRACT. In the fallback the cache does not hold it, so the model must say it cannot look it up.

## Incident (reasoner) toolset: unchanged on purpose
`related_context, get_sensor_history, get_action_history, find_incidents` stay as trained. A fog-backed "similar past
incidents" tool was not added, for three reasons:
1. The early alert allows 1 call and refinements 2 (D7). A fog round-trip with a 2 s timeout would sit on the alert's
   critical path, and the 40-55 min gate plus real compute cuts are the current latency goal.
2. find_incidents now already reaches every past incident through the all-time index, and retrieval.go supplies
   similar past AI reports.
3. The 35,151 r2 incident rows and the Go report validator gate are tied to the 4-tool header. Changing it means
   re-rendering and re-gating them, with no measured weakness that needs it.

## Verified
- `go test ./...` in app/backend passes, including:
  - `TestChatFogParity`: 92 calls (46 x fog online/offline) on a 90-incident fixture (40 archived). Go equals Python
    in fields, types and values; max numeric difference 0.
  - `TestChatFogFallbackUnset`: fog unset, archived incidents still counted, fog line "never synced".
  - `TestChatFogFallbackDownAndTimeout`: HTTP 500 and a 200 ms timeout give a fallback in under 450 ms, and the
    second call does not wait.
  - `TestChatFogOnline`: source fog, coverage, reachable line, device note, and an error answer that does not mark
    the fog down.
  - `TestChatHeaderR3MatchesTraining`: header and system byte-identical, tools equal tools_r3 chat, prefix render,
    keep-warm header, device-since sentence.
- Fixture and outputs: `tools/parity_r3_cases.json`, `parity_r3_out_py.json`, `parity_r3_out_go.json`.

## Open (owner)
- Which fog serves `/v1/tool`: a Supabase Edge Function over Postgres (FOG_OPTIONS.md) or a laptop/fog box running
  this backend's `FogHandler`. Also the sync uploader (outbox). `pending_uploads` currently counts incidents newer
  than the last successful fog contact.
- The 9/15-tool prompts still show the IST half-hour (`Truncate`) in their device-time line. Only the r3 path is fixed.
