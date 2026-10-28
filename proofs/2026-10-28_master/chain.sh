#!/usr/bin/env bash
# Board chain (owner 2026-10-28: standalone, survives Claude sessions; launch: bash proofs/detach.sh chain <this>).
#  1 B50 confirm through the app: chaos2 (6 incidents, 210 s apart, board < 60 C). Swap-back failure -> rollback to mixA50.
#  2 after build_newhex: push the new llama.cpp to /data/local/tmp/llama.cpp-new, board llama-bench old vs new (bench_new.sh).
#  3 after plan.sh's winner_build: if a P3B*/T30 model was staged (gate2 winner over B50 too), deploy + chaos smoke; fail -> rollback.
# Guards: laptop free RAM < 1.5 GB -> wait; board heat in chaos2 (60 C) and bench_new (65 C); one NPU client (each step stops the app).
# Results: chain.log, CHAIN_STATUS.json. Each step is skipped when its marker exists (re-launch resumes).
M=/mnt/c/Users/hp/Desktop/qidk/proofs/2026-10-28_master; L=$M/chain.log; A=/mnt/c/Users/hp/Desktop/qidk/Code/platform-tools/adb.exe
RF=/mnt/c/Users/hp/Desktop/qidk/proofs/2026-10-27_reasoner_fast; NEW=/mnt/c/Users/hp/gpu_work/llama.cpp-new/pkg-android/llama.cpp
DP=/mnt/c/Users/hp/Desktop/qidk/proofs/2026-10-25_domain_plan; STAGE=/mnt/c/Users/hp/Desktop/qidk/Code/models_stage
PS=/mnt/c/Windows/System32/WindowsPowerShell/v1.0/powershell.exe
exec >> $L 2>&1 < /dev/null
log(){ echo "$(date -u +%FT%TZ) $*"; }
ram(){ $PS -NoProfile -Command "[int]((Get-CimInstance Win32_OperatingSystem).FreePhysicalMemory/1024)" 2>/dev/null | tr -dc 0-9; }
ramwait(){ while f=$(ram); [ -n "$f" ] && [ "$f" -lt 1536 ]; do log "laptop RAM $f MB < 1536: wait"; sleep 60; done; }
board(){ until $A get-state 2>/dev/null | grep -q device; do log "board offline: wait"; sleep 60; done; }
chaos(){ (cd $RF/scripts && python3 -I chaos2.py "$@"); }
summ(){ python3 - "$1" <<'P'
import glob, json, os, sys
t0 = float(sys.argv[1]); rows = []
for f in sorted(glob.glob("/mnt/c/Users/hp/Desktop/qidk/proofs/2026-10-27_reasoner_fast/raw/*_incident.json")):
    if os.path.getmtime(f) < t0: continue
    d = json.load(open(f)); i = d.get("incident") or {}; fin = (i.get("final") or {}) if isinstance(i, dict) else {}
    rows.append({"scen": d.get("scenario"), "state": i.get("state") if isinstance(i, dict) else None, "wall_s": d.get("wall_s"),
                 "sev": (fin.get("parsed") or {}).get("severity"), "valid": fin.get("valid"), "title": i.get("title") if isinstance(i, dict) else None})
print(json.dumps({"n": len(rows), "done": sum(r["state"] == "done" for r in rows), "valid": sum(bool(r["valid"]) for r in rows), "rows": rows}))
P
}
st(){ python3 -c "import json,sys;p='$M/CHAIN_STATUS.json';d=json.load(open(p)) if __import__('os').path.exists(p) else {};d[sys.argv[1]]=json.loads(sys.argv[2]);json.dump(d,open(p,'w'),indent=1)" "$1" "$2"; }
log "=== chain start"

# 1 B50 confirm
if [ ! -e $M/.s1 ]; then ramwait; board; t0=$(date +%s); log "1 B50 chaos (6 x 210 s)"
  chaos chaos 6 210; rc=$?; s=$(summ $t0); log "1 rc=$rc $s"; st b50_chaos "{\"rc\": $rc, \"summary\": $s}"
  if [ $rc = 9 ]; then log "1 swap-back failure: rollback to mixA50"
    bash $M/deploy_model.sh rollback htpd_profile.bak_preB50; fi
  touch $M/.s1; fi

# 2 new-kernel board bench
if [ ! -e $M/.s2 ]; then log "2 wait for build_newhex"
  until grep -q "=== build_newhex done" $RF/logs/build_newhex.log 2>/dev/null; do sleep 120; done
  if [ -x $NEW/bin/llama-bench ] && ls $NEW/lib/libggml-hexagon.so >/dev/null 2>&1; then ramwait; board
    $A shell "rm -rf /data/local/tmp/llama.cpp-new.part; mkdir -p /data/local/tmp/llama.cpp-new.part /data/local/tmp/rfast/new"
    $A push "$(wslpath -w $NEW/lib)" /data/local/tmp/llama.cpp-new.part/ > /dev/null && $A push "$(wslpath -w $NEW/bin)" /data/local/tmp/llama.cpp-new.part/ > /dev/null &&
    $A shell "chmod 755 /data/local/tmp/llama.cpp-new.part/bin/*; rm -rf /data/local/tmp/llama.cpp-new; mv /data/local/tmp/llama.cpp-new.part /data/local/tmp/llama.cpp-new"
    $A push "$(wslpath -w $M/bench_new.sh)" /data/local/tmp/rfast/new/bench_new.sh > /dev/null
    $A shell "cd /data/local/tmp/rfast/new && setsid nohup sh bench_new.sh >/dev/null 2>&1 &"; log "2 bench_new started on board"
    until $A shell "cat /data/local/tmp/rfast/new/DONE 2>/dev/null" | grep -q .; do sleep 60; done
    $A pull /data/local/tmp/rfast/new $M/bench_new_out > /dev/null; log "2 bench: $(grep -E '^\||##' $M/bench_new_out/new/bench.md 2>/dev/null | grep -E '##|tg|pp' | tr '\n' ' ' | cut -c1-900)"
    st newhex_bench "\"$M/bench_new_out\""
  else log "2 build produced no llama-bench/libggml-hexagon: skipped (see build_newhex.log)"; st newhex_bench '"build failed"'; fi
  touch $M/.s2; fi

# 3 P3b / T30 winner deploy
if [ ! -e $M/.s3 ]; then log "3 wait for winner_build"
  until grep -q "winner_build rc" $M/plan.log 2>/dev/null; do sleep 300; done
  W=$(python3 -c "import json;print(json.load(open('$DP/QUEUE_DONE_P3B.json'))['winner'])" 2>/dev/null); log "3 winner $W"
  case $W in P3B*|T30) G=$STAGE/ft_${W}_q4_0.gguf
    if [ -s $G ] && [ -s $G.md5 ]; then ramwait; board; bash $M/deploy_model.sh $G $(cat $G.md5); t0=$(date +%s)
      chaos chaos 3 210; rc=$?; s=$(summ $t0); log "3 $W chaos rc=$rc $s"; st winner "{\"tag\": \"$W\", \"rc\": $rc, \"summary\": $s}"
      ok=$(echo "$s" | python3 -c "import json,sys;d=json.load(sys.stdin);print(int(d['n']>0 and d['done']==d['n']))")
      if [ $rc != 0 ] || [ "$ok" != 1 ]; then log "3 $W failed in the app: rollback to B50"; bash $M/deploy_model.sh rollback; fi
    else log "3 $W not staged"; fi;;
    *) log "3 winner $W: B50 stays"; st winner "\"$W (B50 stays)\"";; esac
  touch $M/.s3; fi
log "=== chain done"
