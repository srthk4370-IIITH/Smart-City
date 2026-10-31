# Deploy 9: full head back + v8x5 + AI-so-far UI + chat peak fix (15:25 IST)
- chat: 20 s | tools ['count_incidents'] | busy False | error True | How many incidents were there today? -> The assistant could not run on the NPU (read tcp 127.0.0.1:57116->127.0.0.1:8091: i/o timeout). Please try again.
- chat: 56 s | tools ['sensor_faults'] | busy False | error False | Which sensors look faulty right now? -> AI detected 11 distinct sensors with faults today: SR-AC-KH02-24, SR-AC-KH95-02, SR-AQ-KH03-03, WE-VN04-00, AQ-KN00-00, WM-WD-KH98-00, SR-AC-KH03-15.
- chat: 0 s | tools ['rank_readings (device scan)'] | busy False | error False | What was the highest CO2 today? -> Highest CO2 today: 2013.5 ppm at KH building, level 03, indoor air sensor 03 (SR-AQ-KH03-03), 09:30. (1 CO2 sensors, device readings every 5 min.)
- FAILED (chaos rc=0 fastcheck rc=0) -> previous APK + profile restored
- board now: reasoner_split=3 bin=/data/local/tmp/llama.cpp/bin/htpd_v8x3 reasoner_model=/data/local/tmp/gpu/qwen35_reasoner_q4_0.gguf 
