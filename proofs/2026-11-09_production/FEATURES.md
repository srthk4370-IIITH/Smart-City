# Production features: built, off by default (2026-11-09)

Source: `proofs/2026-11-09_roadmap/ROADMAP.md` §2.3 (L1, L4) and §4. Security hardening is out of scope: it is
documented in `PRODUCTION_GAP.md` and was not built.

Code is in `Code/smart-city-edge-agent/app/backend/prod*.go`. Scripts are in `app/tools/`. Nothing was committed,
installed or run on the board.

**Off by default.** Each feature starts only when its `htpd_profile` key is set. The matching env var
`SCE_<KEY_IN_CAPS>` also works. With no keys:
- nothing starts;
- no store hook is installed;
- `/api/prod/*` answers 404, as before;
- incident JSON is unchanged (the only new field is `clock_uncertain`, which is `omitempty`).

`TestProdOffByDefault` checks this. Keys are read once at app start, so a change needs an app restart. The early-AI
keys are the exception: they are re-read every 10 s.

**Changes to existing files** (small hooks only):
- `main.go`: `startProd(srv)`, the `-fog-addr` flag, and the clock re-stamp callback.
- `server.go`: `s.prodRoutes(mux)`.
- `store.go`: `persistHook` after each incident write.
- `sensors.go`: `devClock` (= `time.Now`) and the time-sync offset in `nowTime`.
- `reason.go`: `CreatedWall: incidentWall()` and the `ClockUnsure` field.

