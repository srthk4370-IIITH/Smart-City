# round-2 profile: under-grading flips (agent one level too low) -> severity-copy + critical-recall tables. After round 1.
cd /mnt/c/Users/hp/Desktop/qidk/proofs/2026-11-13_weight_edit
export HF_HUB_OFFLINE=1 TRANSFORMERS_OFFLINE=1 PYTHONWARNINGS=ignore TORCHINDUCTOR_COMPILE_THREADS=1 PYTHONUNBUFFERED=1
LK=/mnt/c/Users/hp/Desktop/qidk/proofs/2026-10-29_rsn_v3/GPU_LOCK
until grep -q T1B_DONE ~/detached/we_t1b.log 2>/dev/null; do sleep 120; done
until [ ! -e $LK ]; do sleep 60; done; echo "weight_edit neuron_p2 $(date)" > $LK
~/venvs/rsn/bin/python we_neuron.py --mode profile --skip-think --flip under --n-trust 200 --out ~/we_work/n2 > ~/we_work/n2_profile.log 2>&1
cp ~/we_work/n2_summary.json ~/we_work/n2_trust.tsv analysis/neuron/ 2>/dev/null; rm -f $LK; echo P2_DONE
