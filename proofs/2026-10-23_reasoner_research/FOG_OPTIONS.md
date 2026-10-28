# Fog layer: options and trade-offs (discussion document)

**Date:** 2026-10-22 (filed with the 2026-10-23 reasoner research). **Status:** discussion only. This document
does not make a final decision. No code was changed, the board was not touched, nothing was committed, and no
project data was sent anywhere. Only generic web searches were made.
**Companion files:** `REASONER_DESIGN.md` (§C.1 architecture, §C.7 fog sync/RAG/routing), `tools.json` (9 read-only
tools, `search_knowledge` is fog-only), `store_schema.sql` (device SQLite store with `outbox` and `synced_version`).

**The owner's intent (verbatim):** "Fog computing is about storing information somewhere and if needed have an API
service running, whether a given data model or our own can be changed easily... if we can deploy our own then well and
good, else reasoning mostly would want to be local, just data storage on cloud... and if required an API service... we
need research on this more and discuss."

**Read this first: what the fog is for in this project**
1. **Storage of everything.** The QIDK keeps the last 1,000 incidents in full plus an all-time compact index. The fog
   keeps all incidents (every revision), hourly readings, maintenance records, checklist outcomes and the tool-call log.
2. **An API service.** Sync from the device, exact queries over full history, and RAG search over documents.
3. **Optional, swappable model serving.** The fog serves "a given model or our own" behind one OpenAI-compatible URL,
   so the model changes by config. Reasoning stays on the device by default either way.

The alert path never depends on the fog. Today's pipeline is sensors -> rules -> 3B agents on the NPU -> reasoner, and
it runs fully on the QIDK. The fog only adds history, documents and, optionally, a bigger model for chat.

---

## 1. What "fog" means here (vs edge and cloud)

### 1.1 Definitions from the standards
| Term | Source | Meaning | In this project |
|---|---|---|---|
| **Fog computing** | Bonomi et al., Cisco, MCC '12 (the term's origin); OpenFog Reference Architecture (2017), adopted as **IEEE 1934-2018** | A system-level, *hierarchical* architecture that places compute, storage, control and networking anywhere along the continuum from the cloud to the things. OpenFog lists eight pillars: security, scalability, openness, autonomy, RAS (reliability, availability, serviceability), agility, hierarchy and programmability. | A node one level above the QIDK, close on the network: a lab PC or mini-server on the campus LAN. |
| **Edge computing** | NIST SP 500-325 (2018) groups it with fog, cloudlets and "mist", and notes there is no consensus on the boundaries | Compute on or next to the device that produces the data. | The QIDK itself: sensors, rules, NPU agents, reasoner. |
| **Mist computing** | NIST SP 500-325 | Very lightweight compute at the extreme edge (the sensors and actuators themselves). | The SCRC sensor nodes. |
| **Multi-access Edge Computing (MEC)** | ETSI GS MEC 003 (framework and reference architecture; V1 2016, V2.2.1 2020-12) | Telco-operated application hosting inside the mobile or access network, with standard APIs (radio info, location and so on). | **Not applicable.** Nobody here runs a telco network. It is mentioned so evaluators see it was considered. |
| **Cloud** | (common use) | Remote, shared data centres reached over the internet. | Optional. It is only acceptable for data the owner has approved for upload. |

Two OpenFog pillars matter directly for this design:
- **Autonomy:** each tier must keep working when the tier above is unreachable. The QIDK is already offline-first,
  with a 1.5 s fog timeout and then a device fallback that reports `coverage.complete=false`.
- **Hierarchy:** data is reduced as it moves up. The device sends incident versions and hourly roll-ups, not raw
  5-min streams.

### 1.2 What a campus fog node realistically is
| Candidate | Typical spec | LLM capability | Cost | Notes |
|---|---|---|---|---|
| **The project laptop** (RTX 4050 6 GB, already owned) | 8–16 cores, 16+ GB RAM, 6 GB GPU | 3B–4B comfortably. 9B at Q4 only just fits, with a short context. | ₹0 | **Best demo fog.** It is already on the bench next to the board, and it can reach the board over USB with `adb reverse`, so no Wi-Fi is needed. It is not always on. |
| Lab desktop or workstation with a GPU (e.g. 12–24 GB VRAM) | Desktop CPU, 32–64 GB RAM | 9B at 8-bit with a 32k context (12–16 GB). 35B-A3B MoE at Q4 (24 GB+). | Existing lab hardware, or about ₹1.2–2.5 L new | Best "real" fog if the lab has one. It can stay always on. |
| Mini-PC (Intel N100 / Ryzen 7840HS class, no dGPU) | 4–8 cores, 16–32 GB | CPU-only: 3B at roughly 10–20 tok/s, 9B at roughly 4–8 tok/s (estimate; decode is memory-bandwidth bound) | ₹25–70k | Fine for storage, API and embeddings. A model on it is usable only for opt-in "ask the fog" questions. |
| NVIDIA Jetson AGX Orin 64 GB | 12-core Arm, 64 GB unified, 204.8 GB/s | About 14 tok/s single-stream for a 7B Q4 via Ollama (forum report); about 22 tok/s for Qwen3.5-35B-A3B Q4_K_M with llama.cpp (vendor post) | About ₹1.8–2.5 L | An "edge-AI showcase" box. It is weaker per rupee than a desktop GPU. |
| Raspberry Pi 5 / NAS | 4 cores, 8 GB | No useful LLM | ₹8–30k | Storage and API only. |
| Cloud VM (no GPU) | 2–4 vCPU | none useful | about $10–40/month | Data leaves campus, which needs the owner's approval (§2.6). |
| Cloud VM with a GPU (L4 24 GB / A10G) | — | 9B–35B | about $0.7–1.2/h on demand (order of magnitude; check the provider) | Expensive if left always on. Data leaves campus. |

