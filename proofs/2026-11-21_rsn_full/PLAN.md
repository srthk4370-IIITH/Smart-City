# rsn_full data plan (prep_data.py, rerun when new data lands)

- target seen: 12800 rows = 800 steps x 16 (mix 0.65 new / 0.35 replay -> 8320 new, 4480 replay)
- train_new: 20008 rows (11016 real, 8992 synthetic); mean tokens 3555, max 7364 | replay: 4480 rows (1574 real, 2906 synthetic); mean 3004, max 6779
- composition train_new: ALL real rows (real-agent report rows also as -x2 copies), ALL gen5/new-agent rows ({'gen5_tools': 4984, 'real_rows': 4906, 'gen5_multidomain': 1500, 'gen5_domain': 1200, 'beh_v2': 1384}), filler from pool_train_new (report rows weighted x2 vs chat/tool, equal quota per family)
- replay: ALL real-derived rows (pool_replay real + lineage Non-Synthetic reasoner train files) + stratified rest of pool_replay up to 35 percent of seen (family-equal quotas, leftovers redistributed)
- tag src_real: src_kind real/real_flip, window_src real (agt3_real:syn = synthetic window, not real), block contains 'real', lineage; dedupe: exact messages hash + id (old x2/x3 pool copies dropped)
- excluded: ids and normalised last-user-text hashes of gate_set + all test/dev sets; excluded counts {'excluded_userhash': 18, 'dup_content': 986}
- trim > 6000 tokens of row content (Qwen3.5-4B template; the constant tools-schema prefix, ~4.5k for chat_r5, is not counted, but the trainer max-len 7424 on the full template is enforced): tool results cut only list items not cited by later assistant turns (id or quoted number), + '... (N more items)'; incident prompts drop uncited evidence lines of non-S1 sensors; assistant/tool calls/system untouched. Result {'measured': 34804, 'trimmed': 397}
- audit: check_big.py rc=0 (see data/CHECK.md); dev: 295 rows {'report': 120, 'real_agent': 100, 'chat': 27, 'tool': 50} from existing tests minus gate set (dev.jsonl; dev_inc.jsonl = report+real_agent, dev_chat.jsonl = chat+tool, the two names run_full.sh expects)
- run: GO file needed in /mnt/c/Users/hp/Desktop/qidk/proofs/2026-11-21_rsn_full; epochs 1 (rows seen above). Missing optional inputs now: []
