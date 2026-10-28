# Upload manifest: rsn_r2_bundle.zip (125,308,273 bytes, md5 cdb4cd58bea442496c491bf1cfafa438)

The owner skipped the full privacy review (coordinator, 2026-10-28). These facts were noted before it was skipped:
- **FLAG:** `incidents_train.ok.jsonl` includes 1,766 `real_agent` rows. They are real domain-agent outputs paired with real
  E-lines (sensor values) from SCRC windows, built by `real_pool.py`. They are included as planned.
- **FLAG:** `train_store.sqlite` holds 110 real app-test incidents (demo injections; tools exclude them by default). Its
  readings are synthetic. The operator names op_ravi, op_meena, op_arjun and op_sana are synthetic placeholders.
- Everything else is synthetic or generated from templates. Nothing identifies a person. No raw CSV or sensor dumps are included,
  and nothing from eval/ (RW6, RWH, P0) is included.

| path in zip | bytes | content |
|---|---|---|
| adapter/ckpt_step0612/adapter_model.safetensors, adapter_config.json | 129,927,008 / 1,281 | round-1 LoRA (r16, a32) |
| base/SHA256SUMS | 303 | hashes of the local Qwen3.5-4B, used to check the HF download |
| proofs/2026-10-25_reasoner_final/data/incidents_train.ok.jsonl | 41,142,831 | 5,597 verified incident traces (see FLAG) |
| …/data/incidents_border.ok.jsonl | 4,049,237 | 600 synthetic borderline-severity rows |
| …/data/train_store.sqlite | 5,619,712 | training incident store (chat gold executed against it; see FLAG) |
| …/data/replay_prompts.jsonl | 35,248 | 515 template general prompts |
| …/pipeline/*.py, tools_v3.json; train/train_rsn.py, merge_lora.py; SPEC.md | ~0.3 MB | scripts (unchanged copies) |
| proofs/2026-10-23_reasoner_research/P0/host_bench/common.py, tools_impl.py | 33,454 | read-only tool executor used by the chat gold |
| kaggle/kaggle_gen.py, patch_train.py | 4,677 | Kaggle shims (in-process generation; fp16 + GradScaler, Kaggle paths) |
