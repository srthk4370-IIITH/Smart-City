# Approval, action memory and cloud (Supabase) access: discussion document

**Date:** 2026-10-23. **Status:** discussion only. Nothing is final until the owner answers the questions in §6. No code
was changed, the board was not touched, nothing was committed. Only generic web searches were made.
**Companion files:** `REASONER_DESIGN.md` (on-device reasoner, read-only tools), `FOG_OPTIONS.md` (fog and storage options),
`tools.json`, `store_schema.sql`.

**The owner's requests (2026-10-23):**
1. "Even the local model should have access to cloud data and inferences."
2. "It should also store what steps were taken last time, and the approve thingy and all."
3. "The approve thingy should also improve as per the requirement. Research how the approve button should actually
   function."

**The owner's ground rules (from first principles):**
- **(a) Store everything:** every incident, every re-check, every action taken and its outcome.
- **(b) Keep the model on the device:** reasoning, tool-calling chat and memory of past actions all run on the QIDK and
  work offline.
- **(c) No cost now, and a cloud that does not depend on the laptop:**
  - the cloud is the **Supabase free tier**: Postgres + pgvector in the Mumbai region (ap-south-1), with an
    automatic REST API (PostgREST), Edge Functions, and row-level security (RLS) with a per-device identity;
  - the board syncs to it directly over Wi-Fi;
  - free projects pause after about a week with no traffic, so the board must stay fully offline-capable;
  - a paid plan or host comes later, with the same schema and API.
  - This replaces the earlier "laptop as cloud" idea. The laptop stays an optional local fog and model box.
  - Pinecone was rejected: it is vector-only.
- **Keep it simple.** Avoid enterprise complexity.

**Unchanged:** nothing is actuated automatically. Every action is a recommendation for a person to carry out.

---

## 0. The recommendation in one page

1. **Turn Approve into a short checklist.**
   - **Today:** one Approve/Dismiss button covers the whole incident.
   - **Proposed:** the operator **acknowledges** the incident ("I'm on it") and ticks each recommended step as **Done**
     or **Not needed** (with a note). They can add a step of their own.
   - When the readings are back to normal, the operator **closes** the incident with an **outcome**: fixed, sensor
     replaced, sensor repaired or recalibrated, false alarm, no action needed, or resolved on its own.
   - Dismiss stays: it closes the incident as "false alarm" or "no action needed", and still needs a note.
2. **Re-checks drive the workflow and never hide it.**
   - **Elevated after acknowledgement:** the incident goes back to "Needs decision" and has to be acknowledged again.
   - **Curbed:** a note only.
   - **Back to normal:** the app suggests closing it and pre-fills the outcome.
3. **Record who, when, what and why.** Every click becomes one row in an append-only event log (`incident_event`). The
   operator picks their name from a short list on the shared device.
4. **The reasoner remembers.**
   - When it analyses a sensor, the backend adds up to 3 short **memory lines** to the prompt: what happened to this
     sensor before, which steps were done and how it turned out.
   - Example: "M1 INC-0412, 2 Sep: KH03 CO2 stuck → recalibrated → fault again 6 days later".
   - A simple rule adds "replace sensor" when a repair did not hold. Chat gets one extra tool, `get_action_history`.
5. **Supabase (free, Mumbai) is the cloud.**
   - **Sync:** the board pushes its outbox (incidents, re-check revisions, events, steps, outcomes, maintenance, hourly
     summaries and its own AI outputs) straight to Supabase's REST API over Wi-Fi.
   - **Identity and access:** each board signs in as its own Supabase Auth user. RLS lets a board write only its own
     rows, and log tables accept inserts only.
   - **The device model's view of the cloud:** its tools read full history through a few Postgres functions
     (`rpc/...`), and read stored **inferences** (every AI output with its provenance).
   - **Offline, or when the free project is paused:** the outbox queues, the device answers from its own store, and the
     answer says what it could not reach.

---

## 1. What exists today (from the code)

| Piece | Today | Gap |
|---|---|---|
| `POST /api/incidents/{id}/approve\|dismiss\|rerun` (`server.go`) | Approve or dismiss the whole incident. Both are refused while the analysis is running, and approve is refused on a failed analysis. Dismiss needs a note. Notes are capped at 500 characters. | All or nothing: one click accepts every step. |
| `Incident.Approval`, `ApprovalNote` (`reason.go`), set by `SetApproval` | Holds `pending`, `approved` or `dismissed`, plus a note. | **No who or when.** A new decision overwrites the old one, so there is no history. |
| UI footer (`app.js`) | "Approve = you accept this and will carry it out." | Approve is a promise, but nothing ever records that the work was **done**, or how it turned out. |
| Domain health (`domainhealth.go`, `openIncident`) | Any decided incident stops counting as open. | **An approved incident whose work has not been done disappears from the health tile.** |
| Re-checks (`refine.go`) | Elevate, curb or resolve, with a toast and a re-alert. | They do not interact with an approval already given. An approved incident that gets worse stays "approved". |
| `maintenance` table (`store_schema.sql`, proposed) | Rows such as replaced, recalibrated, … | Nothing writes it yet. |

