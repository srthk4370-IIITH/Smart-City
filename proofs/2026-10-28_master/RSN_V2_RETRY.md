# rsn_v2 retry with htpd_v8x3 (2026-10-29)

**Result:** DEPLOYED htpd_v8x3 + rsn_v1: app check PASS (chaos 3 3 3, fastcheck {"fast_incident": "INC-0433", "fast_s": 5.6, "ai_update_s": 47.2, "final_model": "qwen3.5-4b (htpd)", "valid": true, "severity": "sensor_fault", "title": "KH building, level 03: Suspect CO2 readings", "pass": true})

## Cause and fix
**What was tested (host repro, WSL CPU, `v8x3/host_v2q11_{A,B}.*`).** htpd built from the same source, rsn_v2, request q11 with split-3.
- Pass A uses the old v8x2 pick path (`HTPD_PICK_BOUNDED=0`); pass B uses the bounded pick.
- Both passes finish (`stop json`, 612 tokens, sensor_fault/sensor_fault) with byte-identical text.
- The split happens at the same point as on the board (147 tokens).
- **0 slow picks:** no top-64 miss and no full scan.

**What this rules out:** the hypothesised full-vocabulary scan is not what stalls on this request path. The CPU-side forcer/pick logic completes for the same head.

**Remaining explanations:**
1. An HTP-side op that never completed. With `GGML_HEXAGON_OPPOLL=1` the host thread busy-polls, so a stuck DSP op looks exactly like the board symptom: 100% CPU in state R, no stream end, no log growth.
2. A token path that only HTP numerics reach (the board diverges after the split), in which the CPU logic loops.

The board log cannot separate these two.

**Fix in htpd_v8x3** (md5 in `v8x3/android/htpd.md5`):
- (a) Bounded constrained pick: argmax, then top-64 (unchanged), then top-1024 (same token as the old full scan whenever one of the 1024 is allowed), then the first forced token, and a full scan only as the last resort. Counters are logged per request.
- (b) A 150 s wall-clock guard per reason request, checked every decode step. The stream stops with "timeout", the Go gate rejects the text, and the deterministic report stays.
- (c) A cap of 1024 iterations in `Forcer::forced_text`, as a no-progress guard. The forcer gold test is unchanged: 6,046 answers, 0 rejected, the same forced %.
- (d) A heartbeat thread. If decode makes no progress for ≥ 30 s it logs `in_decode` and the phase, so a repeat stall names its side: `in_decode 1` = HTP op; `in_decode 0` = CPU loop.
  - A stall inside one HTP op cannot be bounded by (b). The overnight watchdog covers that case with SIGTERM.


## Board numbers (split-3 + OPPOLL, htpd_v8x3; raw: `v8x3/raw_par`, `raw_v2`, `raw_cons`)
| check | value | gate |
|---|---|---|
| v8x3 + rsn_v1 parse (q10-q14) | 5/5 | 5/5 |
| v8x3 + rsn_v1 same severity/label as v8x2 | 5/5 | >= 4/5 |
| reasoner mean s (v8x3 / v8x2, q10-q14) | 25.2 / 23.4 | - |
| rsn_v2 parse (q10-q19) | 10/10, stops {'json': 10}, q11 stop json | 10/10 |
| severity vs gold v2 / v1 | 10 / 10 | v2 >= v1 |
| label vs gold v2 / v1 | 8 / 9 | v2 >= v1 |
| rsn_v2 mean s (q10-q19) | 22.7 | - |
| rsn_v2 severity consistency (q11-q13 x 3) | 9/9 | >= 8/9 |
| split-6 at 6x3200 ctx, rsn_v1 q10-q14: parse / same sev+label as sp3 / mean s | 0/5 / 0/5 / 0.0 (sp3 25.2) | numbers only, no deploy |

Board state after the run:
```
ebd08e13d58b906ab01979f117d86158  /data/local/tmp/smart_city_edge/edge-agent
model=/data/local/tmp/gpu/ft_B50_q4_0.gguf
reasoner_split=3
bin=/data/local/tmp/llama.cpp/bin/htpd_v8x3
reasoner_model=/data/local/tmp/gpu/qwen35_reasoner_q4_0.gguf

```
Rollback: restore `v8x3/known_good/htpd_profile` (and reinstall `known_good/app.apk`) with the app stopped; log `rsn_v2_retry.log`.
