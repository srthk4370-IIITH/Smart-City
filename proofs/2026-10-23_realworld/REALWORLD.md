# Real-world data: what the agent will meet, what we changed, what to train (2026-10-23)

**Who this is for:**
- the owner, for the workflow;
- the model team, who should read §5 first.

**Scope:** backend only (`app/backend`). Prompt formats are unchanged and byte-identical, and the full Go suite passes.

## 0. In one paragraph
Until now the app read only sliders and replayed series. Its `/api/ingest` used **sample-and-hold**: a device that went silent kept "reading" its last value forever, with simulated jitter on top. That invents data for the AI.

The raw SCRC exports show that silence is the normal state of a real campus feed:
- only **34–67%** of hourly 4 h windows are complete enough for the agent, by the same rule the engine uses (weather 20%);
- 6% of all indoor CO2 rows are below the physical range;
- stuck runs of up to 1,000+ h;
- glitch rates up to 168 per 10k readings;
- firmware versions that flip back and forth inside one node id;
- clocks that are not unix time;
- two different timezone conventions.

**What the backend now does:**
- a data-quality layer: measured feeds with device timestamps, no invented readings, and dedup, late-reading and burst merge;
- OPC-UA-style good/uncertain/bad flags, and staleness;
- a gate-only glitch filter;
- an ISA-18.2 deadband and off-delay on the event gate;
- maintenance and sensor-replacement hooks;
- data quality shown in domain health.

On a real SCRC CO2 series with outages: **91 fabricated readings before, 0 after.**

## 1. Evidence from the raw SCRC exports (`ihub-clean-datasets/*.csv`, one year)
Scripts: `raw_audit.py` (raw rows per node), `summarize.py` and `window_usability.py` (on the 5-min training series). Outputs are `raw_audit/*.json`, `raw_audit/summary.json` and `raw_audit/window_usability.json`. All data stays local.

| finding | numbers (raw) | why it matters |
|---|---|---|
| Native cadence differs per family | AQ outdoor 16 s, CO2 79 s, energy 81–120 s, AC 240 s, water level 207 s, flow 300 s, **TDS ~3,840 s (hourly)** | the engine assumes 1 reading per 5 min. An hourly TDS sensor can never form a 4 h window (it needs ≥45 of 48 buckets), so live it is always `insufficient_data` |
| Outages are routine | share of time in gaps (median node): CO2 12%, power 17–27%, flow 56%, level 47%, weather 70%. Gaps > 24 h: CO2 66, flow 195, TDS 85, occupancy 63 | the old held path turned every outage into a flat line |
| Site-wide silence (≥80% of nodes silent) | water level 3,049 h of 7,596; weather 4,779 of 8,761; flow 1,174; occupancy 1,124; SR-EM 1,504 | gateway or backend outages hit whole domains at once |
| Usable 4 h windows (engine rule, hourly ends) | air 57%, outdoor 67%, HVAC units 81%, occupancy 55%, power 42%, water 34%, **weather 20%** | expect "insufficient data" often; in usable windows, 1–54% contain interpolated gaps |
| Out of range | CO2 < 250 ppm: 436,754 rows (6.2%). **SR-AQ-KH00-02 alone: 367,896, i.e. months of a broken sensor.** AC room temp out of 10–45 °C: 214k. TDS ≤ 1: 2,419. SL power < 0: 316k | sentinels and dead sensors. The old ingest **clamped** them into the range, so −999 looked like a real dip |
| Stuck runs (identical values ≥ 6 h) | AC room temp 399 runs (longest 3,540 h), flow 1,955 (mostly genuine zero flow), EM 169, CO2 24 (longest 1,079 h on TH04-00), TDS 117 | frozen versus genuinely idle must be told apart; staleness is a different problem from stuck values |
| Single-reading glitches (8σ from both neighbours, neighbours agree) | TDS 168 per 10k, water level 47, SR-EM power 43, EM 14, outdoor PM 5.6, CO2 0.2 | one bad reading in a 4 h window can make the rules read "spike → warning" for 4 h |
| Duplicates | TDS: 3,308 repeated device timestamps (434 exact copies); weather 10; flow 4 | at-least-once delivery |
| Arrival order | the export is not time-ordered: 379k CO2 rows arrive after a newer one; TDS file order runs Nov → Mar | late or out-of-order merge is needed |
| Device clock | EM.csv: **21,814 rows with `Sensor_Timestamp` ≈ 1.0e6** (uptime counter, not unix time). Elsewhere device time equals server time, so lateness and bursts cannot be measured from this export | never trust a device ts blindly |
| Timezone | `WM-WL` and `WM_WD` stamp `+05:30`; every other file stamps `+00:00` | `training/extract_series.py` uses `fromisoformat(...).timestamp()`, which handles both. A live gateway must send UTC epoch |
| Firmware / unit changes | SR-EM: V1 reports W, V2 kW (handled ×1/1000 in `extract_series.py`). **TDS KH96-02: 872 version flips V1.0.0↔V4.x** (two devices under one id?). 190 version changes have a ≥1.5× median shift across the change | a level shift with no physical cause. The meter's unit must come from metadata, never be guessed |
| Training series = bucket **means by server time** | `extract_series.py` | the live measured feed now does the same: a bucket is the mean of its readings |

