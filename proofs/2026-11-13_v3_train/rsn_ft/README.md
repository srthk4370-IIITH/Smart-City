# rsn v3 fine-tune recipe (edited r3-2800 + v4 data), 2026-11-13 — NOT RUN (data APPROVED 2026-11-13, `--mix 0.75`)

Owner decision 2026-11-13: the reasoner is r3-2800 (Qwen3.5-4B, rsn_v3 r3 LoRA step 2800) with directly edited weights
(think-gating fix, done separately), then a SHORT fine-tune on the v4 data + r3 replay, then the strict gate vs r3-2800.
Nothing here has been started. The owner must approve the data first (`proofs/2026-11-13_v3_data/rsn/APPROVAL.md`).

## Trainer: `rsn_ft_train.py`
A copy of `proofs/2026-11-12_topup_r4/train/topup_train.py` (r4 top-up, CPU-tested, never trained) with these changes only:

| change | why |
|---|---|
| `--base DIR` may be the **edited base** (merged weights + tokenizer); `--model-dir` = its NF4 pre-quant (optional; else NF4 on the fly) | the weight edit produces a new base |
| `--init-adapter` is **optional**. Given: the LoRA is loaded and INIT_CHECKed as in r4. Absent: a fresh LoRA (`--lora-r 32 --lora-alpha 64`, r3 targets) on `--base`; B = 0, so step 0 == the edited model | the edit may be delivered either as "base + r3 adapter" or as a merged model |
| tools per row: `incident_v4`, `chat_r5` (new) and `incident`, `chat` (r3 replay) from one `tools_v4.json` | v4 rows use the new headers; replay rows keep r3's |
| gen slices `--gen-v4-inc` / `--gen-v4-chat` (aliases of the r4 flags); the v4 chat slice is scored with the chat_r5 header | the in-training "new" score is the v4 dev |
| `--r3-ref X`: eligibility needs r3 slices >= X - `--r3-tol` (0.01), X = r3 score of the **unedited r3-2800** on the same slices | owner gate "r3 slices >= r3-2800 - 0.01", not "vs the edited start" |

Everything else is unchanged except the mix (here `--mix 0.75`: 12 new + 4 replay rows per step, so the ~1,900 replay rows are seen about once instead of cycled 3x; with 0.5 the run would be ~40 M tokens, ~14 h); LR 3e-5, warm-up 3 %, cosine to 0.1x, 1 pass over the new rows,
`--oom-stop` (no skipped rows), data check (> 2 % unusable new rows -> exit 9), resumable `schedule.json`, best-K 3, patience 3,
exit codes 0/3/6/7/9/10. Fit flags as r3/r4: `--micro-tokens 7424 --head-cpu --ckpt-offload --mlp-chunk 512 --lean-host
--shared-prefix --oom-stop`, `RSN3_GEN_TOK_BUDGET=8400`, max_len 7424.

## Command (fill BASE / NF4 / START when the edited model exists)
```
~/venvs/rsn/bin/python rsn_ft_train.py --base $BASE [--model-dir $NF4] [--init-adapter $START] \
  --tools  $D/tools_v4.json --new $D/train_new.jsonl --replay $D/replay.jsonl --out ~/smartcity_runs/rsn3_4b_v3ft \
  --gen-v4-inc $D/tests/dev_inc.jsonl --gen-v4-chat $R4/dev_gen_chat.jsonl \
  --gen-inc $R3G/gen_inc_r2.jsonl --gen-chat $R3G/gen_chat_r3.jsonl --gen-r3 auto --r3-ref <r3-2800 r3 score> \
  --lr 3e-5 --warmup 0.03 --floor 0.1 --accum 16 --mix 0.75 --epochs 1 --save-every 25 --eval-every 200 --gen-every 200 \
  --patience 3 --keep-best 3 --w-r4 0.5 --r3-tol 0.01 --gen-r4-n 60 --gen-n 40 --hours 6 \
  --micro-tokens 7424 --head-cpu --ckpt-offload --mlp-chunk 512 --lean-host --shared-prefix --oom-stop
```
`D = proofs/2026-11-13_v3_data/rsn/data/final`, `R4 = proofs/2026-11-12_topup_r4/data/final` (r4 dev chat records; the chat_r5
header is applied by the trainer), `R3G` = the r3 run's gen slices (as `paths_r4.sh`). Run it detached (`proofs/detach.sh` +
keepalive) in 6 h chunks with the r4 controller pattern (`chain_r4.sh` / `topup_chunk.sh` guards: GPU_LOCK, heat 92/88 C,
Windows RAM, disk >= 20 GB on C:, STOP file); copy those scripts with the run dir `rsn3_4b_v3ft` when the owner starts it.
Step-0 scoring of the start model is kept: it records the edited model's v4 and r3 scores.

## Budget (data pack numbers)
New rows 6,133 (incl. the owner's +740) + replay 1,857; `--mix 0.75` -> ~511 steps of 16 rows (12 new + 4 replay), replay ~1.1 passes: ~29.6 M tokens, ~10.3 h at 800 tok/s (+ ~1 h gen-eval). Token totals and the ETA are in
`APPROVAL.md` (measured with the Qwen3.5-4B template).

## Strict gate after training (vs r3-2800; all must hold, else r3-2800 stays)
V3_DESIGN §5.4 "rsn_v4 vs r3-2800" with the 2026-11-13 edits: the 19 checks and r3 test slices within noise
(>= r3-2800 - 0.01 / 1 item), test_inc_r4 / test_chat_r4 not lower, test_fog per state >= r3-2800, P0 G1 safety, plus the
new held-out sets in `data/final/tests/` (test_campus, test_unseen_metric, test_unseen_layout, test_real_agent **cleaned**,
test_taxonomy per type, think_empty_single >= 0.98 / think_ok_multi >= 0.95). Site-tool chat (test_campus_chat) is scored
with the Python twin `gen_chat_v4.SiteTools` as executor (the in-training ToolsR3 executor has no site tools).
Gate scripts: adapt `proofs/2026-11-12_topup_r4/train/post/gate_r4.sh` + `gate_score_r4.py` (not done here).
