# v2 latency: what costs time, and cuts that do not change model outputs (2026-10-21, paper study, no device access)

All numbers are from logs already on the laptop: v2 device eval `proofs/2026-10-20_v2_post/device/{test_all,host400,placement_v2}`
(htpd 8 x 1408, DRAFT + PREFIX_CACHE + LEGACY_PREFILL + HMX_PIPE_ALL + FA_STREAMS), the v2 app run
`proofs/2026-10-21_v2_app/refine` and the v1 window study `proofs/2026-10-16_window_study`. Scripts in this folder rerun every number
(WSL `~/venvs/train/bin/python <script>`).

## 1. Where the time goes (v2)

**Batch of 8 agents** (`fit_batches.py` -> `fit_batches.json`; 139 batches, runaways excluded):
- prefill ~= 0.39 s + **1.45 ms x uncached prompt tokens** (~690 tok/s; the system turn is already cached). Median 5.4 s.
- decode ~= **58 ms x max generated tokens in the batch** (the batch waits for its longest stream). Median 5.6 s for 96 tokens.
- Split: 46% prefill / 54% decode at 4 h, 50/50 at 12 h (`profile.json`).
- The replay in `sim_draft.py` puts a batch of 8 at ~35 decode steps, so **one decode step is ~158 ms**. A single stream is ~130-175 ms.
  The weight-bandwidth floor is ~30-40 ms, so most of a step is overhead (see C3).

**Prompt tokens** (`profile.py`, `fit_check.py`; Llama 3.2 tokenizer):
| | 4 h | 8 h | 12 h |
|---|---|---|---|
| v2 median (AQ/water/power) | 686 | 782 | 878 |
| v2 max, any role (HVAC is largest) | 843 | 946 | 1072 |
| v1 (window study) | 597 | 692 | 787 |

- The system turn per role is 262-348 tokens (cached). v1's was 261.
- The `SERIES` line is 104 / 200 / 296 tokens. That is 27% / 39% / 51% of the uncached part.

**Output:**
- Mean 84-87 tokens, p99 108. Valid answers are never above ~120.
- **54% of output tokens are fixed JSON scaffolding** (key names and punctuation).
- Key order is fixed in 99% of outputs: pattern, status, observations, likely_cause, confidence, event_active, onset, [fault_kind].
- Every field is read by the backend (`policy.go`), so stopping earlier than `"action"` is not possible.

**Single-agent incidents in the app** (Mode 3, `refine/*.json`):
- Early alert: agent 3.1-5.3 s (time to first token 0.4-0.7 s), 18-36 tok/s.
- Refinements of the same sensor: 2.3-3.7 s, 45-61 tok/s.
- The gap comes from drafting. A refinement's previous answer sits in htpd's `g_recent`, so its n-gram drafts hit.

**Runaways:**
- 39 of 4738 outputs (0.8%) are garbage, e.g. `"step 0, 0 1-1\n1 1\n1 1..."`. Each runs to 315 tokens (`stop:"ctx"`, the 320 default `--max-new` minus 5).
- A batch with one of them takes **21.3 s of decode instead of 5.6 s**. That is 2.8-4% of batches.
- They come in **runs of consecutive stream ids in the same batch**: Q0008-Q0012 (streams 0-4), Q0146 d4..d24, Q0233 d12..d24.
- This looks like one bad prefill ubatch (split_equal takes runs of consecutive sequences), not a model behaviour.

## 2. Ranked candidates

"Identical" here means identical under greedy decoding. HTP batched float sums are not bit-reproducible: the same binary run twice gives
21-24 of 25 identical texts (HANDBOOK 2.37). Every change below must therefore be judged against that noise floor with the A/B harness
(`proofs/2026-10-16_htpd_ab/ab.py`) plus the 54-window accuracy check.

