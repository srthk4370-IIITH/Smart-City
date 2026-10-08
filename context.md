# context.md — Repository Understanding & PRD Review

> Written 2026-10-01 by Claude (read-only pass). Nothing in the repo was modified except creating this file.
> Purpose: (1) map what actually exists, (2) compare it with `PRD.md` v2.0, (3) list what should be done better / changed.

---

## 1. What this repo is

**Project:** Agentic Edge AI for Smart Cities (team esw-m26-14 "NASA", IIIT-H ESW-M26).
**Target:** Qualcomm QIDK, Snapdragon 8 Gen 3 (SM8650), HTP V75, Android 14, device serial `3ce9a4e2`.
**Idea:** Always-on cheap anomaly detection → LLM domain agents → cross-domain root-cause synthesis → policy gate → human approval. Evaluated against rules-only and single-SLM baselines.

### Layout

```
qidk/
├── PRD.md                 1507 lines, "authoritative" v2.0 spec (AI-authored, 2026-09-17)
├── README.md              Course template README (structure, AI-usage note)
├── run.md                 Setup → download Genie bundle → deploy → run web dashboard
├── deploy.md              Demo runbook (bundle already on device, start uvicorn, open :8000)
├── Presentation/ppt.md    Slide script (406 lines) — claims Llama+Qwen multi-agent, ~7s
├── Resources/RESOURCES.md 4-line list
├── Demos/                 empty (.gitkeep)
└── Code/
    ├── platform-tools/    Windows ADB/fastboot binaries committed to git
    └── smart-city-edge-agent/
        ├── src/smart_city_edge/   core Python package (see §2)
        ├── scripts/               ~40 training / deploy / demo scripts
        ├── configs/               thresholds.yaml, prompts.yaml, genie json, LoRA yamls
        ├── models/bootstrap/      trained decision-tree routing models + 60 MB corpus JSONL (committed)
        ├── models/genie_bundle/   Llama 3.2 3B w4a16 bundle locally (git-ignored? — .bin files present on disk)
        ├── models/anomaly/        EMPTY (only .gitkeep)
        ├── qidk_runtime/          tiny C++ runner for bootstrap decision tree
        ├── android/SmartCityEdge/ placeholder README only — no Android app
        ├── tests/                 5 pytest files
        └── data/                  manifests/dataset_manifest.json only; labels/processed/raw empty
```

---

## 2. What the code actually does (module by module)

