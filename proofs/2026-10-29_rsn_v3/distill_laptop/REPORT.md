# Per-kind distillation report

## train: 8000 records, 1429 sampled, 8549 rows {'reference': 6593, 'distill': 1321, 'template': 630, 'distill_long': 5}
sample pass 0.280, question pass 0.544, long kept 5 / dropped 18, fallback 7223, unsampled 6571; hard think tokens kept {'n': 1254, 'zero': 0, 'p50': 56, 'max': 282}

| kind | hard | records | samples | pass | sample pass | question pass | kept | long_kept | fallback |
|---|---|---|---|---|---|---|---|---|---|
| actions | 0 | 121 | 8 | 3 | 0.375 | 0.500 | 2 | 0 | 120 |
| actuation | 0 | 45 | 8 | 7 | 0.875 | 1.000 | 4 | 0 | 43 |
| compare_buildings | 1 | 177 | 223 | 90 | 0.404 | 0.725 | 86 | 0 | 127 |
| compare_days | 1 | 192 | 230 | 84 | 0.365 | 0.725 | 86 | 2 | 142 |
| compare_levels | 1 | 200 | 219 | 102 | 0.466 | 0.841 | 100 | 0 | 142 |
| compare_periods | 1 | 181 | 203 | 114 | 0.562 | 0.843 | 110 | 0 | 122 |
| count_metric | 0 | 228 | 8 | 4 | 0.500 | 0.500 | 2 | 0 | 227 |
| count_sev | 0 | 212 | 4 | 1 | 0.250 | 1.000 | 1 | 0 | 211 |
| detail | 0 | 99 | 4 | 4 | 1.000 | 1.000 | 2 | 0 | 98 |
| explain_incident | 1 | 144 | 266 | 35 | 0.132 | 0.329 | 35 | 0 | 121 |
| explain_latest | 1 | 157 | 280 | 3 | 0.011 | 0.043 | 3 | 0 | 154 |
| faults | 0 | 91 | 8 | 0 | 0.000 | 0.000 | 0 | 0 | 91 |
| faulty_explain | 1 | 61 | 243 | 5 | 0.021 | 0.082 | 6 | 1 | 56 |
| faulty_list | 0 | 103 | 8 | 0 | 0.000 | 0.000 | 0 | 0 | 103 |
| find | 0 | 161 | 8 | 2 | 0.250 | 0.500 | 2 | 0 | 160 |
| fog_knowledge | 0 | 36 | 8 | 3 | 0.375 | 0.500 | 2 | 0 | 35 |
| followup_detail | 1 | 218 | 267 | 38 | 0.142 | 0.371 | 38 | 0 | 192 |
| followup_metric | 1 | 180 | 177 | 128 | 0.723 | 0.957 | 127 | 0 | 114 |
| followup_nocall | 1 | 155 | 235 | 99 | 0.421 | 0.843 | 99 | 0 | 96 |
| followup_period | 1 | 217 | 200 | 136 | 0.680 | 0.900 | 115 | 0 | 154 |
| followup_place | 1 | 216 | 164 | 133 | 0.811 | 0.957 | 132 | 0 | 149 |
| followup_whatif | 1 | 198 | 240 | 80 | 0.333 | 0.754 | 81 | 1 | 146 |
| followup_worst | 1 | 154 | 267 | 57 | 0.213 | 0.571 | 57 | 0 | 114 |
| group | 0 | 190 | 4 | 4 | 1.000 | 1.000 | 2 | 0 | 189 |
| health | 0 | 51 | 8 | 2 | 0.250 | 1.000 | 2 | 0 | 49 |
| history | 0 | 190 | 4 | 2 | 0.500 | 1.000 | 2 | 0 | 189 |
| history_old | 0 | 96 | 8 | 3 | 0.375 | 1.000 | 3 | 0 | 94 |
| injected | 0 | 92 | 8 | 4 | 0.500 | 0.500 | 2 | 0 | 91 |
| levels_domain | 0 | 124 | 4 | 0 | 0.000 | 0.000 | 0 | 0 | 124 |
| levels_metric | 0 | 220 | 8 | 6 | 0.750 | 1.000 | 4 | 0 | 218 |
| levels_place | 0 | 259 | 8 | 3 | 0.375 | 0.500 | 2 | 0 | 258 |
| limits | 0 | 126 | 8 | 4 | 0.500 | 0.500 | 2 | 0 | 125 |
| multistep | 1 | 87 | 250 | 28 | 0.112 | 0.203 | 28 | 0 | 73 |
| offline_docs | 0 | 28 | 8 | 7 | 0.875 | 1.000 | 4 | 0 | 26 |
| offtopic | 0 | 41 | 8 | 8 | 1.000 | 1.000 | 4 | 0 | 39 |
| old_data | 0 | 41 | 8 | 3 | 0.375 | 0.500 | 2 | 0 | 40 |
| open_all | 0 | 74 | 8 | 0 | 0.000 | 0.000 | 0 | 0 | 74 |
| open_domain | 0 | 121 | 8 | 8 | 1.000 | 1.000 | 4 | 0 | 119 |
| overview | 1 | 55 | 217 | 23 | 0.106 | 0.309 | 23 | 0 | 38 |
| rank_clean | 0 | 123 | 8 | 7 | 0.875 | 1.000 | 4 | 0 | 121 |
| rank_highest | 0 | 399 | 8 | 8 | 1.000 | 1.000 | 4 | 0 | 397 |
| rank_lowest | 0 | 199 | 8 | 5 | 0.625 | 1.000 | 4 | 0 | 197 |
| rank_place | 0 | 203 | 8 | 7 | 0.875 | 1.000 | 4 | 0 | 201 |
| rank_spike | 0 | 201 | 8 | 5 | 0.625 | 1.000 | 4 | 0 | 199 |
| recent | 0 | 71 | 8 | 0 | 0.000 | 0.000 | 0 | 0 | 71 |
| recent_filtered | 0 | 174 | 8 | 0 | 0.000 | 0.000 | 0 | 0 | 174 |
| recommend | 1 | 154 | 280 | 6 | 0.021 | 0.071 | 6 | 0 | 149 |
| refuse_close | 0 | 91 | 4 | 4 | 1.000 | 1.000 | 2 | 0 | 90 |
| refuse_personal | 0 | 45 | 8 | 1 | 0.125 | 0.500 | 1 | 0 | 44 |
| trend | 0 | 234 | 4 | 0 | 0.000 | 0.000 | 0 | 0 | 234 |
| unanswerable | 0 | 118 | 8 | 1 | 0.125 | 0.500 | 1 | 0 | 117 |
| whatif_ac | 1 | 176 | 267 | 39 | 0.146 | 0.406 | 39 | 0 | 148 |
| whatif_occ | 1 | 273 | 264 | 34 | 0.129 | 0.362 | 35 | 1 | 248 |
| whatif_temp | 1 | 198 | 255 | 48 | 0.188 | 0.400 | 48 | 0 | 170 |

