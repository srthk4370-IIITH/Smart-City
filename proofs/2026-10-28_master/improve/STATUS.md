# Morning improvements (08:25 IST start)
- I0 build OK: apk 4d9c632e, edge-agent 45d1a090
- I1 GPU bench: aborted_cpu_heat; results in gpu_bench_out/out.md; min MemAvailable 6370 MB
- V2 deploy cancelled 09:0x IST: host RWH 106 same-id score v2 severity 87.6% vs v1 94.7% (genuinely worse); rsn_v1 stays
- V2 skipped (cancelled, see line above)
- I2 DEPLOYED: edge-agent 45d1a090, seed ok=yes; chaos 2 rc=0; fastcheck {"fast_incident": "INC-0441", "fast_s": 5.6, "ai_update_s": 47.2, "final_model": "qwen3.5-4b (htpd)", "valid": true, "severity": "sensor_fault", "title": "KH building, level 03: Suspect CO2 readings", "pass": true}
- board now: 45d1a0908f506261db22647c20fc8181  /data/local/tmp/smart_city_edge/edge-agent reasoner_split=3 bin=/data/local/tmp/llama.cpp/bin/htpd_v8x3 reasoner_model=/data/local/tmp/gpu/qwen35_reasoner_q4_0.gguf 
- GPU rerun: ok; max temp 92 C; min avail 5814 MB; max kgsl 0 MB
| model                          |       size |     params | backend    | ngl |  fa | dev          |            test |                  t/s |
| ------------------------------ | ---------: | ---------: | ---------- | --: | --: | ------------ | --------------: | -------------------: |
| qwen35 4B Q4_0                 |   2.42 GiB |     4.33 B | OpenCL,HTP |  99 |   0 | GPUOpenCL    |             pp1 |          7.35 ± 0.27 |
| qwen35 4B Q4_0                 |   2.42 GiB |     4.33 B | OpenCL,HTP |  99 |   0 | GPUOpenCL    |             pp2 |          5.94 ± 0.00 |
| qwen35 4B Q4_0                 |   2.42 GiB |     4.33 B | OpenCL,HTP |  99 |   0 | GPUOpenCL    |             pp3 |          8.44 ± 0.07 |
| qwen35 4B Q4_0                 |   2.42 GiB |     4.33 B | OpenCL,HTP |  99 |   0 | GPUOpenCL    |             pp4 |         11.37 ± 0.12 |
| qwen35 4B Q4_0                 |   2.42 GiB |     4.33 B | OpenCL,HTP |  99 |   0 | GPUOpenCL    |             pp6 |         17.06 ± 0.12 |
| qwen35 4B Q4_0                 |   2.42 GiB |     4.33 B | OpenCL,HTP |  99 |   0 | GPUOpenCL    |             pp8 |         22.76 ± 0.70 |
| qwen35 4B Q4_0                 |   2.42 GiB |     4.33 B | OpenCL,HTP |  99 |   0 | GPUOpenCL    |           pp512 |        153.67 ± 0.80 |
| qwen35 4B Q4_0                 |   2.42 GiB |     4.33 B | OpenCL,HTP |  99 |   0 | GPUOpenCL    |            tg64 |          8.35 ± 0.15 |