Literature (generic web research, URLs in §7):
- ISA-18.2 / EEMUA 191: deadband, on/off delay, chattering, out-of-service and shelving.
- OPC UA status codes and Haystack `curStatus`: good, uncertain, bad, stale.
- MQTT QoS1 duplicates: dedupe on the timestamp in the payload.
- Store-and-forward gateways replay a backlog in bursts with the original timestamps.
- CloudWatch has an INSUFFICIENT_DATA state.
- GRU-D: missingness carries information, so do not impute for the model.
- School IoT deployments: outages from under 1% to 36%; about 19% faulty readings in one sensor network.

## 2. Our pipeline against each issue: before → after

| # | issue | before (traced) | failure scenario | after | test |
|---|---|---|---|---|---|
| 1 | Device goes silent | `feed()` samples the held `SimSensor.Value` + `NoiseScale` jitter every poll, forever | a CO2 node offline 6 h is read as a jittery flat 6 h; the AI analyses invented data | **measured feed** (a reading with `ts`): bucket = mean of real readings, otherwise empty. Legacy held API values stop after 15 min of wall time (`apiHoldSec`) | `TestDQMeasuredFeedNoInventedData`, `TestDQHeldAPIValueGoesStale`, `TestDQRealSCRCReplay` (real data: 91 → 0 fabricated) |
| 2 | Gaps inside the window | the Window rule (≤3 of 48 missing, live edge forward-filled ≤3) existed but never triggered, because nothing was ever missing | — | now real: windows with too many gaps give `insufficient_data` plus a **reason** (`no reading for 25 min (sensor or gateway offline)`, `7 of 48 readings missing…`, `warming up…`, `sensor replaced…`). No AI call. Refinements say `insufficient data at this stage (<reason>), previous finding kept` | measured / burst tests |
| 3 | On-delay counted repeated windows | `same++` every poll, even with no new reading (forward-filled edge) | an offline sensor reaches 8 "readings" on stale data | `same` advances only when bucket `sim` holds a real reading. Insufficient data resets it | burst test |
| 4 | Late / out-of-order / gateway burst | no timestamp; a burst collapsed into the last value | a reconnect flushing 2 h of backlog becomes one reading | a reading with `ts` lands in **its own bucket** (late ones merge as a mean). The gaps fill, so the window is usable again. Too old (> 26 h) is dropped | `TestDQBurstAfterReconnectBackfills` |
| 5 | Duplicates (QoS1) | n/a (each POST was a new value) | — | the same device `ts` twice → `duplicate`, counted | burst test |
| 6 | Bad clocks | n/a | uptime-counter ts, or a device clock ahead | ts < 1e9, or more than 5 min in the future → arrival time, flagged `uncertain` (`+clock`) | `TestDQIngestQualityRules` |
| 7 | Bad values and sentinels | `SetSensor` clamps to [min, max] | −999 → 0 → CO2 "critical dip" | measured feed: out of range → `rejected_range`. `quality:"bad"` is never stored. Legacy clamp is kept (the app suite drives rail faults that way) but counted and flagged `uncertain` | quality-rules and held tests |
| 8 | Single-reading glitch | the rules see a "spike"; status stays abnormal while it is in the 4 h window, and after 8 readings an incident opens | TDS sensor at 168 glitches per 10k → about weekly false incidents | `glitchFree` (**gate only**): one isolated reading ≥8 robust σ from both neighbours, neighbours agree, only for CO2/temp/RH/TDS/pH/level/room temp. Never for power, flow, PM2.5 or occupancy. Two or more glitches = a fault pattern, left alone. The candidate keeps the **raw** window, so the AI never sees modified data. Quality shows `uncertain: one-reading glitch at HH:MM ignored` | `TestDQGlitchFilterGateOnly` |
| 9 | Chattering at the limit | any normal reading reset the on-delay, and one normal reading ended an episode. The re-arm then raised a new incident on the next value above the limit | CO2 hovering at 1000 ppm: either **never** alerts (5 above, 1 below, repeat) or floods incidents | **deadband 5% of the warning limit + off-delay 3 readings.** A normal reading still inside the deadband neither restarts the count nor ends the episode until it repeats 3 times | `TestDQChatterAtLimitOneIncident` (120 readings, exactly 1 incident) |
| 10 | Maintenance / test gas | — | a technician's 2,500 ppm test gas raises a critical incident | `POST /api/maintenance {node, metric?, minutes, reason}`: readings are not recorded, the gate is held, quality is `maintenance`, and the gate re-arms | `TestDQMaintenanceAndReplacement` |
| 11 | Sensor replacement | — | the new sensor reads 40 ppm lower; E9 reports a "level shift", and refinements compare against the old baseline | `replaced:true` drops the history up to now. The sensor shows `sensor replaced: N of 48 readings since the swap` until a full new window exists | same test |
| 12 | Data quality is invisible | `domainhealth` showed only `stale` (always fresh under hold) | — | each `SensorState` now has `quality`, `quality_reason`, `coverage_4h`, `feed` (held/measured) and `ingest` counters. `DomainHealth.data_quality[]` lists non-good sensors with the reason | `TestDQHealthShowsDataQuality` |

