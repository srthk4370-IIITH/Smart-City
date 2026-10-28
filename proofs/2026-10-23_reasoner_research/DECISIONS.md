# Cross-domain reasoner, storage, approval: final decisions (2026-10-23)

These decisions were agreed with the project owner through AskUserQuestion. The background research is in this
folder: `REASONER_DESIGN.md`, `FOG_OPTIONS.md` and `APPROVAL_AND_MEMORY.md`, plus `tools.json` and
`store_schema.sql`.

## First principles
1. **Store all data:** every incident, every re-check, every action taken and its outcome.
2. **An intelligent model on the device.** It does cross-domain reasoning for each incident, and it is a
   conversational, agentic interface that calls read-only tools to fetch incidents and sensor data. It keeps a
   memory of past actions. It works offline.
3. **No cost now.** Paid options come only at real deployment, and the board code stays the same.

## Priorities
1. The local model on the board: reasoner and chat.
2. Fog: data stored in Supabase, with computation over it done by our local model.
3. A cloud model, later. Research and an architecture proposal come first.

## Architecture
- **The QIDK orchestrates.**
  - It runs the agent loop and every tool, against local SQLite or Supabase.
  - Any cloud model sees only the tool results the board sends. It never holds database credentials.
  - Models never count. Exact numbers come from SQL, and a checker rejects any number no tool returned.
- **Device store:** the last 1,000 incidents in full, plus an all-time index row (~300 B) per incident, so offline
  counts stay exact.
- **Cloud store:** Supabase free tier, Mumbai region. It is independent of the laptop.
  - Postgres gives exact SQL; pgvector is available later.
  - Auto REST API.
  - Security: per-board Auth user, RLS, insert-only logs.
  - Free projects pause after about 1 week idle. Regular board sync keeps the project active, and the board
    works offline regardless.
  - Pinecone was rejected because it is vector-only and cannot give exact counts.
  - The laptop is a dev machine only.
- **What goes to the cloud:** derived data only.
  - Incidents, re-check history, checklist steps and outcomes, AI inferences (with model and inputs), health
    snapshots, hourly sensor summaries.
  - Raw 5-min readings stay on the board.
  - Operator ids, not names.
  - The board is the only writer. Dashboard approvals come later, as requests the board applies.
- **Sync:** an outbox in the same SQLite transaction, sent every 60 s by idempotent upserts. Offline, the outbox
  queues up to 50 MB.
- **Cloud data for the local model:**
  - Tools read Supabase only when the device lacks the data, with a 2 s timeout.
  - Results are cached on the device.
  - Every answer has a source badge.
- **Escalation to a cloud model, once it exists**, follows deterministic backend rules, never the LLM:
  1. **Coverage:** older data is fetched from the cloud; counts stay local via the index.
  2. **Verification failed:** the cloud model is asked with the same tool results.
  3. **Too big:** more than about 4 tool calls, or a multi-month analysis.
  4. **The reasoner's `needs_deeper` flag** offers escalation.
  5. **Opt-in buttons:** "Ask the fog model" and "Analyse deeper".

  If the cloud model times out, the device answer stands.
- **Model choice:** decided after the P0 benchmark. The candidates are the v2 3B plus a reasoner LoRA (one model,
  one NPU client) and a separate Qwen. The owner leans to Qwen for accuracy, but numbers decide.

## Approval and action memory
- **Approve is a lifecycle:**
  1. Acknowledge, recording who and when.
  2. A checklist: each recommended step is marked Done or Not needed, with a note. Operators can add steps.
  3. Close with an outcome: sensor replaced, sensor repaired, fixed by action, resolved on its own, false alarm,
     or no action needed.

  Dismiss (note required) and "Approve all" stay.
- **Faults:** "Replace sensor" Done means the sensor was replaced. If readings return to normal after a repair or
  recalibration, it was repaired.
- **Operator:** a name picker on the shared device, with no password. A PIN can be added later.
- **Closing:** when readings return to normal, the app suggests closing with the outcome pre-filled. It
  auto-closes as "resolved on its own (auto)" after 24 h unless a step is still open.
- **Re-checks:**
  - If a re-check makes an acknowledged incident worse, it goes back to Needs decision and re-alerts.
  - Acknowledging never lowers severity.
  - An unacknowledged critical incident re-alerts once after 15 min.
- **Memory:**
  - Up to 3 short memory lines (past incidents and actions on the same sensor) go into each reasoner prompt.
  - Rule: if a fault returns within 30 days of a repair, "Replace sensor" is added as a step.
  - The chat gets a `get_action_history` tool.
  - Whether a fix worked is judged by recurrence within 7 days.
  - Operator edits become training data only after an owner review.

## Reasoner evaluation scheme (approved 2026-10-23)
- **Gates (pass/fail):**
  - **Groundedness and safety:** no invented numbers or incident ids; only whitelisted human actions; abstains when unsure.
  - **Deployability:** runs as Q4 on the NPU, one client, usable latency.
- **Weights:**
  - 45%: core cross-domain reasoning, including time/memory reasoning and robustness.
  - 25%: picking the right tools.
  - 20%: understanding the data.
  - 10%: calibration, consistency and communication.
- Always measured on the quantized model as deployed.

## Real-world inputs the reasoner must handle (owner, 2026-10-23)
The reasoner's training data and its evaluation cover `proofs/2026-10-23_realworld/REALWORLD.md`:

- **§5.8, concurrent multi-domain events:** onsets 0–60 min apart. Examples: CO2 + power (occupancy), outdoor PM +
  indoor PM (ingress), level + flow (pump). These are generated as reasoner-level samples: the 2–3 agent outputs plus
  the truth.
- **Backend data-quality signals:** `quality` / `quality_reason` (insufficient data, stale, maintenance, sensor
  replaced) and glitch-filtered gates.
- **Readings that look like problems but may not be:**
  - stuck sensors vs genuinely idle signals;
  - physically impossible readings (CO2 < 300 ppm);
  - holiday low load;
  - weather-driven daily cycles: heat → room temperature → AC power, rain → level, outdoor PM → indoor PM.

**Rules:**
- Sensor faults are kept separate from process events.
- The reasoner never reasons over invented or imputed data.
- When data is missing it says "insufficient data" instead of guessing.
