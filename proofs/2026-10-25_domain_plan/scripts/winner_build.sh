#!/usr/bin/env bash
# Standalone merge + stage for the P3b queue winner (fixes the queue's c49 path; run in MAIN's shell after QUEUE_DONE_P3B.json):
#   bash winner_build.sh [TAG]   TAG default = winner in QUEUE_DONE_P3B.json (P3B05/P3B07/P3B10/T30/B50)
# mix uses m50_adapter (exact mixA50): P3Bxx = (1-a) m50 + a P3b; T30 = m50 + T30 (relative); B50 -> use b50_build.sh.
# Then (GPU, if ~/smartcity_runs/GPU_FREE_FOR_REASONER exists and no other llama-server runs) runtime-LoRA vs Q4_0 parity on fid200.
R=~/smartcity_runs/agents_v2_topup3f; D=/mnt/c/Users/hp/Desktop/qidk/proofs/2026-10-25_domain_plan; S=$D/scripts; STAGE=/mnt/c/Users/hp/Desktop/qidk/Code/models_stage
LG=$R/lora_gguf; M=$R/post/gguf/ft_mixA50_q4_0.gguf; H3E=/mnt/c/Users/hp/Desktop/qidk/Code/smart-city-edge-agent/training/v2/topup3e
exec >> $D/winner_build.log 2>&1 < /dev/null
W=${1:-$(python3 -c "import json;print(json.load(open('$D/QUEUE_DONE_P3B.json'))['winner'])")}; echo "=== $(date -u +%FT%TZ) winner_build $W"
C=$(cat $LG/p3b_last.src 2>/dev/null)
case $W in
  P3B*) a=$(python3 -c "print(int('${W#P3B}')/10)"); MIX="[[\"$R/m50_adapter\", $(python3 -c "print(round(1-$a,4))")], [\"$C\", $a]]"; SPEC="$LG/p3b_last.gguf:$a,$LG/m50.gguf:-$a";;
  T30) MIX="[[\"$R/m50_adapter\", 1.0], [\"$R/p2/T30\", 1.0]]"; SPEC="$LG/p2_T30.gguf:1.0";;
  B50) exec bash $S/b50_build.sh;;
  *) echo "no winner ($W): nothing to build"; exit 0;;
esac
mkdir -p $R/post/$W; echo "{\"mix\": $MIX, \"chosen\": \"$W\"}" > $R/post/$W/choice.json; rm -rf $R/post/$W/merged
[ -s $R/post/gguf/ft_${W}_q4_0.gguf ] || bash /mnt/c/Users/hp/Desktop/qidk/Code/smart-city-edge-agent/training/v2/topup3f/post_3f.sh none $W
Q=$R/post/gguf/ft_${W}_q4_0.gguf; [ -s $Q ] || { echo "BUILD FAILED"; tail -5 $R/post/$W/post.log; exit 1; }
cp $Q $STAGE/ft_${W}_q4_0.gguf.part && md5sum $STAGE/ft_${W}_q4_0.gguf.part | cut -d" " -f1 > $STAGE/ft_${W}_q4_0.gguf.md5 && mv -f $STAGE/ft_${W}_q4_0.gguf.part $STAGE/ft_${W}_q4_0.gguf
echo "staged $STAGE/ft_${W}_q4_0.gguf md5 $(cat $STAGE/ft_${W}_q4_0.gguf.md5)"
if [ -e ~/smartcity_runs/GPU_FREE_FOR_REASONER ] && ! pgrep -f llama-server >/dev/null; then
  source ~/venvs/train/bin/activate; FD=$R/eval_fid200
  for t in ${W}_LR ${W}_Q4; do mod=$M; sp="$SPEC"; [ $t = ${W}_Q4 ] && { mod=$Q; sp=""; }
    (cd $H3E && LORA_SCALED="$sp" python $S/host_eval_paced.py run --out $FD --model $mod --tag $t --cuda --threads 2 --np 4 >> $FD/eval_w_$t.log 2>&1); done
  python3 - $FD/eval/${W}_LR/samples.jsonl $FD/eval/${W}_Q4/samples.jsonl $D/diag/parity_$W.json <<'P'
import json, sys
a = {json.loads(l)["id"]: json.loads(l) for l in open(sys.argv[1])}; b = {json.loads(l)["id"]: json.loads(l) for l in open(sys.argv[2])}
ids = [i for i in a if i in b]; k = ("pattern", "status", "likely_cause")
r = {"n": len(ids), "same_answer": sum(all((a[i].get("pred") or {}).get(x) == (b[i].get("pred") or {}).get(x) for x in k) for i in ids)}
json.dump(r, open(sys.argv[3], "w")); print("parity", r)
P
else echo "parity skipped (GPU not free)"; fi
