# agent per-department neuron profile (snap_1500) + base eval, while the gate exports on CPU; then reasoner round 1 if GPU still free
cd /mnt/c/Users/hp/Desktop/qidk/proofs/2026-11-13_weight_edit
export HF_HUB_OFFLINE=1 TRANSFORMERS_OFFLINE=1 PYTHONWARNINGS=ignore TORCHINDUCTOR_COMPILE_THREADS=1 PYTHONUNBUFFERED=1
LK=/mnt/c/Users/hp/Desktop/qidk/proofs/2026-10-29_rsn_v3/GPU_LOCK; P=~/venvs/rsn/bin/python; AD=~/smartcity_runs/agt_v3/run/snap_1500
[ -e $LK ] && { echo "lock busy: $(cat $LK)"; exit 0; }
echo "weight_edit agent_prof $(date)" > $LK
$P we_agent_neuron.py --mode profile --adapter $AD --specs calm_water,calm_power,calm_all,over_power,over_all --n 120 --out ~/we_work/a1 > ~/we_work/a1_profile.log 2>&1
$P we_agent_neuron.py --mode eval --adapter $AD --out ~/we_work/a1_eval.json --tweaks none --ev-n 400 > ~/we_work/a1_eval.log 2>&1
mkdir -p analysis/agent; cp ~/we_work/a1_* analysis/agent/ 2>/dev/null; rm -f $LK; echo AGENT_PROF_DONE
