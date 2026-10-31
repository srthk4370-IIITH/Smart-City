# 2026-10-31 agents fast path: profile + htpd_v9e agent draft index — NOT deployed (one output flip in 24)

Live board was not changed: deploy19 (htpd_v9d) still runs. htpd_v9e is on the board (`/data/local/tmp/llama.cpp/bin/htpd_v9e`, md5 0080ce23…) but no profile uses it. deploy20.sh (proofs/2026-10-29_latency/deploy20.sh) is ready but has not been run.

## Where the time goes
**Fastcheck AI update, 27 s** (raw/fastcheck_1793393640 + _3479; INC-0530/0532):
- Fast path at 5.8 s: rules only, no NPU. The time is the poll cadence.
- About 7 s waiting for the 8-reading gate. This is the test's own sensor time.
- Agent: 2.1 s or 3.6 s. There is 1 NPU agent, so 1 stream.
- Reasoner: 13.2 s or 14.1 s, including the swap (agents' model unloaded in 115 ms, reasoner loaded in 2.9 s).
- The remaining 3-5 s is fastcheck's 5 s poll granularity.

**NPU agents per AI run in the real app** (state/incidents.jsonl, 537 deduplicated requests): 1 agent 413, 2 agents 66, 3 agents 24, 8 to 14 agents 46. So the single-stream path is what matters.

**Single-agent request** (lab ag2, 24 real app requests, base v9d):
- Prefill 0.23-1.5 s (prefix cache hit; the rest is the 0.4-1.1k-token data tail).
- Decode 84-89 ms per draft step (9 rows: K=8).
- 9-70 steps per request, 552 in total.
- Draft acceptance falls from about 85% on repeated shapes to 8% on the first request after a start (a00: 70 steps, 28 of 352 drafts kept).
- JSON forcer: 0 forced tokens. CPU pick, forcer and emit are under 0.4 ms per step (HANDBOOK 2.62). Not a lever.

**10-agent batch** (earlier windows klong_ab, live_ab2, spec_ab):
- Prefill 6.4 s warm (8.4-10 s cold).
- 33 decode steps at k=2 (30 rows), about 170 ms per step.
- Agents' model back 2.6-2.8 s.
- Outputs are 9-10/10 identical run to run.

**Swap** (lab ag2 q10, board htpd.log):
- Reasoner load: model phase 2.7-3.1 s, context 0.12 s, pieces 4 ms. Repack is 0.64-0.75 s of the model phase (8 threads).
- During the load (cpu_base.log, 100 ms samples), htpd uses about 3.7 CPU-s of user time (multithreaded repack and copies) and 1.8 CPU-s of system time (rpcmem/dma-buf allocation and mapping, page faults).
- MemAvailable falls from 9.2 GB to 4.9 GB.
- Agents' model back: 2.0-2.9 s. This is off the critical path except for back-to-back incidents and chat.
- Page cache: only 50% of the reasoner GGUF is resident at idle. Reading it takes 0.74 s half-cold vs 0.40 s warm (tools/fincore). The 5.2 GB of both GGUFs does not fit in the about 4.7 GB of cache.
  - A readahead during the agents' run would save at most about 0.35 s, and it evicts the agents' file. Not pursued.
- Overlapping the reasoner load with the agents' tail needs both models' buffers at once. That is the two-resident-models setup that rebooted the board (HANDBOOK 2.27/2.37), so it was not done.

## What was tried: htpd_v9e agent drafts (off by default)
These are env-gated changes to the batched verified drafting (run_batch):
- `HTPD_AGENT_NGMAX=8`: n-gram orders 8..1 (v9d uses 3..1).
- `HTPD_AGENT_RECENT_MAX=500`: a hashed index of the last 500 agent outputs (newest wins). It replaces the linear scan of the last 64.
- `HTPD_AGENT_CORPUS=<file>`: the index is seeded at start from past outputs (token ids), and every agent output is appended.

Rows per step are unchanged (k+1 per stream) and every draft is still verified.

- Offline replay of all 537 real requests (sim.py, exact for the current proposer):
  - Steady state, single agent: 18.9 → 14.7 steps.
  - Fresh process: 29.2 → about 14.7 steps.
  - K16 for a single stream gives fewer steps but costs about 19% more per step (HANDBOOK 2.47). No gain, rejected.
- Host (WSL CPU, q2b): default env is byte-identical to v9d, 6/6. The env-on runs are also 6/6, but q2b is hybrid/recurrent, so drafting is off there and those runs only show the env is harmless without drafting.

**Board lab ag2** (lab/ag2/score.md; base v9d, v9e, base2 v9d in one window; the v9e corpus holds only outputs from before the lab requests):

| config | mean wall per request | draft steps | ms/step | outputs vs base |
|---|---|---|---|---|
| base v9d | 2594 ms | 552 | 83.9 | - |
| base2 v9d | 2806 ms | 552 | 89.4 | 24/24 identical |
| **v9e** | **2058 ms (-21% / -27%)** | **366 (-34%)** | 88.4 | **23/24 identical** |

The one difference (a09, 2-agent request INC-0528, CO2 agent):
- One observation's wording changed: "CO2 climbing at +51.1 ppm/h, now 757 ppm [E4,E1]" became "CO2 keeps rising, +51.1 ppm/h with r2 0.49 [E4]".
- pattern, status, likely_cause, confidence, event_active and onset are identical.
- The base output equals the app's original output.
- The cause: different accepted lengths move tokens to other step boundaries, so the HTP rounding differs and a near-tie flips. Base vs itself is 24/24, so this flip is v9e's.

## Decision
The rule for this task was identical agent outputs on the lab set vs current. v9e got 23/24, so **it is not deployed**.

It gives about -0.5 to -0.75 s per single-agent incident (more on the first incidents after an htpd start), with every structured field identical. This is the same class of late-text near-tie flip the owner accepted for deploy18/19. If the owner accepts it: `wsl bash /mnt/c/Users/hp/Desktop/qidk/proofs/2026-10-29_latency/deploy20.sh` (it pulls known_good from the board, then runs chaos 2 + fastcheck x2 with auto-rollback; corpus agent_corpus_all.txt md5 a136e22a…).

Remaining swap levers each need a ggml-hexagon change and carry board risk, so they are for the owner to choose:
- Reuse the rpcmem weight block across swaps: up to about 1.8 CPU-s of system time per load.
- A repacked-weights cache on disk: up to 0.7 s.

## Files
- sim_prep.py, sim.py: replay of the drafting proposer.
- make_lab.py, agl/: the lab set.
- agent_corpus_lab.txt / agent_corpus_all.txt.
- lab_ag.sh, lab_ag_run.sh: the lab window.
- lab/ag1: aborted. The request files lacked a trailing newline; its q10 CPU trace is still valid.
- lab/ag2: the real window.
- score_ag.py.
- host/: host check.
- tools/fincore(.c), tools/tok.cpp.
- v9e/: board binary + source.
- build_v9e.sh.
