#!/bin/bash
# writes proofs/2026-11-18_rsn_p2/READY_FOR_DEPLOY.md (never deploys)
QP=/mnt/c/Users/hp/Desktop/qidk/proofs; O=$QP/2026-11-18_rsn_p2; ST=/mnt/c/Users/hp/Desktop/qidk/Code/models_stage; V2=$QP/2026-11-17_agt_topup_v2
FA=~/smartcity_runs/FINAL_AGENT; AG=$(head -1 $FA 2>/dev/null); AR=$(sed -n 2p $FA 2>/dev/null)
RG=$ST/rsn_v3_4b_p2_q4_0.gguf; RWHY="p2 PASSED the gate"
grep -q "^RESULT: PASS" $O/GATE.md 2>/dev/null || { RG=$(ls -t $ST/rsn_v3_4b_ft*_q4_0.gguf 2>/dev/null | head -1); RWHY="p2 did NOT pass the gate: fine-tune best stays"; }
tool=0; grep -q "FINAL_K2" <<<"$AR$AG" || true; case "$AG" in *agt_topup_k2*|*agt_topup_k2b*) tool=1;; esac
m5() { [ -s "$1.md5" ] && cut -d' ' -f1 "$1.md5" || md5sum "$1" | cut -d' ' -f1; }
{ echo "# READY FOR DEPLOY (not deployed)"; echo
  echo "## Agent"; echo "- GGUF: $AG"; echo "- md5: $(m5 "$AG")"; echo "- reason: $AR"
  echo "- numbers: $(head -c 600 $V2/DECISION.md $V2/DECISION_r2.md 2>/dev/null | tr '\n' ' ')"; echo
  echo "## Reasoner"; echo "- GGUF: $RG"; echo "- md5: $(m5 "$RG")"; echo "- $RWHY"; echo "- audit: $(grep -m1 'bad' $O/AUDIT.md 2>/dev/null)"
  echo '```'; head -n 14 $O/GATE.md 2>/dev/null | cut -c1-200; echo '```'; echo
  echo "## Deploy steps (owner runs)"
  echo "1. Stop the app (one NPU/llama client at a time; wait for exit)."
  echo "2. Push both GGUFs to the board as .part, check md5 on device, then mv over the old names (agent: $(basename "$AG"), reasoner: $(basename "$RG"))."
  echo "3. Profile: set the model line to the agent GGUF and the reasoner_model line to the reasoner GGUF; agent_ctx 1280; HTPD_JSON_ABORT=1."
  if [ $tool = 1 ]; then echo "4. agent_tools=1 (final agent is v2 with tool calls)."; else echo "4. agent_tools stays off (final agent is the s0300 v1 winner without tool calls)."; fi
  echo "5. Start the app and run one real-input check."; } > $O/READY_FOR_DEPLOY.md