**What realistically counts as "fog" here:** a box on the same LAN, or on USB, as the QIDK, owned by the lab. A cloud
VM is technically "cloud", not fog. It only becomes a fog tier in the OpenFog sense if it sits regionally close and the
architecture treats it as an intermediate layer.

---

## 2. Storage for incidents, readings and checklist outcomes

### 2.1 What has to be stored (sizes from `store_schema.sql`)
| Data | Volume | Shape | Needs |
|---|---|---|---|
| Incident versions (full JSON report and its index row) | ~300 B index + ~5–30 KB full per version; ~3 versions (early / 1.5 h / 3 h) | Document plus relational index | Exact counts and group-by; text and vector search |
| `incident_sensor` rows | ~10–14 per incident | relational | joins for "how many CO2 spikes" |
| Readings | 30 series: 5-min raw is ~260k rows per 30 days; hourly is ~260k rows per year (~10 MB/yr) | time series | range scans, roll-ups |
| Maintenance and checklist outcomes, approvals, operator notes | small, append-only | relational | audit trail |
| Tool-call and agent-call logs | a few MB per day under stress | append-only log | evaluation, self-learning data |
| Raw logs, proofs, plots | GBs | blobs | archive only |

At this scale (well under 10 GB a year), **any** option below is fast enough. The choice is about privacy,
availability, effort and cost, not performance.

### 2.2 Option (a): managed cloud databases
| Service | What you get | Free / entry tier (verify before use) | Fit |
|---|---|---|---|
| **Supabase** (managed Postgres, pgvector, auth, REST) | Postgres + PostgREST + auth + storage | Free: 2 projects, 500 MB DB, 5 GB egress; **pauses after ~7 days idle**. Pro: $25/org/month. | Good DX. The pause makes it a poor fit for a fog that must always accept sync. |
| **Neon** (serverless Postgres) | Postgres, branching, pgvector | Free: 100 CU-h/month per project, compute scales to zero after 5 min (adds cold-start latency), storage 0.5 GB → 1 GB (changelog 2026-10-02) | Fine for a demo. The cold start eats into the 1.5 s tool timeout. |
| **AWS RDS / Aurora Postgres** | Managed Postgres, pgvector available | Paid after the 12-month free tier (`db.t4g.micro` class) | Heavier setup (VPC, IAM). Overkill for a demo. |
| **Firebase / Firestore** | Document DB with built-in Android offline cache | Free: 1 GiB, 50k reads / 20k writes per day | Documents only. No SQL `COUNT ... GROUP BY` joins, so the exact-count tools would need re-modelling. **Not recommended**, because it breaks the "same schema on device and fog" design. |
| **InfluxDB 3 Core / Cloud** | Time series | Core is MIT/Apache-2.0. Core queries are scoped to a recent window (72 h was the design; InfluxData relaxed it in 2025, but historical queries are positioned as an Enterprise feature) | Readings only. It would be a second database next to the incident store. |
| **Timescale (Tiger) Cloud** | Postgres + TimescaleDB | Paid | Same model as option (b), but managed. |

**What every cloud option implies:** incidents carry SCRC sensor IDs, locations, readings and operator notes. Under
the owner's rule ("data never sent online without approval"), any cloud database is **opt-in**. It needs either
explicit approval or a redacted or synthetic dataset (see §2.6).

### 2.3 Option (b): self-hosted on a LAN box
| Stack | Pros | Cons |
|---|---|---|
| **PostgreSQL 16/17 + TimescaleDB + pgvector** | One database for incidents (relational + JSONB), readings (hypertables, continuous aggregates, compression) and embeddings (HNSW). Mature. pgvector supports exact and approximate (HNSW, IVFFlat) search. | About 1 day of setup. TimescaleDB Community Edition is under the Timescale License, which is free for self-hosting and only restricts offering it as a hosted DBaaS, so it is fine for us. The Apache-2 build lacks compression and continuous aggregates. Plain Postgres is enough at our volume anyway. |
| **SQLite + sqlite-vec** | Same engine as the device (`store_schema.sql` copies over unchanged). Single file, zero administration, trivial backup (copy a file). | One writer at a time (fine: one device). sqlite-vec is pre-v1 and brute-force only, which is fine at under 100k vectors. Upstream maintenance status is uncertain (a community fork exists). |
| **DuckDB** (analytics only) | Fast ad-hoc analysis of exported Parquet | Not a sync target. Use it for reports, not the API. |

**The trade-off:** SQLite is "same code, zero administration". Postgres is "real multi-user database, better
concurrency, pgvector HNSW, easy to point dashboards or Grafana at". For a single-device demo SQLite is enough. If the
fog will serve several QIDKs or a web dashboard, Postgres is the better long-term choice. The Go API can hide the
difference behind one `Store` interface: `modernc.org/sqlite` for SQLite, `pgx` for Postgres.

