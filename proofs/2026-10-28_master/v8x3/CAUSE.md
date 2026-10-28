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