| # | change | expected saving | output risk | effort |
|---|---|---|---|---|
| 1 | Raise drafting for small batches: `HTPD_DRAFT_K=8` (env only) | 1 agent: 26.4 -> 21.1 steps = **-0.7 s (-20% of decode)**; 4 agents: k 4 -> 7 (not replayed without corpus); 8+ agents: no change (the k cap is 32/streams-1) | none (verified drafts) | env in `htpdclient.go` |
| 2 | Static per-role **draft corpus** (n-grams from trained completions, `train.jsonl` only) as a further verified draft source | 1 agent warm: 26.4 -> 18.3 steps with k=8 = **-1.1 s**; cold (after htpd restart, empty `g_recent`): 58.8 -> 20.1 steps = **-5 s**; 4 agents 31.7 -> 22.9 (-1.2 s); 8 agents 35.4 -> 31.9 (-0.55 s); 10 agents with 44 rows 40.8 -> 32.5 (-1.3 s) | none (verified; a wrong draft costs nothing but a rejected row) | htpd `propose()` + `--draft-corpus` file + small generator script |
| 3 | **Runaway guard**: agent-only new-token cap of 160 (or `--max-new 200` for both, matching the app's documented 200 cap), better a grammar abort (stop a stream whose `pattern` value leaves the enum or that emits a newline outside a string) | runaway batch 21.3 s -> ~9.3 s (cap 160) or ~5.6 s (abort); **mean -0.4 to -0.6 s per batch, p97 -12 to -16 s** | valid outputs unchanged (all are 120 tokens or fewer); garbage becomes shorter garbage, with the same JSON-invalid verdict downstream. Check how `policy.go` handles the stop | 1 arg / ~20 lines in `Scanner` |
| 3b | Find the cause of the consecutive-stream garbage: rerun the exact batches (Q0008-15 d0 n96; Q0146 n48; Q0233 n144) with and without `HTPD_LEGACY_PREFILL`, `--ubatch 256`, and with the board cool | removes the runaway cost entirely | **changes outputs, for the better**: 0.8% garbage becomes valid answers. Flag it as an accuracy fix | investigation |
| 4 | Profile one decode step (`GGML_HEXAGON_PROFILE=1`) and try scheduling-only knobs: `GGML_HEXAGON_OPPOLL=1` (poll instead of interrupt), `OPQUEUE`; request logits only for rows that can be read (pad rows past the draft are never read: `j > drs.size()`) | a step is ~158 ms against a ~30-40 ms bandwidth floor. Each 10 ms saved per step is ~0.35 s per 8-agent batch and ~0.25 s per single agent. Copying logits for 32 rows is 16.4 MB per step | OPPOLL/OPQUEUE: bit-identical math. Logits only for read rows: changes only how many rows lm_head computes; verify 25/25 | env / ~5 lines |
| 5 | **More agents per batch** (one batch instead of 10+3): 13 x 976 cells for 4 h-only batches (largest 4 h prompt 843 + 1 + 5 drafts + ~125 output = 974; 12,688 cells fits the current 12,800-cell KV), keeping 10 x 1280 when any prompt is 8 h or longer. Or continuous batching: admit queued prompts into streams freed mid-decode | 13-agent incident: estimated ~18.8 s -> ~15.4 s (**-3.4 s**); the second batch's ~4.3 s decode disappears; 13 streams draft with k=1 | room per stream shrinks: an output identical unless it would pass ~125 tokens (no valid one does). Batch composition changes: noise floor | htpd context-layout swap (`make_ctx`, measure `swap_ms`) or a slot-admission loop |
| 6 | 64-row draft cap (k=7 at 8 streams), or 44 rows for 10 streams | 8 agents 35.4 -> 29.2 steps (-0.95 s) only if a 64-row step costs about the same as 32; with corpus 24.5 steps (-1.7 s). **Measure the step cost first** (HMX tile is 32 rows) | none (verified) | constant `32` in `run_batch` -> env |
| 7 | Keep each stream's system-turn KV resident between batches (skip `seq_rm` of `[0,P)` and the blob restore when the stream's role repeats) | at most the ~0.39 s prefill intercept per 8-agent batch, likely ~0.1-0.3 s; ~0.05 s for 1 agent | none (same KV bytes); stream-index permutation is at noise floor | htpd `run_batch` prefix-cache block |
| 8 | Thermal: heatsink/fan (eval ran at 80-83 C with cool-down waits; one 31 s batch) | removes throttled outliers | none | hardware |