### 2.4 Option (c): object storage for raw logs
- **Cloudflare R2:** about $0.015/GB-month, **no egress fees**, and a free tier of 10 GB-month. **AWS S3 Standard:**
  about $0.023/GB-month, plus about $0.09/GB internet egress.
- **Self-hosted S3-compatible store** (e.g. MinIO, Garage) on the fog box, or simply a directory with a nightly
  `rsync` to a lab NAS.
- **Use:** the archive of `proofs/`, agent-call JSONL, raw replay logs. It is **not** part of the query path.
- **Privacy:** the same rule applies. R2 and S3 are online, so they hold only approved, redacted or encrypted content.
  Client-side encryption (e.g. `age` or `restic` with a key that stays on campus) makes a cloud bucket hold ciphertext
  only. That is a reasonable middle ground to put to the owner.

### 2.5 Sync design (device → fog)
This is already sketched in REASONER_DESIGN §C.7. Here it is in full, with the reasons:

```
 QIDK persist() ──► SQLite tx: write incident row (version++) + INSERT outbox(kind,key,body)   (same transaction)
                                                    │
 sync loop (every 10 s, or on new rows; backoff 5 s → 5 min when offline)
                                                    ▼
   POST /v1/sync  {device_id, batch:[{seq, kind, key:"INC-0123@7", body(gzip JSON)}...]}   over mTLS
                                                    ▼
 FOG: BEGIN; for each item: UPSERT ... WHERE incoming.version > stored.version; record (device_id, seq); COMMIT
      → 200 {acked_seq: N}
                                                    ▼
 QIDK: DELETE FROM outbox WHERE seq <= N;  UPDATE incident SET synced_version = ...
```

| Property | How it is achieved |
|---|---|
| **Append-only event log** | `outbox` rows are never edited. A change to an incident is a new version row. The fog keeps every version (`incident_version` table) plus a "latest" view. |
| **Idempotent** | The key is `(incident_id, version)`, so re-sending a batch after a lost ack is harmless (`ON CONFLICT DO NOTHING` for versions; upsert-if-newer for "latest"). The fog also stores `(device_id, last_seq)`. |
| **Offline queue** | The outbox *is* the queue. It survives reboots, because it lives in the same WAL SQLite file. The cap is about 50 MB, after which the oldest reading roll-ups are dropped first and incidents last, with a counter logged. |
| **Conflict-free** | The device is the **single writer** for its own incidents, so there are no concurrent writers and no CRDT is needed. The fog never edits device data. Fog-side additions (embeddings, document chunks, annotations) go in separate tables keyed by incident id. If an operator ever approves an incident on a fog dashboard, that becomes a *request* the device pulls and applies itself, which is a later phase. |
| **Ordering** | Per-device `seq` is monotonic. The fog applies batches in seq order and rejects gaps (409 plus `expected_seq`, after which the device resends). |
| **Auth** | **mTLS** with a small private CA (e.g. `step-ca`, or a one-off `openssl` CA): each QIDK gets a client certificate, and the fog pins its CA. Simpler alternative: a per-device HMAC key over the body plus a timestamp, sent over TLS. **The fog never initiates connections to the board** and never sends commands, which matches the existing rule that models and adapters are deployed only by hand. |
| **Integrity** | A SHA-256 of each batch body. The fog recomputes counts nightly and compares them with the device's `/api/tools/count_incidents` (the acceptance test in P5). |
| **Back-fill** | On first connect, the device replays the all-time index plus whatever full records are still on it. Older full records exist only in `state/incidents.archive*` until they are imported once by hand. |

### 2.6 Privacy and the owner's rule
- **The rule (project memory):** raw SCRC data is never sent online without approval.
- **A LAN or USB fog keeps data on campus.** No approval is needed beyond what already applies to the laptop. This is
  the main reason to prefer a self-hosted fog.
- **Any cloud database, bucket or hosted LLM requires approval.** Ways to get approval-friendly data:
  - (i) **synthetic** incidents only (the stress and chaos generators);
  - (ii) **redacted**: node IDs hashed, locations coarsened, operator notes dropped;
  - (iii) **encrypted at rest with a key held on campus** (works for backups and object storage, not for a queryable
    database).
- **Personal data:** operator names and notes may count as personal data under India's DPDP Act 2023. Its Rules were
  notified in November 2025, with phased obligations over 12–18 months. Keeping that data on a LAN fog avoids
  cross-border transfer questions. This is a note, not legal advice.
- The public evaluation website (Cloudflare Pages) already follows the "approved content only" pattern. The fog would
  follow the same pattern.

### 2.7 Cost summary (storage only)
| Option | Monthly | One-off |
|---|---|---|
| LAN fog on the existing laptop or lab PC | ₹0 (electricity) | ₹0 |
| Mini-PC fog | about ₹100–200 electricity | ₹25–70k |
| Supabase / Neon free tier | $0 (with pausing / cold start) | — |
| Supabase Pro | $25 | — |
| R2 for 50 GB of logs | about $0.60 | — |

---

## 3. The API service

### 3.1 Shape
A **thin Go service in the same repository** (e.g. `app/fog/`). It reuses the backend's incident structs, the SQLite
schema and, most importantly, **the same `ToolExecutor` code**, so a tool gives the same answer on the device and on the
fog, only over more data.

**REST/JSON vs gRPC:** REST/JSON over HTTPS is recommended. The device backend already speaks JSON and SSE, curl and the
browser can debug it, and one device does not need gRPC's streaming or codegen.

