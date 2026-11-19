# Prototype → production: the gap (2026-11-09)

**What this is.** The list of what the Smart City Edge Agent prototype does today, what a production deployment
would need, why we skipped it for the prototype, and what it costs. It is a to-do list for production, not a claim of
work done. No app code, board or GPU was touched to write it.

**Sources.** `proofs/2026-11-09_roadmap/ROADMAP.md` (§4 real-world deployment, §5 plan, §6 unknowns; cited as RM),
`HANDBOOK.md` (HB), `proofs/2026-10-23_reasoner_research/DECISIONS.md` (DEC) and `FOG_OPTIONS.md` (FOG),
`proofs/2026-10-23_realworld/REALWORLD.md` (RW). Efforts are the roadmap's estimates; "not estimated" means no source
gives a number. Nothing here is measured unless a source says so.

**Status labels.**
- **IN PROGRESS** — the team is building it now (another agent, in parallel). Not done until its proof folder says so.
- **DOCUMENTED ONLY** — written down as a production to-do; deliberately **not implemented** in the prototype.
- **PROCESS / HARDWARE** — needs a decision, a site, money or a device, not code.

**Priority.** **B** = blocker before anyone relies on it; **H** = high; **M** = medium (RM §4 scale).

---

## 0. The short version

1. **Security is the biggest gap, and it is documented only.** The app reaches the NPU through the board's own adbd on
   127.0.0.1:5555 with no auth, and the HTTP API on port 8000 serves reads (incidents, per-room occupancy) to anyone on
   the LAN in plaintext. Fine on a lab bench; not fine on shared Wi-Fi.
2. **Nobody off the board is told about an incident yet.** Alerts, heartbeat and the fog uploader are in progress.
3. **The board has never seen a real sensor feed.** The ingest path is built and tested; the MQTT bridge is in progress.
4. **Updates need a laptop and a USB cable.** Deploys are safe (md5, self-test, automatic rollback) but unsigned and
   manual; OTA with rollback is in progress.
5. **Production starts with a shadow pilot**: rules and the critical fast path page people, AI reports are logged and
   shown but not paged, for 2-4 weeks on one floor (RM §4, §5).

| # | Area | Status | Priority |
|---|---|---|---|
| S1-S9 | Security hardening | **DOCUMENTED ONLY** | B / H / M |
| R1 | Watchdogs | done (process level); board level in progress via heartbeat | H |
| R2 | Power loss | partly done; hardware open | H |
| R3 | Thermal | hardware + soak test open | H |
| R4 | Storage wear | not measured | M |
| R5 | Time sync | **IN PROGRESS** | H |
| O1 | OTA + rollback | **IN PROGRESS** | H |
| O2 | Monitoring / heartbeat | **IN PROGRESS** | H |
| O3 | Fog uploader (backup, history) | **IN PROGRESS** | B (multi-site) |
| O4 | Multi-site fleet | documented | M |
| O5 | Retention | policy open | M |
| D1 | Real sensor ingestion (MQTT bridge) | **IN PROGRESS** | B |
| D2-D4 | Cadence, calibration metadata, data quality UI | documented | H / M |
| A1 | Off-board alerts + escalation | **IN PROGRESS** | B |
| A2 | Early provisional AI + automatic warm-up | **IN PROGRESS** | H |
| C1-C2 | IS 10500 / CPCB limits; privacy (DPDP Act 2023) | documented | M |
| T1-T3 | Shadow mode, canary, pilot | **PROCESS** | H |

---

## 1. Security (DOCUMENTED ONLY: not implemented in the prototype)

Why skipped for all of them: the prototype runs on a Qualcomm dev kit on a lab bench, on a network we control, with
synthetic and replayed campus data. The evaluation measured accuracy and latency. Hardening would have cost days per
item and changed nothing the evaluators could measure. Production cannot skip any **B** item below.

