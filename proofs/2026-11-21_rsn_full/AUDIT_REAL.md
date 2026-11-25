# AUDIT_REAL

Cutoff epoch 1765391400 (2025-12-11 00:00 IST, see CUTOFF.md). Verifiers: G.full_check (round-1 + v4 checks), check_big.audit_report (ids exist, severity valid, contrast family severity, sensor_fault only on strong evidence, chain cites ids), real rows: severity == rule gold.

| file | rows | src_real | bad (verify+audit) | bad % | families | sev dist |
|---|---|---|---|---|---|---|
| gen5_multidomain | 1500 | 0 | 0 | 0.00% | 77 | {'critical': 716, 'warning': 716, 'sensor_fault': 59, 'normal': 9} |
| gen5_domain | 1200 | 0 | 0 | 0.00% | 7 | {'normal': 310, 'sensor_fault': 317, 'critical': 291, 'warning': 282} |

total 2700 rows, real 0, injected 2700, bad 0 (0.00%; limit 2%).
Gold: real rows = rule gold (sft_v2 labels, label-audit judge on the exact E-lines) + deployed agent s0450 output (greedy, GPU) -> verified v2 report builder (gen_agt3); injected rows = gold by construction.
Not done: board incidents (old_inc.jsonl) - sim clock +1 y, old report schema, no verified gold; reasoner-model self-distill not used (deterministic verified builder); injected scenes use generated series (not real windows).