### 3.2 Endpoints (draft)
| Endpoint | Method | Purpose | Used by |
|---|---|---|---|
| `/v1/sync` | POST | Outbox batch upload (§2.5) → `{acked_seq}` | device sync loop |
| `/v1/sync/state` | GET | `{last_seq, counts}` for resume and integrity checks | device on reconnect |
| `/v1/tools/{name}` | POST | Run one of the read-only tools (`count_incidents`, `find_incidents`, `get_incident`, `sensor_faults`, `get_sensor_history`, `list_sensors`, `domain_health`, `related_context`) over the full store, using the same JSON schema as `tools.json`. Returns `coverage.source="fog", complete=true`. | device ToolExecutor |
| `/v1/knowledge/search` | POST | `search_knowledge(query, k)`: hybrid BM25 + vector over documents and incident summaries, returning passages with source ids | device ToolExecutor |
| `/v1/ask` | POST (SSE) | Optional: "ask the fog model". Takes the question plus device tool results, and the fog LLM runs its own tool loop. | device, opt-in per question |
| `/v1/llm/*` | proxy | Optional: a pass-through to the local OpenAI-compatible model server, so the device needs only one fog URL | device / evaluators |
| `/v1/health` | GET | Liveness, DB status, model name and version, embedding model | device routing, dashboard |
| `/admin/docs` | POST | Upload and re-index manuals and SOPs (LAN-only, admin cert) | operator / developer |

**All endpoints are read-only except `/v1/sync` and `/admin/docs`.** The fog never writes to the device.

### 3.3 How the device routes online and offline
Routing is done by the executor, never by the LLM. This repeats REASONER_DESIGN §C.7, made concrete:

```
ToolExecutor.Run(call):
  if call.tool == search_knowledge:
        fog up? → /v1/knowledge/search ; else → {available:false, reason:"fog offline"}
  elif call needs history older than device coverage (time range starts before oldest full record)
       or call is a count/list over all time:
        fog healthy (last /v1/health < 30 s ago) and outbox lag small?
            → POST /v1/tools/{name} with 1.5 s timeout
               ok   → result (coverage.source=fog)
               fail → device result with coverage.complete = false (or true if the all-time index covers it)
        else → device result (same coverage rule)
  else → device (fast path, < 20 ms)
```
- **Staleness guard:** if the outbox holds unsynced incidents in the asked time range, the fog result is *merged* with
  the device's unsynced rows, or the device answers alone. A count must never miss the newest incident just because it
  has not synced yet.
- **The UI shows the source:** "Answered from full history (fog)" or "Answered from this device (last 1,000
  incidents + all-time index)".

---

## 4. Optional model serving on the fog (swappable)

### 4.1 The swap mechanism: one OpenAI-compatible URL
All the mainstream local servers expose `POST /v1/chat/completions` (and most expose `/v1/embeddings`). The fog API or
the device then needs only `{base_url, model, api_key}` in config, and **changing the model means changing config or
reloading the server**, not code. This directly answers the owner's "whether a given model or our own can be changed
easily".

| Server | Formats | Tool calling | Serves our own fine-tune? | Notes |
|---|---|---|---|---|
| **llama.cpp `llama-server`** | GGUF (any quant) | Yes, with `--jinja` and native handlers for Llama 3.x and Qwen | **Yes, directly.** The same `ft_v2*.gguf` the board runs, plus the reasoner LoRA via `--lora` / `/lora-adapters` hot-swap. | Same engine family as htpd, so behaviour is closest to the device. Runs on CUDA, Vulkan or CPU. Includes `/v1/embeddings` (`--embedding`). **Recommended.** |
| **Ollama** | GGUF (wraps llama.cpp) | Yes (`tools` array; model-dependent) | Yes: a `Modelfile` with `FROM ./ft_v2.gguf` and `ADAPTER ./reasoner_lora.gguf` | Easiest model management (`ollama pull/run`). Listens on 127.0.0.1:11434 by default. Slightly behind upstream llama.cpp. |
| **vLLM** | HF safetensors, AWQ/GPTQ/FP8 (GGUF support is experimental) | Yes (`--enable-auto-tool-choice --tool-call-parser ...`, `tool_choice=required` since 0.8.3) | Yes: the HF merged model, or `--enable-lora` with multiple LoRAs | Best throughput and batching. Needs an NVIDIA GPU with enough VRAM, and Linux. Overkill for one user. |
| **SGLang** | HF | Yes | Yes | Similar to vLLM. |
| **TGI** (Hugging Face) | HF | Yes | Yes | **In maintenance mode since December 2025.** Hugging Face itself recommends vLLM, SGLang or llama.cpp. Do not start new work on it. |
| **LM Studio (`lms` / llmster headless)** | GGUF, MLX | Yes | Yes (load any GGUF) | A friendly GUI for demos. Serves on :1234 `/v1`. Its licence is proprietary freeware, so check it for lab use. |