| # | Item | Today (prototype) | Production needs | Effort | Pri |
|---|---|---|---|---|---|
| S1 | **Device access (adb)** | Android apps cannot open the NPU, so the app drives htpd through the board's own adbd on 127.0.0.1:5555, which has **no auth** (`AdbLocal.java`; HB). In tcpip mode adbd usually listens on all interfaces; the actual bind address on our board is **unknown** (RM §6) | Short term: confirm the bind address; firewall 5555 to loopback (iptables needs root) or keep the board off shared Wi-Fi. Production: no adb at all. A system service with a SELinux/fastrpc policy in the device image, or a Qualcomm IoT SKU (QCS-class, Linux) where the NPU service is native | 1 day short term; weeks for a production image | **B** |
| S2 | **API auth + TLS** | HTTP on 0.0.0.0:8000. Off-device **writes** need `X-API-Token`; **reads are open on the LAN**; everything is plaintext, so the token travels in clear (`auth.go`, HB 2.35) | Token or mTLS for off-device reads too; TLS (self-signed + certificate pinning for the gateway); bind to loopback unless LAN ingest is switched on | 1-2 days | **B** |
| S3 | **Secrets / keys** | One shared API token for off-device writes (`X-API-Token`, `auth.go`), no rotation; the website password lives in a gitignored script on the laptop | Secrets out of config files and scripts; Android Keystore (or a secure element) on the device; rotation procedure in the runbook | not estimated | H |
| S4 | **Per-device keys** | One board, one token | Per-board identity: own key/cert, own fog Auth user, RLS per board (DEC, RM §4 multi-site); revoke one board without touching the rest | covered by the 1-day multi-site schema + S2 | H |
| S5 | **Least privilege** | The app has a local adb shell (more than it needs); chat and reasoner tools are read-only; no actuation path, every action needs human approval (HB 2.44) | Keep tools read-only and approvals human. Remove the shell path (S1). Fog: board is the only writer; dashboard approvals are requests the board applies (DEC) | part of S1 | H |
| S6 | **Audit log** | Append-only event log; operators pick a name, **no password** (HB 2.49, DEC) | PIN per operator (already planned in DEC); operator id in every event; audit log exported to the fog | 1 day | H |
| S7 | **Privacy of occupancy data** | Per-room occupancy and CO2 on the board and readable on the LAN (S2) | Raw stays on the board; the cloud gets occupancy aggregated per zone/hour and operator ids, not names (DEC); closing S2 removes the LAN leak. Small rooms can identify people | 0.5 day + policy | M |
| S8 | **Update signing** | Deploys push files over adb with md5 checks; nothing is signed (HB 2.67-2.73) | Signed bundle (APK + profile + model sha256 + manifest); the board refuses unsigned bundles. Part of the OTA work (O1) | inside O1's 3-4 days | H |
| S9 | **Network exposure** | Board on lab Wi-Fi; port 8000 and possibly 5555 reachable | Own VLAN or isolated network; only the gateway can reach ingest; outbound only to the fog over TLS | site-dependent | **B** |

