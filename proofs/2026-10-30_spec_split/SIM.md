# Speculative drafting in split-3 reasoner decode: offline simulation (2026-10-30)

This is an offline, CPU-only simulation on the laptop. It used no board, no GPU and no network. It measures how many
decode steps the live reasoner (rsn_v1 = Qwen3.5-4B Q4_0, htpd split-3) would need if each stream also fed up to K
draft tokens per step, verified greedily. It does not measure any real latency. Projected times come from the per-row
board cost table given in the task.

## Data used
- **Evaluated reports:** the board answers to requests q10-q15 (`2026-10-27_reasoner_fast/bench/rreq_split/q1*.json`).
  The files are `2026-10-29_latency/rp29_ab/{base,base0,rb29,rp29}_q1*.json` and `q2b_ab/4b_q1*.json`, 35 files in all. They contain
  **18 unique (request, text) reports**, and every table below is a mean over those 18. The 2B files (`2b_*`) are a different model and
  are not used.
- **Prompts:** the `prompt` field of the request, tokenized with specials parsed. This is the history for prompt lookup.
- **Tokenizer:** `~/models/qwen3.5-4b/tokenizer.json` in WSL, through the `tokenizers` package in `~/venvs/rsn`.
- **Corpus of past reports by the same model.** 487 unique texts are tokenized as htpd would emit them (see Method).
  - `gen_rsn_v1` (320): rsn_v1, the same GGUF, run on laptop CUDA over train-split incidents
    (`2026-10-28_master/rag_seed/gen_rsn_v1.jsonl`).
  - `v1_106_rwh` (105): the `eval/results/v1_106/rwh.jsonl` host eval of the 106 RWH incidents. It is
    presumed to be rsn_v1 from its directory name, which I did not verify.
  - `board_live` (38): live board incidents whose `final.raw` is a v3 report from qwen3.5-4b (htpd)
    (`board_incidents_b50.jsonl` and `board_incidents.jsonl`, deduplicated).
  - `board_ab` (24): the A/B outputs. All of them are q10-q15, so the exclusion rule below removes all of them for every
    evaluated report. In practice they contribute nothing.
- **Leakage rule:** for each evaluated report, every corpus document with the same incident id (`rwh-000NN`) is
  excluded. That covers the same RWH incident in `v1_106_rwh` and every board A/B output of the same request.
  The sensitivity runs further restrict the corpus to disjoint sources (see Results).

## Method
1. **Reconstruction (`recon.py`, `validate.py`).** `recon.py` is a byte-level Python port of htpd's `Forcer`
   (`reason_logic.h`) and of the split `handle()` rule (`htpd.cpp`). After each model pick, the forcer's
   deterministic continuation (key names, `", "`, `": "`, brackets, unique enum rests) is tokenized, and all of it
   except the last token is injected as forced tokens. If it ends the answer, all of it is injected; the cap is 64.
   The model's own pick is taken as the first BPE token of the remaining answer text.
   - The answer is split at `, "observations"`, `, "agent_checks"` and `, "checklist"`. Each stream (head + group,
     ending at its sentinel key) is replayed with its sub-schema.
   - The fork pick is the pick after which the forced text names the group's first key, as in htpd.
   - **Validation:** for all 28 reports that have an htpd log, the reconstruction matches the log **exactly**: split point, per-stream
     tokens, per-stream forced tokens, total decode steps and mean rows per step (`validate.json`, `check_board_vs_proj.json`).
     The pick/forced split is therefore exact in count. The individual pick token ids are an approximation, because they are
     BPE of the final text.
2. **Steps and rows.** The baseline uses no drafts.
   - Head: one stream. Step rows = pending + forced tokens.
   - After the fork: one step feeds every active stream's pending + forced rows. Total steps = head steps + the
     longest continuation stream.
   - Cost per step comes from the table (1:66, 2:82, 3:113, 4:133, 6:106, 8:109, 16:120, 64:171 ms), linear in between.
