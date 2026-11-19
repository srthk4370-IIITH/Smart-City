# after agent snapshot scoring: agent per-department profile on BEST snapshot, then reasoner combined eval (A2g+B1)
cd /mnt/c/Users/hp/Desktop/qidk/proofs/2026-11-13_weight_edit
export HF_HUB_OFFLINE=1 TRANSFORMERS_OFFLINE=1 PYTHONWARNINGS=ignore TORCHINDUCTOR_COMPILE_THREADS=1 PYTHONUNBUFFERED=1
LK=/mnt/c/Users/hp/Desktop/qidk/proofs/2026-10-29_rsn_v3/GPU_LOCK; P=~/venvs/rsn/bin/python
until grep -q AFTER6_DONE ~/detached/agt_after6.log; do sleep 60; done
until [ ! -e $LK ]; do sleep 30; done; echo "weight_edit chain_morning $(date)" > $LK
B=$(cat ~/smartcity_runs/agt_v3/post/BEST); AD=~/smartcity_runs/agt_v3/run/$B
$P we_agent_neuron.py --mode profile --adapter $AD --specs calm_water,calm_power,calm_all,over_power,over_all --n 120 --out ~/we_work/a2 > ~/we_work/a2_profile.log 2>&1
$P we_agent_neuron.py --mode eval --adapter $AD --out ~/we_work/a2_eval.json --tweaks none --ev-n 400 > ~/we_work/a2_eval.log 2>&1
mkdir -p analysis/agent; cp ~/we_work/a2_*.tsv ~/we_work/a2_summary.json ~/we_work/a2_eval.json analysis/agent/ 2>/dev/null
echo AGENT_PROF2_DONE
cp ~/we_work/t1b_eval.json ~/we_work/c1_eval.json
$P we_neuron.py --mode eval --out ~/we_work/c1_eval.json --ev-easy 50 --ev-hard 30 --ev-trust 60 --nll-rows 15 --tweaks none,tweaks/C1_A2g_B1.json > ~/we_work/c1.log 2>&1
cp ~/we_work/c1_eval.json analysis/neuron/; rm -f $LK; echo CHAIN_DONE