---

## 2. What the research says (short)

| Source | What it says | What we take |
|---|---|---|
| **ISA-18.2 / IEC 62682 alarm states**: Normal, Unacknowledged, Acknowledged, Return-to-normal-unacknowledged, Shelved, Suppressed, Out-of-service ([ISA-18.2 state diagram, ICONICS](https://documentation.iconics.com/v10.97.3/Content/Alarming/Alarm%20Server/Alarm%20References/alarm-state-transition-diagram.htm); [PyAutomation](https://pyautomation.readthedocs.io/en/latest/Developments_Guide/core/alarms/); [3GPP TR 32.859](https://itecspec.com/3gpp/32.859/s/10)) | Acknowledging is separate from the condition: acknowledging does not make the process normal, and a return to normal does not count as an acknowledgement. Shelving is time-limited, and when it expires the alarm comes back **unacknowledged** ([Elipse](https://kb.elipse.com.br/en/shelving-alarms-in-e3alarm/), [Rockwell](https://www.rockwellautomation.com/en-fi/docs/factorytalk-services-platform/6-60/factorytalk-services-platform-help-ditamap/factorytalk-alarms-and-events-help/alarm-and-event-summary/use-alarm-summary-at-runtime/shelve-alarms.html)). | Keep "Acknowledged" separate from the status the health tile shows. "Back to normal but not yet reviewed" stays visible. Shelving is left for later. |
| **EEMUA 191**: under 1 alarm per 10 min in steady state, under 10 per 10 min after an upset ([Honeywell ASM paper](https://process.honeywell.com/content/dam/process/en/documents/document-lists/doc_asm-consortium/white-papers/February%2028%202005%20-%20Acheiving%20Effective%20Alarm%20System%20Performance%20Benchmarking.pdf); [IChemE guide](https://www.icheme.org/media/16019/icheme-alarm-management-practical-guide-06_05_2021.pdf)) | Operators have limited attention. | Few clicks, at most 3–5 steps per incident, re-alert only when something changes. |
| **ITIL/ITSM lifecycle**: New → In progress → Resolved → Closed. A resolution code and close notes are mandatory, and Closed follows Resolved after a period ([ServiceNow: resolve and close](https://www.servicenow.com/docs/r/it-service-management/incident-management/resolve-and-close-an-incident.html); [ServiceNow auto-close](https://www.servicenow.com/docs/r/QykF2iRSIs6VXztArCSo3w/GtrvW~uA6emUVLpSiQKWOw); [SimpleOne state model](https://docs.simpleone.ru/itsm/incident-management/incident-tickets/state-model); [AlertOps](https://alertops.com/incident-management-lifecycle-essentials)) | "Resolved" (the condition is gone) and "Closed" (a human has confirmed the outcome) are different things, and closing needs an outcome code. | Our Resolved / Closed split, with an outcome list. |
| **PagerDuty / Opsgenie**: acknowledging stops escalation and makes that person the owner. Without an acknowledgement the incident re-notifies or escalates. Snooze ends with the alert open again ([PagerDuty escalation policies](https://support.pagerduty.com/v1/docs/escalation-policies); [Opsgenie acknowledge](https://support.atlassian.com/opsgenie/docs/acknowledge-and-unacknowledge-an-alert/); [Opsgenie snooze](https://docs.opsgenie.com/v1.0/docs/snooze)) | Acknowledgement means ownership, and a missing acknowledgement means a reminder. | Record who acknowledged. Re-alert inside the app if a critical incident is not acknowledged within 15 min. No paging service. |
| **CMMS work orders** (Maximo WAPPR → APPR → INPRG → COMP → CLOSE, with CLOSE locked; UpKeep meter-triggered work orders with checklists) ([IBM Maximo status changes](https://supportcontent.ibm.com/support/pages/node/1112013); [UpKeep meter triggers](https://help.onupkeep.com/en/articles/4739933-how-to-import-meter-work-order-triggers); [UpKeep advanced set-up](https://help.onupkeep.com/en/articles/4658030-advanced-steps-for-account-set-up)) | Maintenance is a checklist with sign-off. A closed record is history and is not edited. | The per-step checklist, plus a maintenance row when a sensor is replaced or recalibrated. |
| **ISO 14224 failure data**: failure mode, cause and mechanism kept apart, plus the maintenance action (replace, repair, adjust, recalibrate) ([Fabrico summary](https://www.fabrico.io/blog/iso-14224-failure-taxonomy-codes/); [OxMaint taxonomy](https://oxmaint.com/industries/manufacturing-plant/maintenance-failure-code-taxonomy-manufacturing-cmms)) | What was observed, why it happened and what was done are three different fields. | We already have the pattern (mode) and likely_cause. Add the action taken and the outcome. |
| **Microsoft HAX guidelines** (Amershi et al., CHI 2019): support efficient dismissal (G8) and efficient correction (G9: switch a decision, make detailed edits); make clear why; learn from user behaviour ([Microsoft project page](https://www.microsoft.com/research/project/guidelines-for-human-ai-interaction/); [HAX library](https://www.microsoft.com/en-us/haxtoolkit/library/example/10,11,13/)) | AI suggestions need cheap accept, reject and edit actions, one suggestion at a time. | Per-step Done / Not needed, "add my own step" as the "approve with changes", and the why shown next to each step. |
| **Google PAIR Feedback + Control**: implicit feedback (accept/reject counts) and explicit corrections; tell users what is collected ([PAIR chapter](https://pair.withgoogle.com/chapter/feedback-controls/)) | Operators' decisions are training signal. | Each step's decision and the outcome are logged, and the About page says so. |
| **Automation bias**: people over-trust automated recommendations, experts too, and training does not prevent it ([Parasuraman & Manzey 2010](https://depositonce.tu-berlin.de/items/0c787d91-6021-480b-a333-009e0d1d0092/full)). **EU AI Act Art. 14**: overseers must be able to disregard or override output and be aware of automation bias ([AI Act Service Desk](https://ai-act-service-desk.ec.europa.eu/en/ai-act/article-14)) | One "Approve all" button invites rubber-stamping. | Per-step decisions. "Accepted" alone is **not** treated as proof the AI was right; the outcome is. |
| **Human-in-the-loop agents**: pause, approve, edit or reject each tool call ([LangGraph human-in-the-loop](https://docs.langchain.com/oss/python/langgraph/add-human-in-the-loop)) | Approval is per proposed action. | Same idea, applied to the steps. |
| **Audit records**: event type, time, place, source, outcome, identity (NIST SP 800-53 AU-3; [UpGuard summary](https://www.upguard.com/compliance/nist-sp-800-53/au/au-3)) | Who, when, what and why. | The `incident_event` columns. |
| **Two-person rule / four eyes** ([Open Risk Manual](https://openriskmanual.org/wiki/Four_Eyes_Principle)) | Two people for high-risk *executions*. | **Not needed now.** The app executes nothing, so there is no high-risk execution to double-check. Revisit if actuation is ever added. |
| **Memory in LLM agents**: Reflexion stores verbal feedback from past trials in an episodic memory and improves without weight updates ([Shinn et al., NeurIPS 2023](https://proceedings.neurips.cc/paper_files/paper/2023/hash/1b44b878bb782e6954cd888628510e90-Abstract.html)) | Past outcomes in the prompt change behaviour, cheaply. | Memory lines (M1..M3) in the reasoner prompt. |
| **Provenance**: W3C PROV models an entity, the activity that generated it, and the agent it is attributed to ([W3C PROV-O](https://www.w3.org/TR/prov-o/)) | Every stored inference records which model made it, from what inputs, and when. | The `inference` table fields. |
| **Offline sync**: last-write-wins is lossy; prefer an append-only log and a single writer ([LWW trap](https://omr.it.com/blog/epoch-based-conflict-resolution-offline-first-apps/); [local-first overview](https://wal.sh/research/local-first)) | One writer per record avoids conflicts. | The device is the only writer of its rows. The cloud only receives them (insert-only logs). |

**Not adopted, to keep things simple:** escalation chains, on-call rosters, paging, SMS or e-mail, two-person approval,
shelving or out-of-service states, CMMS parts inventory, and role-based permissions. Each can be added later without
changing the data model.

---

## 3. Proposed approval model

### 3.1 States (one field, `workflow`, separate from severity and status)
```
 Analysing ──report ready──► Needs decision ──Acknowledge──► In progress ──readings normal──► Resolved ──Close + outcome──► Closed
      │                           │   ▲                          │  (steps ticked)              │ (app suggests closing)
      │                           │   └──── elevated by a re-check (re-acknowledge) ◄─────────────┘
      │                           └──Dismiss + note──► Closed (false alarm / no action needed)
      └─ failed ─► Interrupted (rerun, or Dismiss with a note)
```
| State | Meaning | How it is reached |
|---|---|---|
| Analysing | The AI is still working. No decisions are allowed (today's rule). | The incident is created. |
| **Needs decision** | Nobody has taken it yet. | The report is ready, or a re-check **elevated** it. |
| **In progress** | Someone owns it; the steps are being worked through. | **Acknowledge** ("I'm on it"), or ticking any step, which acknowledges automatically. |
| **Resolved** | The readings are back to the pre-onset baseline (today's `resolved` rule in refine.go). | Automatic, from the re-check or the live state. |
| **Closed** | A human has recorded the outcome. The record is final; a recurrence opens a **new** incident linked to it. | Close with an outcome, or Dismiss with a note. |

- **Resolved while still "Needs decision"** (ISA's "return to normal, unacknowledged") still shows as "back to normal,
  not yet reviewed". It does not vanish.
- **Health tiles:** an incident that is open and not closed counts for its domain whatever its workflow state. That fixes
  the gap in §1. The tile shows "1 needs decision · 1 in progress (Ravi)".
- **Severity and status never change because of a click.** Only the readings and the AI change them. Acknowledging is
  not "fixing".

### 3.2 The checklist (the "approve with changes")
- **Items:** the reasoner's whitelisted actions, plus the playbook steps when the AI says only "monitor", at most 5.
  Each item shows its *why* (one line, with evidence ids behind "Technical details").
- **Per item:** **Done** · **Not needed** (a short note, or one tap on a reason: "already fine", "not possible now",
  "wrong suggestion") · left open.
- **"+ Add my own step":** free text. This is how the operator approves with changes: mark the AI's step "Not needed"
  and add their own.
- **Sensor steps** write a `maintenance` row when ticked Done. This follows the owner's rule:
  - "Replace sensor" Done → `replaced` (counts as a replaced sensor);
  - "Recalibrate / repair / check on site" Done, and the readings return to normal → `repaired`.
- **New whitelist codes needed:** `replace_sensor`, `recalibrate_sensor`, and `restart_or_reconnect_sensor` (for power
  or network). The existing `check_sensor` stays.

### 3.3 Closing and outcomes
- **Close** asks for one outcome, which the app **pre-fills** from what happened. The operator confirms or changes it:

| Outcome | Pre-filled when |
|---|---|
| `sensor_replaced` | the replace step is Done |
| `sensor_repaired` | a sensor step other than replace is Done and the readings are back to normal |
| `fixed_by_action` | another step is Done and the readings are back to normal |
| `resolved_on_its_own` | the readings are back to normal and no step is Done |
| `false_alarm` | the operator dismissed it, or says the AI was wrong |
| `no_action_needed` | the operator dismissed it as real but harmless |

- A note is required for `false_alarm` and `no_action_needed` (today's dismiss rule) and optional otherwise.
- **Effectiveness, computed later and not by the operator:** if the same sensor raises the same kind of incident within
  7 days of closing, the closed incident is marked `recurred`. This, not "accepted", is the label that says whether the
  action worked.

### 3.4 How the 1.5 h and 3 h re-checks interact
| Re-check result | Needs decision | In progress |
|---|---|---|
| **Elevated** | re-alert (as today) | **back to Needs decision**: re-alert, "Got worse since you acknowledged: please re-acknowledge". Ticked steps are kept; new steps are marked "new". |
| **Curbed** | note on the timeline | note on the timeline; no re-alert |
| **Same** | nothing | nothing |
| **Resolved** | "back to normal, not yet reviewed" | prompt "Back to normal since HH:MM. Close?" with the outcome pre-filled |
| A step is **no longer recommended** | removed | kept if ticked, otherwise shown as "no longer suggested" |

**Reminder:** a critical incident still in Needs decision after 15 min, or a warning after 60 min, re-alerts once in
the app (sound plus an Android notification). There is nothing more: no escalation chain.

### 3.5 Who did it (a shared device)
- A **name picker** in the header shows a few operator names, set in Settings. The chosen name stays selected until
  changed or after 30 min idle, and is stored with every event.
- **No passwords:** this is accountability on a shared kiosk, not security. A 4-digit PIN can be added later.

### 3.6 API (small changes)
| Endpoint | Body | Note |
|---|---|---|
| `POST /api/incidents/{id}/ack` | `{operator}` | |
| `POST /api/incidents/{id}/steps/{step_id}` | `{operator, state: done\|not_needed\|open, note}` | |
| `POST /api/incidents/{id}/steps` | `{operator, text}` | adds an operator step |
| `POST /api/incidents/{id}/close` | `{operator, outcome, note}` | |
| `POST /api/incidents/{id}/dismiss` | `{operator, note, outcome?}` | kept, = close with `false_alarm` or `no_action_needed` |
| `POST /api/incidents/{id}/approve` | | kept for compatibility, = acknowledge + mark every step accepted (logged as "approve all") |

- **Existing records:** `approved` maps to *In progress*, and `dismissed` maps to *Closed (no_action_needed)*, marked
  legacy.
- SSE `incident` events carry `workflow` and the step changes.

---

## 4. Storage and memory ("what steps were taken last time")

### 4.1 Three small additions to `store_schema.sql`
```sql
-- Append-only audit log: one row per click or automatic transition. Never updated or deleted.
CREATE TABLE incident_event (
  seq INTEGER PRIMARY KEY AUTOINCREMENT, incident_id TEXT NOT NULL, at_wall TEXT NOT NULL,
  actor TEXT NOT NULL,          -- operator name | 'system' | 'reasoner'
  event TEXT NOT NULL,          -- created, analysed, recheck_elevated|curbed|same|resolved, ack, step_done,
                                -- step_not_needed, step_added, closed, dismissed, reminder, recurred
  step_id TEXT, outcome TEXT, note TEXT, detail_json TEXT);
-- The checklist, one row per step (current state; the history is in incident_event).
CREATE TABLE incident_step (
  incident_id TEXT NOT NULL, step_id TEXT NOT NULL,   -- s1, s2 ...
  source TEXT NOT NULL,          -- reasoner | agent | playbook | operator
  action TEXT,                   -- whitelist code (NULL for operator free text)
  target TEXT, text TEXT NOT NULL, why TEXT,
  added_at_stage TEXT,           -- early | 1.5h | 3h
  state TEXT NOT NULL DEFAULT 'open',  -- open | done | not_needed | withdrawn
  by TEXT, at_wall TEXT, note TEXT,
  PRIMARY KEY (incident_id, step_id));
-- Columns added to the existing `incident` index row:
--   workflow, owner, acked_at, resolved_at, closed_at, outcome, outcome_note, recurred_by
-- The existing `maintenance` table gets its rows from sensor steps ticked Done (§3.2).
```
Each row is a few hundred bytes. These rows are kept **all time** on the device, like the incident index, so "what was
done last time" survives the 1,000-incident limit on full records.

### 4.2 How the reasoner uses the memory
- **At incident time, with no extra NPU step:**
  - the backend looks up past incidents on the same flagged sensors (same node and metric first, then the same
    location and domain, at most 90 days back);
  - it writes **up to 3 memory lines** into the reasoner prompt, about 30 tokens each:
    ```
    M1 INC-0412 2026-09-02 KH03 co2 flatline (sensor_fault) -> recalibrate_sensor done (Ravi) -> closed sensor_repaired -> RECURRED 6 d later (INC-0455)
    M2 INC-0455 2026-09-08 KH03 co2 flatline (sensor_fault) -> open, no steps done
    ```
  - The policy gate accepts M ids as evidence, exactly like the E and H ids.
- **A deterministic "repair did not hold" rule, as a safety net next to the model:** when a sensor has a `sensor_fault`
  again within 30 days of a recalibration or repair, the step list gets "Replace sensor", with the why "recalibrated on
  2 Sep, fault returned".
  - The reasoner is trained (R1 data) to say this itself.
  - The rule guarantees it even when the model misses it.
- **In chat:** one new read-only tool, `get_action_history(node | domain | location, time, outcome?)`. It returns steps,
  outcomes and maintenance rows. It answers questions like "what did we do last time KH03 went flat?" and "how many
  sensors were replaced this year?".
  - Cloud-side calls cover all history; offline, the device's all-time rows do.

### 4.3 Learning from operators (later, and simple)
- **The data gets collected now, automatically:**
  - every step decision with its note;
  - operator-added steps;
  - outcomes;
  - recurrence.
- **Later use:**
  - **adapter retrain:** steps that were Done and did not recur become positive examples; "Not needed: wrong
    suggestion" and operator-added replacements become preference pairs (chosen = the operator's step);
  - **confidence calibration:** `false_alarm` outcomes serve as negatives.
- **Owner review first:** a review page, like the v2 data review, comes before any of this enters training. Operator
  clicks are noisy, and acceptance is not proof the AI was right (automation bias).

---

## 5. The cloud on Supabase (free tier), and how the device model uses it

### 5.1 What runs where
| Piece | QIDK (always) | Supabase free (when Wi-Fi works and the project is awake) | Laptop (optional) |
|---|---|---|---|
| Sensors, rules, agents, reasoner, chat | yes, on the NPU | no model. Edge Functions are not used for LLMs now | an optional bigger "ask deeper" model later |
| Store | SQLite: last 1,000 full incidents, plus all-time index, events, steps, maintenance; readings 30 d at 5-min, hourly forever | Postgres: **all derived data, all time**: incidents (latest row + every revision), events, steps, outcomes, maintenance, hourly summaries, inferences | reads the cloud like any client |
| Approvals and steps | **written here only** | copies (insert-only logs) | — |
| Raw 5-min readings | on the device (30 d) | **not uploaded** (derived data only, per the owner's decision) | — |
| Cost | ₹0 | ₹0. Free tier: 500 MB database, 2 projects, pauses after 7 days idle (third-party summaries; confirm on supabase.com/pricing) | ₹0 |

**Size check:**

| Data | Size per year |
|---|---|
| Incident summaries (≈ 2 KB each × a few thousand) | about 10 MB |
| Events and steps | under 5 MB |
| Hourly summaries (30 series × 8,760 h × ≈ 60 B) | about 16 MB |
| Inferences (text) | under 20 MB |
| **Total** | **≈ 50 MB per year per board** |

That is well inside 500 MB, so the free tier lasts years for one or two boards.

### 5.2 Tables (Postgres, mirroring the device's SQLite; `device_id` on every row)
```sql
create table devices (device_id text primary key, auth_uid uuid unique not null, name text);
create table incident        (device_id text, id text, version int, payload jsonb,      -- latest summary row
                              workflow text, severity text, outcome text, created_at timestamptz, closed_at timestamptz,
                              primary key (device_id, id));
create table incident_rev    (device_id text, id text, version int, stage text, payload jsonb, at timestamptz,
                              primary key (device_id, id, version));                     -- every analysis and re-check
create table incident_event  (device_id text, seq bigint, incident_id text, at timestamptz, actor text, event text,
                              step_id text, outcome text, note text, detail jsonb, primary key (device_id, seq));
create table incident_step   (device_id text, incident_id text, step_id text, source text, action text, text text,
                              why text, state text, by text, at timestamptz, note text,
                              primary key (device_id, incident_id, step_id));
create table maintenance     (device_id text, seq bigint, at timestamptz, node text, metric text, action text,
                              incident_id text, operator text, note text, primary key (device_id, seq));
create table reading_hourly  (device_id text, node text, metric text, t timestamptz, n int, mean real, min real,
                              max real, last real, primary key (device_id, node, metric, t));
create table inference       (device_id text, id text, kind text,        -- report | recheck | chat_answer | deeper | summary
                              model text, model_version text, made_at timestamptz, made_on text,  -- qidk | laptop | cloud
                              inputs jsonb, text text, facts jsonb, gate text,   -- provenance (W3C PROV: entity/activity/agent)
                              embedding vector(384),                     -- optional, filled later (pgvector)
                              primary key (device_id, id));
```
- **Every AI output the board makes is an inference row:** the report, each re-check and each chat answer, with the
  model id (`v2+reasoner-lora-1`), the inputs (incident or query ids) and the policy-gate result.
  - The local model can therefore look up its own earlier conclusions after the full record has left the device.
  - Inferences made on the laptop or, later, in a paid cloud go into the same table, with `made_on` saying where.
- **pgvector is optional for now.** v1 finds similar incidents with exact SQL: the same node, metric and pattern or
  label. The `embedding` column is filled later by the laptop or a paid embedder.

### 5.3 Security: row-level security and the per-device identity
- **Identity:**
  - each board gets its **own Supabase Auth user**, a service account with a long random password stored in the
    board's `state/`;
  - the board signs in once, keeps the refresh token, and sends the user JWT on every call;
  - the `service_role` key **never** goes on the board.
  - RLS is evaluated on the JWT in the `Authorization` header, not on the `apikey`
    ([Supabase troubleshooting](https://supabase.com/docs/guides/troubleshooting/why-is-my-service-role-key-client-getting-rls-errors-or-not-returning-data-7_1K9z)).
- **Policies:**
  - **Writes:** the row's `device_id` must equal the caller's device, looked up as `device_id = (select device_id
    from devices where auth_uid = auth.uid())`.
  - **Log tables** (`incident_rev`, `incident_event`, `maintenance`, `inference`): `INSERT` only, no `UPDATE` or
    `DELETE` policy. The audit trail cannot be rewritten from a board.
  - **`incident` and `incident_step`:** insert plus update of the board's own rows. A trigger keeps an update only when
    `new.version > old.version`, so an old retry can never overwrite newer data.
  - **Reads:** a board reads its own rows. A read-only "viewer" user (the laptop, or evaluators) reads all rows.
- **Region:** Mumbai (ap-south-1), so the data stays in India. In the cloud, operator names are replaced by a short
  operator id; the names stay on the device. That is a DPDP-friendly default.

### 5.4 Sync and the offline queue
```
QIDK persist()  -> SQLite tx: write row + INSERT outbox(kind, key, body)          (same transaction, survives reboots)
sync loop       -> every 60 s when Wi-Fi is up (and right after a decision); backoff 1 min -> 30 min on errors
                -> POST /rest/v1/<table>?on_conflict=<pk>   Prefer: resolution=ignore-duplicates (logs)
                                                             Prefer: resolution=merge-duplicates  (incident, steps)
                -> 2xx: DELETE outbox rows sent; else keep them and retry
```
- **Idempotent:** every row has a natural primary key, (device, seq) or (device, id, version), so re-sending after a
  lost reply is harmless (PostgREST upsert:
  [postgrest-dart](https://github.com/supabase/postgrest-dart/pull/23/files)).
- **Single writer:** only the board writes its rows, so there are no conflicts and no last-write-wins.
- **Outbox cap:** 50 MB. If it fills, hourly summaries are dropped before incidents, and a counter is logged.
- **The free project pauses** after 7 days with no traffic.
  - A board that syncs every minute keeps the project awake.
  - If the board was off for over a week, the sync gets errors, the outbox keeps queueing, and the UI shows "Cloud
    paused, data queued (N items)". Someone restores the project from the dashboard and the queue drains.
  - The alert path never waits on the cloud.
- **Not used:** Realtime subscriptions, since the device does not need pushes. Edge Functions are kept for later, for
  example a nightly summary job.

### 5.5 The device model's access to cloud data and inferences
- **Same tools, routed by the executor:**
  - the reasoner and chat call the same read-only tools (`count_incidents`, `find_incidents`, `get_incident`,
    `get_sensor_history` (hourly), `get_action_history`, `get_inferences`);
  - the Go executor decides: device first, and when the question needs data the device no longer holds, it calls
    Supabase **RPC functions** (`POST /rest/v1/rpc/count_incidents`, …) with the same JSON arguments, under a 2 s
    timeout;
  - the RPCs are small SQL functions written to match the device's semantics. One shared fixture test runs both and
    must give identical answers.
- **Merging:** rows still in the outbox (not yet synced) are merged into cloud results, so a count never misses the
  newest incident.
- **`get_inferences(incident | node | kind)`** returns earlier AI conclusions with their provenance. Examples: "the
  3 h re-check on INC-0412 concluded sensor_fault (v2+lora-1)", or a deeper laptop-model analysis.
- **Cache:** the device keeps an inference cache (about 5 MB, 30 days), so cached results still work offline.
- **Trust rules:**
  - cloud data and inferences are **data, not instructions**: they are quoted in a labelled block and cited as
    `C1..Cn`;
  - they never change severity or close an incident by themselves;
  - every number in an answer still comes from an exact tool.
- **Badges on every answer and memory line:**
  - `This device`;
  - `Cloud (full history)`;
  - `Earlier inference · <model> · <date>`;
  - `Cached · 3 h old`;
  - when offline or paused: "Cloud not reachable: answered from this device (last 1,000 incidents + all-time index)".

### 5.6 Offline vs online
| Feature | Offline or cloud paused (device only) | Cloud reachable |
|---|---|---|
| Alerts, AI analysis, re-checks, checklist, close, audit log | full (queued for sync) | full, and synced |
| "What was done last time" (memory lines, `get_action_history`) | full: steps, outcomes and maintenance are kept all time on the device | same, plus details of incidents no longer held in full |
| Exact counts | exact from the all-time index | exact from the cloud, merged with unsynced rows |
| Old incident details | last 1,000 full incidents | everything |
| Readings history | 30 d at 5-min, hourly forever | hourly forever (5-min never leaves the board) |
| Earlier inferences | own and cached ones | all, from every source |

---

## 6. Questions to decide (each with a recommended answer)

1. **How should Approve work?**
   - (a) Keep a single Approve/Dismiss.
   - (b) **Acknowledge, then a per-step checklist (Done / Not needed / add my own), then close with an outcome.**
     Dismiss is kept, and "Approve all" is kept as a shortcut.
   - (c) Checklist only, with no Acknowledge.
   - **Recommended: (b).** It is the pattern shared by ISA-18.2, ITSM and the CMMS tools, and it produces the
     "what was done and did it work" data.
2. **Who is the operator on the shared device?**
   - (a) Nobody is recorded.
   - (b) **A name picker, no password.**
   - (c) A name plus a 4-digit PIN.
   - **Recommended: (b) now.** (c) can come later if evaluators ask for it.
3. **When the readings are back to normal, who closes the incident?**
   - (a) **The app suggests closing with a pre-filled outcome and the operator confirms. If nobody acts within 24 h it
     auto-closes as `resolved_on_its_own (auto)`, unless a step is still open.**
   - (b) Always manual.
   - (c) Fully automatic.
   - **Recommended: (a).**
4. **If a re-check makes an acknowledged incident worse, does it need re-acknowledging?**
   - (a) **Yes: back to Needs decision, with a re-alert.**
   - (b) A toast only.
   - **Recommended: (a).** This is ISA-18.2 behaviour.
5. **How does the reasoner get its memory of past actions?**
   - (a) **The backend always adds up to 3 memory lines to the prompt, plus the "repair did not hold → replace" rule,
     plus `get_action_history` in chat.**
   - (b) Only when the model calls a tool.
   - **Recommended: (a).** It costs no extra NPU round and is deterministic.
6. **What goes to Supabase, and who writes it?**
   - (a) **The board is the only writer:**
     - it pushes derived data and every AI output (as `inference` rows with provenance), with insert-only logs under
       per-board RLS;
     - raw 5-min readings stay on the board;
     - operator names are replaced by ids in the cloud;
     - the board reads cloud history and inferences through RPCs and caches them.
   - (b) Also allow approvals from a web or laptop dashboard, written to Supabase and pulled by the board.
   - (c) Also upload raw 5-min readings.
   - **Recommended: (a).** It means a single writer, no conflicts, about 50 MB per year (well inside the 500 MB free
     tier), and it matches the "derived data only" decision. (b) can come later as "requests" that the board applies
     itself.

---

## Sources
- ISA-18.2 alarm state diagram (ICONICS docs): https://documentation.iconics.com/v10.97.3/Content/Alarming/Alarm%20Server/Alarm%20References/alarm-state-transition-diagram.htm
- PyAutomation ISA-18.2 alarm states: https://pyautomation.readthedocs.io/en/latest/Developments_Guide/core/alarms/
- 3GPP TR 32.859 (ISA-18.2 states, shelving requirements): https://itecspec.com/3gpp/32.859/s/10 , https://www.itecspec.com/3gpp/32.859/s/11.2.1
- OPC UA Part 9 alarms: https://reference.opcfoundation.org/Core/Part9/4.8
- Shelving with expiry: Elipse https://kb.elipse.com.br/en/shelving-alarms-in-e3alarm/ ; Rockwell FactoryTalk https://www.rockwellautomation.com/en-fi/docs/factorytalk-services-platform/6-60/factorytalk-services-platform-help-ditamap/factorytalk-alarms-and-events-help/alarm-and-event-summary/use-alarm-summary-at-runtime/shelve-alarms.html
- EEMUA 191 alarm rates: Honeywell ASM benchmarking https://process.honeywell.com/content/dam/process/en/documents/document-lists/doc_asm-consortium/white-papers/February%2028%202005%20-%20Acheiving%20Effective%20Alarm%20System%20Performance%20Benchmarking.pdf ; IChemE practical guide https://www.icheme.org/media/16019/icheme-alarm-management-practical-guide-06_05_2021.pdf
- ServiceNow resolve and close: https://www.servicenow.com/docs/r/it-service-management/incident-management/resolve-and-close-an-incident.html ; auto-close: https://www.servicenow.com/docs/r/QykF2iRSIs6VXztArCSo3w/GtrvW~uA6emUVLpSiQKWOw
- SimpleOne incident state model: https://docs.simpleone.ru/itsm/incident-management/incident-tickets/state-model ; AlertOps lifecycle: https://alertops.com/incident-management-lifecycle-essentials
- PagerDuty escalation policies: https://support.pagerduty.com/v1/docs/escalation-policies
- Opsgenie acknowledge: https://support.atlassian.com/opsgenie/docs/acknowledge-and-unacknowledge-an-alert/ ; snooze: https://docs.opsgenie.com/v1.0/docs/snooze ; notification flow: https://support.atlassian.com/opsgenie/docs/alert-notifications-flow
- IBM Maximo allowable work-order status changes: https://supportcontent.ibm.com/support/pages/node/1112013
- UpKeep meter triggers and checklists: https://help.onupkeep.com/en/articles/4739933-how-to-import-meter-work-order-triggers , https://help.onupkeep.com/en/articles/4658030-advanced-steps-for-account-set-up
- ISO 14224 taxonomy summaries: https://www.fabrico.io/blog/iso-14224-failure-taxonomy-codes/ , https://oxmaint.com/industries/manufacturing-plant/maintenance-failure-code-taxonomy-manufacturing-cmms
- Microsoft Guidelines for Human-AI Interaction (Amershi et al., CHI 2019): https://www.microsoft.com/research/project/guidelines-for-human-ai-interaction/ ; HAX Toolkit library: https://www.microsoft.com/en-us/haxtoolkit/library/example/10,11,13/
- Google PAIR Guidebook, Feedback + Control: https://pair.withgoogle.com/chapter/feedback-controls/
- Parasuraman & Manzey (2010), Complacency and bias in human use of automation: https://depositonce.tu-berlin.de/items/0c787d91-6021-480b-a333-009e0d1d0092/full
- EU AI Act Article 14 (human oversight): https://ai-act-service-desk.ec.europa.eu/en/ai-act/article-14
- LangGraph human-in-the-loop: https://docs.langchain.com/oss/python/langgraph/add-human-in-the-loop
- NIST SP 800-53 AU-3 (content of audit records), summary: https://www.upguard.com/compliance/nist-sp-800-53/au/au-3
- Four-eyes principle: https://openriskmanual.org/wiki/Four_Eyes_Principle
- Reflexion (Shinn et al., NeurIPS 2023): https://proceedings.neurips.cc/paper_files/paper/2023/hash/1b44b878bb782e6954cd888628510e90-Abstract.html
- W3C PROV-O: https://www.w3.org/TR/prov-o/
- Offline sync and last-write-wins: https://omr.it.com/blog/epoch-based-conflict-resolution-offline-first-apps/ , https://wal.sh/research/local-first
- Project code read: `app/backend/server.go` (approve/dismiss/rerun), `reason.go` (`Incident.Approval`, `SetApproval`), `domainhealth.go` (`openIncident`, `actionStep`), `app/device/web/app.js` (decision footer); HANDBOOK 2.42–2.43.
- Supabase free-tier limits (third-party summaries; confirm at https://supabase.com/pricing): https://www.jetadmin.io/blog/supabase-pricing-2026-guide-to-plans-limits-and-real-world-costs/ , https://neon.com/guides/neon-vs-supabase-free-plan
- Supabase RLS is evaluated on the Authorization JWT, not the apikey: https://supabase.com/docs/guides/troubleshooting/why-is-my-service-role-key-client-getting-rls-errors-or-not-returning-data-7_1K9z
- PostgREST upsert (`on_conflict`, `Prefer: resolution=merge-duplicates`): https://github.com/supabase/postgrest-dart/pull/23/files
