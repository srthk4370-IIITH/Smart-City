#!/usr/bin/env bash
# gate_now_r2.sh: eval 2026-11-04 12:00 IST. All gate inputs of g2b_r2 are done (rwh, rwh2, dev, p0 run, chat dev v3);
# gate_eval.sh is still on the informational test_r2 suite (hours). Score the gate now with the same command, into
# gate/g2b_r2 (gate.json/GATE.md); test_r2 keeps running and may rescore at its end (same inputs -> same verdict).
KG=/mnt/c/Users/hp/Desktop/qidk/proofs/2026-10-29_rsn_v3/kaggle; R1=/mnt/c/Users/hp/Desktop/qidk/proofs/2026-10-25_reasoner_final
TAG=rsn_v3_g2b_r2; OUT=$KG/gate/g2b_r2; DEVMD5=$(md5sum < /mnt/c/Users/hp/Desktop/qidk/proofs/2026-10-29_rsn_v3/data/chat3_dev.jsonl | cut -c1-12)
CB=$KG/gate/rsn_v1_chatdev3_$DEVMD5.jsonl; RWH2=$(ls -t $KG/build/*/heldout/incidents_rwh2.jsonl 2>/dev/null | head -1)
ls -la $CB $RWH2 | cut -c30-
(cd "$R1/eval" && python3 p0_score.py "$TAG" ft612 2>&1 | tail -2) > "$OUT/p0.txt"
python3 "$KG/local/gate_score.py" --new "$TAG" --base ft612 --chat-new "$OUT/chatdev3_v3.jsonl" --chat-base "$CB" --out "$OUT" \
  --p0 "$OUT/p0.txt" --rwh2 "$RWH2" > "$OUT/gate_score.log" 2>&1
rc=$?; echo "rc=$rc"
echo "- $(date '+%F %T') [gate_now_r2] scored early (test_r2 informational still running): rc=$rc" >> $KG/STATUS.md
cat $OUT/GATE.md
