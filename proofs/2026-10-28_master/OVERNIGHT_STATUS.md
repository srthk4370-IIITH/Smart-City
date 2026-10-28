# Overnight status (2026-10-28T22:18:36Z, IST 03:48)

| job | state |
|---|---|
| final | stopped |
| split_post | stopped |
| rag_deploy | stopped |
| rag_seed | alive |
| website_final | stopped |
| watch | alive |
| x2x3 | alive |

**Board:** online, 49 C, MemAvailable 5061 MB, procs: 30651 htpd_v8x2 
**BOARD_LOCK:** x2x3
**Stalled-htpd SIGTERMs tonight:** 0

## final.sh
```
2026-10-28T18:18:19Z F5 profile: bin=/data/local/tmp/llama.cpp/bin/htpd_v8x2 model=/data/local/tmp/gpu/ft_B50_q4_0.gguf reasoner_model=/data/local/tmp/gpu/qwen35_reasoner_q4_0.gguf reasoner_split=3 
2026-10-28T18:18:49Z F5 stop: STOPPED
2026-10-28T18:19:21Z F5 deployed: edge-agent c97afdeb1c06607fc1535cb6806f9d1d; htpd: ready in 2016 ms: 10 agent streams x 1280 ctx, synth ctx 4096, device HTP0, port 8091 htpd: v8 reasoner slot: /data
2026-10-28T18:43:54Z F6 chaos rc=0 (n done valid: 6 6 6); fastcheck rc=0 {"fast_incident": "INC-0418", "fast_s": 6.3, "ai_update_s": 55.2, "final_model": "qwen3.5-4b (htpd)", "valid": true, "severity"
2026-10-28T18:43:55Z F6 result: PASS: chaos 6/6 done+valid, fast path then AI on the same incident: {"fast_incident": "INC-0418", "fast_s": 6.3, "ai_update_s": 55.2, "final_model": "qwen3.5-4b (htpd)"
2026-10-28T18:43:55Z F7 FINAL_STATUS.md + HANDBOOK 2.56 written
```
result: PASS: chaos 6/6 done+valid, fast path then AI on the same incident: {"fast_incident": "INC-0418", "fast_s": 6.3, "ai_update_s": 55.2, "final_model": "qwen3.5-4b (htpd)", "valid": true, "severity": "sensor_fault", "title": "KH building, level 03: Suspect CO2 readings", "pass": true}

## split_post
```
reasoner_split=3
2026-10-28T19:02:10Z app up with split 3
2026-10-28T19:02:10Z === split_post done
```

## rag_deploy
```
```
RAG_STATUS.md written

## rag_seed
```
```

## rsn_v2 retry
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