**Unchanged on purpose:**
- prompt text;
- the Window gap rule (it mirrors training);
- slider behaviour;
- legacy `/api/ingest {node, metric, value}`, apart from the 15-min stale cut and the `quality:"bad"` drop;
- the v2 window ladder;
- refine elevate/curb.

**Full suite:** green (`go_test_full.log`), `go vet` clean.

### Still open: decisions or follow-ups, not implemented
1. **Native cadence slower than 5 min (hourly TDS).** A live TDS sensor will always be `insufficient_data`. There are two options:
   - give such sensors a per-sensor native interval, and let the agent see "readings every 60 min" (this needs training data with sparse windows);
   - or keep them rules-only.

   Owner decision. Do not interpolate 12 buckets: that invents data.
2. **On-delay after a backfill burst.** A burst can reveal an event that is already hours old, but the gate still waits 8 *new* readings (40 min). This is conservative. Re-evaluating each backfilled bucket would alert sooner.
3. **Unit and firmware changes.** These need sensor metadata on the feed: version or unit, triggering a baseline reset like a replacement. No reliable auto-detection: the TDS version flapping shows that the version field itself is dirty.
4. **Holidays and calendar.** There is no holiday calendar. Low-occupancy holidays will read as "off-hours presence absent / low load". This is a training gap, see §5.
5. **Timezone.** The feed contract is UTC epoch seconds, and the board's display is IST. The SCRC files mix `+00:00` and `+05:30`, so any new importer must parse offsets.
6. **Demo speed.** The measured mode maps device time to sensor time by age (`now − ts`). This is exact when polls are real-time (Speed 1, 300 s). At the 2 s demo poll, use the slider or held path.

