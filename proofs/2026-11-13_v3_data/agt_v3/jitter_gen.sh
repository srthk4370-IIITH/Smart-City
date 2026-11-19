# 2026-11-13 owner: card jitter 14.7 % -> 30 % of existing-metric rows; new rows with every existing card jittered (seed 4041)
cd /mnt/c/Users/hp/Desktop/qidk/proofs/2026-11-13_v3_data/agt_v3
export AGT_JX=1.0
nice -n 15 ~/venvs/rsn/bin/python gen_agt.py --out $HOME/smartcity_runs/v3_data_jx --procs 6 --seed 4041 --only train \
  --plan '{"calm_routine": 2700, "ex_stable": 1800, "ex_fault": 1200, "ex_longrange": 600, "hole_calm_fault": 600, "dq_edge": 300, "ex_event": 900}' 2>&1 | tail -2
echo GEN_DONE