3. **Drafting (`sim.py`).** Each step, each active stream adds up to K draft tokens after its certain rows.
   - Verification follows htpd's v8s loop. A draft token is kept while it equals the true next token. Forced tokens
     after an accepted pick are matched against the following draft tokens. The pick at the first unmatched position is
     still obtained (the bonus pick), unless that position is a forced token.
   - Head drafts are capped at the fork pick.
   - **P:** htpd `ngram_draft`. It finds the most recent earlier occurrence, in prompt + generated history, of the longest
     history suffix of n = 4..1 tokens, and copies up to K following tokens.
   - **C:** SuffixDecoding-style. It finds the longest suffix (up to 32 tokens) of the stream's generated history that occurs in the corpus,
     then walks a frequency-weighted continuation over all occurrences that share that longest match.
   - **PC:** whichever of P and C has the longer match. For this comparison only, P's match is extended backwards to 32
     tokens; ties go to P.
   - **Gate m:** a source drafts only if its match length is at least m. m = 1 means no gate; m = 2 is htpd's default n-min for P.
   - **Partial rejection:** a stream-step whose draft was not fully kept, where the stream continues. A real implementation would
     need a recurrent-state restore for each one. I count these both per drafted stream-step and as
     "global steps with at least one stream needing a restore".

## Results
Baseline means: **183.3 steps, 15.97 s projected decode, 2.53 rows/step**. The all-tokens-sampled upper bound is 248 steps,
but it is not needed because the classification is exact.

Selected rows are below. The full 49-config table is `tables.md`. "partial" is the share of drafted stream-steps that end
with a partial rejection. "restore steps" is the share of global steps where at least one stream needs a restore.

| config | steps | decode s (table) | rows/step | max rows | accept (kept/drafted) | steps vs base | decode vs base | partial | restore steps |
|---|---|---|---|---|---|---|---|---|---|
| none | 183.3 | 15.97 | 2.53 | 14 | - | - | - | - | - |
| P K2 m3 | 149.7 | 14.06 | 3.56 | 15 | 49.8% | -18.3% | -11.9% | 61.7% | 24.5% |
| P K4 m3 | 145.4 | 13.30 | 4.18 | 20 | 35.2% | -20.8% | -16.9% | 79.7% | 28.2% |
| P K6 m3 | 144.4 | 13.18 | 4.79 | 27 | 26.6% | -21.3% | -17.6% | 87.5% | 28.7% |
| P K8 m1 | 121.8 | 13.69 | 13.90 | 38 | 9.9% | -33.5% | -14.0% | 96.0% | 85.6% |
| C K2 m3 | 91.3 | 10.07 | 6.06 | 22 | 71.2% | -50.5% | -37.0% | 35.8% | 46.8% |
| C K4 m3 | 73.0 | 8.28 | 8.94 | 26 | 59.8% | -60.7% | -48.6% | 51.4% | 59.5% |
| C K8 m2 | 57.9 | 6.81 | 15.71 | 38 | 41.3% | -68.9% | -58.1% | 71.9% | 77.9% |
| PC K2 m3 | 88.2 | 9.72 | 6.19 | 20 | 73.5% | -52.2% | -39.4% | 33.8% | 45.7% |
| PC K4 m3 | 69.6 | 7.86 | 9.21 | 26 | 62.0% | -62.6% | -51.4% | 50.6% | 58.9% |
| PC K6 m2 | 59.7 | 6.82 | 12.86 | 32 | 50.4% | -68.0% | -58.0% | 63.9% | 72.6% |
| **PC K8 m2** (lowest projected decode) | **55.4** | **6.51** | 15.97 | 38 | **43.1%** | **-70.4%** | **-60.1%** | **71.2%** | **77.8%** |
| PC K8 m1 (fewest steps) | 54.7 | 6.55 | 16.61 | 38 | 41.5% | -70.8% | -59.9% | 72.3% | 82.5% |

**Corpus sensitivity** (mean over the same 18 reports; `tables_<tag>.md`):