### 4.2 GPU needs per model size (rough; weights plus a moderate context)
| Model | Q4 (≈0.6 GB per B params) | Q8 | Typical GPU | CPU-only decode (desktop DDR5, estimate) |
|---|---|---|---|---|
| Our Llama-3.2-3B v2 (+ reasoner LoRA) | ~2 GB (+ KV ~0.45 GB per 4k context) | ~3.5 GB | any 4 GB+ GPU, or the laptop's RTX 4050 | ~12–20 tok/s |
| Qwen3.5-4B | ~2.7 GB | ~4.5 GB | 6 GB | ~10–15 tok/s |
| **Qwen3.5-9B** (REASONER_DESIGN's fog default) | ~5.5–6 GB | ~10 GB | 8 GB (Q4) / 12–16 GB (Q8 with a 32k context) | ~4–8 tok/s |
| Qwen3.5-35B-A3B (MoE, ~3B active) | ~20–22 GB | ~37 GB | 24 GB; or CPU with 32–64 GB RAM, because only ~3B parameters are active per token | ~8–15 tok/s (MoE helps on CPU) |
| Embedding model (Qwen3-Embedding-0.6B / EmbeddingGemma-300M) | <0.5 GB | <1 GB | CPU is enough | ~50–200 short passages/s |

The CPU and Jetson figures are order-of-magnitude estimates based on memory bandwidth and a few public reports. They
must be measured with `llama-bench` on the actual fog box before anyone quotes them.

### 4.3 When a fog model is worth it, and when to keep reasoning local
| Factor | Keep local (QIDK NPU) | Fog model |
|---|---|---|
| **Alert-path latency** | Required. It never waits on the network. | Never on the alert path. |
| **Chat latency** | First token in under 2 s when the NPU is idle | LAN round trip of about 1–5 ms is negligible. Model speed dominates: a 9B on a 12 GB GPU decodes faster than the 3B on the NPU (~35 tok/s), and on CPU it is slower. WAN or cloud adds 50–300 ms per call plus queueing. |
| **Quality** | 3B + LoRA: good at narrow tool use, weaker on open-ended "why" questions | 9B / 35B-A3B: clearly better at multi-step reasoning (BFCL-v4 66–67 vs ~50 for 4B-class models, see REASONER_DESIGN §B) |
| **Availability** | Always | Only when the fog is up and reachable. Every fog answer must therefore be optional and labelled. |
| **Privacy** | Data stays on the board | A LAN fog: on campus. A cloud VM or hosted API: approval needed. |
| **Thermals / board load** | The NPU is shared with the agents (the board reaches 93–94 °C in chaos) | Takes load off the board during long chats |
| **"Our own model" story** | This is the core contribution | Can run *the same* GGUF + LoRA to show it is portable, or a bigger model as a comparator |

**Recommendation for discussion:** the device model always answers. The fog model is an **opt-in "Ask the fog
model"** button for open-ended questions, plus a comparator in evaluation (the same question goes to the device 3B and
the fog 9B, and the answers are scored side by side). This matches the owner's "reasoning mostly would want to be
local".

### 4.4 Hosted APIs (OpenAI, Anthropic, Google and others)
- **Integration is the same:** an OpenAI-compatible or vendor SDK call, so it is one more `base_url` in the same
  config.
- **Data terms (summarised from vendor pages; verify at the time of use):**
  - OpenAI: API data is not used for training by default since 2023-03-01. Abuse-monitoring logs are kept up to 30
    days. Zero Data Retention needs prior approval.
  - Anthropic: commercial and API data is not used for training unless the customer opts in. Retention is 7–30 days by
    default depending on terms. ZDR is available for eligible customers.
- **Implications:**
  - Every prompt with incident content **leaves campus and the country**, which needs the owner's explicit approval
    under the project rule.
  - It needs internet access, so it fails offline.
  - Per-token cost. Even if small for a demo, it is recurring.
  - It weakens the "agentic edge AI" story if it becomes the main reasoner.
- **Acceptable uses, if approved:** an evaluation-only judge or comparator on **synthetic or redacted** incidents, or a
  clearly labelled "external model" option that is off by default. REASONER_DESIGN §D already rules out a cloud
  teacher for training data.

---

## 5. RAG on the fog

| Decision | Options | Suggested default |
|---|---|---|
| **Embedding model** | Qwen3-Embedding-0.6B (Apache-2.0, multilingual, strong MTEB); EmbeddingGemma-300M (308M, <200 MB quantised, 768-d with Matryoshka truncation to 256/128); bge-m3 / nomic-embed (alternatives) | **EmbeddingGemma-300M at 256-d** (small, runs on CPU with llama-server `--embedding` or sentence-transformers). Switch to Qwen3-Embedding-0.6B if retrieval tests show misses. |
| **Vector store** | pgvector (HNSW) in Postgres; sqlite-vec in SQLite; a dedicated vector database (Qdrant, Chroma) | **Whatever the fog database is**: pgvector or sqlite-vec. Under 100k vectors, a separate vector database adds operations work for no gain. |
| **Lexical side** | Postgres `tsvector` / SQLite FTS5 (BM25) | Hybrid: BM25 + vector, merged with reciprocal rank fusion, top-k 5 |
| **What gets embedded** | (1) each incident's *final* title + root cause + explanation + operator note (one chunk per incident version 3h/final); (2) maintenance and checklist notes; (3) documents: SOPs, equipment manuals, the SCRC sensor datasheets, HANDBOOK domain sections, ISA-18.2 / EEMUA-style alarm guidance summaries the lab is allowed to store; (4) optional: per-domain playbooks | (1)–(3). **Do not embed raw readings**, because numbers are answered by the exact tools, never by RAG. |
| **Chunking** | 300–500 tokens with heading path; one chunk per incident summary | Store `source_id`, `title`, `section` and `uri` for citations |
| **Re-index** | Embed on sync (incident summaries), embed on upload (docs) | Store the embedding model name and version per row. When the model changes, re-embed everything in a background job. |

