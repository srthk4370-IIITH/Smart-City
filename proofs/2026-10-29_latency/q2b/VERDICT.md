# q2b verdict: Qwen3.5-2B (base, Q4_0) on the QIDK NPU via htpd_v8x5 vs the live 4B reasoner

Speed and execution correctness only. The 2B is the untrained BASE model, so answer quality/accuracy is NOT measured.
Same window, same split requests (/data/local/tmp/rfast/rreq_split/qN.json), same htpd env (lab_ab.sh); k=0 (q10) is the warm-up and is excluded from means.

## Answer
- **Does the 2B run on the NPU through htpd? YES**
- **Decode ms/step: 2B 37.6 vs 4B 127.8 (x0.29)**; prefill 516 vs 1052 ms; mean total 26.8 s vs 23.2 s (2B steps/request 699 vs 4B 172)
- Reasoner load (model phase, mean): 2B 2347 ms vs 4B 3974 ms

## Projection: 2B at the 4B's own step counts
projected = 2B prefill(q) + 4B steps(q) x 2B ms/step(mean) + 4B non-step overhead(q). Base-model step counts differ, so this is the fair speed number.

| q | 4B total s | 4B steps | 2B total s (actual) | 2B steps | 2B projected s |
|---|---|---|---|---|---|
| q10#1 | 30.0 | 211 | 26.8 | 699 | 8.7 |
| q11#2 | 29.5 | 204 | 26.9 | 699 | 8.3 |
| q12#3 | 20.4 | 166 | 26.5 | 699 | 6.8 |
| q13#4 | 24.3 | 178 | 27.0 | 699 | 7.4 |
| q14#5 | 17.6 | 137 | 26.8 | 699 | 5.6 |
| q15#6 | 17.1 | 139 | 26.7 | 699 | 5.6 |

**Projected mean reasoner time: 2B 7.1 s vs 4B 23.2 s (70% saved per request).**

## Per request
| cfg | q#k | ok | stop | total ms | prefill ms | tokens | forced | steps | rows/step | ms/step | parses | keys |
|---|---|---|---|---|---|---|---|---|---|---|---|---|
| 4b | q10#0 | yes | json | 35536 | 3648 | 571 | 151 | 201 | 2.82 | 137.39 | yes | 16 |
| 4b | q10#1 | yes | json | 30036 | 1428 | 583 | 151 | 211 | 2.74 | 135.22 | yes | 16 |
| 4b | q11#2 | yes | json | 29485 | 1090 | 573 | 146 | 204 | 2.79 | 138.84 | yes | 16 |
| 4b | q12#3 | yes | json | 20428 | 971 | 355 | 97 | 166 | 2.11 | 116.84 | yes | 16 |
| 4b | q13#4 | yes | json | 24339 | 1385 | 429 | 118 | 178 | 2.39 | 128.57 | yes | 16 |
| 4b | q14#5 | yes | json | 17640 | 739 | 352 | 106 | 137 | 2.54 | 122.83 | yes | 16 |
| 4b | q15#6 | yes | json | 17099 | 697 | 339 | 105 | 139 | 2.41 | 117.57 | yes | 16 |
| 2b | q10#0 | yes | max | 30518 | 1691 | 700 | 0 | 699 | 1.0 | 37.67 | NO | 0 |
| 2b | q10#1 | yes | max | 26836 | 700 | 700 | 0 | 699 | 1.0 | 37.36 | NO | 0 |
| 2b | q11#2 | yes | max | 26878 | 534 | 700 | 0 | 699 | 1.0 | 37.66 | NO | 0 |
| 2b | q12#3 | yes | max | 26506 | 482 | 700 | 0 | 699 | 1.0 | 37.2 | NO | 0 |
| 2b | q13#4 | yes | max | 27008 | 676 | 700 | 0 | 699 | 1.0 | 37.64 | NO | 0 |
| 2b | q14#5 | yes | max | 26771 | 363 | 700 | 0 | 699 | 1.0 | 37.75 | NO | 0 |
| 2b | q15#6 | yes | max | 26738 | 339 | 700 | 0 | 699 | 1.0 | 37.74 | NO | 0 |