## 3. Feed contract (for whoever connects real gateways)
```
POST /api/ingest {"node","metric","value"}                       # legacy: held like a slider, expires after 15 min silent
POST /api/ingest {"node","metric","value","ts":<unix s UTC>,"quality":"good|uncertain|bad"}
POST /api/ingest {"readings":[{node,metric,value,ts,quality}, ...]}   # gateway batch / backlog, <= 5000
  -> {"results":["accepted","late","duplicate","rejected_range","rejected_bad","too_old","before_replacement","maintenance","accepted+clock",...]}
POST /api/maintenance {"node","metric"?,"minutes":60,"reason":"calibration","replaced":false}   # minutes 0 ends it
```
The first reading with `ts` switches that sensor to the measured feed and drops its simulated pre-fill. The sensor then warms up until it has 45 or more real buckets; a gateway can backfill the last 4–12 h in one batch to skip the warm-up.

## 4. Tests and proofs in this folder
- `go_test_dq.log`: the 9 `TestDQ*` tests, verbose, including the real-data replay numbers.
- `go_test_full.log`: the full suite.
- `raw_audit.py`, `raw_audit/*.json` and `raw_audit/summary.json`: per-node raw statistics.
- `window_usability.py` and `raw_audit/window_usability.json`.
- Code:
  - `app/backend/dataquality.go` (new);
  - `dataquality_test.go` and `dataquality_replay_test.go` (new);
  - edits in `engine.go` (feed, detect: glitch, maintenance, deadband/off-delay, fresh-reading on-delay, quality), `sensors.go` (clamp flag), `server.go` (`/api/ingest` ts/quality/batch, `/api/maintenance`), `domainhealth.go` (`data_quality`) and `refine.go` (reasoned no-window note).

## 5. Real-world cases the domain agents must handle: ranked, with a synthesis recipe from SCRC series
These are ranked by how often they will occur on the live feed multiplied by how badly they are covered today.

The inputs are always **raw values**: never smooth or impute what the agent reads. Labels are in the v2 schema: `pattern`, `status`, `event_active`, `onset`, `fault_kind`.

1. **Gaps interpolated inside the window, near the edges.**
   - *Real:* 1–54% of usable windows contain 1–3 interpolated buckets (occupancy 54%, weather 42%, HVAC 21%, water 13%). The v2 generator allows up to 6 missing.
   - *Risk:* a linear fill across a gap looks like a ramp, a step or a flat run.
   - *Synthesize:*
     - take clean windows and delete 1–3 buckets (or up to 6 at 8–12 h) at random, including runs adjacent to an event and within the last 4 buckets;
     - linear-fill exactly as `Window()` and `generate_v2` do;
     - keep the original label.
   - Add hard negatives: a 3-bucket fill on a calm window must stay `stable`/`normal`, never `step` or `flatline`.
2. **A single glitch spike or dip in a calm window** (quality-related, not a process event).
   - *Real:* TDS 168 per 10k, level 47, SR-EM 43.
   - The gate now filters one isolated glitch in CO2/temp/RH/TDS/pH/level, but the AI still sees raw windows: in a refinement, or when another real abnormality coexists.
   - *Synthesize:* insert one reading at 8–30 robust σ (or a sentinel such as 0, or a range-rail value) into a calm SCRC window.
   - *Label:* `pattern=spike|dip`, `status=normal`, `event_active=false` and `fault_kind=dropout` for a 0/rail value, else `normal`/`monitor`. A single 5-min point is not an event for these metrics.
   - For power and flow, keep the existing load-surge labels.