| Module | Status | Notes |
|---|---|---|
| `schemas.py` | Solid | Pydantic strict models: SensorRecord, FeatureWindow, AnomalyEvent, DomainAnalysis, RootCauseReport. `requires_human_approval: Literal[True]`. **No `causal_chain`, no `schema_version` on most models, no IncidentRecord / OrchestratorPlan.** |
| `rules.py` | Partial | Hardcoded 5 thresholds (CO2 1000, PM2.5 35, water pressure 400, energy 100, flow 50). Loads only *flat* numeric YAML keys → the nested `thresholds.yaml` format in PRD would be silently ignored. No duration / hysteresis / warning-vs-critical. Weather & occupancy rules absent. Evidence selection by substring match on IDs (`"air" in ev`). |
| `anomaly_model.py` | Partial | AE 16→64→16→64→16 (matches PRD). ONNX export opset 14 (PRD says 17). **Fallback writes a fake "ONNX_MOCK" file and a random-weight numpy AE** when torch missing — dangerous silent fallback. `AnomalyScorer` pads/truncates vectors silently. No ONNX Runtime loading path. |
| `training_data.py` + `train_domain_anomaly.py` | Good | Honest per-domain AE training, chronological 70/15/15, threshold = dev p99, metadata with hashes. **Per-domain models (5 × small AEs)** — contradicts PRD's single 16-dim joint vector. No trained artifacts committed (`models/anomaly/` empty). |
| `ingestor.py` | Minimal | Reads only aq.csv, wm-wf.csv, em.csv. No temporal join, no 1-min buckets, no forward-fill/TTL, no mask, no quarantine log. Hardcoded user paths (`C:/Users/hp/...`, `/home/rishit-nanda/...`). |
| `topology.py` | OK-ish | Loads `latest.json`; `CATEGORY_TO_DOMAIN` maps `"sr"`→WEATHER (wrong — SR = smart room), unknown categories default to ENERGY. No hot reload. `data/raw/latest.json` not in repo. |
| `policy.py` | Partial | JSON parse → schema → evidence ⊆ known set → crude keyword block (`actuate/override/shut off/lock`) only if `allowed_actions` given and *bypassed* if the text also contains an allowed-action substring. No domain-ownership check, no time-window check, no fallback substitution, no model/config hash in audit, audit write errors swallowed. |
| `prompts.py` | Partial | Uses **ChatML `<|im_start|>` tokens (Qwen format) but the deployed model is Llama 3.2**, which uses `<|begin_of_text|><|start_header_id|>…`. Llama will see these as plain text → degraded JSON compliance. |
| `genie_runner.py` | Works for demo | Shells `adb shell genie-t2t-run-2.50 --prompt_file …`. Hardcoded ADB paths (point to `qidk/platform-tools`, but binaries live in `qidk/Code/platform-tools`). No `-s serial`. Docstring claims warm-state restore / sub-5s, but code comments admit `-s` save fails (err 14001) and every call is cold (~7s). Mock fallback silently returns canned JSON. |
| `evaluator.py` | Skeleton | 3 modes, but: Mode 3 runs domain agents then calls them "orchestrator" for synthesis (no routing step, no Qwen). Fallback injects a **dummy DomainAnalysis** if agents fail → masks failure. "evidence_precision = 1 − rejection_rate" is not evidence precision. No accuracy, F1, taxonomy, ground truth, p95, repeats. |
| `bootstrap_runtime.py` + `qidk_runtime/*.cpp` | Works | Decision tree air-quality triage + routing plan. Training metadata itself admits 100% accuracy = imitation of threshold policy, not diagnosis. C++ `predict` loops `i < 8` over votes regardless of class count (possible OOB read). |
| `webapp/app.py` | **Demo-only, misleading** | See §3. |
| `scripts/prepare_domain_agent_sft.py` | Synthetic | 17 hand-written scenarios × noise augmentation to 200/domain. Labels text identical across perturbations → model memorizes templates. |
| `scripts/prepare_sft_dataset.py` | Good | Strict, requires human labels with train/dev/test; labels dir is empty so it can't run. |
| `scripts/run_qidk_llama_roles.py` | Broken-ish | Uses `genie-t2t-run` (not `-2.50`), different bundle dir (`/data/local/tmp/smart_city_edge/genie_bundle`) than runner/deploy.md (`/data/local/tmp/genie_bundle`). |
| `scripts/deploy_bundle.ps1` | Inconsistent | Default ADB `C:\Android\platform-tools\platform-tools\adb.exe`; pushes to `/data/local/tmp/smart_city_edge/genie_bundle`; requires `qairt_version.txt` (not present). No `-ModelName` param though PRD calls it with one. |
| `Makefile` | Drifted | Targets reference `train-slm`, `prepare-sft` fine, but PRD uses `make train-llama-roles DOMAIN=energy` — Makefile ignores `DOMAIN`. Help says "16 unit tests". |
| tests | Not run here | Windows Python 3.14 lacks pytest; WSL venv needed. Tests cover schemas/policy/rules basics only. |

