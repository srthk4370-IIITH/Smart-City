# AUTO_STATUS (supervisor, updated 2026-11-12 12:55:12 UTC)

- phase: training finished -> post (export + gate)
- last step: [10:06:22] step 2800/4297 (e1) loss 0.0267 lr 3.44e-05 744 tok/s ETA epoch1 37.9 h scale 1
- best: {"top":[[0.9917,2800],[0.9917,2000],[0.9667,1200]],"best":0.9917,"since_best":2,"evals":7}
- last evals:
  - [05:04:09] DEV step 2600 incident 0.0890 chat 0.0098
  - [10:10:34] DEV step 2800 incident 0.0863 chat 0.0092
  - [11:32:37] GEN step 2800 {"step": 2800, "t": 1794310357.7866828, "dev": {"n_inc": 40, "parse": 1.0, "severity": 0.975, "label": 0.975, "n_chat": 60, "chat_pass": 1.0, "sc
- processes: chain=0 trainer=0 post=0 gate=0 keepalive=2
- GPU 67 C, Windows available 1880 MB, WSL 894 MB available
- post markers: export.done gate.done pick.done wait.done  gate: dev3.done r3new.done r3v1.done rep.done rwh2.done t2new.done t2v1.done 
- gate verdict: # 4B r3 gate: rsn_v3_4b_r3 vs ft612 (rsn_v1) -> **PASS**
- restarts (24 h): train 0, post 0
- recent status lines:
  - 2026-11-10 15:48:21 [post_4b] gate: r3v1 done (chat_r3 r3test: 983 new items -> /mnt/c/Users/hp/Desktop/qidk/proofs/2026-11-06_4b_local/post/gate_r3/chat_test_r3_v1.js)
  - 2026-11-10 20:15:44 [post_4b] gate: t2new done (rsn_v3_4b_r3 test_r2: 1368 items)
  - 2026-11-11 00:37:08 [post_4b] gate: t2v1 done (ft612 test_r2: 1368 items)
  - 2026-11-11 00:37:19 [post_4b] gate: final GATE PASS (/mnt/c/Users/hp/Desktop/qidk/proofs/2026-11-06_4b_local/post/gate_r3/GATE.md)
  - 2026-11-11 00:37:19 [post_4b] step gate done: PASS -> /mnt/c/Users/hp/Desktop/qidk/proofs/2026-11-06_4b_local/post/gate_r3/GATE.md
  - 2026-11-11 00:37:19 [post_4b] post chain DONE: /mnt/c/Users/hp/Desktop/qidk/Code/models_stage/rsn_v3_4b_r3_q4_0.gguf (931f9dd7fb99660c34e762feaf37208d), gate PASS (/mnt

## ALERTS
- 2026-11-10 08:34:15 OOM STOP in train.log
