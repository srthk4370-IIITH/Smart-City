# 2026-11-13 owner: fault share 22% -> ~12%; extra non-fault rows (new seed 3031), filtered + merged by rebalance.py
cd /mnt/c/Users/hp/Desktop/qidk/proofs/2026-11-13_v3_data/agt_v3
nice -n 15 ~/venvs/rsn/bin/python gen_agt.py --out $HOME/smartcity_runs/v3_data_rb --procs 6 --seed 3031 --only train \
  --plan '{"calm_routine": 2400, "ex_event": 2400, "ex_stable": 1500, "hole_power": 300, "hole_water": 300}' 2>&1 | tail -3
echo GEN_DONE
