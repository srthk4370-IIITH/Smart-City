# FINAL status (2026-10-28T18:43:55Z)
**Result:** PASS: chaos 6/6 done+valid, fast path then AI on the same incident: {"fast_incident": "INC-0418", "fast_s": 6.3, "ai_update_s": 55.2, "final_model": "qwen3.5-4b (htpd)", "valid": true, "severity": "sensor_fault", "title": "KH building, level 03: Suspect CO2 readings", "pass": true}

| part | deployed | why |
|---|---|---|
| reasoner | qwen35_reasoner_q4_0.gguf | rsn_v1 kept: rsn_v2 board accuracy FAIL {'n': 30, 'parse': 30, 'sev': 27, 'lab': 25, 's': 22.5} {'n': 3, 'parse': 1, 'sev': 1, 'lab': 1, 's': 28.1} |
| agents | ft_B50_q4_0.gguf | B50 kept: P3b winner T30 fails gate2 head-to-head vs B50 (dev +7 CI[-19,+35], sev -13, E1 -4; diag/gate2_T30_vs_B50.json), owner rule accuracy first |
| split decoding | reasoner_split=3 | split6_ab (`/mnt/c/Users/hp/Desktop/qidk/proofs/2026-10-27_reasoner_fast/raw/split6/acc.md`) |
| app | fast_early APK 0deb016ee2ee8f85b7171d74cfda070f / edge-agent c97afdeb1c06607fc1535cb6806f9d1d (fast path on; early AI: ) | owner order 4 |
| daemon | htpd_v8x2 + 620d222 libs | SDK route gave no win (RESULTS §8) |

Board state after the run:
```
c97afdeb1c06607fc1535cb6806f9d1d  /data/local/tmp/smart_city_edge/edge-agent
env=HTPD_AGENT_MAX_NEW=160 HTPD_JSON_ABORT=2 HTPD_SYNTH_PREFIX_CACHE=1 GGML_HEXAGON_OPPOLL=1 HTPD_REASON_IDLE_MS=3000
bin=/data/local/tmp/llama.cpp/bin/htpd_v8x2
model=/data/local/tmp/gpu/ft_B50_q4_0.gguf
reasoner_model=/data/local/tmp/gpu/qwen35_reasoner_q4_0.gguf
reasoner_split=3
22ec1278f645848de3343e0e9c21f0d1  /data/local/tmp/llama.cpp/bin/htpd_v8x2
```
Rollback (WSL): known-good = `/mnt/c/Users/hp/Desktop/qidk/proofs/2026-10-28_master/final/known_good` (profile, installed APK 9d066495, 8e1ae828):
`bash /mnt/c/Users/hp/Desktop/qidk/proofs/2026-10-28_master/final_rollback.sh` (stops the app, restores the profile, reinstalls the APK, starts it).
Log: `/mnt/c/Users/hp/Desktop/qidk/proofs/2026-10-28_master/final.log`; chaos incidents: `/mnt/c/Users/hp/Desktop/qidk/proofs/2026-10-28_master/final/chaos/`; fast-path check: `/mnt/c/Users/hp/Desktop/qidk/proofs/2026-10-27_reasoner_fast/raw/fastcheck_*.json`.
