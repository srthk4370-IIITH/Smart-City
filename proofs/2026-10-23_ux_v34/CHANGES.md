# UX release v34: approval lifecycle, data quality, maintenance, shift summary (2026-10-23)

**Specs:** `proofs/2026-10-23_reasoner_research/APPROVAL_AND_MEMORY.md` §3 and `DECISIONS.md` ("Approval and action
memory"); the UI principles come from `proofs/2026-10-21_ux/UX_RESEARCH.md`.
**Not touched:** model prompts, policy, refine thresholds, htpd, features, training. The board was not touched and
nothing was committed.

## Backend (Go)

### New: `backend/workflow.go`
- **`workflow` field**, separate from severity and status. States: `analysing`, `needs_decision`, `in_progress`,
  `resolved`, `closed`, and `interrupted` (the analysis failed).
- **Per-step checklist.** Built from:
  - the report's action;
  - the flagged agents' actions;
  - the rules when there is no valid AI report;
  - the domain playbook when the AI says only "monitor".

  At most 5 suggested steps. Each step can be Done or Not needed (with an optional note) or reopened. Operators can
  add up to 5 steps of their own. At a re-check, steps that are no longer suggested are withdrawn, and new ones are
  marked "new".
- **Append-only event log.** Every click and automatic transition adds one row: who, when, what and a note. It is
  persisted inside the incident in `state/incidents.jsonl`. A restart reloads it, which is tested.
- **Acknowledging** records the owner and the time and never changes severity. Ticking or adding a step acknowledges
  automatically.
- **Close** needs one of 6 outcomes. False alarm and no action needed also need a note. A closed incident is final:
  any further action returns 409.
- **Dismiss** = close as no action needed (the default) or false alarm, with a note required.
- **Approve** = acknowledge plus every open step accepted, logged as `approve_all`. `SetApproval` maps onto the
  lifecycle for old callers.
- **Re-checks** (hook in `refine.go`, analysis unchanged):
  - **Worse on an acknowledged incident:** back to `needs_decision`, `worse_at` is set, and the SSE event carries
    `reack:true`.
  - **Readings back to normal:** `resolved`, with the close outcome pre-filled.
  - **After close:** logged only.
- **Workflow tick** (every engine poll, from `main.go`):
  - **Reminder:** an unacknowledged critical incident re-alerts once after 15 min.
  - **Live return to normal:** all flagged sensors normal for at least 6 readings sets `resolved`. Abnormal again
    goes back to the previous state.
  - **Auto-close** after 24 h resolved, unless the owner still has an open step.
- **30-day rule.** A sensor fault within 30 days of a repair adds the step "Replace the … sensor". A repair is a close
  as repaired, or a sensor step marked Done on an incident that then resolved.
- **Grouping** for the list: repeat incidents on the same flagged sensor, or the same domain and pattern, within
  30 min collapse into one group, led by the newest.
- **Memory.** `History()` returns earlier incidents on the same sensor with steps, outcomes and owner, plus
  recurrence within 7 days and maintenance rows. Maintenance rows are kept in `state/maintenance.jsonl`, which is
  append-only. Model prompts are unchanged.

### Changes to existing files
- **`reason.go`:** `Incident` embeds `WorkflowState`. Creation and analysed transitions are added, and `SetApproval`
  is mapped onto the lifecycle.
- **`store.go`:** old records are migrated on load:

  | Old record | Becomes |
  |---|---|
  | approved | in_progress (legacy, steps accepted) |
  | dismissed | closed, no_action_needed (legacy) |
  | running | interrupted |

  `persist` now marshals under the read lock.
- **`refine.go`:** a single hook after a revision is recorded. No threshold or analysis change.
- **`domainhealth.go`:**
  - Tiles count every incident that is not closed. An unowned incident also has to be within the 12 h window; an
    owned one counts until it is closed.
  - Each tile incident carries `workflow` and `owner`.
  - Out-of-service sensors are counted as `out_of_service` and never raise a tile.
- **`server.go`:**
  - New endpoints: `POST /api/incidents/{id}/ack|close|steps|steps/{sid}`, `GET …/events`, `GET …/history`.
  - Approve and dismiss are kept.
  - The list carries the workflow, owner, timestamps, step counts, `group` and `group_size`.
  - `/api/live` ignores out-of-service sensors for the role status.
  - `/api/maintenance` takes an `operator` and logs a row.
- **`engine.go` / `dataquality.go`:** a new `maint_until` field on the sensor state.
- **`main.go`:** calls the workflow tick, and the SSE `live` event carries quality, reason and `maint_until`.

### Clocks
People timers use the device wall clock: the reminder, auto-close, grouping and event times. Re-checks stay in sensor
time. Sensor time runs about 150x faster in the demo, which would fire a "15 min" reminder 6 s after an alert.

## Web UI (`device/web`, `sw.js` → `sce-shell-v34`)

### Operator picker
- A header button opens a sheet with this device's names. Operators can add or remove names. The list is stored in
  localStorage with try/catch.
- The chosen name is forgotten after 30 min idle.
- An action with no name chosen opens the picker first.

### Incident sheet
- A workflow chip (glyph and word) and the countdown "Next check at 1.5 h · in ~N s/min", from sensor time and the
  poll rate.
- Banners:
  - "Got worse since Ravi acknowledged it…" (`role=alert`);
  - "Back to normal since … Close it as …?";
  - the reminder.
- **What to do** is now the checklist:
  - Done / Not needed, with quick reasons and a note, and Undo;
  - "+ Add step";
  - the source and the why for each step, and who did it and when.
- **Activity** timeline: newest first, with 6 shown and "Show all".
- **History of this sensor.**
- Footer:

  | State | Footer |
  |---|---|
  | Needs decision | **I'm on it** / Dismiss… |
  | Owned | "Ravi is on it since …" + Close… (and "Take over as …") |
  | Close… / Dismiss… | Outcome radio group (6, or 2 for dismiss) pre-filled, note, Confirm |
  | Closed | Outcome, by whom, when, note |
- Focus and drafts survive live re-renders.

### Incident list
- **Filters:**
  - state chips: All / Needs decision / In progress / Resolved / Closed / Analysing;
  - domain and date selects;
  - text search over id, title, sensors, owner and outcome.
- **Grouping:** "▸ N related" expands the group.
- **Cards** show the workflow chip, with the owner or outcome, "x of y steps ticked" and the countdown.

### Health tiles and data quality
- Health tiles show "1 needs decision · 1 in progress (Ravi)" and "◆ Data: 1 out of service". The domain sheet has a
  "Sensor data quality" section with the reasons.
- Data-quality chip (◆ and a word) on live rows, domain-sheet rows and the sensor sheet, where the reason is a tap
  away.
- Out-of-service rows read "⊘ Out of service" in grey.

### Sensor sheet maintenance
"Mark out of service" (optional until-time, sensor time, default 24 h; reason) / "Back in service" / "Sensor replaced",
with a confirmation. All call `POST /api/maintenance`. The backend already held the event gate during maintenance;
v34 adds the tile and live suppression.

### Shift summary
- On opening: "Since HH:MM: N new · N got worse · N resolved", based on the last visit stored per device in
  localStorage with try/catch.
- It can be dismissed and is announced politely (`aria-live`).

### Toasts
The reminder toast (`role=alert`, Open), "acknowledge it again" on a worse re-check, and back-to-normal.

### Deep link
`#incident/INC-0007` opens that incident; the Android notification uses it.

### Small fixes
- **Tab labels at 360 px + 130 %:** they size to their content and are no longer cut ("INCIDEN…").
- **WebView fallbacks:** `@supports not (container-type)` fallback for the hero counters, and a `color-mix` fallback.
- **Overflow pass:** the clock hides at ≤400 px to make room for the operator button. Tile time, maintenance button
  labels and the live-row unit now wrap.

## Android

### `EdgeService`
- One notification per incident, updated in place (tag = id), only while the dashboard is not in front:
  - a new Critical incident once the analysis has finished;
  - a "got worse" re-check;
  - the 15-min reminder.
- Incidents present when the service starts are not re-announced.
- In-progress or closed incidents lose their notification.
- Tapping a notification opens that incident.

### `MainActivity` and the manifest
- `MainActivity`: a `foreground` flag (`onResume`/`onPause`), `EXTRA_INCIDENT` validated as `INC-\d{1,8}`, and
  `onNewIntent` sets the location hash, or the incident loads with the page.
- Manifest: `launchMode="singleTop"`.

## Tests and evidence (this folder)

| What | Result |
|---|---|
| `go vet ./...` + `go test -p 1 -v ./...` (WSL, `GOMAXPROCS=2`, `nice`) | OK, 92 passed, 0 failed (`go_test.log`). |
| New Go tests (`backend/workflow_test.go`) | 13 tests: state machine and events with reload, auto-ack on a step, approve/dismiss compatibility, reminder once, live resolve and auto-close (including the owner with an open step), re-ack on worse, re-ack through the real refine pipeline, the 30-day rule, recurrence within 7 days, grouping, health counting and out-of-service, legacy migration, the HTTP API (new endpoints, old approve/dismiss, events, history, list). |
| `ui_health_check_v2.js` | OK (8 scenarios) |
| `ui_stream_check.js` | OK |
| `ui_incident_summary_check.js` | OK |

All three are logged in `ui_node_checks.log`.

- **`ui_v34_check.js`** (new; CDP, headless Chrome, host `--mock` backend seeded through the real API): **83/83 OK**
  at 412×915, 360×780 + 130 % text, and 1440×900. 0 page errors. Files: `ui_v34_check.json`, `ui_v34_check.log`,
  `seed.json`, and 39 screenshots in `screens/`.
- **Overflow audit** (`../2026-10-23_ui_overflow/ui_overflow_audit.js`; 10 configurations × 19 states): **0 overflow
  findings**, 35 ellipsis, 0 page errors (`overflow_audit.json` / `.txt`). The first run found 52 findings, which the
  "v34 overflow pass" CSS fixed.
- **Builds:** `build.sh` (vet, arm64 and host) and `android/build_apk.sh` both OK. The MD5 hashes are in
  `manifest.json`.

## Left out or deviations
- **Auto-close outcome.** It uses the pre-filled outcome when the owner did steps (for example fixed by action), and
  "resolved on its own" otherwise. The note is always `auto`.
- **Health tiles.** Unowned incidents older than 12 h of sensor time are listed by the app as "Earlier, still awaiting
  your decision" rather than on the tile. This keeps the existing health test.
- **Not built:**
  - the "warning after 60 min" reminder (spec §3.4; the task named only critical at 15 min);
  - a PIN;
  - reasoner memory lines and `get_action_history` (the prompts may not change);
  - cloud sync;
  - the `maintenance` row written when a "Replace sensor" step is ticked. That needs the engine's history drop, so it
    is left to the "Sensor replaced" button.
- **History** reads the 1,000 incidents in memory, not the archive.
- **Not verified on the board** (off-limits): WebView rendering, Android notifications, tap-to-open.
