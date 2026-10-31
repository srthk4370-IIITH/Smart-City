# 2026-10-31 latency night: htpd_v9d (live draft corpus + corpus with the app's own reports + long drafts)
Test set: 6 held-out real app incidents (corpus/rreq_real q100-q105, built from the board's incidents.jsonl by corpus/make_real.py), warm-up excluded, 8 requests per config.
| config | reasoner mean s | steps | sev+label vs cur | text vs cur |
|---|---|---|---|---|
| cur (deploy18: v9c corpus 463) | 11.83 | 59.2 | - | - |
| + app reports in corpus (576 docs) | 9.98 | 46.8 | 8/8 | 6/8 |
| + live corpus growth | 9.61 (rerun 9.58) | 44.5 | 8/8 | 6/8 |
| + KLONG16 rows 48 | 8.89 | 36.1 | 8/8 | 6/8 vs rl |
| + K12 rows 40 | 9.29 | 39.0 | 8/8 | 6/8 vs rl |
Repeats of the same incident with live growth: q101 8.29 -> 5.52 s (4.58 with KLONG16), q103 8.26 -> 6.17 (5.13).
Text diffs = late-field near-tie flips (monitor_next wording, explanation "second/third time this week", one agent_checks claim); the app's own original reports differ from the lab base on the same fields. Host CPU (2B): live vs off byte-identical 6/6.
Decision: deploy19 = htpd_v9d + reason_corpus_v2 (corpus_real_all) + HTPD_REASON_CORPUS_LIVE=reason_corpus_live.jsonl + KLONG16 ROWS48 (proofs/2026-10-29_latency/deploy19.sh, status deploy19/STATUS.md). Rollback: deploy19/known_good (profile + APK).
Lab raw: lab/live_ab (empty: request files lacked newline), lab/live_ab2, lab/klong_ab (score.md each).