**How results feed the on-device reasoner:**
1. The device model calls `search_knowledge(query, k)`, and the device executor forwards it to `/v1/knowledge/search`.
2. The fog returns at most k passages of about 120 tokens each: `{source_id, title, snippet, score}`. **No generation
   happens on the fog** in this path, so it works even without a fog LLM (options A and C below).
3. The device inserts them as a quoted, labelled `<retrieved>` data block (prompt-injection hygiene, REASONER_DESIGN
   §A.5). The 3B model must cite `source_id`, and the backend renders the citations as links.
4. Offline, the tool returns `{available:false}` and the model says "manuals and full history are unavailable offline".
5. "Similar past incidents" for the incident sheet use the same vector index (incident-summary chunks), fetched in the
   background, never on the alert path.

---

## 6. Architecture options

All four keep the **alert path 100% on the QIDK**. They differ in where full history lives, whether a bigger model
exists, and where data goes.

### Option A: LAN fog box, Postgres (or SQLite) + pgvector + Go API, no LLM
```
 [SCRC sensors] → QIDK: rules → 3B agents (NPU) → reasoner + chat (NPU, LoRA)
                    │  SQLite: last 1000 full + all-time index + outbox
                    │  mTLS HTTPS (Wi-Fi LAN, or USB via `adb reverse`)
                    ▼
        LAN FOG (laptop / lab PC / mini-PC)
        Go fog API: /v1/sync  /v1/tools/*  /v1/knowledge/search  /v1/health
        Postgres(+Timescale optional)+pgvector   |  embeddings on CPU (EmbeddingGemma)
        docs index (SOPs, manuals)               |  nightly backup → lab NAS (or encrypted → R2, if approved)
```
- **Cost:** ₹0 on the laptop; ₹25–70k for a dedicated mini-PC.
- **Effort:** about 4–6 days: the fog Go service (reusing ToolExecutor), the sync loop, mTLS, and the embedding/docs
  indexer.
- **Privacy:** best. Everything stays on campus.
- **Offline behaviour:** the device answers alone with coverage notes. Sync catches up on reconnect.
- **Chat online:** the 3B on the device answers. Counts and searches run over the complete history on the fog, and
  documents are searchable. **Chat offline:** the same answers from the device, with "partial coverage" where needed,
  and no document search.
- **Downside:** no stronger model for open-ended questions.

### Option B: A plus swappable model serving (llama.cpp server or Ollama)
```
        LAN FOG with GPU (laptop RTX 4050 6 GB for 3B/4B; lab GPU 12–24 GB for 9B / 35B-A3B)
        Go fog API ─┬─ store + RAG (as A)
                    └─ /v1/ask → llama-server  (OpenAI-compatible :8080/v1)
                                  model = config: ft_v2_q4_0.gguf + reasoner LoRA  |  Qwen3.5-9B  |  anything GGUF
 QIDK chat: device model by default; "Ask the fog model" button → /v1/ask (SSE), answer labelled "fog model"
```
- **Cost:** ₹0 (the laptop, 3B/4B, or a 9B at Q4 with a short context); ₹1.2–2.5 L for a 16–24 GB GPU workstation if
  the lab has none.
- **Effort:** A plus about 2–3 days: the model server as a service, the `/v1/ask` tool loop reusing the executor, a
  model registry in config, and an evaluation harness comparing the device and fog answers.
- **Privacy:** same as A.
- **Offline behaviour:** same as A. The button is greyed out with "fog offline".
- **Chat:** online, open-ended questions can use the stronger model. Offline, it falls back to the device.
- **Why it fits the owner's words:** "if we can deploy our own then well and good". Our own GGUF and LoRA run unchanged
  on the fog, and so can any other GGUF, by changing one config line.

### Option C: managed cloud database + serverless API (no fog LLM)
```
 QIDK ──HTTPS (internet)──► Cloudflare Worker / Supabase Edge Function / Cloud Run  (sync + tools + search)
                                   │
                          Supabase/Neon Postgres + pgvector        (+ R2 for logs)
```
- **Cost:** $0 on free tiers (Supabase pauses after a week idle; Neon cold-starts after 5 min). About $25–50/month for
  always-on.
- **Effort:** about 4–6 days. The tool executor must be re-implemented in TypeScript for Workers, or run as a Go
  container on Cloud Run or Fly.io. The pgvector, auth and network setup is easy.
- **Privacy:** **raw SCRC data leaves campus.** This needs explicit approval or redacted/synthetic data only.
- **Offline behaviour:** same as A, but "online" now means internet access, not LAN. Campus internet outages and
  proxies matter.
- **Chat:** same as A, plus WAN latency (about 100–300 ms per tool call, plus any cold start). The 1.5 s timeout will
  sometimes trip on a cold Neon or Supabase instance.
- **When it makes sense:** remote evaluators need to browse history without being on campus, and the owner approves a
  redacted dataset.

