# htpd v9 split-spec (speculative drafts inside split decoding): status log

Laptop only (no board, no GPU, no commits). Source: Code/smart-city-edge-agent/app/htpd/htpd.cpp (v8x5 + v9), baseline copy v9work/base_src.

- 10-30 v9 code in htpd.cpp (HTPD_REASON_SPLIT_SPEC / _SPEC_MIN / _CORPUS / _SPEC_ROWS / _SPEC_KVU); host build ok; corpus built (v9/corpus_excl_q10_15.jsonl 458 docs, v9/corpus_all.jsonl 463 docs)
- 10-30 v8x5 binary = build_htpd_wsl.sh (NDK r26d) of the current htpd.cpp from /mnt/c/.../app/htpd (rebuild differs only in embedded paths)
- 10-30 smoke (2B base, q14): 2B base answers in a ```json fence (forcer off, no split): host tests start the answer at "{" (--brace); with it: fork ok, 3 streams, no crash
- 10-30 10:17 host job: start (2B base Q4_0 CPU -t 6; base, v9k0, v9k8, v9k8 kv streams)
- 10-30 15:52 v9 board binary built (build_htpd_wsl.sh, NDK r26d, as v8x5): v9/htpd md5 e82dba5ae822796bf8be82285bdc036b, source copy v9/htpd_v9.cpp; same NEEDED libs as v8x5; HTPD_REASON_SPEC_ALIGN added (host binary htpd_v9b)
- 10-30 10:34 host job: base done
- 10-30 10:50 host job: v9k0 done
- 10-30 11:37 host job: v9k8 done
- 10-30 11:47 host job: v9k8s (kv streams) done
- 10-30 11:47 host job: DONE
- 10-30 11:47 host job2: start (htpd_v9b 829c1200)
- 10-30 11:52 host job2: v9k0b done
- 10-30 12:01 host job2: v9k8n (no drafts) done
- 10-30 12:17 host job2: v9k8a (align) done
- 10-30 12:17 host job2: DONE
