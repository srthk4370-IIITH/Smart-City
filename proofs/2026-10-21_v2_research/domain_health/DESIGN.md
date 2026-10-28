# Domain health monitor: design note (2026-10-21)

**What was asked:** a place where the operator can see how each domain (air quality, water, power,
occupancy, weather, HVAC) is doing right now. It should show whether a domain has been elevated,
whether it is at warning, and what to do next when it is.

## What operations dashboards do (research)

| Practice | Source | What we take from it |
|---|---|---|
| ISA-18.2 alarm life cycle: Normal → Unacknowledged → Acknowledged → *RTN-unacknowledged*. Shelved and out-of-service alarms are kept separate from process alarms. Each alarm has a documented cause, consequence and corrective action. | ISA-18.2 summaries: processonline.com.au "Improving alarm management with ISA-18.2 Part 2"; ICONICS ISA-18.2 state-transition docs | An incident stays **open** until the operator approves or dismisses it, even after the readings return to normal (the RTN-unack state). **Sensor faults and stale data are counted apart from the process status.** Every abnormal tile shows **corrective steps**. |
| EEMUA 191 / IEC 62682 alarm rates: under 1 alarm per 10 min in steady state, about 10 per 10 min after an upset. Floods hide the important alarms. | ABB SCADA alarm-management white paper; IChemE alarm-management guide | We do **not** add a new alarm stream. A tile changes only when a domain's level changes. Pushes go out on change only (SSE `health`), and a toast appears only when a *refinement* raises an incident's severity. A lowered severity gets a quiet note. |
| ISA-101 high-performance HMI: Level-1 overview with area status summaries and alarm counts by area, linked to detail. Colour is reserved for abnormal states, and the screen stays grey or neutral when all is well. | ISA-101 overviews: orise.com "traditional vs high performance HMI"; Tatsoft ISA-101 how-to | **Six tiles, one per domain, at the top of Campus Live.** A compact strip at the top of the Sensors tab (the start tab) links to them. Normal tiles stay neutral and compact; only abnormal tiles get a coloured edge and take a full row. |
| Health rollups: "worst-of" across members is the default, as in SCOM dependency monitors, Cloudera and New Relic. A grey Unknown or stale state is shown when no data arrives, so a silent feed never looks green. | Microsoft SCOM "Create a Health Rollup"; Cloudera Manager status summary; New Relic Pathpoint health indicators; dbt data-health tile | **Worst-of rollup**, not weighted. Weights would hide one critical tank behind three normal sensors. Missing or old data gets its own **"Warming up / data stale"** label rather than counting as normal. |
| WCAG 2.x 1.4.1 Use of Color | w3.org/WAI/WCAG21/Understanding/use-of-color | Every level has a **glyph and a word** (● Normal, ▲ Warning, ■ Critical, ◆ Sensor fault, ○ Warming up). Every trend has an **arrow and a word** (↑ Elevated from …, ↓ Curbed from …). |

## Chosen design

**Backend:** `app/backend/domainhealth.go`, served at `GET /api/health` and pushed as SSE `health` on change.
It is computed on every engine poll from in-memory engine and reasoner state. It makes no NPU calls and no disk reads.

- **status**: the worst live process status (normal < warning < critical) over the domain's own sensors.
  Context-only sensors (HVAC context in v1, setpoint and ac_on in v2) never raise it.
- **AI raise only**: while the live status is abnormal, an open incident's reasoner severity can raise
  it, for example from warning to critical after a refinement. This sets `raised_by_ai` and the tile says so.
  The AI never lowers a live warning and never creates a status when the readings are normal. A curb
  shows on the incident instead, so live evidence is never hidden.
- **headline**: the process status if it is abnormal; otherwise `sensor_fault`, then
  `insufficient_data`, then normal. `sensor_faults`, `counts`, `fresh` and `stale[]` are always
  reported separately. A sensor is stale when it has no value, has insufficient data, or its last
  reading is more than 10 min of sensor time old.
- **trend**: `elevated` or `curbed` (with `trend_from`) when the headline changes level. The arrow stays
  for 30 min of sensor time and then returns to `steady`. **since** is the sensor time the headline
  reached its current level; the tile shows it as time-in-state.
- **incidents**: open incidents that touch the domain, by role or by the report's `affected_domains`.
  Open means approval is pending, the incident is from the current sensor-history epoch, and it is no
  more than 12 h old in sensor time. Each one carries its severity, refine stage, and `change` (the
  latest revision raised or lowered it).
- **steps**, at most 3, shown only for warning, critical or sensor fault:
  1. The action from the open incident's valid report, then the valid agent actions for that
     domain's flagged (non-context) sensors.
  2. Only whitelisted actions (`actionAllowed`) are used, worded as recommendations for a person to
     carry out. `switch_off_ac` reads "operator decision; the app switches nothing".
  3. "monitor" on its own is not guidance, so in that case, and when no AI action is usable, a
     **static per-domain playbook** for warning, critical or fault is used instead.

**UI:** in `app.js`, the section `/* ----- domain health ----- */`.

- The panel sits under the hero on Campus Live, with a strip of six chips on the Sensors tab.
- Each tile is focusable (tabindex 0) and has a full spoken `aria-label`. Level changes are announced
  through a polite `aria-live` region.
- Incident chips open the incident sheet.
- When a refinement raises an incident, a `role=alert` toast with an **Open** button appears. A
  lowered incident gets a plain toast.
- The service-worker cache is bumped to `sce-shell-v29`.

## Rejected alternatives

- **Weighted health score (0–100):** it hides a single critical sensor and cannot be explained to an evaluator.
- **New toast for every live status change:** this produces alarm floods (EEMUA 191). The live cards
  already show those changes.
- **Letting the AI lower the domain status:** a refined "fine" while the rule still reads warning
  would hide live evidence. Lowering already has a rule-agreement check in `refine.go`.

## Evidence

- `go_test_health.log`: 9 Go tests covering rollup, fault separation, context sensors, staleness,
  trend, AI raise limits, steps from agents and the report, playbook fallback with an actuation
  check, and the tracker on the real engine.
- `ui_health_check.log` / `ui_health_check.js`: a browser-free render check run with
  `node ui_health_check.js <app.js>`.
- Full suite: `go vet .` is clean and `go test ./...` passes (56 s).