### Option D: cloud VM with a GPU (full fog in the cloud)
```
 QIDK ──WireGuard/Tailscale or mTLS──► Cloud VM (L4 24 GB / A10G)
                                       Go fog API + Postgres+pgvector + vLLM or llama-server (Qwen3.5-9B/35B-A3B, our GGUF)
```
- **Cost:** about $0.7–1.2/h on demand for the GPU. Always-on is about $500–900/month, so it must be started only for
  sessions. Spot or preemptible instances are cheaper but can be interrupted.
- **Effort:** about 1 week: infrastructure, a VPN, a start/stop script, and the same Go service as B.
- **Privacy:** worst. Data and prompts are on a provider's machine (possibly outside India).
- **Offline behaviour:** same as A. Availability also depends on the VM being started.
- **Chat:** a strong model, with WAN latency.
- **When it makes sense:** only if no lab GPU exists *and* a large-model comparison is required *and* approval is
  given. Otherwise B on a lab GPU dominates it.

### Side-by-side
| | A: LAN, no LLM | B: LAN + swappable LLM | C: managed cloud DB | D: cloud GPU VM |
|---|---|---|---|---|
| Full history and exact counts | yes | yes | yes | yes |
| Document RAG | yes | yes | yes | yes |
| Stronger model for chat | no | **yes (our own or any GGUF)** | no | yes |
| Data leaves campus | no | no | **yes** | **yes** |
| Works with no internet (LAN only) | yes | yes | no | no |
| Monthly cost | ₹0 | ₹0 | $0–50 | $50–900 |
| One-off cost | ₹0–70k | ₹0–2.5 L | 0 | 0 |
| Effort | ~4–6 d | ~6–9 d | ~4–6 d | ~7–10 d |
| Fits "reasoning mostly local" | yes | yes (fog model opt-in) | yes | yes, but in the cloud |
| Evaluation story | edge + fog storage | **edge + fog storage + portable own model + comparator** | edge + cloud | edge + cloud AI |

---

## 7. Recommended default for the university demo and evaluation

**Option B, staged so that A is delivered first. It runs on the existing project laptop and moves to a lab GPU PC if
one is available.**

1. **Stage 1 (Option A, in REASONER_DESIGN P5):**
   - Go fog service in the repo, using SQLite + sqlite-vec first (same schema as the device, near-zero setup), and
     Postgres + pgvector later only if a dashboard or several devices need it.
   - Sync over mTLS. The board reaches the laptop over **USB with `adb reverse`** during demos (no campus Wi-Fi
     isolation issues), or over the LAN.
   - EmbeddingGemma on CPU and a document index.
   - Acceptance: the fog `count_incidents` equals the device's all-time index, and the unplug-mid-chat test always
     answers with a coverage note.
2. **Stage 2 (Option B):**
   - `llama-server` on the laptop GPU serving **our own** `ft_v2` GGUF + the reasoner LoRA, which demonstrates "our
     model, portable from NPU to fog".
   - Then Qwen3.5-9B as the swappable comparator, with the model chosen in a one-line config.
   - An "Ask the fog model" button that is opt-in and labelled.
3. **Cloud only by explicit approval:**
   - an encrypted backup to R2;
   - optionally a redacted, read-only copy for remote evaluators;
   - no hosted LLM on project data.

Why this default:
- It satisfies the privacy rule with no exceptions.
- It costs nothing.
- It reuses the device's Go code, so tool answers are identical on the device and the fog.
- It keeps reasoning local.
- It directly demonstrates "a given model or our own can be changed easily".
- It gives evaluators a clear three-tier story: **mist (sensors) → edge (QIDK NPU) → fog (LAN box)**, aligned with the
  OpenFog/IEEE 1934 hierarchy and autonomy pillars, with optional cloud above.

**Board-safety note:** the fog never pushes files or models to the QIDK. Model updates keep the existing manual rule
(`.part` + md5 + `mv`, app stopped, one NPU client at a time).

---

## 8. Questions to discuss with the owner
1. **Where does the fog live?** The project laptop (only on during sessions), a lab PC or workstation (which one, and
   is there a GPU and how much VRAM?), or buy a mini-PC or Jetson? This decides A vs B and 9B vs 35B-A3B.
2. **Any cloud at all?** Is *any* upload acceptable: (a) nothing; (b) encrypted backups only; (c) a redacted or
   synthetic read-only copy for remote evaluators; (d) full data to a managed database? Which provider or region is
   acceptable (India region)?
3. **Hosted LLM APIs:** allowed for evaluation-only judging on synthetic data, or ruled out entirely?
4. **Fog model role:** opt-in "Ask the fog model" only (recommended); automatic for open-ended questions; or none
   (Option A)?
5. **Which model on the fog first:** our own v2 GGUF + LoRA (portability story), Qwen3.5-9B (quality comparator), or
   both behind the config switch?
6. **Database:** SQLite + sqlite-vec (same as device, zero administration) or Postgres + pgvector (+ Timescale) from the
   start? Will more than one QIDK or a web dashboard ever connect?
7. **Network path in demos:** USB `adb reverse` (most reliable), lab Wi-Fi (check client isolation and firewall), or a
   VPN (Tailscale / WireGuard) for off-campus access?
8. **Retention on the fog:** keep every incident version forever? Raw 5-min readings forever, or hourly only? Proof
   archives too?
9. **Documents for RAG:** which manuals, SOPs and datasheets may be stored and indexed (licensing and confidentiality),
   and who curates them?
10. **Write-back:** should approvals or maintenance entries ever be made on the fog side (a dashboard) and pulled by the
    device, or does the device stay the only writer (recommended for now)?