3. **Post-maintenance or replacement level shift.**
   - *Real:* 190 firmware changes with a ≥1.5× median shift (TDS); SR-EM W → kW.
   - *Synthesize:* at a random onset in an SCRC window, apply an offset of 0.5–3× the noise or a ×0.5–2 gain, with no transient. Make variants with a 1–6 bucket gap just before the shift (the sensor was off while it was swapped).
   - *Label:* `step_increase`/`step_decrease`, `status=sensor_fault`, `fault_kind=bias`, action `inspect_sensor`. Do not label it a process event when only one sensor of a co-located pair moves (needs E-line context; see 8).
4. **Slow calibration drift over 12 h.**
   - *Synthesize:* add a linear ramp of 0.5–2× noise per 6 h to a real 12 h history; E9 should show `slow drift`.
   - *Label:* `fault_kind=drift`, `sensor_fault` when the drift is physically implausible (CO2 drifting below outdoor ~420, TDS drifting upward while flow is stable), else `warning`. v2 had drifts; add **small** ones (1–2× noise) labelled `normal`/`monitor` as negatives.
5. **Stuck or frozen value versus a genuinely idle signal.**
   - *Real:* AC room temp, 399 runs ≥ 6 h; CO2 up to 1,079 h; flow 1,955 (mostly genuine zero flow).
   - *Synthesize:* replace the second half of a window with its last value, at exact repeats (stuck) or with ±1 quantisation step (quantised).
   - *Contrast:* night-time zero flow, an AC off with the room temperature drifting, and occupancy 0 overnight are `normal`.
   - Key cue: the real data still has tiny noise; stuck data has none, at a non-zero level.
6. **Long-dead or below-physical sensor** (SR-AQ-KH00-02: months of CO2 < 250).
   - *Synthesize:* hold or wander the CO2 value in 150–300 ppm.
   - *Label:* `sensor_fault`, `fault_kind=bias` or `stuck`, `inspect_sensor`, at any window position. A fresh one in the last hour should also be labelled.
7. **Holiday or weekend low-occupancy days.**
   - *Synthesize:* splice a weekday's power, CO2 or occupancy window with a Sunday or public-holiday window from the same node (compute weekday medians from SCRC), keeping the weekday timestamp.
   - *Label:* `normal`/`stable` with `low load`. Negatives: *weekday* low load with HVAC running → `warning`, `schedule_or_control_fault`.
   - Needs a calendar-aware E-line only if the owner wants one. That would be a prompt change, so not now.
8. **Concurrent multi-domain events.**
   - *Synthesize:* inject events into two to three domains with onsets 0–60 min apart: CO2 plus power (occupancy), outdoor PM plus indoor PM (ingress), level plus flow (pump). Each agent still sees one sensor.
   - The cross-domain reasoner, not the agents, needs these. Generate them as reasoner-level samples with the two to three agent outputs plus the truth.
9. **Recovery right after a gap.**
   - *Synthesize:* a window whose newest 4–12 buckets come after a 2–6 h hole. Make the pre-gap level differ from the post-gap level (the event happened during the outage).
   - *Label:* `step`, with `onset` at the first post-gap reading and `event_active=true` if beyond limits.
   - The window contains only real points; history lines (E9/E10) are computed over the gap-limited history (`historyLocked` stops at gaps > 3).
10. **Short windows from history truncated by gaps.**
    - `ValidV2N` shrinks the window when the history is short. Make sure every role has enough 2–4 h windows that are a truncated 12 h history: E9 "12 h view" over only 3–5 h, and E10 "in the last 4 h".
    - *Synthesize:* cut the SCRC history at a random gap.
11. **Chattering around a limit.**
    - *Synthesize:* a value hovering at the warning limit ±3% with noise.
    - *Label:* `warning`, `pattern=erratic|stable`, `event_active=true`. It must not swing between `normal` and `warning` across adjacent windows; this is a consistency test, not new data.
12. **Weather-driven correlation.**
    - Outdoor heat → room temperature → AC power; rain → level; outdoor PM → indoor PM.
    - Already partly covered (`outdoor_pollution_ingress`, `high_heat_load`). Add samples where the agent sees only its own sensor rising slowly in step with a daily cycle: `normal` (daily cycle) unless it is beyond limits.

