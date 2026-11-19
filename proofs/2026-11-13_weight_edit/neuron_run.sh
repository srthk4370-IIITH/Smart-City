# neuron surgery step 1: profile tables + base eval (r3-2800 only)
cd /mnt/c/Users/hp/Desktop/qidk/proofs/2026-11-13_weight_edit
export HF_HUB_OFFLINE=1 TRANSFORMERS_OFFLINE=1 PYTHONWARNINGS=ignore TORCHINDUCTOR_COMPILE_THREADS=1 PYTHONUNBUFFERED=1
LK=/mnt/c/Users/hp/Desktop/qidk/proofs/2026-10-29_rsn_v3/GPU_LOCK; P=~/venvs/rsn/bin/python
until [ ! -e $LK ]; do sleep 60; done; echo "weight_edit neuron $(date)" > $LK
[ -s ~/we_work/n1_summary.json ] || $P we_neuron.py --mode profile --out ~/we_work/n1 --n-think-easy 80 --n-think-hard 60 --n-trust 200 > ~/we_work/n1_profile.log 2>&1
$P we_neuron.py --mode eval --out ~/we_work/n1_eval.json --tweaks none > ~/we_work/n1_eval.log 2>&1
mkdir -p analysis/neuron; cp ~/we_work/n1_summary.json ~/we_work/n1_think.tsv ~/we_work/n1_trust.tsv ~/we_work/n1_eval.json analysis/neuron/
rm -f $LK; echo NEURON1_DONE
