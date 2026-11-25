# AUDIT_TOOLS (gen5_tools.jsonl vs tools_v5.json)

| family | rows | bad | bad % |
|---|---|---|---|
| gen5_agentic | 1464 | 2 | 0.1% |
| gen5_compare_periods | 240 | 0 | 0.0% |
| gen5_data_health | 160 | 0 | 0.0% |
| gen5_domain_health | 240 | 0 | 0.0% |
| gen5_faulty_sensors | 240 | 0 | 0.0% |
| gen5_fog_status | 240 | 0 | 0.0% |
| gen5_forecast_crossing | 240 | 0 | 0.0% |
| gen5_get_action_history | 240 | 0 | 0.0% |
| gen5_get_site_tree | 240 | 0 | 0.0% |
| gen5_nodes_under | 240 | 0 | 0.0% |
| gen5_open_incidents | 240 | 0 | 0.0% |
| gen5_recent_incidents | 240 | 0 | 0.0% |
| gen5_recurring_issues | 240 | 0 | 0.0% |
| gen5_search_knowledge | 240 | 0 | 0.0% |
| gen5_sensor_faults | 240 | 0 | 0.0% |
| gen5_what_if | 240 | 0 | 0.0% |
- bad example gen5-agentic-04791: ['co2 no ppm']
- bad example gen5-agentic-04805: ['co2 no ppm']

total 4984 rows, bad 2 = 0.04% (limit 2%)
agentic: 1464 rows, recovery 310 (21.2%), calls per row {2: 440, 3: 964, 4: 60}
agentic kinds: {'drill': 90, 'health_top': 100, 'recurring_history': 100, 'compare_find': 100, 'tree_none': 71, 'tree_status': 29, 'flt_history': 100, 'know_levels': 64, 'whatif_levels': 100, 'fog_search': 100, 'cooccur_chain': 100, 'open_detail': 100, 'faults_worst': 100, 'recover_badid': 75, 'recover_badnode': 75, 'recover_noplace': 50, 'recover_nosite': 50, 'drill_widen': 60}
fog states: {'offline': 2190, 'online': 2125, 'timeout': 669}
format rows: {None: 4297, 'one_sentence': 343, 'two_lines': 344}

RESULT: PASS
