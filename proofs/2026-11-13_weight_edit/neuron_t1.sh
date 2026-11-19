# neuron tweak round 1 (group tests). Waits for the GPU lock (agents first).
cd /mnt/c/Users/hp/Desktop/qidk/proofs/2026-11-13_weight_edit
export HF_HUB_OFFLINE=1 TRANSFORMERS_OFFLINE=1 PYTHONWARNINGS=ignore TORCHINDUCTOR_COMPILE_THREADS=1 PYTHONUNBUFFERED=1
LK=/mnt/c/Users/hp/Desktop/qidk/proofs/2026-10-29_rsn_v3/GPU_LOCK
# agents first: wait until every agt_v3 snapshot on the laptop has a dev score
R=~/smartcity_runs/agt_v3; until [ -z "$(for d in $R/run/snap_*; do [ -s $R/post/$(basename $d)/dev_score.json ] || echo x; done)" ]; do sleep 300; done
until [ ! -e $LK ] && [ "$(nvidia-smi --query-gpu=memory.used --format=csv,noheader,nounits | head -1 | tr -dc 0-9)" -lt 800 ]; do sleep 120; done
echo "weight_edit neuron_t1 $(date)" > $LK
T=tweaks; ~/venvs/rsn/bin/python we_neuron.py --mode eval --out ~/we_work/t1_eval.json --ev-easy 50 --ev-hard 30 --ev-trust 60 --nll-rows 15 \
  --tweaks none,$T/A1_rew1969.json,$T/A2_rew4.json,$T/A3_dial_boost.json,$T/B1_agentnormal_det.json,$T/B2_det_plus_harm.json > ~/we_work/t1.log 2>&1
cp ~/we_work/t1_eval.json analysis/neuron/; rm -f $LK; echo T1_DONE