fail reasons: {'think_too_long': 2904, 'missing_fact': 2804, 'missing_call': 2134, 'invented_num': 771, 'extra_calls': 612, 'unit_mismatch': 475, 'status:too_many_calls': 203, 'unexpected_call': 103, 'too_long': 84, 'invented_id': 29, 'actuation_claim': 25, 'invented_time': 15, 'no_refusal': 6, 'final_markup': 3}

## dev: 300 records, 300 sampled, 431 rows {'distill': 313, 'reference': 71, 'template': 47}
sample pass 0.389, question pass 0.607, long kept 0 / dropped 22, fallback 118, unsampled 0; hard think tokens kept {'n': 82, 'zero': 0, 'p50': 55, 'max': 79}

| kind | hard | records | samples | pass | sample pass | question pass | kept | long_kept | fallback |
|---|---|---|---|---|---|---|---|---|---|
| actions | 0 | 6 | 24 | 6 | 0.250 | 0.833 | 6 | 0 | 1 |
| actuation | 0 | 6 | 24 | 24 | 1.000 | 1.000 | 12 | 0 | 0 |
| compare_buildings | 1 | 5 | 14 | 6 | 0.429 | 0.600 | 6 | 0 | 2 |
| compare_days | 1 | 5 | 20 | 2 | 0.100 | 0.400 | 2 | 0 | 3 |
| compare_levels | 1 | 5 | 18 | 8 | 0.444 | 1.000 | 8 | 0 | 0 |
| compare_periods | 1 | 5 | 18 | 4 | 0.222 | 0.600 | 4 | 0 | 2 |
| count_metric | 0 | 6 | 24 | 18 | 0.750 | 1.000 | 11 | 0 | 0 |
| count_sev | 0 | 6 | 24 | 21 | 0.875 | 1.000 | 12 | 0 | 0 |
| detail | 0 | 6 | 24 | 24 | 1.000 | 1.000 | 12 | 0 | 0 |
| explain_incident | 1 | 5 | 18 | 2 | 0.111 | 0.200 | 2 | 0 | 4 |
| explain_latest | 1 | 5 | 20 | 0 | 0.000 | 0.000 | 0 | 0 | 5 |
| faults | 0 | 6 | 24 | 3 | 0.125 | 0.167 | 2 | 0 | 5 |
| faulty_explain | 1 | 6 | 24 | 2 | 0.083 | 0.333 | 2 | 0 | 4 |
| faulty_list | 0 | 6 | 24 | 1 | 0.042 | 0.167 | 1 | 0 | 5 |
| find | 0 | 6 | 24 | 10 | 0.417 | 0.500 | 6 | 0 | 3 |
| fog_knowledge | 0 | 5 | 20 | 11 | 0.550 | 0.600 | 6 | 0 | 2 |
| followup_detail | 1 | 5 | 19 | 3 | 0.158 | 0.400 | 3 | 0 | 3 |
| followup_metric | 1 | 5 | 20 | 12 | 0.600 | 1.000 | 8 | 0 | 0 |
| followup_nocall | 1 | 5 | 18 | 7 | 0.389 | 1.000 | 7 | 0 | 0 |
| followup_period | 1 | 5 | 20 | 4 | 0.200 | 0.800 | 4 | 0 | 1 |
| followup_place | 1 | 5 | 19 | 12 | 0.632 | 1.000 | 9 | 0 | 0 |
| followup_whatif | 1 | 5 | 17 | 4 | 0.235 | 0.400 | 4 | 0 | 3 |
| followup_worst | 1 | 5 | 20 | 2 | 0.100 | 0.400 | 2 | 0 | 3 |
| group | 0 | 6 | 24 | 15 | 0.625 | 0.833 | 10 | 0 | 1 |
| health | 0 | 6 | 24 | 1 | 0.042 | 0.167 | 1 | 0 | 5 |
| history | 0 | 6 | 24 | 19 | 0.792 | 1.000 | 12 | 0 | 0 |
| history_old | 0 | 5 | 20 | 1 | 0.050 | 0.200 | 1 | 0 | 4 |
| injected | 0 | 6 | 24 | 0 | 0.000 | 0.000 | 0 | 0 | 6 |
| levels_domain | 0 | 6 | 24 | 10 | 0.417 | 0.667 | 7 | 0 | 2 |
| levels_metric | 0 | 6 | 24 | 13 | 0.542 | 0.833 | 9 | 0 | 1 |
| levels_place | 0 | 6 | 24 | 14 | 0.583 | 0.833 | 10 | 0 | 1 |
| limits | 0 | 6 | 24 | 15 | 0.625 | 0.833 | 9 | 0 | 1 |
| multistep | 1 | 6 | 20 | 6 | 0.300 | 0.500 | 6 | 0 | 3 |
| offline_docs | 0 | 6 | 24 | 12 | 0.500 | 0.500 | 6 | 0 | 3 |
| offtopic | 0 | 6 | 24 | 15 | 0.625 | 0.833 | 9 | 0 | 1 |
| old_data | 0 | 6 | 24 | 3 | 0.125 | 0.333 | 3 | 0 | 4 |
| open_all | 0 | 6 | 24 | 0 | 0.000 | 0.000 | 0 | 0 | 6 |
| open_domain | 0 | 6 | 24 | 21 | 0.875 | 1.000 | 12 | 0 | 0 |
| overview | 1 | 5 | 20 | 1 | 0.050 | 0.200 | 1 | 0 | 4 |
| rank_clean | 0 | 6 | 24 | 13 | 0.542 | 0.833 | 10 | 0 | 1 |
| rank_highest | 0 | 6 | 24 | 13 | 0.542 | 0.667 | 8 | 0 | 2 |
| rank_lowest | 0 | 6 | 24 | 8 | 0.333 | 0.667 | 7 | 0 | 2 |
| rank_place | 0 | 6 | 24 | 15 | 0.625 | 1.000 | 10 | 0 | 0 |
| rank_spike | 0 | 6 | 24 | 11 | 0.458 | 0.833 | 8 | 0 | 1 |
| recent | 0 | 6 | 24 | 8 | 0.333 | 0.833 | 7 | 0 | 1 |
| recent_filtered | 0 | 6 | 24 | 1 | 0.042 | 0.167 | 1 | 0 | 5 |
| recommend | 1 | 5 | 18 | 3 | 0.167 | 0.400 | 3 | 0 | 3 |
| refuse_close | 0 | 5 | 20 | 17 | 0.850 | 1.000 | 10 | 0 | 0 |
| refuse_personal | 0 | 5 | 20 | 20 | 1.000 | 1.000 | 10 | 0 | 0 |
| trend | 0 | 5 | 20 | 0 | 0.000 | 0.000 | 0 | 0 | 5 |
| unanswerable | 0 | 5 | 20 | 4 | 0.200 | 0.400 | 3 | 0 | 3 |
| whatif_ac | 1 | 5 | 20 | 1 | 0.050 | 0.200 | 1 | 0 | 4 |
| whatif_occ | 1 | 5 | 18 | 3 | 0.167 | 0.400 | 3 | 0 | 3 |
| whatif_temp | 1 | 5 | 18 | 7 | 0.389 | 1.000 | 7 | 0 | 0 |

fail reasons: {'missing_fact': 479, 'missing_call': 363, 'think_too_long': 246, 'invented_num': 141, 'extra_calls': 76, 'status:too_many_calls': 61, 'unit_mismatch': 52, 'too_long': 32, 'unexpected_call': 11, 'no_refusal': 9, 'invented_id': 5, 'actuation_claim': 4, 'invented_time': 2}

