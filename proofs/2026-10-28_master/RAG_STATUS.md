# Retrieval preliminary deploy (2026-10-28T19:14:20Z)
**Result:** PASS: 4/4 incidents had a preliminary within 2 s and the AI report on the same incident; fastcheck {"fast_incident": "INC-0427", "fast_s": 5.5, "ai_update_s": 47.5, "final_model": "deterministic (related domains verified steady)", "valid": true, "severity": "sensor_fault", "title": "CO2 step increase: KH building, level 03, indoor air sensor 03", "pass": true}

APK 4baf7f79 (edge-agent ebd08e13, seed library: none); models and htpd_profile unchanged.

| incident | scenario | created -> preliminary (s) | preliminary basis | AI report on same incident | title |
|---|---|---|---|---|---|
| INC-0423 | crowded_room | 0 | rules | yes | Normal operation: Power warning, CO2 warning |
| INC-0425 | off_hours_presence | 0 | retrieval | yes | Occupancy off hours, CO2 and AC running at KH building, level 03 |
| INC-0426 | ventilation_failure | 0 | rules | yes | CO2 rising fast, ventilation not keeping up (KH building, level 03) |
| INC-0427 | fastcheck | 0 | retrieval | yes | CO2 step increase: KH building, level 03, indoor air sensor 03 |

Retrieval hit rate: 2/4 incidents had a retrieved match

Board state now:
```
ebd08e13d58b906ab01979f117d86158  /data/local/tmp/smart_city_edge/edge-agent
bin=/data/local/tmp/llama.cpp/bin/htpd_v8x2
model=/data/local/tmp/gpu/ft_B50_q4_0.gguf
reasoner_model=/data/local/tmp/gpu/qwen35_reasoner_q4_0.gguf
reasoner_split=3
```
Rollback (WSL; stops the app, reinstalls the snapshot APK, starts it; models/profile were never changed):
`bash /mnt/c/Users/hp/Desktop/qidk/proofs/2026-10-28_master/rag_rollback.sh`   (snapshot: `/mnt/c/Users/hp/Desktop/qidk/proofs/2026-10-28_master/rag_build/known_good`). Log: `/mnt/c/Users/hp/Desktop/qidk/proofs/2026-10-28_master/rag_build/rag_deploy.log`.
