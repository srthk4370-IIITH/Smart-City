# Final pre-eval check 09:34 IST
{"fast_incident": "INC-0717", "fast_s": 6.9, "ai_update_s": 77.9, "final_model": "qwen3.5-4b (htpd)", "valid": true, "severity": "sensor_fault", "title": "CO2 sensor fault (stuck): KH building, level 03", "pass": true}
{"warm_for_s":60}

== 0.1 s | None | Which incident needs my attention first?
  ANSWER Start with [INC-0660] KH building, level 98: pH 9.63 over the critical limit (9.0) (water) (critical, water): it is the most urgent of the 53 incidents waiting for your decision (worst severi
== 0.1 s | None | Show me critical alerts
  ANSWER Latest 5 incidents, newest first: INC-0419 CO2 spike: KH building, level 03, indoor air sensor 03 (critical, 2026-10-13 12:45); INC-0178 Normal operation: Tank level critical, Power warning, 
== 9.2 s | qwen3.5-2b rsn_v3 (cpu) | Give me a quick status of the whole campus in two lines.
  ANSWER Air quality: 54 open incidents, worst critical; water: 1 open incident, worst critical; power: 0 open incidents, worst normal; occupancy: 0 open incidents, worst normal; weather: 6 open incid
0
MemAvailable:    3225568 kB
72700
- second fastcheck (cold-start test) 09:37:
{"fast_incident": "INC-0719", "fast_s": 5.6, "ai_update_s": 28.0, "final_model": "qwen3.5-4b (htpd)", "valid": true, "severity": "sensor_fault", "title": "KH building, level 03: CO2 sensor fault: stepped up", "pass": true}
