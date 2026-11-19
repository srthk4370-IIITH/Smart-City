cd /mnt/c/Users/hp/Desktop/qidk/proofs/2026-11-13_weight_edit
export HF_HUB_OFFLINE=1 TRANSFORMERS_OFFLINE=1 PYTHONWARNINGS=ignore TORCHINDUCTOR_COMPILE_THREADS=1 PYTHONUNBUFFERED=1
LK=/mnt/c/Users/hp/Desktop/qidk/proofs/2026-10-29_rsn_v3/GPU_LOCK
[ -e $LK ] && { echo busy; exit 0; }; echo "weight_edit tool_probe $(date)" > $LK
~/venvs/rsn/bin/python tool_probe.py 2>&1 | grep -v "Loading\|Triton" | tail -25 > ~/we_work/tool_probe.txt
rm -f $LK; echo PROBE_DONE
