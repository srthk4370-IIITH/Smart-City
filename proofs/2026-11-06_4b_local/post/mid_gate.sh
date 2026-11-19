#!/usr/bin/env bash
# mid_gate.sh: owner 2026-11-09 "gate now, then resume". Mid-run core gate of the step-2000 best checkpoint, then the
# training resumes. Separate from post_chain.sh (own GGUF name, own gate dir, own STOP file), so the end-of-run chain is
# untouched. Steps: clean stop of the laptop run -> copy ckpt_best_2000 adapter -> export_4b.sh (Q4_0, NTFS work dir)
# -> gate_4b.sh core steps (rep, rwh2, dev3, score1 = the verdict) -> stop the gate before the informational suites
# -> ctl_4b.sh start. Status lines [mid_gate] in kaggle/STATUS.md. Launch: proofs/detach.sh mid_gate <this> + keepalive.
SCRIPT=mid_gate; source /mnt/c/Users/hp/Desktop/qidk/proofs/2026-10-29_rsn_v3/kaggle/local/guard.sh
H=$QIDK/proofs/2026-11-06_4b_local; P=$H/post; R=$HOME/smartcity_runs/rsn3_4b_r3
STEP=${STEP:-2000}; NAME=rsn_v3_4b_r3_s$STEP; A=$HOME/smartcity_runs/rsn3_4b_r3_mid$STEP
export GATE_OUT=$P/gate_s$STEP GATE_TAG=rsn_v3_4b_s$STEP STOPF=$P/STOP_mid LOGD=$P/export_s$STEP
rm -f "$STOPF"
resume() { bash "$H/ctl_4b.sh" start | tail -1 | while read l; do status "resume training: $l"; done; }
status "start: stop training, export + core gate of ckpt_best_$(printf %04d $STEP)"
bash "$H/ctl_4b.sh" stop > /dev/null 2>&1
pgrep -f "python.*train_rsn3.py.*rsn3_4b_r3" > /dev/null && { status "trainer still running: abort"; exit 1; }
mkdir -p "$A"; cp -a "$R/ckpt_best_$(printf %04d $STEP)/." "$A/" || { status "no ckpt_best_$STEP"; resume; exit 1; }
status "export $NAME from $A"
bash "$P/export_4b.sh" "$HOME/models/qwen3.5-4b" "$A" "$NAME"; rc=$?
G=$QIDK/Code/models_stage/${NAME}_q4_0.gguf
[ $rc = 0 ] && [ -s "$G" ] || { status "export failed rc=$rc: resume training"; resume; exit 1; }
status "gate (core) $G -> $GATE_OUT"
bash "$P/gate_4b.sh" "$G" &
GP=$!
while kill -0 $GP 2>/dev/null; do
  if [ -e "$GATE_OUT/.m/score1.done" ]; then status "core verdict written: stopping gate before informational suites"; touch "$STOPF"; break; fi
  sleep 60
done
for i in $(seq 1 60); do kill -0 $GP 2>/dev/null || break; sleep 10; done
kill $GP 2>/dev/null; pkill -f "llama-server.*$NAME" 2>/dev/null
grep -q "^post_4b" "$V3/GPU_LOCK" 2>/dev/null && rm -f "$V3/GPU_LOCK"
rm -f "$STOPF"
status "verdict: $(grep -m1 -E 'PASS|FAIL' $GATE_OUT/GATE.md 2>/dev/null | cut -c1-120)"
resume
