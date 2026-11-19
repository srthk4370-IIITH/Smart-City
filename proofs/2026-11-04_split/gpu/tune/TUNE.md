# GPU chat flag sweep (03:24 IST)
| config | cold s | warm s (Q1..Q4) | re-prefill tok | gen t/s | same text as A |
|---|---|---|---|---|---|
| A | 13.0 | 6.8 7.1 10.1 4.0 | 520 516 520 514 | 8.0 8.0 7.9 8.0 8.3 | YYYYY |
| B_cms0 | 13.1 | 6.9 7.1 10.3 4.1 | 520 516 520 514 | 8.0 7.8 7.8 7.9 7.9 | YYYYY |
| C_cms0_ub128 | 14.7 | 5.6 6.0 9.2 3.0 | 136 132 136 130 | 8.0 8.0 7.9 7.9 7.9 | YYYYY |
| D_t4 | 12.5 | 6.2 6.4 9.2 3.8 | 520 516 520 514 | 9.1 9.0 9.1 9.1 8.9 | YYYYY |
| E_mtp | 15.5 | 7.6 8.2 11.9 4.8 | 520 516 520 514 | 6.4 7.3 6.8 6.8 6.6 | YYYYY |
| F_ngram | 13.2 | 6.8 7.1 10.2 4.1 | 520 516 520 514 | 7.8 7.9 7.9 7.9 7.9 | YYYYY |
- chat_gpu restarted (stage-1 flags)

# round 2 (03:31 IST)
| config | cold s | warm s (Q1..Q4) | re-prefill tok | gen t/s | same text as A |
|---|---|---|---|---|---|
| G_t4_ub128 | 14.3 | 5.1 5.3 8.1 2.7 | 136 132 136 130 | 9.0 9.1 9.1 9.0 8.8 | YYYYY |
| H_t6_ub128 | 13.8 | 4.7 5.0 7.6 2.5 | 136 132 136 130 | 10.1 10.0 9.7 9.7 10.1 | YYYYY |
| I_t4_ub64 | 17.7 | 4.9 5.2 7.9 2.5 | 72 68 72 66 | 9.1 9.1 9.0 9.0 9.1 | YYYYY |
- chat_gpu restarted (stage-1 flags)

# round 3, CPU only (04:02 IST)
| config | cold s | warm s (Q1..Q4) | re-prefill tok | gen t/s | same text as A |
|---|---|---|---|---|---|
| J_cpu_t6 | 18.0 | 2.5 2.7 3.7 1.7 | 136 132 136 130 | 26.1 25.6 25.1 25.0 25.4 | YYYYY |
| K_cpu_t8 | 22.6 | 4.5 4.1 5.4 2.8 | 136 132 136 130 | 20.3 11.6 14.2 17.1 14.4 | YYYYY |
- chat_gpu restarted (stage-1 flags)

# round 4, CPU threads (04:04 IST)
| config | cold s | warm s (Q1..Q4) | re-prefill tok | gen t/s | same text as A |
|---|---|---|---|---|---|
| L_cpu_t4 | 21.7 | 2.7 2.9 3.9 1.9 | 136 132 136 130 | 24.9 24.5 24.1 23.8 23.9 | YYYYY |
| M_cpu_t5 | 20.3 | 2.6 2.8 3.8 1.9 | 136 132 136 130 | 25.5 25.5 25.0 24.6 25.0 | YYYYY |
- chat_gpu restarted (stage-1 flags)

# round 5, CPU decode + GPU prefill (op offload), CPU -ub 256 (04:54 IST)
| config | cold s | warm s (Q1..Q4) | re-prefill tok | gen t/s | same text as A |
|---|---|---|---|---|---|
| N_cpu_gpuprefill | 27.4 | 2.9 3.0 4.1 2.0 | 136 132 136 130 | 23.9 23.7 23.7 23.3 23.6 | YYYYY |
| O_cpu_ub256 | 20.1 | 3.7 3.9 4.9 2.9 | 264 260 264 258 | 24.7 24.8 24.1 23.9 24.3 | YYYYY |
| P_cpu_gpuprefill_ub512 | 20.0 | 5.6 5.8 6.8 4.9 | 520 516 520 514 | 25.3 24.7 24.7 24.3 24.8 | YYYYY |
- chat_gpu restarted (stage-1 flags)

# round 6, CPU batch threads for prefill (05:19 IST)
| config | cold s | warm s (Q1..Q4) | re-prefill tok | gen t/s | same text as A |
|---|---|---|---|---|---|
| Q_cpu_t5_tb8 | 20.6 | 2.6 2.8 3.7 1.9 | 136 132 136 130 | 26.6 26.6 26.3 26.1 26.0 | YYYYY |
| R_cpu_t5_tb7 | 23.0 | 2.8 2.9 3.8 1.8 | 136 132 136 130 | 25.7 25.6 25.7 25.3 25.3 | YYYYY |
- chat_gpu restarted (stage-1 flags)
- round 6: -tb 7/8 give no prefill gain (cold 20.6-23 s vs 20.3 s); tuning closed, deployed: CPU -t 5 -tb 5 -cms 0 -ub 128.
