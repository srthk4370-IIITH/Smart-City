#!/usr/bin/env bash
# rsn_p2_gate.sh: small strict gate (<= ~1 h GPU) of the part-2 top-up vs the fine-tune best -> proofs/2026-11-18_rsn_p2/GATE.md (last line RESULT: PASS|FAIL)
#  1 r3 slice / r4 incidents: the trainer's own keep-best gen evals (same subsets, --gen-n 40 / --gen-r4-n 60) from best.json of both runs;
#    PASS: p2 r3 >= ft r3 - 0.01 and p2 r4 >= ft r4 - 0.02
#  2 new families' held-out rows (data/final_v2/tests/dev_p2.jsonl): both GGUFs (Q4_0, host llama-server, think 1) -> rsn_p2_score.py;
#    PASS: p2 accuracy (severity + id/fault hygiene) > ft accuracy
# FAST (owner 2026-11-18, <= 30 min): fixed stratified subset of dev_p2 (8 per family, seed 18); ONE Q4_0 export (the p2 candidate); the ft best's GGUF/results are reused if they exist.
# DYNAMIC RULE: PASS if weighted delta (r3 .35, r4 .35, new families .30; p2 minus ft) >= +0.02, no slice drops > 0.10, r4 (incidents) and new-family severity drop <= 0.03, p2 JSON validity >= 0.98.
# (old per-slice rules below replaced) exports of the checkpoints via export_ft.sh; GPU only under GPU_LOCK (waited for, nothing killed).
SCRIPT=rsn_p2_gate; source /mnt/c/Users/hp/Desktop/qidk/proofs/2026-10-29_rsn_v3/kaggle/local/guard.sh
R=$QIDK/proofs/2026-11-13_v3_data/rsn; FT=$QIDK/proofs/2026-11-13_v3_train/rsn_ft; OUT=$QIDK/proofs/2026-11-18_rsn_p2; mkdir -p $OUT/res
RFT=~/smartcity_runs/rsn3_4b_v3ft; RP2=~/smartcity_runs/rsn3_4b_v3ft_p2; BASE=$(cat $FT/chain/BASE)
DEV=$R/data/final_v2/tests/dev_p2.jsonl; LC=~/llama-cuda-b11815; LOCK=$V3/GPU_LOCK; PORT=18199; PY=~/venvs/rsn/bin/python
STAGE=$QIDK/Code/models_stage; STATUS=$OUT/STATUS.md
[ -s "$DEV" ] || die "no dev_p2.jsonl" 2
python3 - "$DEV" "$OUT/dev_p2_sub.jsonl" <<'PY'
import json,random,sys,collections
R=random.Random(18); g=collections.defaultdict(list)
for l in open(sys.argv[1],encoding="utf-8"):
    if l.strip(): r=json.loads(l); g[r.get("p2_family","?")].append(l if l.endswith("
") else l+"
")
open(sys.argv[2],"w",newline="
",encoding="utf-8").writelines(x for f in sorted(g) for x in R.sample(g[f],min(8,len(g[f]))))
PY
DEV=$OUT/dev_p2_sub.jsonl
top() { python3 -c "import json,sys;b=json.load(open('$1/best.json'));print(b['top'][0][1]); " ; }
bh() { python3 - "$1" "$2" <<'PY'
import json,sys
b=json.load(open(sys.argv[1]+'/best.json')); s=int(sys.argv[2])
h=[x for x in b['history'] if x['step']==s][0]; print(h['r3'],h['r4'],h['combined'])
PY
}
SF=$(top $RFT); SP=$(top $RP2); [ -n "$SF" ] && [ -n "$SP" ] || die "no best step" 2
CF=$(printf "%s/ckpt_best_%04d" $RFT $SF); CP=$(printf "%s/ckpt_best_%04d" $RP2 $SP)
read FR3 FR4 FC < <(bh $RFT $SF); read PR3 PR4 PC < <(bh $RP2 $SP)
status "gate: ft best step $SF (r3 $FR3 r4 $FR4), p2 best step $SP (r3 $PR3 r4 $PR4)"
GF0=$STAGE/rsn_v3_4b_ft${SF}_q4_0.gguf; [ -s "$GF0" ] || bash $FT/post/export_ft.sh $BASE $CF rsn_v3_4b_ft$SF || die "export ft best" 3
bash $FT/post/export_ft.sh $BASE $CP rsn_v3_4b_p2 || die "export p2 best" 3
GF=$STAGE/rsn_v3_4b_ft${SF}_q4_0.gguf; GP=$STAGE/rsn_v3_4b_p2_q4_0.gguf
run_model() {   # run_model <gguf> <tag>
  local t0=$(date +%s)
  until { [ ! -e "$LOCK" ] || grep -q "^rsn_p2_gate " "$LOCK"; } && [ "$(nvidia-smi --query-gpu=memory.used --format=csv,noheader,nounits | head -1 | tr -dc 0-9)" -lt 800 ]; do sleep 120; done
  echo "rsn_p2_gate $(date -Is) pid=$$" > "$LOCK"
  LD_LIBRARY_PATH=$LC/bin nice -n 10 $LC/bin/llama-server -m "$1" -ngl 99 -cram 256 -c 12288 -np 1 --jinja -t 2 -tb 2 --host 127.0.0.1 --port $PORT --no-webui > $OUT/res/server_$2.log 2>&1 &
  local sp=$!; for i in $(seq 90); do curl -sf http://127.0.0.1:$PORT/health >/dev/null && break; sleep 5; done
  timeout 900 python3 $FT/post/run_ft.py --think 1 --tag $2 --port $PORT --resdir $OUT/res v4 --name dev_p2 --file $DEV --tools $R/data/final_v2/tools_v4.json >> $OUT/res/run_$2.log 2>&1
  kill $sp 2>/dev/null; wait $sp 2>/dev/null; grep -q "^rsn_p2_gate " "$LOCK" 2>/dev/null && rm -f "$LOCK"
  status "gate: $2 done in $(( $(date +%s) - t0 )) s"
}
[ -s $OUT/res/ft/dev_p2.jsonl ] && [ "$(wc -l < $OUT/res/ft/dev_p2.jsonl)" -ge "$(wc -l < $DEV)" ] || run_model $GF ft; run_model $GP p2
SC=$(python3 $R/rsn_p2_score.py $DEV $OUT/res/ft/dev_p2.jsonl $OUT/res/p2/dev_p2.jsonl) || die "score" 3
echo "$SC" > $OUT/new_family_scores.json
python3 - "$SC" "$FR3" "$FR4" "$PR3" "$PR4" "$SF" "$SP" "$GP" > $OUT/GATE.md <<'PY'
import json,sys
sc=json.loads(sys.argv[1]); fr3,fr4,pr3,pr4=map(float,sys.argv[2:6]); sf,sp,gp=sys.argv[6:9]
dr3,dr4,dn=pr3-fr3,pr4-fr4,sc["p2"]["acc"]-sc["ft"]["acc"]; wd=.35*dr3+.35*dr4+.30*dn
c1=dr3>=-0.10 and dr4>=-0.10 and dn>=-0.10; c2=dr4>=-0.03 and sc["p2"]["sev"]-sc["ft"]["sev"]>=-0.03; c3=wd>=0.02; c4=sc["p2"].get("valid",1)>=0.98
ok=c1 and c2 and c3 and c4
print("RULE: PASS if weighted delta (r3 .35, r4 .35, new families .30) >= +0.02, no slice drop > 0.10, r4 and new-family severity drop <= 0.03, JSON validity >= 0.98
")
print("weighted delta %+.4f (>=0.02 %s); slice drops ok %s; safety (r4, severity) ok %s; JSON validity %.3f ok %s
" % (wd,c3,c1,c2,sc["p2"].get("valid",1),c4))
print("# Reasoner part 2 gate (fine-tune best step %s vs p2 best step %s)\n" % (sf,sp))
print("| slice | ft best | p2 best | rule | ok |\n|---|---|---|---|---|")
print("| r3 slice (gen eval) | %.4f | %.4f | weighted | %+.3f |" % (fr3,pr3,dr3))
print("| r4 incidents (gen eval) | %.4f | %.4f | weighted, safety | %+.3f |" % (fr4,pr4,dr4))
print("| new families held-out, n=%d (severity + id hygiene) | %.4f | %.4f | weighted | %+.3f |" % (sc["p2"]["n"],sc["ft"]["acc"],sc["p2"]["acc"],dn))
print("\nseverity-only: ft %.4f p2 %.4f; hygiene: ft %.4f p2 %.4f\n" % (sc["ft"]["sev"],sc["p2"]["sev"],sc["ft"]["hyg"],sc["p2"]["hyg"]))
print("per family [n, sev ok, hygiene ok, both]: ft %s\n p2 %s\n" % (json.dumps(sc["ft"]["per_family"]),json.dumps(sc["p2"]["per_family"])))
print("candidate GGUF: %s (not deployed)\n" % gp)
print("RESULT: %s" % ("PASS" if ok else "FAIL"))
PY
tail -1 $OUT/GATE.md
