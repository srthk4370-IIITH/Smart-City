#!/usr/bin/env bash
# Standalone, after final.sh F7 (deploy PASS): the split-4/6 A/B that failed in split6_ab (its request files had no
# trailing newline, so htpd dropped every request; fixed 2026-10-28). Runs sp6 + sp4 with the DEPLOYED reasoner on the
# 30 RWH prompts and compares with that reasoner's sp3 run (raw/split6 sp3 for rsn_v1, raw/acc_v2 sp3v2 for rsn_v2).
# Pick = fastest of sp4/sp6 with parse 30/30, sev=gold and label=gold >= sp3, at most 1 sev/label differing from sp3.
# If one wins: set reasoner_split on the board profile, restart the app, chaos2 3 incidents; any failure -> back to 3.
# Log: split_post.log. Nothing else changes.
M=/mnt/c/Users/hp/Desktop/qidk/proofs/2026-10-28_master; RF=/mnt/c/Users/hp/Desktop/qidk/proofs/2026-10-27_reasoner_fast; F=$M/final
A=/mnt/c/Users/hp/Desktop/qidk/Code/platform-tools/adb.exe; K=$M/BOARD_LOCK; W=/data/local/tmp/smart_city_edge; G=/data/local/tmp/gpu; RB=/data/local/tmp/rfast
exec >> $M/split_post.log 2>&1 < /dev/null
log(){ echo "$(date -u +%FT%TZ) $*"; }
w(){ wslpath -w "$1"; }
sh_(){ $A shell "$@" | tr -d '\r'; }
board(){ until $A get-state 2>/dev/null | grep -q device; do sleep 60; done; }
stop_app(){ sh_ 'am force-stop com.iiith.smartcityedge; pkill -x edge-agent; for p in $(pidof htpd_v8x2 htpd_v8r htpd_v8s htpd_v8t htpd_v8p htpd_v8p2 htpd_v7 htpd); do kill -TERM $p; done
  i=0; while [ $i -lt 120 ] && ps -A -o NAME= | grep -qE "^(htpd|edge-agent)"; do sleep 1; i=$((i+1)); done
  sleep 30; if ps -A -o NAME= | grep -qE "^(htpd|edge-agent|genie|llama)"; then echo STILL; else echo STOPPED; fi'; }
start_app(){ n0=$(sh_ "grep -c 'htpd: ready in' $W/state/htpd.log" | tail -1); sh_ 'am start -n com.iiith.smartcityedge/.MainActivity >/dev/null 2>&1'
  for i in $(seq 1 60); do sleep 5; [ "$(sh_ "grep -c 'htpd: ready in' $W/state/htpd.log" | tail -1)" -gt "${n0:-0}" ] && return 0; done; return 1; }
set_split(){ sh_ "cp $W/htpd_profile $W/htpd_profile.bak_split; grep -v '^reasoner_split=' $W/htpd_profile > $W/htpd_profile.t; echo reasoner_split=$1 >> $W/htpd_profile.t; mv $W/htpd_profile.t $W/htpd_profile; grep reasoner_split $W/htpd_profile"; }
log "=== split_post: wait for final F7"
until [ -e $F/.f7 ]; do sleep 120; done
grep -q '^PASS' $F/result 2>/dev/null || { log "final result not PASS ($(cat $F/result 2>/dev/null)): nothing to do"; exit 0; }
R=$(cat $F/reasoner); case $R in rsn_v2*) REF=sp3v2; RD=$RF/raw/acc_v2;; *) REF=sp3; RD=$RF/raw/split6;; esac
[ "$(cat $F/split)" = 3 ] || { log "deployed split is $(cat $F/split), not 3: nothing to do"; exit 0; }
board; while [ -e $K ] && [ $(( $(date +%s) - $(stat -c %Y $K) )) -lt 10800 ]; do log "BOARD_LOCK held: wait"; sleep 60; done
echo split_post > $K; ( while [ -e $K ]; do touch $K; sleep 600; done ) & TP=$!; trap 'kill $TP 2>/dev/null; rm -f $K' EXIT
for d in rreq_split4 rreq_split6; do sh_ "rm -rf $RB/$d"; $A push "$(w $RF/bench/$d)" $RB/ > /dev/null; done
sh_ "tail -c1 $RB/rreq_split6/q11.json | od -c | head -1"
printf '#!/system/bin/sh\ncd %s; [ -d ab ] && mv ab ab_prev_$(date +%%H%%M%%S)\nREQS="10 10 11 12 13 14 15 16 17 18 19" sh ab_board.sh "sp6x,htpd_v8x2,%s,GGML_HEXAGON_OPPOLL=1" "sp4x,htpd_v8x2,%s,GGML_HEXAGON_OPPOLL=1"\n' $RB $G/$R $G/$R > $M/run_split_post.sh
$A push "$(w $M/run_split_post.sh)" $RB/run_split_post.sh > /dev/null
sh_ "cd $RB; (setsid nohup sh run_split_post.sh > /dev/null 2>&1 < /dev/null &)"; log "A/B started: sp6x, sp4x with $R (ref $REF)"; sleep 120
until sh_ "tail -1 $RB/ab/ab.log 2>/dev/null" | grep -q "=== ab done"; do board; sleep 60; done
D=$RF/raw/split_post; rm -rf $D; $A pull $RB/ab "$(w $RF/raw)" > /dev/null; mv $RF/raw/ab $D; cp $RD/${REF}_q1[0-9]_*.json $D/
(cd $RF/scripts && REF=$REF python3 -I split_acc.py ../raw/split_post 10) > $D/acc.md; log "acc: $(grep -E '^\| sp' $D/acc.md | tr '\n' ' ')"
N=$(python3 - $D/acc.md $REF <<'P'
import sys
rows = {}
for l in open(sys.argv[1]):
    c = [x.strip() for x in l.strip().strip("|").split("|")]
    if len(c) >= 10 and c[0].startswith("sp"):
        rows[c[0]] = dict(n=int(c[1]), parse=int(c[2]), sev=int(c[3]), lab=int(c[4]), sevref=int(c[7]), labref=int(c[8]), s=float(c[9]))
b = rows.get(sys.argv[2]); best = "3"
if b:
    ok = [k for k in ("sp6x", "sp4x") if k in rows and rows[k]["parse"] == rows[k]["n"] >= 10 and rows[k]["sev"] >= b["sev"]
          and rows[k]["lab"] >= b["lab"] and rows[k]["sevref"] >= rows[k]["n"] - 1 and rows[k]["labref"] >= rows[k]["n"] - 1 and rows[k]["s"] < b["s"]]
    if ok: best = min(ok, key=lambda k: rows[k]["s"])[2]
print(best)
P
)
log "pick: split $N"
[ "$N" = 3 ] && { log "split-3 stays"; exit 0; }
r=$(stop_app); log "stop: $r"; [ "$r" = STOPPED ] || { log "ABORT: app not stopped; split-3 stays"; start_app; exit 1; }
set_split $N; start_app && log "app up with split $N" || log "app NOT up"
t0=$(date +%s); (cd $RF/scripts && python3 -I chaos2.py chaos 2 150); rc=$?
ok=$(python3 - $t0 <<'P'
import glob, json, os, sys
t0 = float(sys.argv[1]); n = d = 0
for f in glob.glob("/mnt/c/Users/hp/Desktop/qidk/proofs/2026-10-27_reasoner_fast/raw/*_incident.json"):
    if os.path.getmtime(f) < t0: continue
    i = json.load(open(f)).get("incident") or {}; n += 1; d += isinstance(i, dict) and i.get("state") == "done" and bool((i.get("final") or {}).get("valid"))
print(f"{d}/{n}")
P
)
split_at=$(sh_ "grep -o 'split at [0-9]* tokens into [0-9]* streams' $W/state/htpd.log | tail -1")
log "chaos rc=$rc done+valid $ok; htpd: $split_at"
if [ $rc = 0 ] && [ "$ok" = "3/3" ] && echo "$split_at" | grep -q "into $N streams"; then
  echo "$N" > $F/split_post_result; log "=== split $N LIVE"
else
  log "check failed: back to split 3"; stop_app > /dev/null; set_split 3; start_app && log "app up with split 3"; echo "3 (split $N failed the app check)" > $F/split_post_result
fi
log "=== split_post done"
