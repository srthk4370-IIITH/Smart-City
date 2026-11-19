cd /mnt/c/Users/hp/Desktop/qidk/proofs/2026-11-13_weight_edit
export HF_HUB_OFFLINE=1 TRANSFORMERS_OFFLINE=1 PYTHONWARNINGS=ignore TORCHINDUCTOR_COMPILE_THREADS=1 PYTHONUNBUFFERED=1
LK=/mnt/c/Users/hp/Desktop/qidk/proofs/2026-10-29_rsn_v3/GPU_LOCK
until grep -q T1_DONE ~/detached/we_t1.log 2>/dev/null; do sleep 120; done
until [ ! -e $LK ]; do sleep 30; done; echo "weight_edit neuron_t1b $(date)" > $LK
cp ~/we_work/t1_eval.json ~/we_work/t1b_eval.json 2>/dev/null
~/venvs/rsn/bin/python we_neuron.py --mode eval --out ~/we_work/t1b_eval.json --ev-easy 50 --ev-hard 30 --ev-trust 60 --nll-rows 15 \
  --tweaks none,tweaks/A1g3_rew1969.json,tweaks/A1g6_rew1969.json,tweaks/A2g_rew4.json > ~/we_work/t1b.log 2>&1
cp ~/we_work/t1b_eval.json analysis/neuron/; rm -f $LK; echo T1B_DONE