| corpus | best config | steps | decode s | vs base | accept | partial |
|---|---|---|---|---|---|---|
| all (487, same-incident excluded) | PC K8 m2 | 55.4 | 6.51 | -60.1% | 43.1% | 71.2% |
| gen_rsn_v1 only (320 train-split incidents, disjoint) | PC K8 m3 | 63.6 | 6.97 | -56.8% | 43.5% | 72.1% |
| gen_rsn_v1 + board_live (no RWH docs) | PC K8 m3 | 63.3 | 6.93 | -57.1% | 43.7% | 72.1% |
| board_live only (38 live reports) | PC K8 m3 | 101.4 | 9.78 | -39.4% | 32.7% | 84.1% |

**Cost calibration.** On the 28 logged reports, the board's measured in-loop decode time is 1.53x the table projection.
That comes to 24.4 s against 16.0 s for the baseline, while the steps and rows/step match exactly. The table therefore misses about 46 ms per step in this loop.
If that is treated as a fixed per-step overhead (table + 45.7 ms/step), the projections become:

| config | projected decode s (additive calibration) | vs base |
|---|---|---|
| none | 24.34 | - |
| P K6 m3 | 19.77 | -18.8% |
| PC K8 m2 | 9.04 | -62.8% |
| PC K8 m2, gen_rsn_v1-only corpus | 9.78 | -59.8% |
| PC K8 m2, board_live-only corpus | 14.45 | -40.6% |

The per-report numbers are in `tables.md`. The best config cuts every report: for example, q10 goes from 201 to 70 steps and q14 from 137 to 34.

## Best config
**PC, K=8, m=2:**
- Steps: 183.3 → 55.4 (-70%).
- Projected decode: 15.97 → 6.51 s (-60%) with the table, or 24.3 → 9.0 s with the additive calibration.
- Acceptance: 43.1% (311 of 722 drafted tokens kept per report).
- Partial rejection: 71% of drafted stream-steps end with one, and 78% of global steps would need at least one recurrent-state restore.

A lower-restore alternative is **PC K4 m3**: -51% decode (table), 62% acceptance and 51% partial rejection. Prompt lookup alone (P)
gives at most about -18%. Nearly all of the gain comes from the corpus.

## Caveats
- **Restores are not costed.** Qwen3.5 has recurrent layers. Every partial rejection needs a state restore, for example htpd v8s's n_rs_seq
  snapshots, which take K snapshots per stream. That happens on 71-78% of steps in the best config. Its time and memory cost on the board is
  unknown and is not in the projection. Smaller K reduces it: K2 is about 34-36% partial.
- **Verification logits are assumed free.** Every draft row needs logits, and the lm_head (248k vocab) then runs on up to 38 rows per step. Whether the
  pp cost table includes that is not known. Rows above 16 are interpolated between the 16- and 64-row points.
- **Pick tokens are approximated.** Pick token ids are BPE of the final text. Counts are exact, but the exact token ids the board emitted are not
  available. If the model's picks are not canonical BPE, acceptance would be lower.
- **The corpus is close to the eval set.** It is dominated by reports on synthetic incidents from the same generator families as the RWH requests. The disjoint
  train-split corpus gives about the same saving. The 38 live board reports alone give -39%, which is a better guide to real
  sensor incidents, but rests on a small corpus.
- **Some corpus docs were not replayed.** 74 of the 487 corpus docs (56 gen_rsn_v1, 18 v1_106) do not fit the forced layout. They are tokenized by plain BPE instead
  of the htpd replay, which slightly lowers C's matches.
- **Only 6 requests.** The evaluation covers six prompts: 18 unique outputs from 35 board files, with repeated runs of the same prompt. Mean values are
  dominated by q10 and q13, which have 5 and 6 variants.
- **The board's real decode time is about 1.5x the table.** Absolute seconds should be read relative to the baseline, and both calibrations are shown.

## Files
- `recon.py`: Forcer port and replay. `data.py`: data loading. `validate.py` → `validate.json`.
- `sim.py` → `sim_results.json`. Corpus variants are run by `run_variants.sh` → `sim_results_{genonly,boardonly,norwh}.json`.
- `analyze.py` → `tables*.md`, `summary*.json`. `checks.py` → `check_board_vs_proj.json`. `calib.py` → `calib.md`, `calib.json`.
- `corpus_tokens.json`: the corpus token ids, including board reports. It is private and stays on the laptop.
