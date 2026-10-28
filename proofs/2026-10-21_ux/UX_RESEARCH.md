# Operator UX research and audit (2026-10-21)

The app is meant to be deployable for campus facilities staff, not only for the engineers and evaluators who built it.
This note covers:

- what operator and monitoring UIs should do, with sources;
- an audit of every screen element before this change;
- the information hierarchy now implemented;
- how the work was verified.

Cross-domain reasoning and the model internals are treated as a black box here. They stay fully visible under **Technical details** and the **Engineering view**, but they no longer lead any screen.

## 1. Sources

Verification marks:

- [V] the page was fetched and its content confirmed.
- [S] the URL came up in search but was not fetched.
- [K] the rule is well established, but the URL was not fetched.

ISA-101 and ISA-18.2 are paywalled, so their figures are given as summarised by practitioner sources.

| # | Source | Rules used here |
|---|--------|-----------------|
| 1 | ISA-101 committee page, ISA [V]: https://www.isa.org/standards-and-publications/isa-standards/isa-standards-committees/isa101 | Navigation hierarchy, colour use and alarm conventions are one designed system, not ad-hoc choices |
| 2 | "Going Gray: A New HMI Standard", control.com [S]: https://control.com/technical-articles/going-gray/ | A grey baseline is the normal state. Colour is reserved for abnormal conditions and required action |
| 3 | "ISA Will-DuPage covers high-performance HMIs", Control Global 2019 [S]: https://www.controlglobal.com/industrynews/2019/isa-will-dupage-covers-high-performance-hmis | Display levels: L1 overview, L2 area, L3 detail, L4 diagnostics. An uncluttered display makes real abnormals stand out |
| 4 | ISA-18.2 / EEMUA 191 as summarised by Process Online [S]: https://www.processonline.com.au/articles/65390-Improving-alarm-management-with-ISA-18-2-Part-2 | 3–4 priorities, with high priority rare. About 1 alarm per 10 min per operator. A flood is more than 10 in 10 min. Each alarm has a cause, a consequence and an operator action. Out-of-service (bad sensor) is kept apart from process alarms |
| 5 | NN/g, "Error-Message Guidelines" [V]: https://www.nngroup.com/articles/error-message-guidelines/ | Plain language. Hide technical codes unless needed. State the specific problem and a concrete fix. Indicators must not rely on colour alone. Severity decides how loud the message is |
| 6 | NN/g, "Progressive Disclosure" [V]: https://www.nngroup.com/articles/progressive-disclosure/ | Show the essentials first and move rare detail to a second level. Keep to at most 2 disclosure levels. Label the control so people know what it reveals |
| 7 | W3C WCAG 2.2, Understanding 2.5.8 Target Size [V]: https://www.w3.org/WAI/WCAG22/Understanding/target-size-minimum.html. Also 1.4.1 Use of Color and 1.4.3 Contrast [K] | Targets at least 24 px (we use 44–56 px). Colour is never the only cue. Text contrast at least 4.5:1 |
| 8 | W3C WCAG 2.2, Understanding 4.1.3 Status Messages [V]: https://www.w3.org/WAI/WCAG22/Understanding/status-messages.html | Status changes are announced without moving focus: `aria-live="polite"` for updates, `role="alert"` for urgent ones |
| 9 | Material Design 3, accessibility [K]: https://m3.material.io/foundations/designing/structure | 48 dp touch targets with about 8 dp spacing. Pair colour with an icon or text |
| 10 | PagerDuty Incident Response, Severity Levels [V]: https://response.pagerduty.com/before/severity_levels/. Atlassian incident handbook [K]: https://www.atlassian.com/incident-management | Few severities, each mapped to one response. When in doubt, use the higher severity. Every incident shows its status, timeline and what changed |
| 11 | Google PAIR, People + AI Guidebook, "Explainability + Trust" [V]: https://pair.withgoogle.com/chapter/explainability-trust/ | Show confidence only where it affects the decision, with context. Don't say "what" without "why". Prefer categories to raw scores |
| 12 | Microsoft HAX, Guidelines for Human-AI Interaction (Amershi et al., CHI 2019) [V, partial]: https://www.microsoft.com/en-us/haxtoolkit/ai-guidelines/ | G2: make clear how well the system can do. G11: make clear why it did what it did. G9: support efficient correction. G17: provide global controls (our Engineering view switch) |

## 2. Principles applied

