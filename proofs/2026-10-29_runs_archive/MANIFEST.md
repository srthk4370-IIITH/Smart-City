# Archive of removed model files and training runs (2026-10-29, owner: free C:, keep proofs)

Removed files are listed with size and md5. The results they produced stay in proofs/ and HANDBOOK (sections named).

## Code/models_stage (Windows)
| file | size | md5 | why removed | results kept in |
|---|---|---|---|---|
| ft_T30_q4_0.gguf | 2800617952 B | a7ce589cd7d0463ae56b0a1a0ea3e9d4 | rejected agents candidate (gate2 FAIL vs B50: dev +7 CI[-19,+35], sev -13, E1 -4) | HANDBOOK 2.54b; proofs/2026-10-28_master (final/agents_why) |
| rsn_v2_q4_0.gguf | 2611783520 B | b4562c8655cd652d1c15d080a20906fb | rejected reasoner round 2 (RWH 106 same ids: severity 87.6% vs v1 94.7%) | HANDBOOK 2.58, 2.59; proofs/2026-10-28_master/RSN_V2_RETRY.md, v8x3/raw_v2; proofs/2026-10-25_reasoner_final/eval/results/rsn_v2 |

Kept: ft_B50_q4_0.gguf and rsn_v1_q4_0.gguf (the live models; local copies for redeploys), their md5 sidecars, rsn_v1_q4_0_keep.keep_ids.npy.
rsn_v2_q4_0.gguf also remains on the board (/data/local/tmp/gpu/); T30 was never pushed to the board.

## QIDK board /data/local/tmp/gpu (to remove 2026-10-29 ~13:25 IST; partition 100% full, 107 MB free)
Rollback snapshots reference only ft_B50_q4_0.gguf and qwen35_reasoner_q4_0.gguf (kept). Also to remove: their .md5 / .prefix_*.state cache files, and all but the 3 newest reasoner prefix caches (htpd recreates them).

| file | size | md5 | why |
|---|---|---|---|
| ft_mixA50_q4_0.gguf | 2800617952 B | 8397bb0e8a58005cf339999fa6634ad3 | previous live agents (superseded by B50) |
| ft_v21_q4_0.gguf | 2800617952 B | 7fa523c25139af55d104580bd130455f | v2.1 (B50 ingredient; superseded) |
| ft_v2_q4_0.gguf | 2800617920 B | 250f109cf253c7fe582f3676e4f5d5a3 | v2 (superseded) |
| ft_v2t3d_q4_0.gguf | 2800617920 B | e9088e111cf85a036a3119e864ab6305 | top-up candidate (superseded) |
| rsn_v1_q4_0_outq4.gguf | 2969364352 B | 3045148ca786febcc572d630e3dbdcce | Q4_0 lm_head variant (rejected: moved an RWH label) |
| rsn_v2_q4_0.gguf | 2611783520 B | b4562c8655cd652d1c15d080a20906fb | rsn_v2 (rejected, HANDBOOK 2.59) |

Kept on the board: ft_B50_q4_0.gguf, qwen35_reasoner_q4_0.gguf (live), rsn_v1_q4_0_keep.gguf (pruned head, awaiting the owner's decision), genie bundles (documented fallback engine).
