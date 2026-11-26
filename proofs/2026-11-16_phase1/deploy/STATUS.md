# Phase 1 deploy 2026-11-16 08:34 IST
08:35:39 ABORT: no board on adb
# Phase 1 deploy 2026-11-16 08:39 IST
08:40:49 preflight: avail=4612MB t=51C /dev/block/dm-45  45G  33G   12G  74% /data/user/0
08:40:50 known_good: 9e82675a34044e6d04939fd456c788ef  /mnt/c/Users/hp/Desktop/qidk/proofs/2026-11-16_phase1/deploy/known_good/app.apk
08:41:23 Stage A: STOPPED
08:47:05 Stage A ok (Phase 1 APK, old profile = old behaviour)
08:47:38 Stage B: STOPPED
08:49:24 Stage B ok
08:50:00 Stage C: STOPPED
08:54:44 Stage C ok (models + v9h + production keys; campus input next)
08:55:17 Stage D: STOPPED
08:55:23 Stage D ok
08:59:17 T: campus API not reachable (board on Wi-Fi? expect the No-network page)
09:29:29 T ok: health {'missing': 27} avail=4520MB t=53C
09:29:29 done (stage all)
09:35:16 switch_agt3: stop app
09:36:49 switch_agt3: start app
09:40:46 switch_agt3: status 
09:40:47 switch_agt3: htpd errors: 49  avail=4161MB t=52C
09:47:30 restart_app (clock offset fixed, relay fixed)
09:48:08 app up
09:50:06 after restart: "clock":{"corrected":"2026-11-16T04:20:04Z","device":"2023-09-20T16:57:42Z","source":"start offset (--clock-unix)","uncertain_incidents":0,"valid":true}
09:50:06 health: {"sim_time":1794802800,"worst":"insufficient_data","domains":[{"domain":"air_quality","headline":"insufficient_data","status":"normal","live_status":"normal","sensor_faults":0,"counts":{"insufficient_data":5},"sensors":5,"context_sensors":0,"trend":"elevated","trend_from":"normal","since":1794802500
09:59:39 1b: stop
10:00:18 1b: app up
10:03:12 1b: link="campus_link_label":"USB cable (laptop)" clock="corrected":"2026-11-16T04:33:11Z"
10:03:13 1b: health={"sim_time":1794803400,"worst":"warning","domains":[{"domain":"air_quality","headline":"warning","status":"warning","live_status":"warning","sensor_faults":0,"counts":{"normal":4,"warning":1},"sensors":5,"context_sensors":0,"trend":"elevated","trend_from":"nor
10:03:13 1b: agent.log tail: 2023/09/20 17:08:19 campus: backfill done (1820 readings, 12 h)|2023/09/20 17:08:58 fog: upload failed (Post "http://127.0.0.1:8092/v1/ingest": EOF); rows stay queued|2023/09/20 17:09:58 fog: upload failed (Post "http://127.0.0.1:8092/v1/ingest": EOF); rows stay queued|
14:10:58 1c: stop
14:11:43 1c: app up
14:14:38 1c: link="campus_link_label":"USB cable (laptop)" clock="corrected":"2026-11-16T08:44:37Z"
14:14:39 1c: health={"sim_time":1794818400,"worst":"critical","domains":[{"domain":"air_quality","headline":"normal","status":"normal","live_status":"normal","sensor_faults":0,"counts":{"normal":5},"sensors":5,"context_sensors":0,"trend":"steady","since":1794775200,"fresh":true,"
14:14:39 1c: agent.log tail: 2023/09/20 21:19:50 htpd: started (pid 15713), up=true|2023/09/20 21:20:20 fog: upload failed (Post "http://127.0.0.1:8092/v1/ingest": EOF); rows stay queued|2023/09/20 21:21:20 fog: upload failed (Post "http://127.0.0.1:8092/v1/ingest": EOF); rows stay queued|
02:25:52 switch_agt3: stop app
02:28:01 switch_agt3: start app
02:32:27 switch_agt3: status 
02:32:28 switch_agt3: htpd errors: 8  avail=4342MB t=52C
02:59:41 1d: stop
03:00:23 1d: app up
03:03:43 1d: link="campus_link_label":"USB cable (laptop)" clock="corrected":"2026-11-16T21:33:44Z"
03:03:43 1d: health={"sim_time":1794864600,"worst":"sensor_fault","domains":[{"domain":"air_quality","headline":"normal","status":"normal","live_status":"normal","sensor_faults":0,"counts":{"normal":5},"sensors":5,"context_sensors":0,"trend":"steady","since":1794821400,"fresh":tr
03:03:43 1d: agent.log tail: 2023/09/21 10:09:05 fog: upload failed (Post "http://127.0.0.1:8092/v1/ingest": EOF); rows stay queued|2023/09/21 10:10:04 fog: upload failed (Post "http://127.0.0.1:8092/v1/ingest": EOF); rows stay queued|2023/09/21 10:11:04 fog: upload failed (Post "http://127.0.0.1:8092/v1/ingest": EOF); rows stay queued|
03:34:22 1e: stop
03:35:07 1e: app up
03:38:24 1e: link="campus_link_label":"USB cable (laptop)" clock="corrected":"2026-11-16T22:08:26Z"
03:38:24 1e: health={"sim_time":1794866700,"worst":"warning","domains":[{"domain":"air_quality","headline":"normal","status":"normal","live_status":"normal","sensor_faults":0,"counts":{"normal":5},"sensors":5,"context_sensors":0,"trend":"steady","since":1794823500,"fresh":true,"i
03:38:24 1e: agent.log tail: 2023/09/21 10:45:59 htpd: started (pid 19961), up=true|2023/09/21 10:46:00 htpd: warm-up 2/5 failed: EOF|2023/09/21 10:46:00 htpd: restart 3/5 in 10s (EOF)|
03:48:27 1f: stop
03:49:09 1f: app up
03:52:25 1f: link="campus_link_label":"USB cable (laptop)" clock="corrected":"2026-11-16T22:22:26Z"
03:52:25 1f: health={"sim_time":1794867600,"worst":"warning","domains":[{"domain":"air_quality","headline":"normal","status":"normal","live_status":"normal","sensor_faults":0,"counts":{"normal":5},"sensors":5,"context_sensors":0,"trend":"steady","since":1794824100,"fresh":true,"d
03:52:25 1f: agent.log tail: 2023/09/21 10:59:50 htpd: warm-up 5/5 failed: EOF|2023/09/21 10:59:50 htpd: not ready after 5 tries - real requests will find it as it is|2023/09/21 10:59:51 fog: upload failed (Post "http://127.0.0.1:8092/v1/ingest": EOF); rows stay queued|
04:00:24 1g: stop
04:01:06 1g: app up
04:04:19 1g: link="campus_link_label":"USB cable (laptop)" clock="corrected":"2026-11-16T22:34:22Z"
04:04:19 1g: health={"sim_time":1794868200,"worst":"warning","domains":[{"domain":"air_quality","headline":"normal","status":"normal","live_status":"normal","sensor_faults":0,"counts":{"normal":5},"sensors":5,"context_sensors":0,"trend":"steady","since":1794825000,"fresh":true,"d
04:04:20 1g: agent.log tail: 2023/09/21 11:09:46 fog: upload failed (Post "http://127.0.0.1:8092/v1/ingest": EOF); rows stay queued|2023/09/21 11:10:46 fog: upload failed (Post "http://127.0.0.1:8092/v1/ingest": EOF); rows stay queued|2023/09/21 11:11:46 fog: upload failed (Post "http://127.0.0.1:8092/v1/ingest": EOF); rows stay queued|
05:26:05 npu_rest: stop app
05:26:39 npu_rest: htpd procs after stop: 0
05:32:17 npu_rest: app up
05:43:21 npu_rest: 2023/09/21 12:41:18 htpd: ready after warm-up (try 1/5)|2023/09/21 12:41:18 reason: NPU crashed - agent not run (INC-0005 SR-EM-KH04-01 power_kw): NPU unavailable (htpd crashed during the request, agent not run: EOF)|2023/09/21 12:41:34 htpd: started (pid 4317), up=true|2023/09/21 12:41:54 htpd: ready after warm-up (try 1/5)|
05:43:22 npu_rest: mmap fails in current htpd.log: 12
05:56:51 try: files 2800617952 agt3_k_q4_0.gguf;2800617952 agt3_s0075_q4_0.gguf;2680929472 rsn_v1_q4_0_keep.gguf;56 rsn_v1_q4_0_keep.gguf.md5;134222632 rsn_v1_q4_0_keep.gguf.prefix_1e56ee51bddac910.state;134222632 rsn_v1_q4_0_keep.gguf.prefix_a5927b71b89b88d6.state;95884108 rsn_v1_q4_0_keep.gguf.prefix_eade7409d71b3388.state;1236741056 rsn_v3_2b_q4_0.gguf;33 rsn_v3_2b_q4_0.gguf.md5;50819680 rsn_v3_2b_q4_0.gguf.prefix_3af9ba936128ec66.state;50819680 rsn_v3_2b_q4_0.gguf.prefix_5fd5a925f73cd9c1.state;36422276 rsn_v3_2b_q4_0.gguf.prefix_c56a981455c6d90b.state;50819680 rsn_v3_2b_q4_0.gguf.prefix_e2cdc4fdb8b1c97e.state;1236741056 rsn_v3_2b_r2_q4_0.gguf;2611783520 rsn_v3_4b_r3c1_q4_0.gguf;95884100 rsn_v3_4b_r3c1_q4_0.gguf.prefix_54f2bef78b64bd33.state;
05:57:26 try: app up (s0075)
06:08:26 try: 2023/09/21 13:05:59 htpd: started (pid 11288), up=true|2023/09/21 13:06:19 htpd: ready after warm-up (try 1/5)|2023/09/21 13:06:19 reason: NPU crashed - agent not run (INC-0006 SR-EM-KH04-01 power_kw): NPU unavailable (ht|2023/09/21 13:06:34 htpd: started (pid 11446), up=true|2023/09/21 13:06:54 htpd: ready after warm-up (try 1/5)|
06:08:26 try: mmap fails: 0
06:26:26 try: files 2800617952 agt3_k_q4_0.gguf;2800617952 agt3_s0075_q4_0.gguf;2680929472 rsn_v1_q4_0_keep.gguf;56 rsn_v1_q4_0_keep.gguf.md5;134222632 rsn_v1_q4_0_keep.gguf.prefix_1e56ee51bddac910.state;134222632 rsn_v1_q4_0_keep.gguf.prefix_a5927b71b89b88d6.state;95884108 rsn_v1_q4_0_keep.gguf.prefix_eade7409d71b3388.state;1236741056 rsn_v3_2b_q4_0.gguf;33 rsn_v3_2b_q4_0.gguf.md5;50819680 rsn_v3_2b_q4_0.gguf.prefix_3af9ba936128ec66.state;50819680 rsn_v3_2b_q4_0.gguf.prefix_5fd5a925f73cd9c1.state;36422276 rsn_v3_2b_q4_0.gguf.prefix_c56a981455c6d90b.state;50819680 rsn_v3_2b_q4_0.gguf.prefix_e2cdc4fdb8b1c97e.state;1236741056 rsn_v3_2b_r2_q4_0.gguf;2611783520 rsn_v3_4b_r3c1_q4_0.gguf;95884100 rsn_v3_4b_r3c1_q4_0.gguf.prefix_54f2bef78b64bd33.state;
06:27:11 try: app up (s0300 ctx1280)
06:38:14 try: 2023/09/21 13:06:19 reason: NPU crashed - agent not run (INC-0006 SR-EM-KH04-01 power_kw): NPU unavailable (ht|2023/09/21 13:06:34 htpd: started (pid 11446), up=true|2023/09/21 13:06:54 htpd: ready after warm-up (try 1/5)|2023/09/21 13:34:47 htpd: started (pid 16837), up=true|2023/09/21 13:35:07 htpd: ready after warm-up (try 1/5)|
06:38:14 try: mmap fails: 0
13:52:21 1h: stop
13:53:04 1h: app up
13:56:23 1h: link="campus_link_label":"USB cable (laptop)" clock="corrected":"2026-11-17T08:26:25Z"
13:56:23 1h: health={"sim_time":1794903900,"worst":"critical","domains":[{"domain":"air_quality","headline":"normal","status":"normal","live_status":"normal","sensor_faults":0,"counts":{"normal":5},"sensors":5,"context_sensors":0,"trend":"steady","since":1794860400,"fresh":true,"
13:56:23 1h: agent.log tail: 2023/09/21 21:01:46 fog: upload failed (Post "http://127.0.0.1:8092/v1/ingest": EOF); rows stay queued|2023/09/21 21:02:46 fog: upload failed (Post "http://127.0.0.1:8092/v1/ingest": EOF); rows stay queued|2023/09/21 21:03:46 fog: upload failed (Post "http://127.0.0.1:8092/v1/ingest": EOF); rows stay queued|
14:43:48 abort1: app up
00:13:27 deploy agent agt3_s0450_q4_0.gguf: stop app
00:20:16 deploy agent agt3_s0450_q4_0.gguf check INC-0017: agents_valid=2/2 final=qwen3.5-4b rsn_v3 (htpd) valid
00:20:16 DEPLOYED agent agt3_s0450_q4_0.gguf
00:34:38 restart_app (clock offset fixed, relay fixed)
00:40:40 app NOT up
00:42:41 after restart: "clock":{"corrected":"2026-11-16T23:00:32Z","device":"2023-09-21T11:38:11Z","source":"start offset (--clock-unix)","uncertain_incidents":0,"valid":true}
00:42:41 health: {"sim_time":1794870000,"worst":"sensor_fault","domains":[{"domain":"air_quality","headline":"normal","status":"normal","live_status":"normal","sensor_faults":0,"counts":{"normal":5},"sensors":5,"context_sensors":0,"trend":"steady","since":1794826200,"fresh":true,"data_quality":[{"sensor":"AQ-KN00-00
14:42:02 restart_app (clock offset fixed, relay fixed)
14:42:43 app up
14:44:43 after restart: "clock":{"corrected":"2026-11-16T03:12:33Z","device":"2023-09-20T15:50:12Z","source":"start offset (--clock-unix)","uncertain_incidents":0,"valid":true}
14:44:43 health: {"sim_time":1794798600,"worst":"warning","domains":[{"domain":"air_quality","headline":"normal","status":"normal","live_status":"normal","sensor_faults":0,"counts":{"normal":5},"sensors":5,"context_sensors":0,"trend":"steady","since":1794755400,"fresh":true,"incidents":[],"steps":[]},{"domain":"wate
14:46:11 fix_clock: device 1695225100 laptop 1795079771 offset 99854671 s
14:46:52 fix_clock: app up
14:47:52 fix_clock: "campus_link_label":"USB cable (laptop)" "corrected":"2026-11-19T09:17:51Z" 
16:35:23 fix_clock: device 1695224845 laptop 1795086323 offset 99861478 s
21:16:19 deploy reasoner rsn_v3_4b_p2_q4_0.gguf: stop app
21:18:55 ABORT: push failed
21:19:04 1j: stop
21:19:44 1j: app up
21:22:46 1j: link="campus_link_label":"USB cable (laptop)" clock="corrected":"2026-11-19T15:52:45Z"
21:22:46 1j: health={"sim_time":1795103400,"worst":"sensor_fault","domains":[{"domain":"air_quality","headline":"normal","status":"normal","live_status":"normal","sensor_faults":0,"counts":{"normal":5},"sensors":5,"context_sensors":0,"trend":"steady","since":1795059900,"fresh":tr
21:22:47 1j: agent.log tail: 2023/09/20 20:32:49 fog: upload failed (Post "http://127.0.0.1:8092/v1/ingest": EOF); rows stay queued|2023/09/20 20:33:49 fog: upload failed (Post "http://127.0.0.1:8092/v1/ingest": EOF); rows stay queued|2023/09/20 20:34:49 fog: upload failed (Post "http://127.0.0.1:8092/v1/ingest": EOF); rows stay queued|
21:29:42 deploy reasoner rsn_v3_4b_p2_q4_0.gguf: stop app
21:35:32 deploy reasoner rsn_v3_4b_p2_q4_0.gguf check INC-0025: agents_valid=1/1 final=qwen3.5-4b rsn_v3 (htpd) valid
21:35:32 DEPLOYED reasoner rsn_v3_4b_p2_q4_0.gguf
21:57:22 1k: stop
22:00:36 1k: app up
22:02:08 1k: stop
22:02:47 1k: app up
22:05:48 1k: link="campus_link_label":"USB cable (laptop)" clock="corrected":"2026-11-19T16:35:46Z"
22:05:48 1k: health={"sim_time":1795106100,"worst":"insufficient_data","domains":[{"domain":"air_quality","headline":"insufficient_data","status":"normal","live_status":"normal","sensor_faults":0,"counts":{"insufficient_data":5},"sensors":5,"context_sensors":0,"trend":"elevated",
22:05:48 1k: agent.log tail: 2023/09/20 15:43:32 fog: upload failed (Post "http://127.0.0.1:8092/v1/ingest": EOF); rows stay queued|2023/09/20 15:44:08 campus: backfill done (1756 readings, 12 h)|2023/09/20 15:44:32 fog: upload failed (Post "http://127.0.0.1:8092/v1/ingest": EOF); rows stay queued|
00:00:50 1l: stop
00:01:36 1l: app up
00:04:36 1l: link="campus_link_label":"USB cable (laptop)" clock="corrected":"2026-11-19T18:34:34Z"
00:04:36 1l: health={"sim_time":1795113000,"worst":"warning","domains":[{"domain":"air_quality","headline":"normal","status":"normal","live_status":"normal","sensor_faults":0,"counts":{"normal":5},"sensors":5,"context_sensors":0,"trend":"steady","since":1795069800,"fresh":true,"i
00:04:37 1l: agent.log tail: 2023/09/20 17:41:18 fog: upload failed (Post "http://127.0.0.1:8092/v1/ingest": EOF); rows stay queued|2023/09/20 17:42:18 fog: upload failed (Post "http://127.0.0.1:8092/v1/ingest": EOF); rows stay queued|2023/09/20 17:43:18 fog: upload failed (Post "http://127.0.0.1:8092/v1/ingest": EOF); rows stay queued|
02:44:30 1m: stop
02:45:17 1m: app up
02:48:17 1m: link="campus_link_label":"USB cable (laptop)" clock="corrected":"2026-11-19T21:18:15Z"
02:48:17 1m: health={"sim_time":1795122900,"worst":"critical","domains":[{"domain":"air_quality","headline":"normal","status":"normal","live_status":"normal","sensor_faults":0,"counts":{"normal":5},"sensors":5,"context_sensors":0,"trend":"steady","since":1795079700,"fresh":true,"
02:48:17 1m: agent.log tail: 2023/09/20 20:25:00 fog: upload failed (Post "http://127.0.0.1:8092/v1/ingest": EOF); rows stay queued|2023/09/20 20:26:00 fog: upload failed (Post "http://127.0.0.1:8092/v1/ingest": EOF); rows stay queued|2023/09/20 20:27:00 fog: upload failed (Post "http://127.0.0.1:8092/v1/ingest": EOF); rows stay queued|
03:02:43 1n: stop
03:03:25 1n: app up
03:06:25 1n: link="campus_link_label":"USB cable (laptop)" clock="corrected":"2026-11-19T21:36:24Z"
03:06:25 1n: health={"sim_time":1795124100,"worst":"warning","domains":[{"domain":"air_quality","headline":"normal","status":"normal","live_status":"normal","sensor_faults":0,"counts":{"normal":5},"sensors":5,"context_sensors":0,"trend":"steady","since":1795080600,"fresh":true,"d
03:06:25 1n: agent.log tail: 2023/09/20 20:43:10 fog: upload failed (Post "http://127.0.0.1:8092/v1/ingest": EOF); rows stay queued|2023/09/20 20:44:10 fog: upload failed (Post "http://127.0.0.1:8092/v1/ingest": EOF); rows stay queued|2023/09/20 20:45:10 fog: upload failed (Post "http://127.0.0.1:8092/v1/ingest": EOF); rows stay queued|
03:28:00 1o: stop
03:28:41 1o: app up
03:31:41 1o: link="campus_link_label":"USB cable (laptop)" clock="corrected":"2026-11-19T22:01:39Z"
03:31:41 1o: health={"sim_time":1795125600,"worst":"warning","domains":[{"domain":"air_quality","headline":"normal","status":"normal","live_status":"normal","sensor_faults":0,"counts":{"normal":5},"sensors":5,"context_sensors":0,"trend":"steady","since":1795082100,"fresh":true,"i
03:31:41 1o: agent.log tail: 2023/09/20 21:09:26 fog: upload failed (Post "http://127.0.0.1:8092/v1/ingest": EOF); rows stay queued|2023/09/20 21:09:40 severity-disagreement {"final":"warning","guard":true,"incident":"INC-0001","label":"normal_operation","reasoner":"norma|2023/09/20 21:10:26 fog: upload failed (Post "http://127.0.0.1:8092/v1/ingest": EOF); rows stay queued|
04:02:46 1q: stop
04:03:27 1q: app up
04:06:29 1q: link="campus_link_label":"USB cable (laptop)" clock="corrected":"2026-11-19T22:36:24Z"
04:06:29 1q: health={"sim_time":1795127700,"worst":"warning","domains":[{"domain":"air_quality","headline":"normal","status":"normal","live_status":"normal","sensor_faults":0,"counts":{"normal":5},"sensors":5,"context_sensors":0,"trend":"steady","since":1795084200,"fresh":true,"i
04:06:29 1q: agent.log tail: 2023/09/20 21:43:14 fog: upload failed (Post "http://127.0.0.1:8092/v1/ingest": EOF); rows stay queued|2023/09/20 21:44:14 fog: upload failed (Post "http://127.0.0.1:8092/v1/ingest": EOF); rows stay queued|2023/09/20 21:45:14 fog: upload failed (Post "http://127.0.0.1:8092/v1/ingest": EOF); rows stay queued|
04:17:19 1r: stop
04:18:02 1r: app up
04:21:02 1r: link="campus_link_label":"USB cable (laptop)" clock="corrected":"2026-11-19T22:50:59Z"
04:21:02 1r: health={"sim_time":1795128600,"worst":"warning","domains":[{"domain":"air_quality","headline":"normal","status":"normal","live_status":"normal","sensor_faults":0,"counts":{"normal":5},"sensors":5,"context_sensors":0,"trend":"curbed","trend_from":"warning","since":179
04:21:02 1r: agent.log tail: 2023/09/20 21:57:47 fog: upload failed (Post "http://127.0.0.1:8092/v1/ingest": EOF); rows stay queued|2023/09/20 21:58:47 fog: upload failed (Post "http://127.0.0.1:8092/v1/ingest": EOF); rows stay queued|2023/09/20 21:59:47 fog: upload failed (Post "http://127.0.0.1:8092/v1/ingest": EOF); rows stay queued|
12:32:57 1s: stop
12:33:38 1s: app up
12:36:38 1s: link="campus_link_label":"USB cable (laptop)" clock="corrected":"2026-11-20T07:06:37Z"
12:36:38 1s: health={"sim_time":1795158300,"worst":"critical","domains":[{"domain":"air_quality","headline":"normal","status":"normal","live_status":"normal","sensor_faults":0,"counts":{"normal":5},"sensors":5,"context_sensors":0,"trend":"steady","since":1795114800,"fresh":true,"
12:36:38 1s: agent.log tail: 2023/09/21 06:12:49 campus: backfill done (1827 readings, 12 h)|2023/09/21 06:13:27 fog: upload failed (Post "http://127.0.0.1:8092/v1/ingest": EOF); rows stay queued|2023/09/21 06:14:27 fog: upload failed (Post "http://127.0.0.1:8092/v1/ingest": EOF); rows stay queued|
13:38:26 1t: stop
13:39:12 1t: app up
13:42:12 1t: link="campus_link_label":"USB cable (laptop)" clock="corrected":"2026-11-20T08:12:10Z"
13:42:13 1t: health={"sim_time":1795162200,"worst":"critical","domains":[{"domain":"air_quality","headline":"normal","status":"normal","live_status":"normal","sensor_faults":0,"counts":{"normal":5},"sensors":5,"context_sensors":0,"trend":"steady","since":1795118700,"fresh":true,"
13:42:13 1t: agent.log tail: 2023/09/21 07:18:57 fog: upload failed (Post "http://127.0.0.1:8092/v1/ingest": EOF); rows stay queued|2023/09/21 07:19:57 fog: upload failed (Post "http://127.0.0.1:8092/v1/ingest": EOF); rows stay queued|2023/09/21 07:20:57 fog: upload failed (Post "http://127.0.0.1:8092/v1/ingest": EOF); rows stay queued|
17:17:54 1u: stop
17:18:40 1u: app up
17:21:41 1u: link="campus_link_label":"USB cable (laptop)" clock="corrected":"2026-11-20T11:51:39Z"
17:21:41 1u: health={"sim_time":1795175400,"worst":"warning","domains":[{"domain":"air_quality","headline":"normal","status":"normal","live_status":"normal","sensor_faults":0,"counts":{"normal":5},"sensors":5,"context_sensors":0,"trend":"steady","since":1795131900,"fresh":true,"i
17:21:41 1u: agent.log tail: 2023/09/21 10:58:25 fog: upload failed (Post "http://127.0.0.1:8092/v1/ingest": EOF); rows stay queued|2023/09/21 10:59:25 fog: upload failed (Post "http://127.0.0.1:8092/v1/ingest": EOF); rows stay queued|2023/09/21 11:00:25 fog: upload failed (Post "http://127.0.0.1:8092/v1/ingest": EOF); rows stay queued|
02:18:48 deploy reasoner rsn_v3_4b_v5_q4_0.gguf: stop app
02:33:21 deploy reasoner rsn_v3_4b_v5_q4_0.gguf: stop app
02:39:39 deploy reasoner rsn_v3_4b_v5_q4_0.gguf check INC-0012: agents_valid=1/1 final=qwen3.5-4b rsn_v3 (htpd) valid
02:39:39 DEPLOYED reasoner rsn_v3_4b_v5_q4_0.gguf