### Missing entirely (vs PRD)
- Qwen anything: no download script, no bundle, no `QwenRunner`, no `run_qidk_qwen_synthesis.py`.
- `ModelManager` / model swap; LoRA adapters (`models/llama-lora/` doesn't exist in repo).
- `TemporalJoinEngine`, `SensorStreamManager`, FeatureWindow stats (mean/min/max/last/trend), evidence-ID format `ev_{domain}_{tag}_{epoch_ms}`.
- Event gating / cooldown / dedup.
- Fog/cloud storage, IncidentRecord, offline buffer, sync service.
- Conversational interface + tools (`query_incident_history`, `get_sensor_stats`, `get_topology_info`).
- Android app, JNI, LlamaRunner/QwenRunner/AnomalyScorer `.so`.
- Ground-truth taxonomy labels, `scrc_events.jsonl`, benchmark results.
- `download_qwen.py`, `qairt-export` (this CLI doesn't exist as named — real path is AI Hub / QAIRT `qnn-*` tools / `qai_hub_models` export).

---

## 3. Critical honesty issue — the web demo

`webapp/app.py /api/evaluate` (what `run.md`/`deploy.md` tell people to demo):

1. Anomaly score is a hand-made formula, not the autoencoder.
2. "Orchestrator" = Python `if` statements; padding forces ≥2 domains even when only one is anomalous.
3. "Domain agents" = Python string templates with fixed confidences (0.94, 0.91…).
4. The **one real NPU call's output (`qwen_res`) is never used** — `root_cause_report` is chosen from a hardcoded `if "water" in …` table with fixed confidence 0.93 and fixed uncertainties.
5. Trace text says "Genie NPU synthesised root cause … warm-state restored" — neither is true.
6. Policy-gate trace always says "Passed all zero-trust policy checks" regardless of `policy_res.is_valid`.
7. Hardcoded recommendations include "Isolate main water valve", "Isolate non-essential energy sub-circuits" — which the PRD's own action gate (§9.4) would block.
8. Variable named `qwen_res` but model is Llama.

Also: `ppt.md` / README present multi-agent Llama+Qwen as working; README says "No AI was used to generate the core models" while PRD's author is "Antigravity (AI)".

**Why it matters:** if evaluators/TA inspect the code, this reads as a faked result. Fix before any demo: either show the real LLM output (even if imperfect) or clearly label the demo as "deterministic simulation + 1 LLM call (output shown raw)".

---

## 4. PRD review — what's good

- Clear layered design; Layer 1 non-LLM gatekeeper is right for power/thermal.
- Strict schemas, `Literal[True]` human approval, evidence-ID grounding, fail-closed gate, audit log — strong safety story.
- Chronological splits, no-leakage rule, explicit failure-mode reporting, p50/p95/p99 — good research hygiene.
- Explicit ban of the `PM10*10` CO2 hack.
- Fallback architecture (§17.2) exists.

---

## 5. PRD — what needs changing / could be better

### 5.1 Scope is far beyond remaining capacity (biggest issue)
PRD describes ~6 subsystems (two LLMs + LoRA×6 + Android/JNI + cloud + chat-with-tools + benchmark of 1,000 labelled events ×3 runs). Repo today has: rules, per-domain AE trainer, bootstrap trees, a Llama bundle that runs via ADB CLI, and a web demo. **Recommend re-baselining into tiers:**
- **Must (thesis):** Layer 1 (rules+AE) on real data → Mode 1/2/3 benchmark on a labelled set → policy gate → on-device latency/RAM numbers.
- **Should:** Persistent incident store (local SQLite/JSONL) + simple dashboard (existing web app is fine; Android optional).
- **Could:** Conversational tool-calling, cloud sync, Android native app, voice, hot-reload topology.
Mark Android app, Firebase, chat as stretch so the thesis isn't held hostage.

### 5.2 Internal contradictions in the PRD
| Where | Contradiction |
|---|---|
| §2.4 thesis "<15 s" vs §14.4 Mode 3 "10–20 s" vs §16.2 "p95 ≤ 20 s" | Pick one target. |
| §4.3 "~3.5 GB total peak" vs §14.4 "<4 GB" vs §16.2 "≤4.5 GB" | Pick one. Also Llama 3B w4a16 on-device is ~2.8 GB per `deploy.md`, not 1.8 GB. |
| §2.3 "Qwen is a larger model" vs §8.2 Qwen 1.5B (smaller than 3B Llama) | Reasoner is actually *smaller*. Either justify (synthesis over compact JSON needs less) or swap roles / use same model. |
| §7.4 "LoRA hot-swap in ms, base stays in HTP" vs §13.5 "merge each adapter → standalone Genie bundle" | Merged bundles = 6 × ~2.8 GB, no hot-swap. Genie LoRA support on HTP needs specific export (LoRA-enabled context bins); not assumed by current pipeline. Decide: (a) prompt-only roles on one base (Fallback 1), or (b) verified Genie LoRA adapters. |
| §7.2 orchestrator min 2 agents vs §7.2 example "pure water drop may only need Water+Weather" + bootstrap plan `air_only` | Forcing ≥2 creates noise; allow 1. |
| §8.2 lists "Qwen2-2B-Instruct" | Doesn't exist (Qwen2 has 0.5B/1.5B/7B). Use Qwen2.5-1.5B/3B. Check AI Hub for a ready SM8650 Genie bundle first (Qwen2.5-7B / 3B variants are published there). |
| §6.4 cooldown "until Qwen report received" vs §12.4 human approval pending 30 min | Clarify whether cooldown ends at report or at approval. |
| §16.3 "100% of reports require approval before cloud commit" vs §10.1/10.4 "write immediately after validation" | Contradiction — decide whether unapproved incidents are stored (they should be, flagged `human_approved=false`). |
| §5.3 16-dim joint vector vs code's per-domain AEs and the training_data.py rationale ("concatenating unrelated sensor rows would create fake joint observations") | Code's reasoning is better. Joint vector only valid after a real spatial temporal join; outdoor sensors aren't per-zone. Update PRD to per-domain AEs + optional joint AE later. |
| §5.4 forward-fill TTL 60 min vs ±2 min skew vs ±5 min out-of-order | Fine, but energy at 15 min and water quality at 30 min make 1-min buckets mostly filled values; consider 5-min buckets. |
| §6.3 "threshold = p99 of **test** split" | That's leakage into eval. Use dev/validation split (as the code already does). |
| §6.3 AE trained on "records not flagged by rule engine" | Means AE learns rules' complement → correlated with Mode 1, weakens comparison. Acknowledge. |
| §13.2 gate "test reconstruction loss < 0.35" | Arbitrary, unit-less across normalisation; replace with FPR-on-held-out-normal target. |

### 5.3 Evaluation design gaps (thesis validity)
- **Ground truth is the crux and is unsolved.** No incident labels exist; dataset has none. 1,000 manual labels is unrealistic. Proposal: ~150–300 labelled events, stratified; two annotators on a subset, report Cohen's κ; document labelling protocol. Alternatively **inject synthetic faults** into real traces (known cause by construction) for a controlled benchmark, plus a smaller real-event qualitative set.
- Label leakage risk: if bootstrap/rule labels seed LoRA training and also define "ground truth", Mode 3 just imitates rules. Keep label source independent.
- Mapping free-text `root_cause` → taxonomy label is undefined. Add a `root_cause_label: TaxonomyEnum` field to RootCauseReport (model must output it) rather than post-hoc classification.
- Paired t-test on binary accuracy is wrong — use **McNemar's test** (paired binary) and bootstrap CIs for macro-F1. Greedy decoding (`temp 0, top-k 1`) makes 3 repeated runs identical → variance is meaningless; vary seeds/temperature or drop the claim.
- Mode 2 vs Mode 3 confound: Mode 3 uses Llama+Qwen (2 models, more compute, more tokens); Mode 2 uses Qwen only. Add **Mode 2b = single Llama** and/or **Mode 3b = same model for agents and synthesis**, so the gain is attributable to decomposition, not model choice. Also report compute-matched comparisons (tokens / latency).
- Mode 1 "accuracy" is undefined — rules output violation strings, not taxonomy. Need a rule→taxonomy mapping.
- Evidence precision is trivially 1.0 after the gate; measure it **before** gate (that's the hallucination rate) and state it as such.
- Power: `dumpsys batterystats` on a dev kit on USB is not a reliable power proxy. Use `/sys/class/power_supply/*/current_now` sampling or Snapdragon Profiler; or drop power claims.

### 5.4 Safety / policy
- Keyword blocklist is easily bypassed and false-positives ("disable" in "disabled sensor"). Better: recommendation must be an **enum from `allowed_actions`** + optional free-text note. The code's `prompts.yaml` already has an action list — make it the contract.
- §9.2 "energy evidence only cited by Energy agent" — Qwen must cite cross-domain; specify per-role.
- Audit log "immutable" on `/data/local/tmp` with `chmod 700` is not immutable; say "append-only by convention + hash chain" (each entry includes previous entry's SHA-256) — cheap and verifiable.
- §15.2 certificate pinning + Firebase: Firebase SDK handles TLS; pinning is extra work, low value for a prototype — drop or mark stretch.
- Prompt injection: tool outputs (incident text that was LLM-generated) also re-enter context — treat as untrusted.

### 5.5 Hardware / deployment realism
- `/data/local/tmp` is **not** wiped on normal reboot on Android (deploy.md says it may be) — verify; but it is accessible to shell only, not to an Android app's sandbox. An Android app can't read `/data/local/tmp` bundles under SELinux enforcing → bundles must live in app-private storage or be pushed via `adb push` to `/sdcard/Android/data/<pkg>/` / bundled. PRD §4.5/§12 should address this before committing to an Android app.
- Genie CLI over ADB has ~4 s HTP init per call (code comments). Multi-agent with 4–6 sequential calls ⇒ 25–40 s cold. Need a **persistent Genie process** (genie C++ API in a long-running native daemon on device, reading prompts from a FIFO/socket) — this is the single biggest latency win and should be a PRD requirement for Mode 3.
- Two LLMs + swap: loading a 2.8 GB context bin takes seconds; swapping per event kills latency. Strong argument for **one model** (Llama 3B) for all roles with role prompts (PRD Fallback 1/2) as the primary plan, Qwen as optional.
- `max-num-tokens: 100` in genie config and `max_tokens=60` in code — a full RootCauseReport JSON needs ~200–350 tokens. Current settings truncate output → invalid JSON. (Note: `max_tokens` param in `run_prompt` is not even passed to genie.)
- Context window 4096 for Llama config; prompts with full JSON schemas + evidence lists can be large — measure.
- Paths: PRD uses `C:\Android\platform-tools\adb.exe`, code uses `qidk/platform-tools`, repo has `qidk/Code/platform-tools`. Centralise in one config (env var `ADB`, `QIDK_SERIAL`, `DEVICE_ROOT`).

### 5.6 Data layer
- Building/zone join key: outdoor AQ, weather, water nodes don't map to rooms. PRD should define a **zone hierarchy** (campus → building → room) and which domains join at which level (weather = campus-level broadcast to all zones).
- `topology` `sr` → weather mapping is wrong; PRD should specify the full node-prefix → domain table (AQ, EM, SR-AQ, SR-AC, SR-OC, SR-EM, WE, WM-WF/WD/WL, WN, SL).
- Evidence-ID per raw observation × 60-min window × 16 features ⇒ hundreds of IDs per event → blows LLM context. Use evidence IDs per **feature-stat** (e.g. `ev_energy_EM-BH01_kw_max_<window_end>`), a few dozen per event.
- Occupancy from `sr_oc.csv` is a JSON dict summed in code — confirm semantics (counts per sensor vs presence flags).

### 5.7 Process / docs
- PRD claims "supersedes all prior .md" but README/run.md/deploy.md/ppt.md describe a different (current demo) system. Add a **"Current Status vs Target"** table to PRD and keep it updated; align ppt.md with reality.
- PRD §7.3 "Orchestrator + AQ adapter trained, checkpoints 200/250" — no adapter in repo; record where it lives (and its eval) or mark unverified.
- Committed binaries: 60 MB corpus JSONL and ADB exes in git. Move to Git LFS / release assets; regenerate corpus via script.
- Add a single `config.py`/`.env` for paths; remove hardcoded `C:/Users/hp` and `/home/rishit-nanda`.
- Add a milestone timeline with owners/dates — PRD has none.

---

## 6. Suggested priority order (if/when changes are allowed)

1. **Make the demo honest**: surface raw LLM output, real policy result, correct labels (Llama not Qwen, cold not warm).
2. Fix Llama prompt template (use Llama 3 chat format / tokenizer `chat_template.jinja` already in bundle) and raise `max-num-tokens` to ~400.
3. Persistent on-device Genie process (or at least measure per-call cold cost) → realistic Mode 3 latency.
4. Implement minimal temporal join (5-min buckets, per building, weather broadcast) → real FeatureWindows + stat evidence IDs.
5. Rules engine reads the nested `thresholds.yaml` (fill real values) with duration/hysteresis.
6. Train & commit per-domain AE artifacts + metadata; ONNX Runtime scoring path; remove mock-ONNX fallback.
7. Labelled eval set (synthetic fault injection + ~200 human labels), taxonomy field in schema, McNemar test, Mode 2b/3b ablations.
8. Single-model multi-role Mode 3 first; add Qwen only if time permits.
9. Local incident store (SQLite) + approve/dismiss in web dashboard. Android/cloud/chat as stretch.
10. Update PRD with resolved contradictions + status table; align README/ppt.

---

## 7. Open questions for the team
- Where is the trained orchestrator LoRA adapter, and was it evaluated?
- Is Android native app a hard course requirement, or is the web dashboard acceptable?
- Is Qwen a hard requirement (advisor ask?) or optional?
- Deadline / evaluation date? Determines which tier of §5.1 is realistic.
- Do any real incident logs from SCRC/campus ops exist for ground truth?
