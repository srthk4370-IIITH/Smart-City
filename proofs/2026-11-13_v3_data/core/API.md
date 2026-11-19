# v3 core API (shared by the agt_v3 and rsn_v4 data builders)

Python 3.12, pure Python (no numpy). Import with `sys.path.insert(0, ".../proofs/2026-11-13_v3_data/core")`.
Importing `evidence` first sets up the `training/` paths (features, features_v2, longrange, hvac, teacher_v2).

| module | what | main calls |
|---|---|---|
| `cards.py` | spec-card schema (`CARD_KEYS`), today's cards, synthetic cards, renderers | `existing_cards()`, `metric_to_card(role, metric, node, location)`, `synthetic_card(type, rng, capacity=None)`, `jitter_card(card, rng)`, `render_full(card, place)`, `render_line(card)`, `validate_card(card)`, `patterns_for(card)`, `TRAIN_TYPES` (24), `TEST_TYPES` (8, never train) |
| `evidence.py` | E1-E10 lines (byte-identical to the app: 275/275 Go parity fixtures re-rendered, `go test TestPromptParityV2` ok) and the agt_v3 prompt | `register(card)`, `agent_system(card, n)`, `agent_user(card, node, location, hist, n, end, place=None, missing=None, hvac_ctx=None)`, `agent_prompt(...)`, `evidence_lines(card, hist, n, end)`, `verify_fixtures()` |
| `sitegraph.py` | site tree + typed links, grouping windows, roll-up, suspect rule, synthetic sites, IIITH tree | `WINDOWS`, `gen_site(seed, split)` (deterministic; train 0-5999, dev 0-299, test 0-399 with held-out motifs), `campus_site()`, `Index(site)` (`path_text`, `lca`, `relation(a, b)`, `rollup`, `suspects`), `render_tree`, `link_table`, `MOTIFS_TEST` |
| `sim.py` | physics simulator + fault injectors (parameters around `calib_stats.json`) | `Calendar(seed)`, `Drivers(seed, start, L, use, capacity, cal, events)`, `channel(card, drv, rng, **p)`, `tank(...)`, `hvac_ctx(drv, rng, node)`, `inject_fault(kind, y, onset, rng, card, s0)`, `calm_ify`, `scatter_missing`, `hold_missing` |
| `calib.py` | aggregate stats from the real laptop series -> `calib_stats.json` (no samples; asserted) | `python3 calib.py` |

Conventions
- Sensor node id = `<device>/<metric>`; every site node/link may carry `inferred: true` + `why` (campus tree).
- Card severity semantics (gold = these): limit cards read E1 (last), E2 (max) for spike/throttling, E3 (min) for
  spike/dip; rate cards compare window max-min with the mean of the window's first hour; card routines (cycle line)
  override as in teacher_v2; values beyond `impossible` are data faults (one isolated glitch = verdict suspect);
  a 5-min change above `max_step` is never a process event; >= 25 % missing = insufficient (critical capped to warning).
- Events used by `Drivers`: heatwave, rain, dust, exam, night_presence, ventilation_failure, power_cut, outage.
- Prompt additions beyond §2.2 (need the Go builder): optional `GAPS:` line after WINDOW; card line 2 may end with
  `max 5-min change X`; card may carry `rate rule` and `tank` lines.
