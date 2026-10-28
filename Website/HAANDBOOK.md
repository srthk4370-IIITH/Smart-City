# Website change log

## 2026-10-19 — Q&A usability and Use Case

- Restored Q&A accordion closing by preserving the HTML `hidden` state for answer bodies.
- Added a concise, data-backed situational Use Case lead for the measured crowded-room incident; its existing evidence chart remains the supporting detail.
- No project files outside `Website/` were changed.

## 2026-10-19 — correction: situations belong in Proofs

- Removed the added Q&A Use Case lead; the Q&A accordion close fix remains.
- Added three scenario-specific answers to the ordinary Q&A list: ventilation failure, tank leak, and multi-system failure.
- Added the Proofs “Measured situations” table: ten final-app scenarios with diagnosis, operator-ready action, agent count, NPU-call count, and measured completion time.

## 2026-10-19 — graphical situations in Decisions and Q&A; accordion Esc / single-open

- Q&A accordion checked in the built site at 360 and 1440 px: click opens, click again closes. Added Esc to close the open answer (a dialog still takes Esc first) and one-open-at-a-time (opening another closes the previous one). The earlier `.qa-body[hidden]` fix is kept.
- New collector `build/collect/situations.py` -> `data/situations/sit_*.json` (7 measured stories, new topic `situations` in run_all/verify/catalog) + `data/situations_index.json` (order, decision links, one "not yet measured" entry with no numbers). Sources: refined re-analysis runs on the QIDK (`proofs/2026-10-16_refined_reanalysis/device*/INC-*_<stage>.json`, `refine_check.jsonl`): tank leak (run 2), power throttling, ventilation failure, stuck sensor (run 3), PM2.5 spike (run 1); `proofs/2026-10-16_hw_grid/workload_INC-0392/0401.json` traces for crowded room and multi-system chaos, with the outcome and time from the final app run (`htpd_v6_app_stress_report_final.json`). AC in an empty room: not yet measured (v2, D119), shown as such.
- Traces are the injected demo readings (SPEC data policy 3), stitched from the early / 1.5 h / 3 h 4-hour windows; limits as in `app/backend/features.go`.
- Chart kit: new `trace` chart type (alert line + severity-coloured markers at alert / 1.5 h / 3 h, event-start shading, warning/critical lines; several sensors -> each line on its own range, tooltip shows real values). `ui.situation()` story card: claim, trace, stage timeline (event start -> alert -> agents done -> refined 1.5 h -> refined 3 h, pattern/status chips by severity), 12 h check row, outcome (severity, title, action, human approval, times, NPU calls), why it matters, decision links, expand to full screen.
- Q&A: "Situations — What happens when…?" section first on the page (one story at a time, `#/qa?sit=<key>` deep link). Scenario questions now carry `situation_id`, show the story as their evidence and link to the card; added "a sensor gets stuck" and "AC in an empty room (not yet measured)"; the tank-leak answer now states the measured 12 h result.
- Decisions: "In practice" section (tank leak, power throttling, stuck sensor, chaos) linked to G15/G16/G17/G05/G06/G04; decision cards get "In practice: … ↓" chips.
- verify.py: 100/100 (14 new situation checks recomputed from the incident JSONs). Browser QA (puppeteer, built site, 360 + 1440): 54/54, no console errors, no horizontal scroll; screenshots in `qa/situations/`.

## 2026-10-19 (evening) — final polish: data fixes, less repetition, Training v2 section

**Data fixes (teaching.md 9.1).**
- `rawdata.py`: pH is two-sided (low warning < 6.5, critical < 6.0, as `generate_dataset.status_of`); the explorer draws the low lines and the subtitle names both sides. Raw data regenerated: breaches 19,819 → 20,538, critical 6,282 → 6,923 (water 3,708 → 4,427).
- `app_ux.py`: chaos claim "~21 s (Genie: 40.8-48.9 s)" (was "was 41-57 s"); Mode 2 vs 3 uses the true median, 3.4 s vs 4.2 s (was the 6th of 10, 3.6 / 4.3); claim/why set in the collector, CLAIMS override removed; G03 text updated.
- `use_case.py`: `uc_cross_domain` claim "All 4 multi-sensor incidents span 2-4 domains in one report" (was "3/3" with 4 plotted); `uc_coverage` notes explain readings vs CSV rows. `latency.py`: LADE notes state −32.5 % (one prompt) vs ~−20 % (14 prompts).
- `qa.py`: breach counts, Mode medians, s/step, dev losses and the training position are filled from the generated data / training log at build time (no typed numbers). New questions: "Is every answer that passes the gate correct?" (names the passed "863 ppm exceeds 1000 ppm" answer as model text, numerically wrong), "What happens after training finishes?", "How will you know v2 is better than v1?" (merged with "What will decide whether v2 ships?"), "What if v2 fails the acceptance test?". 84 questions.

**Removed (repetition, clutter).**
- Route: the anchor row (47 s → 20.7 s repeated the Deck; 54 % → 90.7 % repeated the Accuracy route card); journey phases start closed except the latest.
- Q&A: the third use-case anchor (47 s → 20.7 s), the "Current status" side card (repeated the Deck strip), the second "In short" anchor (54 % → 90.7 %).
- Deck: the "Next → Route" footer (Start here already leads there).
- Chunking: Proofs shows at most 7 cards per tab, then "Show N more results"; Decisions features 7 groups (was 12).

**Added: Training v2 on Route** (`#/route?s=training`, linked from the Deck status strip and the Proofs Training v2 tab): progress bar (step / 4,494 from `status.json` at build time), best dev loss, s/step, hours left, state; dev-loss curve with every eval + train loss per token (log scale); step-over-time chart with the 8 interruption causes as dots and a cause → fix table (BSOD 0xD1, thermal sleep, lid standby, battery, RAM, supervisor, checkpoint interval, start failure); "What v2 changes, and why" (RETRAIN_V2_SPEC highlights); acceptance checklist (spec #20) and the five steps after training.

**Checks.** run_all + rawdata regenerated; `verify.py` 100/100. Browser QA (puppeteer, built site, 360/1440/1920 × 7 pages): no console errors, no horizontal overflow, every chart has the expand button; polish checks (home link, Proofs "more" on 4 tabs, training overview link, pH low limits, new Q&A answers searchable). Screenshots in `qa/polish/`. teaching.md updated (3.2-3.3, breach numbers in 4.1/6.x/7.1, 4.9 claims, status, 9.1 rewritten as fixed/explain, Q&A Q4/Q5/Q64-66/Q79/Q81 + new Q82-Q84).