The website is the one public surface and already has a password page with aggregates only ("private data, public
evidence", HB 2.36).

---

## 2. Reliability

| # | Item | Today | Production needs | Why skipped now | Effort | Pri | Status |
|---|---|---|---|---|---|---|---|
| R1 | **Watchdogs** | EdgeService restarts the backend in 8 s; domain health; logs on the device (HB 2.35, 2.43) | A board-level dead-man: the fog alerts when the heartbeat stops (O2) | No fog existed | with O2 | H | process level done; board level **IN PROGRESS** |
| R2 | **Power loss** | USB brownout reboots; DC adapter advised; BOOT_COMPLETED autostart; JSONL + fsync + rename with torn-line recovery; in-flight incidents marked "interrupted" (HB 2.34, 2.35) | DC supply + small UPS; record the boot reason each boot; re-run interrupted incidents after an unclean boot | Bench power | hardware | H | partly done |
| R3 | **Thermal** | NPU peaks 93-97 °C, throttle trip 100 °C, pacing at ≥ 88 °C; one incident at a time (HB 2.35, 2.62, 2.71) | Heatsink + fan + ventilated enclosure; soak test at 40 °C ambient (Indian summer never tested) | No enclosure, lab bench only | hardware + 1 day test | H | open |
| R4 | **Storage wear** | 1,000 incidents kept + archive, JSONL with fsync (HB 2.35); flash wear **never measured** | Measure write volume per day; cap logs; rotate; alert on low free space (part of the heartbeat) | Short runs only | not estimated | M | open |
| R5 | **Time sync** | RTC resets to 2023 at boot; the app restores a saved offset (HB 2.34). A long power-off leaves a wrong clock and wrong windows | NTP when online; otherwise the gateway's message timestamps (UTC epoch, RW §3); an incident flag "clock uncertain" until synced | The board was always restarted by us | 0.5 day | H | **IN PROGRESS** |

---

## 3. Operations

| # | Item | Today | Production needs | Why skipped now | Effort | Pri | Status |
|---|---|---|---|---|---|---|---|
| O1 | **OTA + rollback** | `deployNN.sh` over adb: `.part` + md5 + mv with the app stopped, chaos 2 + fastcheck, automatic rollback to known_good (HB 2.67-2.73). Needs a laptop and USB | Signed bundle (S8) pulled from the fog; install into an inactive slot; self-test (fastcheck-style synthetic incident); switch; auto-rollback on failure. Same .part/md5 rule | One board on our desk | 3-4 days | H | **IN PROGRESS** |
| O2 | **Monitoring / heartbeat** | Logs on the device only. Nobody notices a dead board | Heartbeat every 60 s (uptime, temperature, queue depth, stage latencies, validator rejects, garbage reruns, silent sensors); dead-man alert in the fog after 5 min of silence | No fog | 1-2 days | H | **IN PROGRESS** |
| O3 | **Backups / fog uploader** | Fog tool contract `POST {fog_url}/v1/tool` + device fallback built and tested (HB 2.74); **Supabase side and uploader not built**; no history off the board | Uploader as DEC specifies: derived data only, idempotent upserts keyed (incident id, version) every 60 s, 50 MB offline queue, board is the only writer, per-board Auth user + RLS. An append-only outbox file with a cursor on the device | Single board, data on the laptop via adb | 3-5 days (+1 day outbox) | B for multi-site | **IN PROGRESS** |
| O4 | **Multi-site fleet** | One board; node ids per campus building | `site_id`/`board_id` on every synced row; one Supabase project, RLS per board; identical models across boards; canary order (T2) | One site | 1 day (schema) | M | documented |
| O5 | **Retention** | 1,000 incidents kept + archive on the board | A written retention policy (for example raw 90 days on the device; the owner sets it), mirrored in the fog | No policy owner yet | policy | M | documented |
| O6 | **Docs / handover** | HANDBOOK is a ~3,000-line lab log | Operator guide, install/runbook (power, network, token, rollback), incident-response SOP | Built for the team, not operators | 2 days | M | documented |

---

## 4. Data

| # | Item | Today | Production needs | Why skipped now | Effort | Pri | Status |
|---|---|---|---|---|---|---|---|
| D1 | **Real sensor ingestion** | HTTP POST `/api/ingest` with ts/quality, dedupe, late/out-of-order merge, backfill ≤ 5000 (RW §3). **No real gateway connected**; the user plays the sensor via sliders | MQTT subscriber in Go feeding the same ingest path (QoS 1; ts dedupe already exists). Modbus TCP/RTU and LoRaWAN on a gateway, not on the board | No site sensors available | 2-3 days for MQTT; gateway depends on the site | **B** | **IN PROGRESS** (MQTT bridge) |
| D2 | **Cadence** | Engine assumes 5-min buckets; hourly TDS is always insufficient_data (RW open item 1) | Rules-only for sparse sensors now; sparse-window training later | Training data was 5-min | decision | H | documented |
| D3 | **Calibration metadata** | Not carried | Feed metadata (unit, firmware, replaced/recalibrated) from day 1 (RW open item 3), so a recalibration is not read as an incident | Replayed data has none | with D1 | M | documented |
| D4 | **Quality** | Strong data-quality layer (RW §0) | Quality chip in the UI; holiday calendar file; alarm-flood guard (≥ 10 alarms in 10 min, EEMUA) (RW §6) | UI time went to the evaluation | 1-2 days | M | documented |

Training and tests used one campus's sensors (test months held out, about 15% of sensors held out). A new site needs a
shadow period (T1) before its accuracy can be claimed.

---

## 5. Alerts and workflow

| # | Item | Today | Production needs | Why skipped now | Effort | Pri | Status |
|---|---|---|---|---|---|---|---|
| A1 | **Off-board alerts** | Android notification on the board; 15-min critical reminder; approval workflow in the app (HB 2.49). Nobody is alerted unless they look at the board | Fog relay → push / email / WhatsApp Business / SMS by severity; escalation ladder (on-call → supervisor at 15/30 min); ack by link written back as a request; local fallback for critical only (GSM modem or LAN siren) | No fog | 3-5 days + provider setup | **B** | **IN PROGRESS** |
| A2 | **Faster AI** | 8-reading gate = 40-55 min sensor time; critical fast path is live; early provisional AI is built and **off**; cold first incident ~78 s | Early provisional AI (`ai_early_k`) only for the event shapes that pass the gate study; automatic warm-up to remove the cold outlier | Accuracy at k=4 not yet measured (RM §6) | gate study + config | H | **IN PROGRESS** |
| A3 | **Human in the loop** | Every action needs operator approval; no actuation path (HB 2.44) | Keep it. Operator edits become training data only after owner review (DEC) | — | — | — | done (by design) |

---

## 6. Compliance

| # | Item | Today | Production needs | Effort | Pri |
|---|---|---|---|---|---|
| C1 | **Regulatory limits** | `phdir.go` uses pH 6.5/8.5; the other limits in `sensors.go` are not yet checked against the standards | IS 10500:2012 (pH 6.5-8.5; TDS acceptable 500, permissible 2000 mg/L); CPCB NAAQS (PM2.5 60 µg/m³ 24 h); indoor CO2 per ASHRAE 62.1 / ISHRAE guidance. Store the standard's name next to each limit | 0.5 day | M |
| C2 | **Privacy** | See S7 | A DPDP Act 2023 notice and a retention policy (O5); aggregate occupancy in the cloud | 0.5 day + policy | M |

Why skipped: the prototype's alerts are advisory and its data is replayed; nobody acts on them yet.

---

## 7. Cost (only numbers a source gives)

- **Fog:** Supabase free tier pauses after about 7 idle days; the 60 s sync keeps it alive. Plan Pro at **$25/month**
  for production (FOG §2.2, RM §4).
- **Alerts:** WhatsApp templates and SMS depend on the provider; **not priced**.
- **Hardware per site:** DC supply + small UPS, heatsink + fan + enclosure, gateway; **not priced**. A production
  device may be a different Qualcomm IoT SKU (S1), also not priced.
- **Compute:** inference stays on the board, so there is no per-question cloud cost by design (decision log: everything
  on the board, for privacy, offline use and seconds-level latency).

---

## 8. Testing in production

| # | Item | Today | Production needs | Pri | Status |
|---|---|---|---|---|---|
| T1 | **Shadow mode** | Every deploy is proven through the app (chaos 2 + fastcheck); self-learning capture exists (HB 2.28) | 2-4 weeks: rules + fast path alert people; AI reports logged and shown, not paged; compare against operator outcomes | H | **PROCESS** |
| T2 | **Canary** | One board | New models and APKs to one board first, then the fleet; automatic rollback (O1) | H | **PROCESS** |
| T3 | **Pilot** | Lab bench, synthetic and replayed data | One floor with real sensors through MQTT (D1), in shadow (RM §5, Nov 16 - Dec 13) | H | **PROCESS** |

---

## 9. Unknowns that affect this list (RM §6)

- adbd's bind address on our board (decides how urgent S1's short-term fix is).
- Board RAM total; flash write volume (R4).
- Thermal and power behaviour in an enclosure in the field (only the lab bench is measured).
- Early-AI accuracy at k=4 (A2).
