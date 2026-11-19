# Upload manifest: rsn_v3_bundle.zip (15,329,659 bytes, md5 d5efe71b8e04adb98539f59ef916bb36)

Built by kaggle/local/make_bundle.sh (allowlist + denylist enforced; nothing from the board: no incidents.jsonl, chats.json or
state files; no real_pool.jsonl; no eval suites RW6/RWH/P0; no model weights). Precedent: round-2 UPLOAD_MANIFEST.md.
- **FLAG (as round 2):** `incidents3_train.jsonl` holds 5644 `real_agent` rows: round-1 generator variants of the 1645 real_pool
  train rows that round 1 already trained on (real domain-agent outputs + real E-lines from SCRC windows). No held-out (RWH) rows.
- **FLAG (as round 2):** the chat tool store (`train_store*.sqlite`) is, or is built from, the round-1 training store (synthetic
  readings; holds the 110 demo-injection app-test incidents that the tools exclude by default; operator names are synthetic).
- Everything else is synthetic or template-generated code/data. Nothing identifies a person.

| path in zip | bytes | md5 | content |
|---|---|---|---|
| BUNDLE_OK_RSN3 | 1,828 | fae0e9e1e11c |  |
| base/SHA256SUMS | 303 | 6b396e6c2dff | hashes of the local Qwen3.5-4B, used to check the HF download |
| proofs/2026-10-25_reasoner_final/tools.json | 8,768 | ea8a3d72e265 | round-1 tool schema read by eval/p0/tools_impl.py at import |
| proofs/2026-10-25_reasoner_final/eval/p0/common.py | 5,653 | 268a29778b87 | script / config (unchanged copy) |
| proofs/2026-10-25_reasoner_final/eval/p0/tools_impl.py | 27,801 | 7dde35bd3112 | script / config (unchanged copy) |
| proofs/2026-10-29_rsn_v3/data/chat3_dev.jsonl | 1,037,931 | 3059c98f8956 | synthetic chat dev (dev-loss slice only; also the gate's chat dev v3 suite, never trained on) |
| proofs/2026-10-29_rsn_v3/data/chat3_manifest.json | 13,145 | b59cef89b0d1 | script / config (unchanged copy) |
| proofs/2026-10-29_rsn_v3/data/chat3_train.jsonl | 28,199,442 | a26ea77116c5 | synthetic chat questions + gold calls/results/reference answers (gen_chat_v3.py, training store) |
| proofs/2026-10-29_rsn_v3/data/train_store_v3.sqlite | 5,636,096 | 599fcda0b8ef | rsn_v3 chat tool store = round-1 training store + synthetic recent readings (make_store_v3.py; see FLAG) |
| proofs/2026-10-29_rsn_v3/data3/incidents3_report.json | 3,204 | 1dfcbd7c21e8 | script / config (unchanged copy) |
| proofs/2026-10-29_rsn_v3/data3/incidents3_train.jsonl | 103,553,058 | 86e94468e5b7 | incident traces: round-1 generator seed 31 (see FLAG for real_agent rows) + 600 synthetic borderline |
| proofs/2026-10-29_rsn_v3/data3/incidents_dev60.jsonl | 300,205 | e16412a09d3a | first 60 round-1 incident dev rows (dev-loss only, never trained on) |
| proofs/2026-10-29_rsn_v3/data3/manifest.json | 1,696 | c14b743d4800 | script / config (unchanged copy) |
| proofs/2026-10-29_rsn_v3/kaggle/build_mix3.py | 4,579 | 06563f24bd71 | script / config (unchanged copy) |
| proofs/2026-10-29_rsn_v3/kaggle/chatloop.py | 12,854 | 9eb008054d66 | script / config (unchanged copy) |
| proofs/2026-10-29_rsn_v3/kaggle/distill.py | 6,062 | b266156b8c94 | script / config (unchanged copy) |
| proofs/2026-10-29_rsn_v3/kaggle/rsn3_kaggle.ipynb | 16,005 | 9ab794ac211b | script / config (unchanged copy) |
| proofs/2026-10-29_rsn_v3/kaggle/rsn3_kaggle.py | 12,551 | 49641dc45985 | script / config (unchanged copy) |
| proofs/2026-10-29_rsn_v3/kaggle/select_distill.py | 6,527 | f4f517c4904b | script / config (unchanged copy) |
| proofs/2026-10-29_rsn_v3/kaggle/train_rsn3.py | 33,797 | 76c2910da326 | script / config (unchanged copy) |
| proofs/2026-10-29_rsn_v3/pipeline/tools_v3_impl.py | 27,015 | ccc2f8186786 | script / config (unchanged copy) |
| proofs/2026-10-29_rsn_v3/pipeline/tools_v4.json | 10,727 | 38a9bafa17fa | script / config (unchanged copy) |
| proofs/2026-10-29_rsn_v3/pipeline/verify_chat.py | 31,987 | a2e2b884eadf | script / config (unchanged copy) |
