# Cross-Machine Engineering Review Request — Agentic Edge AI for Smart Cities

## Purpose

You are reviewing this project from a second developer laptop, which may contain the dataset, QIDK checkout, trained models, event corpus, test environment, and device access that are intentionally absent from this workspace.

Do **not** assume an item is missing globally because it is absent here. Equally, do **not** treat documentation claims as proof that an item exists or works on your machine. Turn every claim below into evidence: a path, a command that succeeds, a version/hash, and a short result.

The presentation's committed question is:

> Does five-domain, on-device multi-agent reasoning improve root-cause diagnosis and evidence grounding over rules and one SLM, while remaining acceptable on QIDK latency, memory, power, and NPU constraints?

The project is credible only if it can answer that question with a reproducible, labelled, on-device experiment.

## First response required from you

Before changing architecture or adding UI, complete this checklist. Mark every row **verified**, **present but broken**, **missing**, or **not applicable**. Include commands and concise output; never substitute a mock or screenshot for evidence.

| Item to verify on your machine | Evidence required |
| --- | --- |
| QIDK checkout | Exact path, commit SHA, and confirmation that `GenAI-Solutions/AI-Assistant`, `GenAI-Solutions/ASR-LLM-TTS`, and `Tools/qairt_docker` exist |
| QIDK device | `adb devices -l`, Android/SoC/ABI/HTP target, free `/data`, SELinux state, and thermal status |
| Python environment | Python version, dependency lock or manifest, package list, and actual `pytest -q` result |
| SCRC data and metadata | Exact path, file list/size, field/unit specification, access/licensing status, and dataset manifest/hash |
| Topology snapshot | Path, node count, source/date, and a successful lookup of `WM-WF-PL00-70` |
| Anomaly artifact | `model.onnx`, normalisation metadata, training log/run ID, feature schema, hash, and validation metrics |
| Event corpus | JSONL path/count, sample validation, source versions, label availability, and corpus hash |
| Genie bundle | Bundle manifest, QAIRT version, SM8650/V75 compatibility, config filename, layout, and hashes |
| QIDK smoke test | Exact successful command, output, exit code, JSON validity, TTFT/latency, RAM, and thermal state |
| Benchmark result | Command, locked test-set version, raw traces, result path, measured metrics, and failures |
| Android app | Gradle/JNI source path, build command, APK hash, install result, and replay-parity test |

For a missing row, explain whether you can recover it locally, need another teammate to supply it, or must rebuild it. A directory or source file alone is not proof of completion.

## Findings to inspect in your version

For every finding, say **fixed**, **still broken**, **not applicable**, or **needs a design decision**. If fixed, cite a file/commit and a passing test or runtime trace.

### A. Is the anomaly model actually trained?

The shared `scripts/train_anomaly.py` only calculates reconstruction error from a newly constructed autoencoder. It has no optimizer, loss/backpropagation loop, epochs, checkpoint selection, or held-out validation. If data is absent, it generates random values but writes `status: trained`.

Questions:

1. Does your copy implement real, deterministic training? Show the seed, train/dev/test split, normalisation fit, loss curve, checkpoint and model hash.
2. Is training limited to verified normal data, with labelled anomalies held out for evaluation?
3. Does deployed scoring load the exact model and scaler produced by training?
4. What are the false-positive rate, detection delay, precision/recall, and drift behavior on a locked test split?

### B. Does runtime scoring match the trained model?

The shared `AnomalyScorer` makes a fresh model by default and does not load `model.onnx` or `norm_params.json`. It pads/truncates vectors, while raw feature position can depend on dictionary order.

Questions:

1. What is the canonical feature schema: source field, unit, range, missing-data handling and fixed order?
2. How does runtime prove its model hash, feature order and normalisation match training?
3. Is ONNX/QNN genuinely used on-device, rather than PyTorch/NumPy on the host?
4. Does a schema mismatch fail closed instead of silently padding/truncating?

### C. Is there a real five-domain event pipeline?

The shared extractor reads air-quality and water-flow only, creates point windows rather than 60-minute aligned windows, and does not use its instantiated anomaly scorer or imported topology registry. Energy, weather and occupancy are not joined into events.

Questions:

1. Where is the timestamped, spatially aware join across energy, air quality, water, weather and occupancy?
2. How are clock skew, sampling-rate differences, duplicates, late data and missing sensors handled?
3. Show a real replay trace with all five domains, evidence objects, and the ring-buffer memory limit.
4. Can every event be traced to documented rule/model trigger logic and raw measurements?

### D. Are the data mappings scientifically valid?

The shared AQ adapter derives CO2 as `PM10 * 10`, replaces missing timestamps with the current time, and silently discards broad parsing failures. Those behaviors could fabricate health/ventilation evidence and corrupt time ordering.

Questions:

1. Does the real dataset contain CO2? If not, why is it a decision feature?
2. What proves every raw-field mapping, unit conversion and calibration assumption?
3. Are malformed/out-of-range records quarantined with reasons instead of silently repaired/dropped?
4. Can an auditor trace each evidence ID to raw record, timestamp, unit and transformation?

### E. Is the rules baseline a real policy baseline?

The shared thresholds config labels itself placeholder and is nested, but `RuleEngine` expects flat numeric keys and usually runs without the config. Water-flow is declared but not checked; weather, occupancy, HVAC state, hysteresis and missing-data behavior are absent.

Questions:

