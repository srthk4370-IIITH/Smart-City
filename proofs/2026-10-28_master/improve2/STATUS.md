# Preliminary checklist build (08:43 IST start)
- I0 build OK: apk c62b6014, edge-agent b770aa57
- I2 DEPLOYED: edge-agent b770aa57, seed ok=yes; chaos 2 rc=0; fastcheck {"fast_incident": "INC-0445", "fast_s": 5.6, "ai_update_s": 42.2, "final_model": "qwen3.5-4b (htpd)", "valid": true, "severity": "sensor_fault", "title": "KH building, level 03: Suspect CO2 readings", "pass": true}
- board now: b770aa570dd48c1a12680ff69794c1e1  /data/local/tmp/smart_city_edge/edge-agent reasoner_split=3 bin=/data/local/tmp/llama.cpp/bin/htpd_v8x3 reasoner_model=/data/local/tmp/gpu/qwen35_reasoner_q4_0.gguf 
- 3r A/B: SUMMARY parse 0/10 same sev+label+title 0/10 mean 3 22.2 s 3r 22.2 s (+0.1%) DEPLOY=0
- 3r not deployed (gate, time, or deploy2 build missing)