1. **Grey when normal, colour only for abnormal (ISA-101).** Normal tiles, rows and icons are neutral. A coloured left edge, glyph and word appear only for warning, critical or sensor problem.
2. **Status is never colour alone (WCAG 1.4.1, M3).** Each status has a glyph and a word: ● Normal, ▲ Warning, ■ Critical, ◆ Sensor problem, ○ Starting up.
3. **Levels of disclosure (ISA-101 L1–L4, NN/g 2 levels):**
   - L1: campus health, with six tiles ordered worst first.
   - L2: the domain sheet, with its open incidents, all steps and its sensors.
   - L3: the incident, covering what is happening, why it matters, what to do and what changed.
   - L4: Technical details, and the Engineering view switch.
4. **Every alarm states cause, consequence and action (ISA-18.2, NN/g).** The incident page leads with *What is happening*, *Why it matters* and *What to do*. A tile shows its one "Do now" step.
5. **What changed (incident-management UX).** Tiles show "↑ Got worse (was Warning)", "↓ Improving" or "✓ Back to normal", plus since when. Incidents tell the 1.5 h and 3 h re-check story in one sentence and a timeline: got worse, improved, resolved or no change.
6. **Confidence as a word, number on tap (PAIR, HAX G2).** Confidence reads High, Medium or Low. Tapping it shows the model's score. Evidence ids stay under Technical details.
7. **Sensor problems kept apart from process alarms (ISA-18.2 out-of-service).** "Sensor problem" and "not reporting fresh readings" are their own words and never read as a facility alarm.
8. **The human decides, nothing actuates.** The Approve and Dismiss footer explains both in one line. Dismiss still needs a note, and the API rules are unchanged.
9. **Live and stale state are always visible.** The panel shows "● Live" or "○ Not updating". The existing offline banner is kept.
10. **Accessibility.**
    - Tiles and chips are real `<button>`s, at least 44–56 px tall.
    - Health changes go to an `aria-live` region. A refinement that raises severity uses `role="alert"`.
    - Reduced motion is honoured, as before.
    - Text is at least 13 px. Dark-theme inks are unchanged and measure at least 5:1 on cards, for example `--tx2` #8f857a on #121110 is about 5.1:1.

## 3. Audit of the screens before this change

Screenshots are in `before/`. Actions:

- **keep**: unchanged.
- **plain**: renamed to plain language.
- **tap**: hidden behind *Technical details* or the Engineering view, still available.
- **fix**: layout bug.
- **remove**: taken out.

### Header and navigation

| Element | Problem | Action |
|---|---|---|
| Mode bar (Rules / Single / Agents) on every screen | Jargon, and takes ~60 px on a phone | **tap**: shown only in the Engineering view (header `</>` button or About switch) |
| Desktop tab rail labels "SENSO…", "I…" | Dark-theme overflow guard (`padding:0 2px`) truncated them | **fix** |
| Incidents tab badge "43" (all incidents ever) | Not actionable | **plain**: now counts *decisions waiting* |
| Clock "19:30 IST" | Fine | keep |

### Live view: hero and health panel (the reported breakage)

| Element | Problem | Action |
|---|---|---|
| Domain names "WATE R", "AIR QUAL ITY", "OCCU PANC Y" | `overflow-wrap:anywhere` plus the status pill squeezing the name | **fix**: name on one line with ellipsis, status on its own line |
| Tiles in fixed order | A critical domain could be the 5th tile | **fix**: worst first, stable within a level |
| "Steady for 9 h 30 min" on every normal tile | Noise. Time-in-state only matters when something is wrong | **remove** on calm tiles. Abnormal tiles show "since 14:05 (25 min)" |
| Coloured domain icons and green "NORMAL" pills | Colour on normal state (anti-ISA-101) | **fix**: grey icons. Normal reads "● Normal" in grey |
| No "what to do" on the tile | Steps were a 3-item list inside the tile | **plain**: one "Do now:" line. All steps in the domain sheet |
| Incident buttons inside the tile | Nested targets, cramped | **tap**: tile opens the domain sheet, which lists the incidents |
| "Raised to Critical by the AI review (live readings: Warning)" | Jargon | **plain** in the domain sheet: "The AI review rated this Critical; the live readings alone say Warning." |
| No live or stale indicator | Operator cannot tell frozen data from calm | added "● Live" / "○ Not updating" |
| "All domains normal" while 42 decisions wait | Contradiction | added "N decisions waiting ›" link |
| Hero counts (excluded HVAC) vs tiles (include v2 HVAC) | Disagreed | **fix**: hero counts come from the same health data |
| Hero system badges (NPU idle, model, thermals, memory) | Engineering detail | **tap**: Engineering view |
| Sensor rows: raw metric key "pm10", full location, "SMA · EMA" | Jargon, truncated | **plain**: "PM10 · KN outdoor" (full location in tooltip and aria), "1 h average". SMA/EMA in the Engineering view |
| Pattern chips "gradual_decrease", causes "capacity_limit_throttling" | Enum text | **plain**: "falling slowly", "the load hitting a capacity limit" |