1. What approved operating policy defines threshold, unit, severity and action for every rule?
2. Does a loaded configuration demonstrably change runtime behavior? Show a test per rule.
3. How do persistence, hysteresis, quality flags and recovery prevent alert flapping?
4. What non-agent statistical/ML baseline is included so the comparison is not simply rules versus prompts?

### F. Does “multi-agent” equal the deck’s architecture?

The shared evaluator calls only `event.domains`, not all five roles. It silently discards domain-output parse errors and creates a dummy analysis if needed. That is not a trustworthy five-specialist-plus-orchestrator experiment.

Questions:

1. Define the exact ablations: rules, single SLM, five-agent + orchestrator, and any cost-matched simpler alternative.
2. Are inputs, evidence, token/context budget, output schema, retry policy and model version comparable and logged across modes?
3. Must every event call five agents? If not, what deterministic routing policy selects agents, and how is routing cost/quality evaluated?
4. Do invalid agent responses fail visibly, or can they be silently replaced? Why?
5. Can five serial calls meet the edge latency/power budget? Show a measured worst-case trace.

### G. Can mocks conceal real runtime failures?

The shared `GenieRunner` defaults to `use_mock_fallback=True`. Missing binaries or execution errors produce deterministic successful-looking JSON for a fixed event/evidence pair. Its host CLI/config contract also conflicts with the documented QIDK smoke command.

Questions:

1. Are mocks restricted to explicitly injected test fixtures and prohibited in benchmark/deployment mode?
2. Does device benchmark mode hard-fail when Genie, bundle, QAIRT compatibility, JSON output or evidence binding fails?
3. What is the actual Genie command/API contract for the installed bundle? Show an authoritative reference and a successful invocation.
4. Is the runner genuinely on-device through ADB/native Android rather than attempting to execute a host binary?

### H. Is the safety/evidence gate as strong as claimed?

The shared gate checks schema, evidence-ID membership and a few recommendation substrings. It does not bind the output `event_id` to input, validate evidence time/domain/window, enforce typed actions, assess claim support, or fail closed if audit logging fails.

Questions:

1. How does every claim bind to a specific measurement and relevant time window, not merely a known identifier?
2. Is each report bound to event ID, immutable evidence snapshot, model version and configuration version?
3. Are recommendations a typed allow-list with a strict boundary between advice and actuation?
4. Where are audit logs stored, how are they redacted/protected, and what happens when persistence fails?
5. Which red-team tests cover fake/stale evidence, event-ID substitution, prompt injection and unsafe recommendations?

### I. Can the benchmark answer the research question?

The shared harness has no root-cause labels, split protocol, annotation method, counterfactual/negative cases, or resource instrumentation. It defines `evidence_precision = 1 - rejection_rate`, which is policy acceptance—not evidence precision. It does not measure TTFT, percentile latency, warm-up/thermal effects, RAM, power/energy, HTP utilisation, model/network footprint, or confidence intervals.

Questions:

1. Where are ground-truth labels, taxonomy, annotator agreement, and leakage-safe train/dev/test split?
2. Define root-cause accuracy, macro-F1, evidence precision/recall, hallucination rate and policy rejection rate precisely.
3. How will timing separate TTFT, total latency and user-visible latency, including warm-up and p50/p95/p99?
4. Which device counters will measure RAM, power/energy proxy, thermal state and HTP/NPU use, and what are their limitations?
5. How will you report abstentions, uncertainty, failures and “insufficient evidence” outcomes?

### J. Is Android a proven demonstration or a second untested system?

The shared Android directory is a placeholder. The shared deployment script likely has a duplicated `platform-tools` path and does not verify device state, storage, bundle integrity, QAIRT compatibility or smoke output.

Questions:

1. Does your machine contain a real Gradle/JNI/CMake project, and does it use the same inference runtime and replay schema as the benchmark?
2. Which native ABI/QAIRT compatibility checks run before install?
3. What proves offline behavior, restart recovery, failed inference handling, human approval and durable auditing?
4. Should Android be deferred until host/device benchmark parity is proven? Give an evidence-based answer.

## Food for thought before implementing more

1. **Root cause or hypothesis?** Observational sensor data is usually correlational. What confounders—weather, maintenance, delayed actuation, occupancy error—must a report expose?
2. **Fairness of the agent comparison:** could multi-agent gains merely come from more tokens/calls? What token/cost-matched control isolates specialization?
3. **Smallest viable system:** if one constrained SLM call nearly matches six calls, why bear the edge cost?
4. **Failure behavior:** what exactly happens when evidence conflicts, data are missing, JSON is invalid, thermal throttling occurs, or the model cannot ground its answer?
5. **Privacy and operations:** what retention, access control, encryption, redaction, update and rollback controls are needed for occupancy/network telemetry and facility recommendations?
6. **Falsifiability:** what measured outcome would make us reject the multi-agent design in favor of a single SLM or a non-LLM solution?

## Required response and plan

Return:

1. the completed verification table with commands and evidence;
2. a disposition for Findings A–J;
3. a corrected architecture/data flow if this shared code is outdated;
4. a 2–3 week plan in hard-gate order: reproducible environment → five-domain labelled replay → non-LLM trigger → one-call QIDK smoke test → controlled benchmark → Android demonstration;
5. the one decision that needs the project guide/TA before further implementation.

Do not start Android UI work or claim benchmark results until data, labels, real Genie execution and device measurements are verified.

## Final principle

The presentation has a sound thesis: bounded, event-driven edge reasoning across coupled infrastructure domains is worth testing. Make the implementation earn it. Evidence, reproducibility and honest failure modes matter more than an attractive multi-agent demo.