Parse = the answer JSON loads. The JSON forcer forces the schema keys ("forced" = forced tokens), so a parse is execution correctness, not base-model quality.

2B sample answer (q10, first 600 chars, for the record only):
```
```json
{
  "title": "TH Building Water Tank & Flow Anomaly",
  "severity": "warning",
  "label": "water_supply_issue",
  "root_cause": "Water tank draining at 04:25 IST (04:25-04:30) causing rapid level decrease from 261.0 to 236.1, exceeding normal variation and approaching critical threshold.",
  "causal_chain": [
    {
      "text": "Water flow meter 40 shows stable flow at 0.26 m3/h (S2.E1, S2.E4).",
      "src": "S2"
    },
    {
      "text": "Water tank level sensor 00 shows level 98 (S1.E1, S1.E3).",
      "src": "S1"
    },
    {
      "text": "Tank level decreasing at -5.9 level/h (
```

## htpd
- 4b: htpd: ready in 2146 ms: 10 agent streams x 1280 ctx, synth ctx 4096, device HTP0, port 8091
  - load phases: model 3974 ms, context 105 ms, pieces 5 ms
- 2b: htpd: ready in 2063 ms: 10 agent streams x 1280 ctx, synth ctx 4096, device HTP0, port 8091
  - load phases: model 2347 ms, context 13 ms, pieces 5 ms
  - error-like lines:
    - `htpd: reason stream 1: 0 tokens (0 forced, 0 constrained picks), stop error, 0 ms`
    - `htpd: reason stream 2: 0 tokens (0 forced, 0 constrained picks), stop error, 0 ms`
    - `htpd: reason stream 1: 0 tokens (0 forced, 0 constrained picks), stop error, 0 ms`
    - `htpd: reason stream 2: 0 tokens (0 forced, 0 constrained picks), stop error, 0 ms`
    - `htpd: reason stream 1: 0 tokens (0 forced, 0 constrained picks), stop error, 0 ms`
    - `htpd: reason stream 2: 0 tokens (0 forced, 0 constrained picks), stop error, 0 ms`
    - `htpd: reason stream 1: 0 tokens (0 forced, 0 constrained picks), stop error, 0 ms`
    - `htpd: reason stream 2: 0 tokens (0 forced, 0 constrained picks), stop error, 0 ms`
    - `htpd: reason stream 1: 0 tokens (0 forced, 0 constrained picks), stop error, 0 ms`
    - `htpd: reason stream 2: 0 tokens (0 forced, 0 constrained picks), stop error, 0 ms`
    - `htpd: reason stream 1: 0 tokens (0 forced, 0 constrained picks), stop error, 0 ms`
    - `htpd: reason stream 2: 0 tokens (0 forced, 0 constrained picks), stop error, 0 ms`
    - `htpd: reason stream 1: 0 tokens (0 forced, 0 constrained picks), stop error, 0 ms`
    - `htpd: reason stream 2: 0 tokens (0 forced, 0 constrained picks), stop error, 0 ms`
    - `htpd: stream 5 aborted after 14 tokens: value longer than any label`
- window ABORT/HEAT lines: none

## Provenance
- model: Qwen/Qwen3.5-2B (HF, base) -> convert_hf_to_gguf.py --outtype bf16 (CPU) -> llama-quantize Q4_0 4 (no imatrix); md5 5d7b7d4bcc499aa3612dac0e18f499f2; board /data/local/tmp/gpu/q2b_base_q4_0.gguf
- window: proofs/2026-10-29_latency/q2b_ab (ab.log, htpd_4b.log, htpd_2b.log, telemetry.log, raw responses); job log ~/detached/q2b.log
- live libs, live profile and the deployed reasoner were not changed; nothing deployed

