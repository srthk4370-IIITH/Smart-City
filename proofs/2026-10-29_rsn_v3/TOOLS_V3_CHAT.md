# Chat tools v3: new tools (shared spec for the training store and the device)

The 9 rsn_v1 chat tools stay as they are (names, args, result shapes; list_sensors' `status` now uses the live rule
below on both sides, and null fields are JSON null on the device too). Six tools are added. The Python implementation
(training store: `pipeline/tools_v3_impl.py` on `data/train_store_v3.sqlite`) and the Go implementation (device:
`Code/smart-city-edge-agent/app/backend/chat_tools_v3.go`) return the **same JSON** for the same data; this is tested
on a shared fixture (`pipeline/parity_cases.json`: `pipeline/parity_py.py` + `backend/chat_tools_v3_parity_test.go`,
field names, JSON types and values must match; numbers within their written rounding).

Common rules:
- `time` is the existing time object (`{"preset": ...}` or `{"from","to"}`), resolved against the store's/device's
  current (sim) time. Reading tools look at the readings with `from <= t < to` and `t <= now` (the device keeps 7 days
  of 5-min readings; the training store has hourly rollups from 2026-08-23 and 5-min readings from 2026-10-19).
- every result carries `coverage`: incident tools as the existing tools (`from` a date); reading tools
  `{"source":"device","complete":from>=kept_from,"from":"YYYY-MM-DD HH:MM","to":...,"note":"device keeps readings from <date>"}`.
- `metric` / `domain` values are the existing enums. Numbers are rounded like get_sensor_history (1 decimal; pf and ph
  3 decimals). Times are "YYYY-MM-DD HH:MM" IST. Sensors are listed in node+metric order.
- Read-only. Unknown sensor/metric/domain → `{"error": "..."}`.

**Live status** of a sensor (rank_readings, current_levels, faulty_sensors.live, list_sensors):
1. `sensor_fault` when a non-injected incident created in the last 4 h (the device's 48-reading window) flags the
   sensor as faulty (the sensor's status or the incident's severity is sensor_fault); on the device also when the
   engine's own rules say sensor_fault (flatline, erratic, implausible), which the training store emulates with its
   fault labels;
2. otherwise the latest reading against the rule limits (backend `features.go` Metrics + hvac room_temp): high-side
   metrics `warning` at >= warning limit, `critical` at >= critical limit; pf (low side) `warning` < 0.85, `critical`
   < 0.7; pH both sides (`warning` < 6.5 or >= 8.5, `critical` < 6.0 or >= 9.0); metrics without limits `normal`;
   no reading `no_data`.
(It is no longer "worst open incident": a sensor with old open incidents but normal readings is `normal`.)

**Occupancy** (`occ`) is a 0/1 presence sensor on the device (`features.go` "occupancy/occ" unit "0/1",
`device/data/sensors.json` min 0, max 1, step 1) and in the store; hourly values are the occupied fraction of the hour
(0-1). There are no people counts.

## 1. rank_readings: highest/lowest readings across sensors
args: `metric` (required), `time` (default today), `order` ("highest" default | "lowest"), `domain`, `location`
(substring of node / location text / building), `limit` (1-5, default 3), `include_faulty` (bool, default true).
result:
```json
{"metric":"co2","order":"highest","items":[{"node":"SR-AQ-KH03-03","location":"KH building, level 03, indoor air sensor 03",
 "value":1640.0,"unit":"ppm","at":"2026-10-22 09:50","status":"warning","faulty_suspect":false}],"sensors":1,"coverage":{...}}
```
Each item is one sensor's own extreme in the period (its first occurrence), sorted by value (ties node+metric).
`status` = live status; `faulty_suspect` = live status sensor_fault OR a sensor-fault incident on it in the period.
`sensors` = how many sensors were compared (after `include_faulty`).

## 2. current_levels: "how are X levels"
args: `metric`, `domain`, `location` (at least one required).
result: per sensor `{"node","metric","location","last","unit","status","today":{"min","max","mean"}|null,"limit"}`,
`count`, `coverage`. `limit` = the device's alert limits, null when the metric has none:
`{"warning":1000,"critical":1500}`; pf adds `"alert":"below"`; pH adds `"low_warning":6.5,"low_critical":6.0`.
`today` covers today's readings up to now. At most 20 items (then `"note":"first 20 shown"`).

## 3. recent_incidents: newest incidents regardless of day
args: `limit` (1-10, default 5), `domain`, `severity` (array), `metric`.
result: same item shape as find_incidents (`label`/`outcome` null when not set, e.g. while the AI still analyses),
newest first, plus `"total"` (all matching, any time). Demo injections excluded.

## 4. open_incidents: what still needs attention, per domain
args: `domain` (optional).
result:
```json
{"domains":[{"domain":"power","pending_review":2,"analysing":0,"by_severity":{"critical":1,"warning":1},"oldest_pending":"2026-10-21 07:20"}],
 "total_pending_review":5,
 "top_pending":[{"id":"INC-0103","severity":"critical","title":"PF dip: VN building, level 01, room energy meter 02","domain":"power"}],
 "definition":"pending_review = approval pending (no operator decision yet); analysing = AI still running","coverage":{...}}
```
Domains with nothing pending or analysing are left out (a requested `domain` is always shown); busiest first, ties by
name; `by_severity` lists non-zero counts only. `total_pending_review` counts each incident once. `top_pending` = up to
3 pending incidents, worst severity first (critical, sensor_fault, warning, normal), then oldest; `domain` = the
requested domain, else the incident's first flagged domain. "What should I check first" = open_incidents →
get_incident(top_pending[0].id) (2 calls instead of open → find → get).

## 5. faulty_sensors: sensors that look faulty
args: `time` (default last_7d).
result: `{"live":[{"node","metric","location","status":"sensor_fault","since"}],
"ai_diagnosed":[{"node","metric","location","incidents":2,"last":"2026-10-22 09:40","fault_kind":"stuck"|null}],
"count_distinct":n,"coverage":{...}}`. `live` = sensors whose live status is sensor_fault; `since` = the first faulty
incident in the 4-h window (device: or the start of the engine's abnormal run, whichever is earlier). `ai_diagnosed`
= sensors flagged sensor_fault in incidents of the period (closed ones too), sorted by incidents desc, at most 10.

## 6. what_if: data-fitted impact of a change
args: `driver` (metric; required), `change_pct` (e.g. 50 or -20) or `change_abs`, `location` (building/node
substring, optional), `time` (fit window, default last_7d).
Method: driver sensors = every sensor of the driver metric matching `location`, grouped by building; per building the
driver series is the mean of its sensors' hourly means (an hour needs >= 6 readings). No location and several
buildings: the building with the most linked targets (ties alphabetical). For every other-metric sensor of that
building: hourly means over the window, least-squares fit target = a + b·driver on the common hours. `driver_now` =
mean of the driver sensors' latest readings; a percent change on a driver that is ~0 now (<= 10% of its mean over
the hours it was above 0) is applied to that typical in-use level (`driver_basis` says which). `driver_after` is
floored at the metric's physical minimum but not capped (occupancy above 1 = busier than a fully occupied hour, an
extrapolation). A target is linked when n >= 24 hours, r2 >= 0.2 and it has a latest reading; after = latest +
b·Δdriver, clamped to the metric's physical range. **At most 5 estimates** (best r2 first, ties node+metric); metrics
without any link are listed (sorted) under `no_clear_link`. `location` in the result = the building that was fitted.
result:
```json
{"driver":"occ","change":"+50%","driver_now":1.0,"driver_after":1.5,"driver_basis":"current reading","unit":"0/1","location":"KH",
 "estimates":[{"metric":"ac_units_on","node":"AC-KH03","now":4.0,"after":5.4,"unit":"units","slope":2.853,"r2":0.5,"hours":168},
   {"metric":"co2","node":"SR-AQ-KH03-01","now":826.5,"after":1004.7,"unit":"ppm","slope":356.417,"r2":0.47,"hours":168}, "... (5 at most)"],
 "no_clear_link":["level","ph","pm25","rh","room_temp","tds"],
 "method":"linear fit of hourly means over the window; association, not a controlled experiment","coverage":{...},
 "note":"occupancy is a 0/1 presence sensor: values are the occupied fraction of an hour (above 1 = extrapolated)"}
```
(`note` only when the driver is occ.) In the training store the fits now spread over r2 ~0.2-0.75 with no-link cases
(make_store_v3.py adds per-hour noise and irregular occupancy / AC schedules; round 1 had r2 0.9-1.0 everywhere).

