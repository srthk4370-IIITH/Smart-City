# Phase 1 app + APK (2026-11-16)

The scope is the owner's decisions in `proofs/2026-11-13_weight_edit/NIGHT_PLAN.md` ("QIDK deploy" and the 2026-11-16
lines). Every feature sits behind an `htpd_profile` key. When a key is missing, the board behaves as it did before, so
the current models keep working.

- **APK:** `SmartCityEdge.phase1.apk`, md5 `09ebe315c183676c30bc5ddefde9c3c9` (also in `SmartCityEdge.phase1.apk.md5`).
- **Build:** `build_phase1.sh`. It follows the `build_r3.sh` pattern: tests first, then the arm64 build and the APK.
- **Deploy:** `deploy_phase1.sh`. It is **not run**; the owner runs it with `LAPTOP_IP=... bash deploy_phase1.sh --go`.
- **Tests:** `go_test.txt`.
- **Host smoke run:** `smoke/` (`summary.json` plus the raw snapshots).
- **Parity fixture generators:** `parity/make_fixtures.py` (cards, agt_v3) and `parity/make_fix_v4.py` (v4 reasoner,
  site tools, r5 header). Python is the reference.

## What is in the APK

| # | Feature | Files | Key (default) |
|---|---|---|---|
| 1 | **Campus API input.** Reads `/verticals/all/latest` every 5 s and ingests only the readings that changed; precise values are re-read from `/temporal`, because `/latest` rounds values ("8 pH"). On start, `/temporal` loads the last 12 h in 1 h chunks while sensor time waits 12 h back; the engine then catches up bucket by bucket with the event gate armed for the last hour only. The agent windows are therefore full at once, and a sensor that has been abnormal for 40 min or more alerts on the first poll, while events earlier in the night raise no alerts. `/nodes` is the registry. Values arrive as strings like "421 ppm"; the unit is checked and W is converted to kW; other units are `rejected_unit`. `created_at` is UTC. Every reading goes through `Engine.IngestReading`. The engine runs on the wall clock (`Engine.Live`). **The sliders are removed** from the UI. | `campus.go`, `engine.go` (SetLive), `dataquality.go` | `input=campus` (off), `campus_url` (http://10.2.203.214:9999), `campus_poll_s` (5), `campus_backfill_h` (12), `campus_fill_max_min` (20) |
| 1b | **No network page.** Shown when the API (and the MQTT broker, if one is set) cannot be reached. It has an "Open Wi-Fi settings" button (Android bridge `SCE.wifi()`) and the age of the last data. On reconnect the app resumes by itself and backfills the gap (up to 12 h). | `phase1.js`, `MainActivity.java`, `/api/campus/status` | follows `input=campus` |
| 2 | MQTT bridge (`prod_mqtt.go`, unchanged), pointed at the laptop broker | | `mqtt_url=tcp://<laptop>:1883`, `mqtt_topics=sce/#` |
| 3 | **Site model.** The campus tree is built automatically from `/nodes`: the building comes from the most frequent specific API name per code; the floor and room come from the node code (`KH03-03`); x,y and lat/lon come from the API (lat/lon accidentally stored in xcor/ycor are dropped). Equipment: SR-AC ac_unit, EM feeder, SR-EM meter, WL tank, WF pump line, WD meter, SL generator, CM camera, WE weather_station, SR-OC gateway. WN poles are left out. **Typed links are proposed by rules** (serves, supplies, feeds, outdoor-for); each is marked `inferred` and carries a `why`. Also built: worst-child roll-up, suspect-parent marking, and a versioned `state/site.json` (each version also kept in `state/site_versions/`) that can be edited through `PUT /api/site`. | `site.go` | always on: GET only reads; the tree is saved on the first read once `/nodes` is known |
| 3b | **Grouping.** A new incident whose flagged sensors are site-linked to an open incident inside that link type's window (§3.4 table: located-in 15 min, serves 30 min, outdoor 60 min, ...) joins its group. The two incidents point at each other through `related_incidents`, and `scope` is the LCA site node. The 3 h limit and the 12-sensor / 4-domain limits apply. An outdoor-for path counts only when one side is the outdoor sensor. | `phase1.go` | `site_group=1` (off) |
| 4 | **Site UI.** Campus map from the API x,y, coloured by roll-up (no floor-plan upload in Phase 1). Tree picker to edit the parent, kind, equipment type, use, capacity and links (add/remove). **Full spec-card editor**: every card field, new sensor types, validated by the backend with the same messages as `cards.validate_card`, and saved in the site config. The agents use a saved card from the next analysis. | `web/phase1.js`, `phase1.css`, `/api/site*`, `/api/cards*` | |
| 5 | **agt_v3 agents.** Card prompt builder byte-identical to the Python reference (`evidence.agent_user` and `build_gate.v3_from_real`). The policy gate uses the card's pattern and cause lists. Parsed and shown: `evidence` ids, `data_quality`, `severity_reason`. Consistency rule: "insufficient" caps the status at warning. | `features_v3.go`, `cards.go`, `policy.go`, `engine_v2.go`, `app.js` | `agents=agt_v3` (off = **B50**, untouched; B50 is also the rollback) |
| 6 | **v4 reasoner prompt** (SITE, card line, agent data, LINKS / SIBLINGS / NEARBY / SUSPECT), `SystemV4`, v4 incident header, `scope` / `suspect_node` report fields, plus **4 site chat tools** (get_site_tree, nodes_under, linked_equipment, site_status) with the r5 header and system. | `reasoner_v4.go`, `chat_site.go`, `chat_header_r5.txt`, `chat_system_r5.txt` | `reasoner_prompt=v4` (**off = r3**, Phase 2) |
| 7 | **Production features.** On: MQTT, time sync, heartbeat, alert delivery, local fog uploader, auto warm-up. Off: early provisional AI. OTA is built but not used. No Supabase. | `prod*.go` (unchanged) | set by `deploy_phase1.sh` Stage C |
| 8 | **Data-health panel**: last-seen age per sensor, fresh / stale (> 30 min) / missing, and the state of the API and MQTT links. | `/api/health/data`, Health tab | `health_stale_min` (30) |
| 8b | **Daily summary.** Once a day at 08:00 IST, the chat reasoner writes a summary of yesterday's stored incidents through the same tools the chat uses, grounded by a deterministic digest. Results go to `state/daily/`. | `/api/daily`, `POST /api/daily/run` | `daily_summary=1` (off), `daily_summary_hour` (8) |
| 8c | **Incident export.** CSV/JSON with severity, title, sensors, scope, group, label and root cause. | `/api/incidents/export?format=csv\|json[&days=N]` | |

### Field mapping (API → sensor bank)

The column choices follow `training/extract_series.py`.

| Bank sensor | API source |
|---|---|
| SR-AQ co2, temp, rh | `co2`, `temperature`, `relative_humidity` |
| AQ outdoor pm25, pm10 | `calibrated_*` (raw value as fallback) |
| WL level | `water_level` (cm) |
| WF flow | `flowrate` (m³/h) |
| WD tds, ph | `compensated_tds_value`, `ph` |
| SR-EM power_kw | `power` (W → kW) |
| EM-CR-SB00-00 power_kw | `gdpower` (W → kW) |
| EM-CR-SB00-00 pf | P / (√3 · V_LL · I) from the grid side; the API has no `gdpower_factor` |
| WE temp, rh, wind | `temperature`, `relative_humidity`, `wind_speed` |
| SR-AC units room_temp, setpoint, ac_on | `room_temp`, `temp_adjust`, `start_stop_status` |
| AC-KH03 ac_units_on, room_temp | Count of running KH03 units and their mean room temperature (units seen in the last 15 min), one value per completed 5 min bucket |
| SR-OC-GW-KH95-01 occ | The `occupancyN` field "SR-OC-GW-KH95-01:v" of its gateway |

**Not in the API:** `WM-WF-KH98-40` flow. The Health tab shows it as "missing".

**Cadence:** the API reports about every 10 min. The empty 5 min bucket between two readings ≤ 20 min apart is
linearly interpolated (states are held instead). This is the same inner-gap fill the agent window already does.

## Test results

**Unit and parity tests.** `go vet` passes and `go test ./...` passes (TestChatRouterBlind2Fixes is skipped; it depends
on the calendar, see the build_r3.sh note). Details are in `go_test.txt`.

Parity results (Python reference vs Go):

| Test | Cases | Mismatches |
|---|---|---|
| Cards: render | 20 of today's cards and 96 synthetic cards (`render_full` with and without place, `render_line`) | 0 |
| Cards: validate | the cards above plus 7 broken cards (`validate_card`) | 0 |
| agt_v3 from the v2 Go fixtures | 275 (171 continuous, 75 hvac_unit, 29 binary_state; tank lines included); conversion and generic builder | 0 |
| agt_v3 rows | 270 (continuous 173, hvac_unit 38, binary_state 47, count 12; 73 synthetic-card rows from dev, test_unseen_metric and test_campus) | 0 |
| v4 incident prompt | 136 rows (94 with agt_v3 agent data, 40 with a SUSPECT line, 30 card sensors) | 0 |
| v4 system text | `system_v4` | equal |
| Site chat tools | 280 calls on 7 sites (campus_site and 6 gen_site), with status and incident overlays | 0 |
| Grouping relation | 420 cases | 0 |
| Suspect sets | 105 cases | 0 |

The r5 chat header equals `tools_v4.json` chat_r5, and the v4 incident header equals incident_v4.

**Campus, grouping and export tests.** A fake API (httptest) covers:
- campus input: the 12 h backfill, W → kW, derived PF, the AC aggregate, occupancy channels, `rejected_unit`, full
  precision from `/temporal`, an outage leading to the offline page, and reconnect with gap backfill;
- live scenario injection: chaos and story scenarios still work on the live engine and are marked injected;
- live catch-up: a sensor critical for the last 50 min alerts on the first poll, and an event from 5 h ago does not (`TestLiveCatchUpFirstAlert`);
- grouping (same room within 15 min: joined; 3 h later: separate; tank vs room: separate) and the CSV/JSON export;
- the auto-tree on the real `/nodes` snapshot: valid, every bank sensor placed; occupancy → CO2 is `located-in`,
  AC → room temperature is `serves`, room → weather is `outdoor-for`.

**Host smoke run.** The backend ran on the laptop for 11 min (2026-11-15 21:50-22:01 UTC) against the live campus
API, with the mock LLM, the CPU only and `agents=agt_v3`. Raw data: `smoke/summary.json` and `smoke/raw/`.

- **Input:** 12 h backfill of 1806 readings in about 1 s. 131 polls at 5 s, API online the whole run, 0 panics.
- **Health:** 24 fresh, 2 stale, 1 missing. The 2 stale are `WM-WD-KH98-00` ph and tds: the API had no reading for
  41 min, which is genuine. The missing one is `WM-WF-KH98-40` flow, which the API does not provide.
- **Site tree:** auto-built and saved as v1, with 16 buildings, 24 floors, 12 rooms, 140 equipment, 21 sensors and
  246 inferred links.
- **First incident:** opened on the first catch-up poll with scope "room energy meter KH04-01". It is the idle SR-EM
  meter: flat 3 W, read as a sensor fault.
- **UI API checks** (`smoke/ui_api_checks.txt`):
  - all static files are served;
  - a broken card gives "critical must be above warning";
  - an owner card saved for `SR-AQ-KH03-03/co2` makes the site v2 (source owner) and is assigned to the sensor;
  - an invalid site PUT is refused with 422;
  - site status, the daily digest and the CSV export all work.
- **Earlier run:** `smoke/*run1_pre_catchup*` was made before the live catch-up change: 26 fresh, 1 missing, 0 panics.

## Laptop side for the board test

- **MQTT broker.** Mosquitto is not installed on the laptop yet. Install it on Windows, or in WSL with
  `sudo apt install mosquitto`. Start it with `mosquitto -p 1883 -v` (Windows: add `listener 1883 0.0.0.0` and
  `allow_anonymous true` to a conf file and pass `-c` with it). Test with
  `python3 app/tools/mqtt_pub.py --host <laptop-ip> --node SR-AQ-KH03-03 --metric co2 --value 600 --step 150 --count 10 --every 2`.
  Readings with a device `ts` take the same path as the API readings.
- **Heartbeat:** `python3 app/tools/heartbeat_monitor.py --port 8787 --dead-s 300`.
- **Alerts:** `python3 proofs/2026-11-16_phase1/tools/alert_sink.py 8094`. To use another sink, set `ALERT_URL=...`.
- **Local fog:** run `edge-agent-host --fog-addr 0.0.0.0:8092` on the laptop, as before. Nothing goes online.

## Deploy (`deploy_phase1.sh`, DEPLOY_R3 stages, auto-rollback)

| Stage | What it does |
|---|---|
| 0 | Preflight: APK and GGUF md5, `LAPTOP_IP` set, board on adb, no other adb job, `tele` and `df` |
| 1 | Snapshot `known_good` (the APK and htpd_profile from the board) |
| A | Install the APK alone, with the profile unchanged, then fastcheck and chaos-lite. A failure triggers a full rollback. |
| B | With the app stopped, push the reasoner GGUF and the htpd v9h binary with .part + md5 + mv |
| C | Retire the 2B split. Write the Phase 1 keys through .part + mv (the list is below), without the campus input yet. Check that `htpd_args` contains v9h and `--reason-ctx 8192`, and that the htpd log has no mapping failure. Run fastcheck and chaos-lite. A failure triggers a profile rollback. fastcheck drives the held `/api/ingest` slider path, which only the simulated engine reads, so it runs before Stage D. |
| D | Add `input=campus` and the `campus_*` keys, then restart. The engine now runs on the wall clock. |
| T | Live checks: campus status (backfill done, online), health, site, prod status, and chaos-lite. Scenario injections ride on the real readings and are marked injected (`TestLiveInjectionOnMeasured`). |

Rollback commands: `--stage rollback-profile` takes about 1 min; `--stage rollback-full` restores known_good (APK and
profile).

**Keys written in Stage C.**

| Group | Keys |
|---|---|
| Reasoner and chat | `reasoner_model=/data/local/tmp/gpu/rsn_v3_4b_r3c1_q4_0.gguf` (r3_edit_C1 Q4_0, **placeholder**: confirm, or set `REASONER_GGUF`), `chat_think=adaptive`, `chat_prompt=r3`, `reason_ctx=8192`, `reasoner_prompt=r3` |
| Agents | `agents=b50` |
| htpd v9h | `bin=.../htpd_v9h`; `env=` gets `HTPD_REASON_POOL=12544 HTPD_REASON_CHAIN=1 HTPD_REASON_DISK_KEEP=6` added |
| Campus input (Stage D) | `input=campus`, `campus_*` |
| Site and reports | `site_group=1`, `daily_summary=1`, `health_stale_min=30` |
| Production | `mqtt_url`, `time_sync=1`, `heartbeat_url`, `heartbeat_s=60`, `board_id`, `site_id`, `alert_webhook`, `fog_upload=1`, `fog_url`, `warm_idle_min=30` |
| Early AI | `ai_early_*` keys removed (off) |

**Later switches:**
- agt_v3 after its re-gate: `agents=agt_v3` plus the agt_v3 agent model key (profile switch).
- Phase 2: `reasoner_prompt=v4` with the new reasoner. This also turns on the site chat tools.

## Fast board test (≤ 45 min, after `deploy_phase1.sh --go`)

1. **(3 min)** The app opens. The Sensors tab has **no sliders**. The Live tab shows readings from the API (Health tab:
   ≥ 26 fresh, `WM-WF-KH98-40` missing).
2. **(2 min)** `/api/campus/status`: `online:true`, `backfill: done (… readings, 12 h)`, `last_data_age_s` < 900.
3. **(5 min)** First alert from the backfill: any abnormal sensor opens an incident within about 1 poll after the
   start, not after 40 min. Note the time on the incidents tab.
4. **(3 min)** **Wi-Fi off** on the board. Within about 20 s the "No network - connect to Wi-Fi" page appears with the
   last-data age. "Open Wi-Fi settings" opens Android Wi-Fi.
5. **(3 min)** **Wi-Fi back on.** The page closes, the log shows `campus: gap backfill`, and Health is fresh again.
6. **(4 min)** **Site tab.** The campus map shows dots and colours. In the tree, edit one inferred link (remove and add
   one), save, and check that the version goes up. Use **Rebuild from API**, then restore.
7. **(6 min)** **Card editor.** Pick `SR-AQ-KH03-03/co2` and choose "Edit card". Validate a broken value (critical below
   warning gives an error), fix it, save. Trigger one analysis and check that the agent prompt (engineering view) shows
   the new CARD. Undo by assigning `co2_indoor` back.
8. **(4 min)** **MQTT.** On the laptop broker, run `mqtt_pub.py` as a ramp on `SR-AQ-KH03-03/co2`. `/api/prod/status`
   shows `mqtt.connected` and accepted counts. Stop the broker for 2 min: it reconnects, and the No-network page does
   **not** appear while the API is reachable.
9. **(5 min)** **fastcheck plus chaos-lite** (Stage T, already run) and **2 stories**:
   - inject an occupancy plus CO2 rise in KH-03 and expect one incident group (`related_incidents`, `scope`);
   - inject a tank drain and expect a separate incident.
10. **(3 min)** **Health tab:** "Summarise yesterday" writes a daily summary (NPU) in `state/daily/`. Export CSV and
    JSON both download.
11. **(3 min)** **Production checks:** the heartbeat appears on the laptop monitor, an alert arrives at `alert_sink.py`,
    the fog outbox drains (`/api/prod/status`), and `warm: idle warm-up` shows after 30 min idle (optional).
12. **(4 min)** **Rollback drill (optional):** `--stage rollback-profile`, then the app is up with the old profile.

## Not done / notes

- **Floor-plan upload:** left out, as decided for Phase 1.
- **Grouping in Phase 1** links incidents into one group: one alert root, `related_incidents`, `scope`, and the group
  shown in the Site tab. The single re-run of the reasoner over the joined sensors (§3.4 "joined" revision) belongs
  with the v4 reasoner (Phase 2).
- **v4 site context in the app:** `buildV4Ctx` (SITE, LINKS, SIBLINGS, NEARBY, SUSPECT from the live site) is written
  but is only used with `reasoner_prompt=v4`. Its byte format is parity-tested; the board content needs a real test
  with the new reasoner.
- **`daily_summary`** uses the chat path, so it waits for the NPU like a chat question. It runs only when the reasoner
  is idle.
- **Mosquitto** is not installed on the laptop, so the MQTT bridge was tested only with the in-process broker tests
  (`TestMQTT*`).
