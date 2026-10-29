#!/usr/bin/env bash
# 2026-10-29: reasoner latency, split "3r" (fork after label) vs "3" on the board, rsn_v1, htpd_v8x3, q10-q19 (+ warm-up).
# Deploy rule: parse 10/10, severity+label identical to "3" on >= 9/10, mean time <= 0.95 x "3" -> profile reasoner_split=3r,
# then chaos 2 + fastcheck; any failure -> reasoner_split=3. Needs the deploy2 build (Go knows "3r"). Cutoff 11:00 IST.
M=/mnt/c/Users/hp/Desktop/qidk/proofs/2026-10-28_master; I=$M/improve2; K=$M/BOARD_LOCK; RF=/mnt/c/Users/hp/Desktop/qidk/proofs/2026-10-27_reasoner_fast
A=/mnt/c/Users/hp/Desktop/qidk/Code/platform-tools/adb.exe; RB=/data/local/tmp/rfast; W=/data/local/tmp/smart_city_edge; D=$M/split3r; mkdir -p $D
exec >> $D/split3r.log 2>&1 < /dev/null
log(){ echo "$(date -u +%FT%TZ) $*"; }; st(){ echo "$*" >> $I/STATUS.md; log "$*"; }
w(){ wslpath -w "$1"; }; sh_(){ $A shell "$@" | tr -d '\r'; }
setp(){ f=$1; k=$2; v=$3; grep -v "^$k=" $f > $f.t; echo "$k=$v" >> $f.t; mv $f.t $f; }
CUT=$(date -d "2026-10-29 05:30 UTC" +%s)
stop_app(){ sh_ 'am force-stop com.iiith.smartcityedge; pkill -x edge-agent; for p in $(pidof htpd_v8x3 htpd_v8x2 htpd); do kill -TERM $p; done
  i=0; while [ $i -lt 120 ] && ps -A -o NAME= | grep -qE "^(htpd|edge-agent)"; do sleep 1; i=$((i+1)); done
  sleep 30; if ps -A -o NAME= | grep -qE "^(htpd|edge-agent|genie|llama)"; then echo STILL; else echo STOPPED; fi'; }
start_app(){ n0=$(sh_ "grep -c 'htpd: ready in' $W/state/htpd.log" | tail -1); sh_ 'am start -n com.iiith.smartcityedge/.MainActivity >/dev/null 2>&1'
  for i in $(seq 1 60); do sleep 5; [ "$(sh_ "grep -c 'htpd: ready in' $W/state/htpd.log" | tail -1)" -gt "${n0:-0}" ] && return 0; done; return 1; }
until grep -q "=== improve done" $I/improve.log 2>/dev/null; do sleep 30; done
[ $(date +%s) -lt $CUT ] || { st "- 3r skipped: after 11:00 IST"; exit 0; }
while [ -e $K ] && [ $(( $(date +%s) - $(stat -c %Y $K) )) -lt 10800 ]; do sleep 30; done
echo split3r > $K; trap 'rm -f $K' EXIT
sed -i 's/\r$//' $RF/scripts/ab_board.sh
$A push "$(w $RF/scripts/ab_board.sh)" $RB/ab_board.sh > /dev/null; $A push "$(w $RF/bench/rreq_split3r)" $RB/ > /dev/null
printf '#!/system/bin/sh\ncd %s; [ -d ab ] && mv ab ab_prev_$(date +%%H%%M%%S)\nREQS="10 10 11 12 13 14 15 16 17 18 19" sh ab_board.sh "spxa,htpd_v8x3,-,GGML_HEXAGON_OPPOLL=1" "spra,htpd_v8x3,-,GGML_HEXAGON_OPPOLL=1"\n' $RB > $D/run.sh
$A push "$(w $D/run.sh)" $RB/run_3r.sh > /dev/null
$A shell "cd $RB; (setsid nohup sh run_3r.sh > /dev/null 2>&1 < /dev/null &)"; log started; sleep 120
t0=$(date +%s); until sh_ "tail -1 $RB/ab/ab.log 2>/dev/null" | grep -q "=== ab done" || [ $(( $(date +%s) - t0 )) -gt 3600 ]; do sleep 30; done
rm -rf $D/raw; $A pull $RB/ab "$(w $D)" > /dev/null; mv $D/ab $D/raw
python3 - $D/raw $RF > $D/result.txt <<'P'
import glob, json, re, sys
d, rf = sys.argv[1], sys.argv[2]
PR = [json.loads(l) for l in open(rf + "/bench/prompts.jsonl", encoding="utf-8")]
def load(n):
    o = {}
    for p in glob.glob(f"{d}/{n}_q*_*.json"):
        q, k = map(int, re.search(r"_q(\d+)_(\d+)\.json", p).groups())
        if k == 0: continue
        x = next((json.loads(l) for l in open(p, encoding="utf-8") if '"outputs"' in l), None)
        j = None
        if x:
            try: j = json.loads(x["outputs"][0]["text"])
            except Exception: pass
        o[q] = (j, x["total_ms"] / 1000 if x else None)
    return o
a, b = load("spxa"), load("spra")
qs = range(10, 20); same = parse = 0; ta = []; tb = []
for q in qs:
    ja, sa = a.get(q, (None, None)); jb, sb = b.get(q, (None, None))
    parse += jb is not None
    if ja and jb and (ja["severity"], ja["label"], ja["title"]) == (jb["severity"], jb["label"], jb["title"]): same += 1
    if sa and sb: ta.append(sa); tb.append(sb)
    g = json.loads(PR[q]["gold"])
    print(f"q{q} 3: {sa} s  3r: {sb} s  gold {g['severity']}/{g['label']}  3={ja and (ja['severity'], ja['label'])}  3r={jb and (jb['severity'], jb['label'])}")
    if jb: print("   3r explanation:", jb.get("explanation", "")[:200]); print("   3  explanation:", (ja or {}).get("explanation", "")[:200])
ma, mb = sum(ta) / max(1, len(ta)), sum(tb) / max(1, len(tb))
ok = parse == 10 and same >= 9 and mb <= 0.95 * ma
print(f"SUMMARY parse {parse}/10 same sev+label+title {same}/10 mean 3 {ma:.1f} s 3r {mb:.1f} s ({100*(mb-ma)/ma:+.1f}%) DEPLOY={int(ok)}")
P
st "- 3r A/B: $(grep SUMMARY $D/result.txt)"
if grep -q "DEPLOY=1" $D/result.txt && [ $(date +%s) -lt $CUT ] && grep -q "I2 DEPLOYED" $I/STATUS.md; then
  sh_ "cat $W/htpd_profile" > $D/profile.3; cp $D/profile.3 $D/profile.3r; setp $D/profile.3r reasoner_split 3r
  r=$(stop_app); log "stop $r"
  if [ "$r" = STOPPED ]; then
    $A push "$(w $D/profile.3r)" $W/htpd_profile.part > /dev/null && sh_ "mv -f $W/htpd_profile.part $W/htpd_profile"
    ok=0; start_app && ok=1; sleep 20
    if [ $ok = 1 ]; then (cd $RF/scripts && python3 -I chaos2.py chaos 2 150); crc=$?; fc=$(cd $RF/scripts && python3 -I fastcheck.py); frc=$?
      log "chaos rc=$crc fastcheck rc=$frc $fc"; [ $crc = 0 ] && [ $frc = 0 ] || ok=0; fi
    if [ $ok = 1 ]; then st "- 3r DEPLOYED: reasoner_split=3r; fastcheck $fc"
    else stop_app > /dev/null; $A push "$(w $D/profile.3)" $W/htpd_profile.part > /dev/null && sh_ "mv -f $W/htpd_profile.part $W/htpd_profile"; start_app; st "- 3r FAILED app check -> split 3 restored"; fi
  else start_app; st "- 3r not deployed: app not stopped"; fi
else st "- 3r not deployed (gate, time, or deploy2 build missing)"; fi
sh_ 'ps -A -o NAME= | grep -q edge-agent' || start_app
log "=== 3r done"