### Incident list

| Element | Problem | Action |
|---|---|---|
| Title "Tank level gradual decrease: KH building, level 98, water tank level sensor 00" | Long, enum words | **plain**: "Tank level falling slowly · KH-98 tank". The full title stays as tooltip and in Technical details |
| "MODE 3", label chip "water supply issue", "1 NPU call · 2.2 s" | Jargon | **tap**: Engineering view |
| "REFINED 3 H" | Jargon | **plain**: "RE-CHECKED 3 H" |
| Severity, decision state, id, domain, time | Useful | keep (id now carries the domain name) |

### Incident sheet (`device_before.png`, `before/incident_sheet_*`)

| Element | Problem | Action |
|---|---|---|
| Title repeated as the rules' title ("Raised by the rules as: …") | Duplicate, confusing | **tap**: Technical details |
| "Sensor time 13 Oct 18:55 IST · analysed 21:29:18 · 4 sensors · 1 NPU calls" | Two clocks plus pipeline counts | **plain**: "Water · detected 13 Oct 18:55 (sensor time)". The rest is under Technical details |
| "MODE 3" pill, "DONE IN 2.1 S" | Engineering metrics | **tap** |
| Flagged-sensor chips "TANK LEVEL / KH building, le…" | Truncated location | **fix/plain**: "Tank level / KH-98 tank · Warning". Full location in tooltip and aria |
| Cross-domain reasoner card (gate, model badge, token stats, label, "87% sure", evidence S1.E2…) | Engineering record shown first | **tap**: Technical details (open by default while the AI works, or in the Engineering view) |
| (missing) What is happening / Why it matters / What to do | No consequence, no plain action | **added**: root cause without evidence ids, consequence by report label, recommended action plus domain playbook |
| "87% sure" | Raw score | **plain**: "High". The number shows on tap |
| History fold (stage codes, "windows to 20:25", per-sensor pattern/status) | Hidden and coded | **plain**: "What changed since the alert", one line per re-check (↑ Got worse / ↓ Improved / ✓ Resolved / No change) plus a verdict sentence. The raw history stays under Technical details |
| Compare modes, NPU agents, context agents, Mode 1 baseline, activity log, raw output, prompts | For evaluators | **tap**: Technical details, unchanged inside |
| Footer "Requires human approval — no automatic actuation." (twice on the page) | Duplicated, says what but not how | **plain**, once: "Approve = you accept this and will carry it out. Dismiss = not needed (note required). Nothing is switched automatically." |

### Sensor sheet (floating sheet over the incident)

| Element | Problem | Action |
|---|---|---|
| Title "S1 · POWER" | Internal ref | **plain**: "Power · KH-04 room 01". S1 shown in the Engineering view |
| "Power agent (NPU) says", the gate, token stats | Jargon | **plain**: "What the AI found". Gate and stats in the Engineering view |
| Observations with E-chips; Evidence S1.E1..E10 list | Codes | **tap**: refs stripped in plain view. Chips and the list in the Engineering view |
| "Longer view … (r2 0.86, 33.0x normal variation) [E9]" | Statistics jargon | **plain**: r2 and ids hidden. Kept in the Engineering view |
| Chart, "Checked because" | Useful | keep (caption reworded) |

### Sensor sheet from Live/Map, Sensors tab, Map, About

| Element | Problem | Action |
|---|---|---|
| "Rule engine says (Mode 1, no AI)", "Evidence E1..E8", "Prompt sent to the on-device LLM" | Jargon | **plain** / **tap** |
| "Analyse with AI agents" | Jargon | **plain**: "Ask the AI to check this sensor" |
| Sensors tab health strip (links to Live) | OK | each chip now opens that domain's sheet directly |
| About | Missing a way to show the engineering detail | added an Engineering view switch card |

