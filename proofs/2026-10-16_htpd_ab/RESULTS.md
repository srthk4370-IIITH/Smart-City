# htpd A/B, 2026-10-16 (QIDK, 3 incidents x 2 reps, agents only; total = rep 2)
Harness: ab.sh / ab.py (waits for board < 55 C before each config; identity = exact text match vs previous config, 25 outputs).
Run-to-run identity noise floor (same binary twice): 21-24/25.

| config | 4 agents | 8 agents | 13 agents | total | prefill 13 | identical |
|---|---|---|---|---|---|---|
| v1 (first htpd) | 15.3 | 20.0 | 28.1 | 63.4 | 8.6 | - |
| v4 (HMX pipe + legacy prefill + parked + drafting) | 6.2 | 10.2 | 17.5 | 33.9 | 8.7 | 24/25 vs pcA |
| v5 + HTPD_PREFIX_CACHE=1 (pcA) | 5.2 | 8.7 | 15.5 | 29.4 | 6.8 | - |
| v5 + prefix cache (pcB, rerun) | 5.3 | 8.9 | 17.3 | 31.5 | 7.1 | 20/25 vs base |
| v5 + prefix cache | 5.4 | 9.0 | 15.9 | 30.4 | 7.9 | - |
| v6 (NEON argmax) + prefix cache | 4.8 | 8.2 | 14.7 | 27.7 | 7.2 | 25/25 vs v5 |
| v5 + prefix cache (after v6) | 5.5 | 8.9 | 15.9 | 30.2 | 7.1 | 25/25 vs v6 |

Accuracy, 54 device windows (eval_htpd.py, ../2026-10-16_htpd_accuracy):
v1: pattern 85.2, status 88.9, cause 83.3, JSON 96.3, policy 94.4, wall 136 s
v5 + prefix cache: pattern 90.7, status 94.4, cause 87.0, JSON 100, policy 100, wall 78.6 s
(Genie reference: pattern 85.2, status 87.0, cause 81.5, JSON 100, policy 100)

App stress (stress_app.py --only scenarios,chaos), v5 + prefix cache: 129/135; chaos 12 agents 21.2 s,
10 agents 20.9 s, 11 staggered 20.6 s; Mode 3 median 4.9 s. Failures: 4x stale genied-alive check (fixed
to accept htpd), 2x thermal (95 C peak, guard tripped once).

App stress, v6 (final, ../2026-10-16_htpd_v6_app_stress_report_final.json): 132/135; chaos 12 agents 20.7 s,
10 agents 20.6 s, 11 staggered 20.8 s; Mode 3 median 3.8 s. Failures: thermal only (96 C peak, guard tripped twice).
