# Automated reasoner chain (owner 2026-11-16): final agent -> v2 agent reruns (GPU) -> v2 build+checks (READY) -> fine-tune on r3_edit_C1
QP=/mnt/c/Users/hp/Desktop/qidk/proofs; R=$QP/2026-11-13_v3_data/rsn; W=$R/data/final_v2/work; LK=$QP/2026-10-29_rsn_v3/GPU_LOCK
st() { echo "$(date -Is) $*"; echo "- $(date -u +%FT%H:%MZ) [rsn_auto] $*" >> $QP/AGENT_REGISTRY.md; }
until [ -s ~/smartcity_runs/agt_topup/FINAL ]; do sleep 120; done
M=$(head -1 ~/smartcity_runs/agt_topup/FINAL | awk '{print $1}'); [ -s "$M" ] || { st "FINAL has no gguf ($M)"; exit 2; }
st "final agent $M: rerunning v2 windows on GPU"
while p=$(cat ~/detached/rsn_v2_s1.pid 2>/dev/null) && kill -0 $p 2>/dev/null; do sleep 30; done
[ -s $W/agent_out.jsonl ] && mv $W/agent_out.jsonl $W/agent_out.snap1750_partial.jsonl; rm -f $W/agent_out.jsonl.STOP
until [ ! -e $LK ]; do sleep 60; done; echo "rsn_auto v2_agent_gpu $(date -Is)" > $LK
cd $R && AGT_MODEL=$M LD_LIBRARY_PATH=$HOME/llama-cuda-b11815/bin nice -n 10 python3 v2_agent_run_gpu.py $W/windows.jsonl $W/agent_out.jsonl > $W/agent_gpu.log 2>&1
rm -f $LK; st "v2 agent reruns: $(wc -l < $W/agent_out.jsonl) outputs"
bash $R/v2_stage2.sh > ~/detached/rsn_v2_s2b.log 2>&1
[ -e $R/data/final_v2/READY ] || { st "dataset v2 NOT ready: $(tail -n 2 ~/detached/rsn_v2_s2b.log | tr '\n' ' ')"; exit 3; }
echo /mnt/c/Users/hp/qidk_models/r3_edit_C1 > $QP/2026-11-13_v3_train/rsn_ft/chain/BASE
st "dataset v2 READY -> starting reasoner fine-tune on r3_edit_C1"
bash $QP/detach.sh rsn_ft_chain $QP/2026-11-13_v3_train/rsn_ft/ft_chain.sh