## Tool descriptions for the model header (pipeline/tools_v4.json "chat")
Compact schemas: metric/domain enums and the time object are spelled out once in the round-1 tools, the new tools
reference them (`"time": {"type":"object","description":"as in count_incidents"}`, metric/domain plain strings).
Header (Qwen3.5 tokenizer, pipeline/measure_header.py → data/header_tokens.json): round-1 9 tools 2,212 tokens,
15 tools 2,846 (+634; the first draft was 3,519, +1,307).
- rank_readings: "Highest or lowest reading of a metric per sensor in a period (default today), with time, place and status."
- current_levels: "Latest reading per sensor with live status, today's min/max/mean and alert limits."
- recent_incidents: "Newest incidents of any day."
- open_incidents: "Incidents awaiting an operator decision per domain and severity, and the top 3 to handle first."
- faulty_sensors: "Sensors faulty now and sensors the AI diagnosed as faulty in a period (default 7 days)."
- what_if: "Estimated effect of changing one metric (e.g. occupancy +50%) on other readings of the same building, fitted from recent history."

## Prompt rendering (device chat.go = training, Qwen3.5 HF chat template)
- History turns (before the last user question): `<|im_start|>user\n{q}<|im_end|>\n<|im_start|>assistant\n{answer}<|im_end|>\n`
  — no `<think>` block (the template strips reasoning from history, with thinking on or off). The device used to write
  an empty think block there; fixed.
- Current question: assistant rounds keep their reasoning: `<|im_start|>assistant\n<think>\n{reasoning}\n</think>\n\n{calls}`.
- Generation prompt: rsn_v1 (trained with enable_thinking=False): `<|im_start|>assistant\n<think>\n\n</think>\n\n`
  (unchanged). rsn_v3 (adaptive thinking, trained with thinking enabled; a target either reasons or closes the block
  at once): `<|im_start|>assistant\n<think>\n` (add_generation_prompt with thinking on); the model writes the
  reasoning (possibly empty) and `</think>`. Device switch: htpd profile `chat_think=adaptive` (or env
  `SCE_CHAT_THINK=adaptive`) when rsn_v3 is deployed.
