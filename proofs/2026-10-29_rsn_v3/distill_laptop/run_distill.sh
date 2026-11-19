#!/bin/bash
# run_distill.sh <outdir> <hours> [extra distill_llama.py args]  -- distil, then select (only when every record is done
# or the run stopped on its wall cap), md5. Started via proofs/detach.sh (+ a hidden wsl.exe keepalive, see README.md).
D=/mnt/c/Users/hp/Desktop/qidk/proofs/2026-10-29_rsn_v3/distill_laptop; V=$D/..; OUT=$1; H=$2; shift 2
source ~/venvs/rsn/bin/activate; export HF_HUB_OFFLINE=1 TRANSFORMERS_OFFLINE=1 TOKENIZERS_PARALLELISM=false PATH=$PATH:/usr/lib/wsl/lib
mkdir -p $OUT; cd $D
python distill_llama.py --dir $OUT --hours $H --set dev=$V/data/chat3_dev.jsonl --set train=$V/data/chat3_train.jsonl "$@"
rc=$?
if [ -e $OUT/STOP ] && ! grep -q "wall cap" $OUT/STATUS.md 2>/dev/null; then echo "stopped by STOP: no selection (rerun to resume)"; exit $rc; fi
bash $D/finalize.sh $OUT