## 4. Information hierarchy now implemented

- **L1, Live → Campus health.**
  - A sentence: "1 of 6 areas needs attention: Water (critical)".
  - "● Live" and "N decisions waiting ›".
  - Six tiles, worst first. Each tile shows name, status (glyph + word), counts, what changed, "Do now", since when and open incidents.
  - The same summary appears as chips on the Sensors tab.
- **L2, Domain sheet** (tap a tile or chip). Content:
  - status + hint ("act now", "check soon");
  - since when and what changed;
  - the AI-vs-live note;
  - stale sensors by name;
  - **What to do now** (all steps, plus where they came from);
  - **Open incidents** (plain headlines, opening L3);
  - **Sensors** (worst first, value + status, opening the chart);
  - Technical details (raw health fields).
- **L3, Incident sheet.** Content:
  - severity, decision state, re-check stage;
  - the plain headline, domains and detected time;
  - (while running) the progress steps;
  - **What is happening**, **Why it matters**, **What to do**, **How sure the AI is** (word, number on tap), **What changed since the alert**;
  - **Sensors involved** and **Also checked nearby**;
  - the live re-check panel;
  - Approve / Dismiss footer.
- **L4, Technical details** (collapsed for operators; open while the AI is streaming or in the Engineering view): ids, mode, rules' title, both clocks, NPU calls and latency, label/action, the cross-domain reasoner card (gate, model, token stats, evidence chips, raw output, prompt), compare modes, NPU agents (live token streams), context agents, history, Mode 1 baseline and activity log.
- **Engineering view** (header `</>`, About switch, remembered per device): mode bar, NPU/model/thermal badges, Mode, label and NPU-call chips on incident cards, SMA/EMA, evidence ids and prompts, and Technical details open by default.

## 5. What changed (files)

- `app/device/web/app.js`:
  - new `plain language` region: `placeShort`, `plainTitle`, `stripRefs`, `confWord` and pattern/cause/action/impact maps (presentation only; the enums come from the backend unchanged);
  - rewritten `domain health` region: worst-first tiles, domain sheet `openDomain` / `renderDomainSheet`, connection indicator and decisions link;
  - the incident sheet split into an operator summary (`mainReport`, `revStory`, `opSummary`, `confButton`) and Technical details;
  - plain list cards, sensor chips and sensor sheets;
  - the Engineering view (`applyEng` / `setEng`);
  - the decisions-waiting badge, and hero counts from health.
  - Token/rtoken/batch streaming code is untouched; live boxes sit inside Technical details, which is open while running.
- `app/device/web/index.html`: Engineering view button; mode bar `eng-only`; health header (Live indicator, summary sentence, decisions link); new `#dsheet` (domain sheet).
- `app/device/web/styles.css`: the old domain-health block was replaced by the operator UX block (tiles, domain sheet, operator sections, dark-theme readable sizes, desktop tab-rail fix, `eng-only`).
- `app/device/web/sw.js`: cache bumped `sce-shell-v29` → `v30`.
- No Go changes. Model prompts, policy, refine, features, htpd and thresholds are untouched.

## 6. Verification

- `node --check app.js`: OK.
- `node proofs/2026-10-21_ux/ui_health_check_v2.js app.js`: OK, 7 scenarios. It covers plain-language helpers, the calm board, worst-first order, elevated/AI-raised/fault tiles, the domain sheet and incident link, time ticking without a rebuild, toasts, curbed/resolved, and the offline indicator.
- `proofs/2026-10-21_v2_research/domain_health/ui_health_check.js` now runs the v2 check. The v1 assertions are kept as `ui_health_check_v1_superseded.js`.
- `node proofs/2026-10-21_v2_research/streaming/ui_stream_check.js app.js`: OK.
- `go vet .` and `go test ./...` (WSL): OK (`go_test.log`). There are no Go changes, so the result was cached.
- Screenshots:
  - `before/` is the live board app (127.0.0.1:8000, read-only) at 412×915 and 1440×900, plus `board_now.png` (adb) and `device_before.png`.
  - `after/` is the new UI served by a host `--mock` backend (Windows build of the same source, `127.0.0.1:18000`, v2 agents) with injected scenarios (tank leak, throttling, stuck sensor, ventilation failure, load surge) at 412×915, 360×780 and 1440×900. `eng_*` are the same views in the Engineering view.