11. **Evaluation:** should the device-vs-fog comparison on the same question set be part of the final evaluation
    evidence (proofs/), and what is the success criterion?

---

## Sources
- Bonomi, Milito, Zhu, Addepalli, "Fog Computing and Its Role in the Internet of Things", MCC '12 (ACM, 2012):
  https://dl.acm.org/doi/10.1145/2342509.2342513 (summary: https://cse.buffalo.edu/faculty/tkosar/cse710_spring19/bonomi-bdiot14)
- IEEE 1934-2018, Adoption of OpenFog Reference Architecture for Fog Computing: https://standards.ieee.org/ieee/1934/7137/ ;
  pillars summary: https://www.i-scoop.eu/openfog-reference-architecture-ieee-1934-standard/ ;
  https://www.controldesign.com/industry-news/news/11309655/ieee-adopts-openfog-reference-architecture-as-official-standard-for-fog-computing
- NIST SP 500-325, Fog Computing Conceptual Model (2018): https://doi.org/10.6028/NIST.SP.500-325 ;
  https://nvlpubs.nist.gov/nistpubs/SpecialPublications/NIST.SP.500-325.pdf
- ETSI GS MEC 003 V2.2.1 (2020-12), MEC Framework and Reference Architecture:
  https://www.etsi.org/deliver/etsi_gs/MEC/001_099/003/02.02.01_60/gs_MEC003v020201p.pdf
- Supabase pricing and free-tier pausing (secondary; verify on supabase.com/pricing):
  https://www.jetadmin.io/blog/supabase-pricing-2026-guide-to-plans-limits-and-real-world-costs/ ;
  https://www.cloudzero.com/blog/supabase-pricing/
- Neon pricing, free plan, scale-to-zero, pgvector: https://neon.com/pricing ; https://neon.com/docs/changelog/2026-10-02 ;
  https://neon.com/faqs/postgres-databases-vector-embeddings-scale-to-zero
- Firestore pricing and free quota: https://firebase.google.com/docs/firestore/pricing ; https://cloud.google.com/firestore/pricing
- TimescaleDB editions and licence: https://www.tigerdata.com/docs/about/latest/timescaledb-editions ; https://www.tigerdata.com/legal/licenses
- InfluxDB 3 Core (MIT/Apache-2.0, query window): https://www.influxdata.com/blog/influxdb3-open-source-public-alpha-jan-27/ ;
  https://community.influxdata.com/t/announcing-influxdb-3-enterprise-free-for-at-home-use-and-an-update-on-influxdb-3-core-s-72-hour-limitation/56109
- pgvector (HNSW / IVFFlat): https://github.com/pgvector/pgvector ; https://pgxn.org/dist/vector
- sqlite-vec: https://github.com/asg017/sqlite-vec
- Cloudflare R2 pricing (secondary; verify on cloudflare.com): https://filebase.com/blog/cloudflare-r2-pricing-costs-savings-and-alternatives-in-2026/ ;
  https://www.computing.co.uk/news/4037831/cloudflare-scraps-egress-fees
- llama.cpp server (OpenAI-compatible, `--jinja` tool calling, LoRA hot-swap, embeddings):
  https://github.com/ggml-org/llama.cpp/tree/master/tools/server ;
  https://github.com/ggml-org/llama.cpp/blob/master/docs/function-calling.md ;
  https://www.mintlify.com/ggml-org/llama.cpp/inference/embeddings
- Ollama OpenAI compatibility: https://ollama.ai/blog/openai-compatibility
- vLLM tool calling: https://docs.vllm.ai/en/v0.11.2/features/tool_calling/
- TGI maintenance mode: https://huggingface.co/docs/text-generation-inference/en/index.md ;
  https://www.spheron.network/blog/migrate-tgi-to-vllm-sglang-2026/
- LM Studio headless server: https://docs.nvidia.com/openshell/latest/tutorials/local-inference-lmstudio ;
  https://www.sitepoint.com/lm-studio-04-headless-deployment-local-llm-apis-without-the-gui
- Jetson AGX Orin LLM performance (anecdotal and academic): https://forums.developer.nvidia.com/t/llm-inference-results/347999 ;
  https://arxiv.org/html/2506.09554v2
- OpenAI API data controls: https://developers.openai.com/api/docs/guides/your-data
- Anthropic data usage (commercial terms): https://docs.claude.com/en/docs/claude-code/data-usage
- India DPDP Rules 2025: https://static.pib.gov.in/WriteReadData/specificdocs/documents/2025/nov/doc20251117695301.pdf ;
  https://en.wikipedia.org/wiki/Digital_Personal_Data_Protection_Rules,_2025
- Embeddings: EmbeddingGemma https://developers.googleblog.com/en/introducing-embeddinggemma/ ; Qwen3 Embedding https://arxiv.org/abs/2506.05176
- RAG (Lewis et al., 2020): https://arxiv.org/abs/2005.11401
- Project context: `REASONER_DESIGN.md` §0, §A.4, §B.3, §C.1, §C.7, §F; `store_schema.sql`; `tools.json`; HANDBOOK 2.43
  (latency figures, thermal 93–94 °C, board-safety rules).

**Caveats:**
- Prices and free-tier limits change often and several came from secondary sources. Verify them on the vendor pages
  before any purchase or sign-up.
- CPU and Jetson token rates are estimates, not measurements.
