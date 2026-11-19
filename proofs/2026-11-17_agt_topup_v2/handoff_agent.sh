#!/bin/bash
# waits for auto_k.sh (and its auto_v2 selection) to end, then writes ~/smartcity_runs/FINAL_AGENT (line 1 gguf path, line 2 reason). Not on STOP.
PF=$(dirname "$(readlink -f "$0")"); S=$HOME/smartcity_runs; K2=$S/agt_topup_k2; K2B=$S/agt_topup_k2b; G0=$S/agt_topup_k/post/s0300/agt3_s0300_q4_0.gguf
while pgrep -f "agt_topup_v2/auto_k.sh|agt_topup_v2/auto_v2.sh|select_v2" > /dev/null; do sleep 120; done  # also wait for the laptop selection
[ -e $PF/STOP ] && { echo "STOP file: no handoff"; exit 0; }
F=""; for d in $K2 $K2B; do [ -s $d/FINAL_K2 ] && g=$(sed -n 's/^gguf=//p' $d/FINAL_K2) && [ -s "$g" ] && F=$g && W=$d && break; done
# owner 2026-11-18: discuss first if no winner / tool calls not learned / something very weak -> AGENT_REVIEW signal, no FINAL_AGENT
SUM=$(ls -t $PF/data/kaggle_eval_r2/SUMMARY.md $PF/data/kaggle_eval/SUMMARY.md 2>/dev/null | head -1)
WHY=$(python3 - "$SUM" "$F" <<'PY'
import sys,re
p,f=sys.argv[1],sys.argv[2]
if not f: print("no v2 winner"); sys.exit()
try: rows=[l.split("|")[1:-1] for l in open(p) if l.startswith("| s")]
except Exception: print("no eval summary"); sys.exit()
ref=[r for r in rows if r[0].strip()=="s0300"]; best=max((r for r in rows if r[0].strip()!="s0300"), key=lambda r: float(r[7] or 0), default=None)
if not best or not ref: print("eval rows missing"); sys.exit()
v,c=float(best[1]),float(best[3]); v0=float(ref[0][1])
w=[]
if c < 0.5: w.append("tool calls not learned (t1 call %.2f)"%c)
if v < v0-0.03: w.append("real val %.3f vs s0300 %.3f"%(v,v0))
print("; ".join(w))
PY
)
WHY="${WHY:-no red flags}; Claude reviews every metric first (owner 2026-11-18)"
if [ -n "$WHY" ]; then printf 'AGENT REVIEW NEEDED (owner wants to discuss before agent-output rows): %s
summary: %s
' "$WHY" "$SUM" > $S/AGENT_REVIEW; echo "AGENT_REVIEW: $WHY"; exit 0; fi
if [ -n "$F" ]; then printf '%s\nv2 winner selected on the laptop Q4_0 (%s/FINAL_K2), dynamic weighted rule\n' "$F" "$W" > $S/FINAL_AGENT.tmp
else [ -s $G0 ] || { echo "s0300 gguf missing"; exit 1; }
  printf '%s\nv2 NOT GOOD or failed (%s): deployed s0300 stays\n' "$G0" "$(tail -n 1 $PF/DECISION.md 2>/dev/null | cut -c1-80)" > $S/FINAL_AGENT.tmp; fi
mv $S/FINAL_AGENT.tmp $S/FINAL_AGENT; echo "FINAL_AGENT: $(head -1 $S/FINAL_AGENT)"
