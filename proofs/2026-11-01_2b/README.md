# deploy26: rsn_v3 2B reasoner on the board (prepared 2026-11-01, laptop only)

The rsn_v3 2B (Qwen3.5-2B fine-tune, Q4_0) replaces rsn_v1 4B in the htpd_v9f reasoner slot. The APK, htpd binary,
NPU libs and agents' model stay the same. Only `htpd_profile` changes.

## Files
- `deploy26_2b.sh`: the deploy script (WSL). Results go to `deploy26/` (STATUS.md, deploy.log, known_good/, lab26_2b/, lab_acc.md, telemetry.log, chat.txt).
- `gguf_check.py`: reads only the GGUF headers and checks that arch, vocab, token table md5 and eos match rsn_v1.

## What is 4B-specific (checked in htpd.cpp, htpdclient.go, reasoner_v3.go, chat.go, the hexagon patch and the GGUF headers)
| Item | 4B value | 2B action |
|---|---|---|
| `reasoner_model=` in htpd_profile | `/data/local/tmp/gpu/qwen35_reasoner_q4_0.gguf` | **change** to `/data/local/tmp/gpu/rsn_v3_2b_q4_0.gguf` (new path; the 4B file is kept). The app writes the path into `state/htpd_args`, so htpd restarts with it. |
| Chat generation prompt | empty think block (rsn_v1 was trained with thinking off) | **add** `chat_think=adaptive` (rsn_v3 was trained with adaptive thinking). The live APK c862b7a1 already reads this key (chat.go, commit 34c7a7f). |
| Draft corpora (`reason_corpus_v2`, `reason_corpus_live`, `chat_corpus`) | token-id arrays from 4B outputs | **compatible**: the token tables are identical (248,320 tokens, md5 9428120f…, eos 248046; checked on the 2B base, and re-checked on the real GGUF before every run). Drafts are verified, so only the acceptance rate can change. The two *live* files move to `*_2b.jsonl` copies, so the 4B corpora stay clean for a rollback. |
| Model shape | 33 blocks, embedding 2560, 4 KV heads | 25 blocks, embedding 2048, 2 KV heads. htpd hard-codes none of these: it takes the context from `--reason-ctx` (default 4096) × streams and reads the dimensions from the GGUF. |
| Reasoner prefix state on disk | `<gguf path>.prefix_<hash>.state` | none needed: the cache is keyed by path, so the 2B builds its own on the first request (expect the first AI update to be about 1-2 s slower). |
| ggml-hexagon / repack | no model-size constants in the patch; tensors are repacked per tensor at load | none (do not modify). The 2B base already ran on the NPU through htpd_v8x5: 37.6 vs 127.8 ms per decode step, load 2.3 vs 4.0 s (`proofs/2026-10-29_latency/q2b/VERDICT.md`). **Never tested yet:** htpd_v9f + lib_rp29 + split-spec. The lab run covers this. |
| `reasoner_split=3`, `HTPD_REASON_SPEC_*` | tuned on the 4B | kept as they are tonight; worth re-tuning later. |
| Model label `"qwen3.5-4b (htpd)"` | hard-coded in reasoner_v3.go:793 and chat.go:132 | **cosmetic, open**: the report badge and fastcheck `final_model` will still say 4B until the APK changes. The script checks htpd.log instead. |
| Pruned lm_head (`rsn_v1_q4_0_keep`) | 4B only, not live | none |

## Modes
```
bash proofs/detach.sh deploy26 /mnt/c/Users/hp/Desktop/qidk/proofs/2026-11-01_2b/deploy26_2b.sh [--check|--force-lab|--skip-lab|--rollback]
```
- `--check`: laptop only, no adb. Checks gate.json, the md5, the tokenizer, and renders the profile diff. Ran OK on the 2B base GGUF (`NEWG=` override).
- `--force-lab`: pushes the model and runs the lab window. The gate does not need to pass, and **nothing is promoted**.
- default: needs `gate/g2b_r1/gate.json` with `"pass": true` (path can be changed with `GATE=`). Push → lab + accuracy guard → promote → app check.
- `--skip-lab`: same as default without the lab window.
- `--rollback`: puts the 4B profile back from `deploy26/known_good`, does a clean restart, then runs chaos 1.

Exit codes: 0 = OK, 1 = failed and rolled back (or the lab guard failed), 2 = refused (gate), 3 = precondition abort.

## Safety (same rules as earlier deploys)
- Waits for other deploy/lab jobs, a board lab_ab.sh and a BOARD_LOCK under 3 h old. Takes BOARD_LOCK `deploy26` and sets night PAUSE. Aborts on DEMO_NOW.
- Stops the app with `pidof` + `kill -TERM` and waits for exit + 30 s. Never uses `pkill -f`. Never reboots.
- Pushes the model only while the app is stopped. It goes as `.part` straight to `/data/local/tmp/gpu`; the md5 is checked on the board before `mv`. Free space is checked first (size + 1.5 GB).
- Pushes the profile as `.part` + `mv` and verifies its md5.
- Rolls back automatically to the 4B profile if any of these fail: htpd not ready, reasoner slot not the 2B, chaos 2, fastcheck ×2, or last reasoner load not the 2B. Chat problems only log a warning (owner rule: fix forward).

## Lab test plan (inside the script, before promotion)
- Uses `lab_ab.sh` (pidof-based, ≤ 55 °C before each request, kills htpd at ≥ 105 °C for 3 samples, app restarted at the end). Config: htpd_v9f with the **live profile env** (lib_rp29, split-spec, corpora), 3 streams, the 2B.
  - The idle release stays at the lab's 600 s, the same as the 4B reference.
  - The live corpus goes to a lab-only file.
- Requests: the RWH bench `rreq_split` q10-q39. q10 is the warm-up, so 30 are scored.
- Reference: rsn_v1 4B sp3 on the same 30 prompts (`raw/acc_v2/sp3_*`, 2026-10-28): parse 30/30, sev = gold 27, label = gold 25, 22.5 s each.
- Pass rule (accuracy first): 2B parses 30/30 **and** sev = gold ≥ 27 **and** label = gold ≥ 25. `LAB_TOL=1` loosens this by one item; the default is 0.
- Also recorded: mean seconds per report, max temperature and minimum MemAvailable (lab `telemetry.log`).
- Window cap: 60 min (`WINDOW_MAX`), then an ABORT and the app comes back.

## What gets recorded
- AI update latency: fastcheck `ai_update_s` ×2, compared with the latest 4B fastcheck (deploy25: 22.1 / 22.3 s).
- From htpd.log: reasoner load and stream times.
- Board sampled every 5 s during the app check: max thermal zone, max NSP zone, minimum MemAvailable, htpd_v9f RSS.

## Estimated time
- Default (with lab): about 45-60 min.
  - Preflight + stop + 1.2 GB push: about 3-4 min.
  - Lab: about 25-35 min (2B ≈ 7-10 s per report, plus cooling to 55 °C).
  - Promote + restart: about 3 min.
  - Chaos 2 + fastcheck ×2 + chat: about 8-10 min.
- `--skip-lab`: about 15 min. `--force-lab`: about 35-40 min.