**Recipe rules (all cases):**
- base windows from TRAIN months only;
- keep the sensor holdouts;
- event sizes in robust σ of that node;
- every synthetic window passes the same Window rule as the engine (≤3 missing at 4 h, or the v2 6-per-48 equivalent);
- keep a 60-sample review page as before.

## 6. Ranked backend follow-ups (not done tonight)
1. An owner decision on hourly sensors (open item 1).
2. Gateway contract plus metadata (unit, firmware, `replaced` events) in the deployment checklist.
3. Re-evaluating the gate over backfilled buckets.
4. A UI chip for `quality` / `quality_reason`: the data is already in `/api/live` and `/api/health`; the web UI does not render it yet.
5. A flood guard (EEMUA: ≥10 alarms in 10 min). Batching into one incident already does most of this.

## 7. Sources (generic web research, 2026-10-23)
- **ISA-18.2 suppression, shelving and out-of-service:**
  - https://www.processonline.com.au/articles/65390-Improving-alarm-management-with-ISA-18-2-Part-2
- **Deadbands and on/off delays:**
  - https://www.exida.com/Blog/why-should-i-use-an-alarm-deadband
  - https://www.octave.com/learn/resources/blogs/taming-wild-alarm-system-part-three
  - https://www.emersonautomationexperts.com/?p=44751
- **Chattering:** https://skoge.folk.ntnu.no/prost/proceedings/ifac2014/media/files/0114.pdf
- **Floods (≥10 in 10 min):** https://digitalrefining.com/article/1000558/alarm-floods-and-plant-incidents
- **OPC UA status codes:**
  - https://reference.opcfoundation.org/specs/OPC-10000-8/7.3
  - aggregates PercentDataGood: https://reference.opcfoundation.org/specs/OPC-10000-13/full
- **Haystack `curStatus`:** https://project-haystack.org/doc/lib-phIoT/curStatus
- **PI stale and bad:** https://docs.aveva.com/bundle/pi-server-f-da-smt/page/1022841.html
- **MQTT QoS1 duplicates and dedup:**
  - https://www.emqx.com/en/blog/introduction-to-mqtt-qos
  - https://help.aliyun.com/en/iot/support/faq-about-messaging
- **Store-and-forward bursts:**
  - https://flowfuse.com/blog/2025/11/store-and-forward-edge-data-buffering/
  - https://proxus.io/blog/store-and-forward-in-iiot/
- **Clocks and DST:**
  - https://docs.aws.amazon.com/wellarchitected/latest/iot-lens/foundations.html
  - https://amplitude.com/blog/dont-trust-client-data
  - https://inventivehq.com/blog/dst-transition-edge-cases-lost-repeated-hours
- **Hampel / median outlier filter:** https://search.r-project.org/CRAN/refmans/pracma/html/hampel.html
- **Sensor fault taxonomy:**
  - https://escholarship.org/uc/item/1rb4285n
  - https://qed.usc.edu/papers/SharmaGG10.pdf
  - about 19% faulty readings: https://hal.archives-ouvertes.fr/hal-00958535
- **Missingness: do not impute for the model:**
  - GRU-D: https://pmc.ncbi.nlm.nih.gov/articles/PMC5904216/
  - https://opensearch.org/blog/a-customer-impact-journey-when-no-data-is-still-important-data/
- **Insufficient-data state:** https://docs.aws.amazon.com/AmazonCloudWatch/latest/monitoring/alarms-and-missing-data.html
- **Real building datasets:**
  - school IoT outages up to 36%: https://arxiv.org/pdf/1907.10818
  - BDG2: https://arxiv.org/pdf/2006.02273
  - BuildingsBench (>10% missing excluded): https://arxiv.org/pdf/2307.00142

Secondary-source caveat: the ISA and EEMUA figures come from vendor or study pages, because the standards are paywalled. Per-signal on/off delay seconds were not verified, so our delays are in readings (8 on, 3 off near the limit).