**Flag only (would change outputs or the system's behaviour; needs retraining or an accuracy re-run):**
- Shorter prompts (biggest prefill lever, since prefill is token-bound at 1.45 ms/token per batch):
  - `SERIES` as integers, deltas, or fewer points;
  - fewer evidence lines;
  - moving the shared lines (NODE/METRIC/LIMITS) into the system turn so the cache covers them.
  - All are prompt changes, so the model was not trained on them: **accuracy risk**.
- Short keys or a dropped `confidence`/`onset`: 54% of output tokens are scaffolding, but drafting already makes most of it cheap (the corpus replay gets 3-4 tokens per step).
  Needs retraining. **Accuracy risk.**
- Forced "jump-forward" scaffold tokens without verification (SGLang compressed-FSM style):
  - Little gain over verified drafting, which costs nothing extra up to 32 rows and already accepts the scaffold.
  - It would alter the 0.8% of outputs that leave the scaffold.
  - Use the grammar only as a *draft source* (already covered by #2).
- Skipping agents whose rule result is "certain": changes which agent outputs exist. A system-behaviour change.
- 8-bit KV (2x slower), ubatch, thread and power knobs: tried 2026-10-16, no gain (HANDBOOK 2.37). The equal-ubatch prefill changed ~30% of outputs.

## 3. Expected outcome (stacking 1+2+3+4-lite)

- **Single-agent incident (most common Mode 3):** agent ~3.8 s median now -> **~2.7 s** warm. A cold start (after an htpd restart) drops from ~8 s to ~3 s. This is below v1's 3.8 s Mode-3 median.
- **8-agent batch (4 h):** 10.4 s -> ~9.3 s, and the runaway tail goes from 21-36 s to ~10 s.
- **13 agents:** est. ~18.8 s (10+3) -> ~14 s with #5 + #2, at or below v1's 14.7 s.
  - The 18.8 s is a model estimate; measure it with the A/B harness: 13 prompts, v2 model.

## 4. How to measure (main session, on device)

1. Pull `/data/local/tmp/smart_city_edge/state/htpd.log` and the backend trace lines `Prefetch(htpd): n agents ... ms (prefill ...)`.
   - Run `python parse_htpd_log.py htpd.log backend.log`.
   - It gives steps per batch, acceptance, ms per step by stream count, and prefix-restore ms. These numbers anchor every estimate above.
2. A/B each change with `proofs/2026-10-16_htpd_ab/ab.py` (board below 55 C before each config).
   - Use 1, 4, 8 and 13 v2 agents; report total, prefill, steps and exact-text identity against the previous config.
   - Accept a change if identity is within the 21-24/25 floor and the 54-window or host400 accuracy is unchanged.
3. Runaway: replay the 3 garbage batches from `placement_v2/prompts.jsonl` (ids above) 3 times each.
4. Store the raw logs and a manifest in `proofs/<date>_v2_latency/` (collect-proofs rule).

## 5. Sources (method background only; no project data was sent online)

- SGLang compressed FSM / multi-token "jump-forward" JSON decoding: https://lmsys.org/blog/2024-02-05-compressed-fsm ; paper https://arxiv.org/html/2312.07104v2
  (RadixAttention prefix sharing is in the same paper).
- Prompt-lookup / n-gram speculative decoding, lossless under greedy up to float precision: https://docs.vllm.ai/usage/speculative_decoding/
- llama.cpp Hexagon backend env knobs (OPPOLL, PROFILE, POWER_MODE, NHVX): `docs/backend/snapdragon/README.md` in the local tree
  `~/gpu_work/llama.cpp` (commit 620d2225); Qualcomm guide https://dragonwingdocs.qualcomm.com/blogs/llamacpp-on-dragonwing

## Files here
- `profile.py` / `profile.json`: prefill/decode split, prompt and output token structure, v1 baseline.
- `fit_batches.py` / `fit_batches.json`: linear fits of prefill and decode per batch.
- `fit_check.py` / `fit_check.json`: prompt max per role and window, output token distribution, ctx fit.
- `sim_draft.py` / `sim_draft.json`: exact replay of htpd's drafting on real outputs, plus the corpus / k / rows variants.
- `parse_htpd_log.py`: device-log parser for the measurements in section 4.
- `v1_sys.py`: v1 system-turn length. `v2_prompt_example_n144.txt`: one 12 h prompt.