**Tests**
- Laptop, WSL, CPU only.
- `go test ./...`: every test passes except `TestChatRouterBlind2Fixes`. That test already failed before this work
  (another agent's date-dependent router test in `chat_fixes_1103_test.go`).
- Logs: `go_test_full.txt`, `go_test_prod.txt` (23 production tests, all pass) and `ota_test.txt` (10/10 pass).

## Shared endpoints
| Endpoint | What it does |
|---|---|
| `GET /api/prod/status` | State of the clock, MQTT, alert queue, fog outbox and warm-up |
| `GET /api/prod/selftest` | OTA health gate. Checks: the engine is ticking, `state/` is writable, htpd is up (when it is the engine), and the clock is valid. Returns 200 or 503 |
| `POST /api/prod/time {"unix":…}` | Laptop time push. Accepted from loopback, or with `X-API-Token` (same guard as every write) |

---

## 1. MQTT ingest bridge (`prod_mqtt.go`): done

**Keys**

| Key | Default | Meaning |
|---|---|---|
| `mqtt_url` | (unset = off) | Broker. `tcp://host:1883` or `mqtts://host:8883`. `user:pass@` in the URL also works |
| `mqtt_topics` | `sce/#` | Topics to subscribe to |
| `mqtt_user`, `mqtt_pass` | (none) | Broker credentials |
| `mqtt_client_id` | `sce-edge-<host>` | Client id |
| `mqtt_qos` | `1` | QoS level |
| `mqtt_clean` | `0` | `0` = persistent session: the broker queues QoS 1 messages while the board is offline |
| `mqtt_keepalive_s` | `30` | Keepalive |

**Design**
- No new dependency: a minimal MQTT 3.1.1 client, about 200 lines.
- Reconnects with backoff: 1 s to 60 s, jittered.
- Acknowledges QoS 1 (PUBACK) only after the reading is ingested (at least once). Duplicates are dropped by device
  timestamp, which the ingest path already does.

**Payload (JSON).** Each reading goes through the same `Engine.IngestReading` as `POST /api/ingest`, so it gets the
range check, quality flag, dedupe, late-reading merge and clock checks.
```
{"node":"SR-AQ-KH03-03","metric":"co2","value":850,"ts":1793000000,"quality":"good|uncertain|bad",
 "unit":"ppm","firmware":"1.4.2","replaced":<unix time of a sensor swap>}
{"readings":[ ... up to 5000 ... ]}          gateway backlog
850  or  {"value":850,"ts":…} on .../<node>/<metric>      node and metric taken from the topic
```

**Extra checks**
- `unit` that differs from the sensor's unit → `rejected_unit`.
- A new `firmware` value is logged.
- A new `replaced` value starts a fresh history (same as `/api/maintenance replaced`).
- Other results: `unknown_sensor`, `invalid_value`, `invalid_json`, `invalid`.
- Ingest results (`accepted`, `late`, `duplicate`, `rejected_range`, `rejected_bad`, `too_old`, …) are counted in
  `/api/prod/status`.

**Test publisher:** `app/tools/mqtt_pub.py` (stdlib only). It can send one reading, a ramp, a backlog batch, or a bare
number.

**Tests** (an in-process broker inside the test):
- `TestMQTTHandleSchemaAndValidation`
- `TestMQTTBridgeBrokerAckReconnect`: auth, PUBACK, broker drop → reconnect → PUBACK.
- `TestMQTTBridgeBadPassword`
- `TestMQTTPublishScript`: `mqtt_pub.py` → broker → bridge → engine.

**Not done:** the replay of a real SCRC series over MQTT (ROADMAP §5 item 4). It is a run, not code: use
`mqtt_pub.py --batch` with the series.

**Board check, Nov 15**
1. On the laptop, run any broker (for example `mosquitto -p 1883`).
2. In `htpd_profile`, set `mqtt_url=tcp://<laptop-ip>:1883`, then restart the app.
3. Send readings: `python3 mqtt_pub.py --host <laptop-ip> --node SR-AQ-KH03-03 --metric co2 --value 600 --step 150 --count 10 --every 2`.
4. Check that `/api/prod/status` shows `mqtt.connected=true` with accepted counts, and that the tile moves.
5. Stop the broker for 2 min, then start it again. Expect a reconnect, and readings queued while it was down arrive.

## 2. Time sync (`prod_time.go`): done

**Keys**

| Key | Default | Meaning |
|---|---|---|
| `time_sync` | `0` | Turns the feature on |
| `ntp_servers` | `pool.ntp.org,time.google.com` | NTP servers. A LAN or gateway server is best |
| `time_trust_mqtt` | `1` | Whether MQTT timestamps may set the clock |

**Behaviour**
- At start, the clock counts as invalid when the device clock is before 2025 and no `--clock-unix` offset was applied
  (the 2023 RTC reset).
- While the clock is invalid, the app tries NTP (SNTP over UDP) every 60 s.
- Otherwise the first trusted source sets the clock once. Trusted sources are:
  - `POST /api/prod/time` from the laptop;
  - MQTT timestamps, when 3 consecutive ones agree within 2 min (one gateway with a wrong clock is not enough).
- While the clock is invalid, incidents get no wall stamp: `created_wall` is empty, `clock_uncertain: true`, and the
  log says why. Once the clock is set, they are re-stamped from the device time recorded when they were created.
- If Android later fixes its own clock, the correction is dropped (same rule as today's `--clock-unix`).

**Tests:** `TestTimeSyncOffByDefault`, `TestTimeSyncNTP` (fake NTP server; the first server is dead),
`TestTimeSyncUnstampedThenRestampedByAPI`, `TestTimeSyncFromMQTTTimestamps`.

**Board check, Nov 15:** set `time_sync=1`, start the app with Wi-Fi off, without the laptop offset.
- `/api/prod/status` shows `clock.valid=false`.
- Inject a scenario: the incident has `clock_uncertain: true`.
- `curl -X POST -d "{\"unix\":$(date +%s)}" localhost:8000/api/prod/time` (over adb forward) → `valid=true`, and
  the incident is re-stamped.
- With Wi-Fi on, check that NTP alone fixes the clock.

## 3. Alert delivery (`prod_alert.go`): done

**Channels**

| Key | Meaning |
|---|---|
| `alert_webhook=url1,url2` | One or more webhook URLs |
| `alert_webhook_format` | `json` (default), `slack`, `ntfy` (Title/Priority/Click headers) or `text` |
| `alert_webhook_header=Authorization: Bearer …` | Extra header. Covers ntfy, Slack, Telegram bot URL and SMS gateways |
| `alert_smtp=host:587` (+ `alert_smtp_user`, `alert_smtp_pass`, `alert_email_from`, `alert_email_to`) | E-mail. STARTTLS when the server offers it |

**What triggers an alert**
- `alert_on=critical,approved` (default). `warning` is optional.
- `alert_injected=0`: demo injections never page anyone.

**Escalation**
- `alert_escalate_min=15`: a critical incident that nobody acknowledged in the app gets one escalation message.
- It goes to `alert_escalate_webhook` / `alert_escalate_email`, or to the normal channels when those are unset.

**Delivery**
- Flood guard: `alert_rate_per_hour=30`. Extra alerts wait, critical ones first; none are dropped.
- `alert_link`: base URL put in each message.
- Queue: `state/alert_queue.json`, rewritten atomically, so it survives restarts.
- Retry with backoff from 15 s to 15 min. An alert is dropped after 24 h.
- Dedup: one alert per (incident, reason), remembered for 7 days.
- Triggered from the store hook, so the fast path, the reasoner and operator approvals all alert.

**Tests:** dedup + injected + approved; retry + restart; escalation unless acknowledged; rate limit; ntfy headers;
SMTP to a local fake server; end to end through `Reasoner.persist` (`TestProdAlertThroughPersist`).

**Board check, Nov 15:** set `alert_webhook=https://ntfy.sh/<private-topic>` and `alert_webhook_format=ntfy`.
- A critical scenario reaches the phone within seconds of the fast path.
- Leave it unacknowledged for `alert_escalate_min` → the escalation arrives.
- Wi-Fi off → the alert is queued (`/api/prod/status`). Wi-Fi back → it is delivered once.

## 4. Heartbeat + dead-man (`prod_heartbeat.go`, `tools/heartbeat_monitor.py`): done

**Keys**

| Key | Default | Meaning |
|---|---|---|
| `heartbeat_url` | (unset) | Where the heartbeat is POSTed |
| `heartbeat_s` | `60` | Period |
| `heartbeat_token` | (none) | Bearer token |
| `board_id`, `site_id` | (none) | Names put on every snapshot |

The feature is also on when the fog uploader is on: snapshots are then queued as fog `health` rows.

**Snapshot contents**
- uptime, clock validity, sim time;
- incident count, silent sensors and sensor faults;
- NPU engine and status, `htpd_up`, reasoner model;
- queues: active, pending, jobs, early, refines, alert queue, fog outbox;
- RAM and temperatures (`deviceStats`), MQTT state.

**Monitor:** `heartbeat_monitor.py --port 8787 --dead-s 300 --alert-url <webhook>`, stdlib only. It alerts once when
a board goes silent, and again when it recovers. It also alerts on a reboot (uptime goes down), an invalid clock and
htpd down. `GET /status` lists the boards.

**Tests:** `TestHeartbeatSnapshotAndFog`; `TestHeartbeatMonitorScript` (runs the real script: dead, then
recovered + restarted).

**Board check, Nov 15**
1. On the laptop, run `python3 heartbeat_monitor.py --dead-s 180`.
2. Set `heartbeat_url=http://<laptop-ip>:8787/heartbeat` and `board_id=qidk-1`.
3. Pull the board's power or Wi-Fi. Expect a "silent" alert after about 3 min, and "recovered" + "restarted" when it
   comes back.

## 5. Fog uploader (`prod_fog.go`): done (against the local FogHandler; Supabase side not built)

**Keys**

| Key | Default | Meaning |
|---|---|---|
| `fog_upload` | (off) | Turns the uploader on. Needs `fog_url` (and optionally `fog_token`), the chat's existing keys |
| `fog_sync_s` | `60` | Upload period |
| `fog_outbox_mb` | `50` | Outbox cap |
| `fog_upload_inputs` | `0` | `1` keeps prompts and windows (raw readings) |
| `fog_upload_occupancy` | `0` | `1` includes per-room occupancy in the summaries |

**What is uploaded** (derived data only, as DECISIONS.md specifies)
- Every stored incident version: re-checks, checklist steps, events and outcomes. Sensor `window`s and model
  `prompt`s are stripped, because they carry raw 5-min readings.
- Health snapshots.
- Hourly per-sensor summaries: mean, min, max, n. No occupancy unless allowed.

**Outbox and replay**
- Outbox: `state/fog_outbox.jsonl` (append + fsync) plus a byte cursor in `fog_outbox.pos`.
- Each row carries `(stream, seq)`. The stream is fixed when the outbox is first created, so a lost outbox cannot
  reuse old seqs.
- The fog applies a row only when its seq is above the last one it applied, so retries are idempotent and the upload
  resumes after an outage.
- Compaction keeps the newest version of each incident.
- Over the cap, health and summary rows are dropped first (logged).

**Fog side**
- `FogIngestHandler` serves `POST /v1/ingest` and upserts incidents into the fog store, so FogHandler's chat tools
  see them.
- Other rows go to `state/fog_rows.jsonl`.
- On a laptop, `edge-agent -fog-addr :8100` serves `/v1/tool`, `/v1/status` and `/v1/ingest`.

**Tests**
- `TestFogUploadOutageResumeIdempotent`: fog down → queued; the answer is lost after the fog applied the batch → the
  board retries and nothing is applied twice; raw data is stripped; the fog's `/v1/status` sees the incident; after
  a restart the stream and seq continue.
- `TestFogOutboxCapKeepsNewestIncident`
- `TestFogHourlySummariesNoOccupancy`

**Board check, Nov 15**
1. On the laptop: `edge-agent-host -dir <copy> -fog-addr 0.0.0.0:8100 -mock`.
2. On the board: `fog_upload=1`, `fog_url=http://<laptop-ip>:8100`.
3. Inject a scenario and approve it. Expect `fog_upload.sent_rows` to rise, and the laptop's `/v1/status` incident
   count to follow.
4. Stop the laptop fog for 5 min, then start it. Expect the outbox to drain with no duplicates.

## 6. Early provisional AI (verified) + automatic warm-up (`prod_warm.go`): done

**Early AI** (`earlyai.go`, built earlier). It is gated by two `htpd_profile` keys, and both must be set:
- `ai_early_k=N`: the number of abnormal readings before a provisional run. Valid range is 1 to `persistReadings`-1;
  absent, 0 or out of range = off.
- `ai_early_shapes=step,flatline,...`: a non-empty whitelist of shape families (spike, step, trend, flatline, noisy,
  fault). An empty list means no shape qualifies, so the feature stays off even with k set.

These keys are re-read every 10 s, so no restart is needed. Switch it off by deleting the keys.
`TestIdleWarmOffByDefault` asserts k = 0 by default. The ROADMAP gate study per shape (about 4-8 h of GPU) is still
needed before turning it on.

**Warm-up** (ROADMAP L4)
- Key: `warm_idle_min=N` (N ≥ 5; off when absent). Works only with the htpd engine.
- After N min with no NPU work, the app sends a 1-token reasoner call on the cached static prefix (rsn_v3 on htpd
  only), then runs `htpd_warmup.jsonl` for the agents, so the agents' model is the resident one.
- Rules:
  - everything goes through the app's own htpd (one NPU client);
  - the warm-up takes the reasoner's queue slot, so no analysis interleaves with it;
  - work that arrives during the warm-up runs right after it;
  - it never runs during an analysis, a busy runner (chat), or the thermal guard.
- Warm-up at boot already existed (`htpdWarmup` at htpd start).
- Watch the heat and power cost of the idle pings.

**Tests:** `TestIdleWarmOffByDefault`, `TestIdleWarmRunsOnceWhenIdleAndYields`.

**Board check, Nov 15:** set `warm_idle_min=30`. Leave the board idle for at least 31 min, then inject a scenario.
Compare its AI time with the 78 s cold case (HB 2.73). The log has `warm: idle warm-up done in … ms`.

## 7. OTA with rollback (`tools/ota/`): done (laptop-tested with a fake adb; NOT run on the board)

**Laptop:** `ADB=…/adb.exe tools/ota/ota_push.sh <bundle_dir>`. The bundle lists `<file> <dest | APK>` in
`bundle.txt`. The script:
1. checks free space;
2. pushes each file as `.part`;
3. checks the md5 on the board;
4. only then renames it in the stage folder;
5. runs the board script.

**Board:** `ota_board.sh apply <stage>` (POSIX sh). It:
1. re-checks every md5;
2. stops the app and waits until no edge-agent or htpd process is left (aborts with nothing changed if they do not
   exit);
3. APK: keeps the installed APK as `rollback.apk`, then runs `pm install -r`;
4. other files: copies to `<dest>.part`, checks the md5, then `mv dest dest.prev; mv dest.part dest`;
5. starts the app;
6. runs the self-test: `/api/prod/selftest` == 200, or `/api/status` for an app built before this endpoint;
7. on failure, restores every `.prev` and the old APK, starts the app and runs the self-test again.

The last output line is `OTA_RESULT=ok|rolled_back|rollback_failed|aborted:…`. `KEEP_PREV=1` (the default) keeps
`.prev` as the known-good copy.

**Test:** `tools/ota/test_ota.sh` (fake adb, am, pm, curl and ps). All 10 checks pass:
- a good update swaps both files;
- a broken APK rolls back the APK and the model;
- a push corrupted in transit is refused;
- a stuck app aborts with nothing changed;
- a damaged staged file is caught by the board's md5 re-check.

**Not built:** signed bundles and a pull from the fog (security scope; PRODUCTION_GAP.md).

**Board check, Nov 15:** only with the owner present, and after a known_good snapshot.
1. Bundle = the current live `htpd_profile` with one harmless key added. Expect `ok`.
2. Bundle = the same profile pointing `bin=` at a missing htpd. Expect the self-test to fail and the result to be
   `rolled_back`.

---

## Owner decisions
1. **Alert channels and provider:** ntfy / Telegram / Slack / an SMS gateway / SMTP account, plus who is on-call and
   who gets escalations. WhatsApp Business templates are not built.
2. **Operator names in synced events:** workflow events carry the operator name picked on the device. DECISIONS.md
   says "ids, not names" in the cloud. Choose: map names to ids before upload, or keep names.
3. **Multi-board fog:** incident ids (`INC-0001`) collide across boards on one fog. Choose: prefix with `board_id` on
   the fog, or one fog store per board. The Supabase schema + RLS is still to build (ROADMAP: 3-5 days).
4. **`fog_upload_inputs`:** default 0 (prompts and windows stay on the board). DECISIONS.md allows "AI inferences
   with inputs". Decide whether inputs mean the raw windows.
5. **Early AI per-shape gate study** before `ai_early_k` goes on, and the `warm_idle_min` value (the heat and power
   cost of idle pings vs. the 78 s cold start).
6. **OTA `KEEP_PREV`:** keeping `.prev` model copies doubles the flash space a model swap needs. Choose keep (safe
   rollback) or delete after success.
