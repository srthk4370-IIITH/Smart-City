#!/usr/bin/env bash
# Retrieval-preliminary APK deploy-if-pass (standalone: bash /mnt/c/Users/hp/Desktop/qidk/proofs/detach.sh rag_deploy <this>).
#  R0 wait: split_post.log "=== split_post done", then BOARD_LOCK (own value "rag"); give up if it would start after 10:30 IST
#  R1 seed: if rag_seed/rag_seed.json is ready (rag_seed/.done) by 09:30 IST, rebuild the APK with it (backend unchanged)
#  R2 snapshot the live state (profile, installed APK, edge-agent md5) -> rag_build/known_good
#  R3 install the APK only (models + profile unchanged): app stopped and NPU clients gone first (one NPU client), start, htpd ready
#  R4 app check: chaos2 3 scenarios (owner: smaller board tests) + fastcheck; every incident needs a preliminary within ~2 s of creation (retrieved or rules)
#     and the AI report replacing it on the SAME incident (final not preliminary, valid, state done)
#  R5 ANY failure -> rollback (reinstall the snapshot APK, start, verify); RAG_STATUS.md + HANDBOOK 2.57
# Board rules: never reboots, one NPU client, heat pacing inside chaos2/fastcheck (< 60 C), APK only (no big pushes).
M=/mnt/c/Users/hp/Desktop/qidk/proofs/2026-10-28_master; B=$M/rag_build; K=$M/BOARD_LOCK; mkdir -p $B/known_good $B/check
RF=/mnt/c/Users/hp/Desktop/qidk/proofs/2026-10-27_reasoner_fast; APP=/mnt/c/Users/hp/Desktop/qidk/Code/smart-city-edge-agent/app
A=/mnt/c/Users/hp/Desktop/qidk/Code/platform-tools/adb.exe; W=/data/local/tmp/smart_city_edge
APK=$B/SmartCityEdge.rag.apk; EA=$B/edge-agent.rag
exec >> $B/rag_deploy.log 2>&1 < /dev/null
log(){ echo "$(date -u +%FT%TZ) $*"; }
w(){ wslpath -w "$1"; }
sh_(){ $A shell "$@" | tr -d '\r'; }
ist(){ TZ=Asia/Kolkata date +%H%M; }
CUT=$(date -d "2026-10-29 10:30 IST" +%s 2>/dev/null || date -d "2026-10-29 05:00 UTC" +%s); SEEDCUT=$((CUT - 3600))   # 10:30 / 09:30 IST
late(){ [ $(date +%s) -ge $CUT ]; }
board(){ until $A get-state 2>/dev/null | grep -q device; do sleep 60; done; }
TP=
lock(){ board; while [ -e $K ] && [ "$(cat $K 2>/dev/null)" != rag ] && [ $(( $(date +%s) - $(stat -c %Y $K) )) -lt 10800 ]; do
    late && return 1; sleep 60; done
  echo rag > $K; ( while [ "$(cat $K 2>/dev/null)" = rag ]; do touch $K; sleep 300; done ) & TP=$!; return 0; }
unlock(){ [ -n "$TP" ] && kill $TP 2>/dev/null; TP=; [ "$(cat $K 2>/dev/null)" = rag ] && rm -f $K; }
trap unlock EXIT
stop_app(){ sh_ 'am force-stop com.iiith.smartcityedge; pkill -x edge-agent; for p in $(pidof htpd_v8x2 htpd_v8r htpd_v8s htpd_v8t htpd_v8p htpd_v8p2 htpd_v7 htpd); do kill -TERM $p; done
  i=0; while [ $i -lt 120 ] && ps -A -o NAME= | grep -qE "^(htpd|edge-agent)"; do sleep 1; i=$((i+1)); done
  sleep 30; if ps -A -o NAME= | grep -qE "^(htpd|edge-agent|genie|llama)"; then echo STILL; else echo STOPPED; fi'; }
start_app(){ n0=$(sh_ "grep -c 'htpd: ready in' $W/state/htpd.log" | tail -1); sh_ 'am start -n com.iiith.smartcityedge/.MainActivity >/dev/null 2>&1'
  for i in $(seq 1 60); do sleep 5; [ "$(sh_ "grep -c 'htpd: ready in' $W/state/htpd.log" | tail -1)" -gt "${n0:-0}" ] && return 0; done; return 1; }
status(){ RES="$1"
  sh_ "md5sum $W/edge-agent; grep -E '^(bin|model|reasoner_model|reasoner_split|ai_early_k)=' $W/htpd_profile" > $B/board_state.txt
  cat > $M/RAG_STATUS.md <<EOF
# Retrieval preliminary deploy ($(date -u +%FT%TZ))
**Result:** $RES

APK $(md5sum $APK | cut -c1-8) (edge-agent $(md5sum $EA | cut -c1-8), seed library: ${SEED:-none}); models and htpd_profile unchanged.

| incident | scenario | created -> preliminary (s) | preliminary basis | AI report on same incident | title |
|---|---|---|---|---|---|
$(cat $B/check/rows.md 2>/dev/null)

Retrieval hit rate: $(cat $B/check/hitrate.txt 2>/dev/null || echo n/a)

Board state now:
\`\`\`
$(cat $B/board_state.txt)
\`\`\`
Rollback (WSL; stops the app, reinstalls the snapshot APK, starts it; models/profile were never changed):
\`bash $M/rag_rollback.sh\`   (snapshot: \`$B/known_good\`). Log: \`$B/rag_deploy.log\`.
EOF
  python3 - "$RES" "$(md5sum $APK | cut -c1-8)" <<'P'
import sys
p = "/mnt/c/Users/hp/Desktop/qidk/HANDBOOK.md"; b = open(p, "rb").read().decode("utf-8"); crlf = "\r\n" in b; s = b.replace("\r\n", "\n")
i = s.find("\n## 2.57 ")
if i >= 0:
    j = s.find("\n## ", i + 5); s = s[:i] + s[j:]
if True:
    e = ("\n## 2.57 Retrieval preliminary (2026-10-29, proofs/2026-10-28_master/RAG_STATUS.md)\n\n"
         "- Every incident gets an instant preliminary (< 5 ms CPU): the nearest finished AI reports (structured features + TF-IDF, same role/metric,\n"
         "  tuned threshold; seed reference cases rank below live reports) adapted to the LIVE values, severity = max(rules, retrieved);\n"
         "  no hit -> rules report + 'full AI report coming'. The AI report replaces it on the same incident; AI-vs-retrieved severity\n"
         f"  disagreements are logged. retrieval.go, retrieval_test.go. APK {sys.argv[2]}. Result: {sys.argv[1]}\n")
    a = "\n## 3. If something goes wrong"
    s = s.replace(a, e + a, 1) if a in s else s + e
    if crlf: s = s.replace("\n", "\r\n")
    open(p, "wb").write(s.encode("utf-8"))
P
  log "RESULT: $RES"; }
rollback(){ log "rollback"; r=$(stop_app); [ "$r" = STOPPED ] || log "rollback: NPU client still running ($r), installing anyway"
  $A install -r -d "$(w $B/known_good/app.apk)" | tail -1; start_app && log "rollback: htpd ready" || log "rollback: htpd NOT ready"
  log "rollback state: $(sh_ "md5sum $W/edge-agent" | tr '\n' ' ')"; }
cat > $M/rag_rollback.sh <<EOF
#!/usr/bin/env bash
# roll back the retrieval-preliminary APK: reinstall the snapshot APK taken by rag_deploy.sh (models/profile unchanged). Never reboots.
A=$A; B=$B; W=$W
r=\$(\$A shell 'am force-stop com.iiith.smartcityedge; pkill -x edge-agent; for p in \$(pidof htpd_v8x2 htpd_v8r htpd_v8s htpd_v8t htpd_v8p htpd_v8p2 htpd_v7 htpd); do kill -TERM \$p; done; i=0; while [ \$i -lt 120 ] && ps -A -o NAME= | grep -qE "^(htpd|edge-agent)"; do sleep 1; i=\$((i+1)); done; sleep 30; echo done' | tr -d '\r')
\$A install -r -d "\$(wslpath -w \$B/known_good/app.apk)" | tail -1; \$A shell 'am start -n com.iiith.smartcityedge/.MainActivity' > /dev/null; sleep 60
\$A shell "md5sum \$W/edge-agent" | tr -d '\r'
EOF
chmod +x $M/rag_rollback.sh

log "=== rag_deploy start; waiting for split_post"
until grep -q "=== split_post done" $M/split_post.log 2>/dev/null; do late && { status "NOT DEPLOYED: split_post not done by 10:30 IST"; exit 0; }; sleep 60; done
late && { status "NOT DEPLOYED: would start after 10:30 IST"; exit 0; }
# R1 seed (rebuild the APK around the same backend with data/rag_seed.json)
SEED=
if [ -e $M/rag_seed/.done ] && [ -s $M/rag_seed/rag_seed.json ] && [ $(date +%s) -lt $SEEDCUT ]; then
  cp $APP/device/edge-agent $B/slot.edge-agent; cp $APP/android/out/SmartCityEdge.apk $B/slot.apk
  cp $EA $APP/device/edge-agent; cp $M/rag_seed/rag_seed.json $APP/device/data/rag_seed.json
  if bash $APP/android/build_apk.sh > $B/apk_seed_build.log 2>&1; then cp $APP/android/out/SmartCityEdge.apk $B/SmartCityEdge.rag_seed.apk; APK=$B/SmartCityEdge.rag_seed.apk
    SEED="$(python3 -c "import json;print(len(json.load(open('$M/rag_seed/rag_seed.json'))))") reference cases"; fi
  rm -f $APP/device/data/rag_seed.json; cp $B/slot.apk $APP/android/out/SmartCityEdge.apk; cp $B/slot.edge-agent $APP/device/edge-agent
  log "R1 seed APK: $(md5sum $APK | cut -c1-8) ($SEED)"
else log "R1 no seed (not ready by 09:30 IST)"; fi
lock || { status "NOT DEPLOYED: BOARD_LOCK still held at 10:30 IST"; exit 0; }
late && { status "NOT DEPLOYED: would start after 10:30 IST"; exit 0; }
# R2 snapshot
sh_ "cat $W/htpd_profile" > $B/known_good/htpd_profile
p=$(sh_ 'pm path com.iiith.smartcityedge' | head -1 | sed 's/^package://'); $A pull "$p" "$(w $B/known_good/app.apk)" > /dev/null
sh_ "md5sum $W/edge-agent" > $B/known_good/edge-agent.md5
[ -s $B/known_good/app.apk ] || { status "NOT DEPLOYED: snapshot failed"; exit 2; }
log "R2 snapshot: apk $(md5sum $B/known_good/app.apk | cut -c1-8), $(cat $B/known_good/edge-agent.md5)"
# R3 install
r=$(stop_app); log "R3 stop: $r"; [ "$r" = STOPPED ] || { status "NOT DEPLOYED: an NPU client was still running"; exit 3; }
$A install -r -d "$(w $APK)" | tail -1
if ! start_app; then rollback; status "FAIL -> rolled back: htpd not ready after install"; exit 0; fi
sleep 20; log "R3 installed: edge-agent $(sh_ "md5sum $W/edge-agent" | cut -c1-8)"
# R4 app check
t0=$(date +%s); (cd $RF/scripts && python3 -I chaos2.py chaos 3 150); rc=$?
fc=$(cd $RF/scripts && python3 -I fastcheck.py); frc=$?
log "R4 chaos rc=$rc fastcheck rc=$frc $fc"
python3 - $t0 $B/check <<'P'
import glob, json, os, re, sys
t0, out = float(sys.argv[1]), sys.argv[2]
files = [f for f in glob.glob("/mnt/c/Users/hp/Desktop/qidk/proofs/2026-10-27_reasoner_fast/raw/chaos_*_incident.json") + glob.glob("/mnt/c/Users/hp/Desktop/qidk/proofs/2026-10-27_reasoner_fast/raw/fastcheck_*.json") if os.path.getmtime(f) >= t0]
sec = lambda t: int(t[:2]) * 3600 + int(t[3:5]) * 60 + int(t[6:8])
rows, ok, n, hits = [], 0, 0, 0
for f in sorted(files):
    x = json.load(open(f)); inc = x.get("incident")
    if not isinstance(inc, dict): rows.append(f"| - | {x.get('scenario', 'fastcheck')} | no incident | - | FAIL | - |"); n += 1; continue
    n += 1; tl = inc.get("timeline") or []
    c = next((sec(t["t"]) for t in tl if "Event gated" in t.get("msg", "") or "Critical fast path" in t.get("msg", "")), None)
    p = next((sec(t["t"]) for t in tl if "Preliminary report shown" in t.get("msg", "")), None)
    if c is None and tl: c = sec(tl[0]["t"])
    dt = (p - c) if (p is not None and c is not None) else None
    fin = inc.get("final") or {}
    ai = inc.get("state") == "done" and not fin.get("preliminary") and bool(fin.get("valid"))
    basis = "retrieval" if inc.get("retrieved") else "rules"
    hits += bool(inc.get("retrieved"))
    good = dt is not None and dt <= 2 and ai
    ok += good
    rows.append(f"| {inc.get('id')} | {x.get('scenario', 'fastcheck')} | {dt if dt is not None else 'none'} | {basis} | {'yes' if ai else 'NO'} | {inc.get('title', '')[:70]} |")
open(f"{out}/rows.md", "w").write("\n".join(rows) + "\n")
open(f"{out}/hitrate.txt", "w").write(f"{hits}/{n} incidents had a retrieved match")
open(f"{out}/ok.txt", "w").write(f"{ok} {n}")
print(ok, n)
P
set -- $(cat $B/check/ok.txt)
mkdir -p $B/check/raw; cp $RF/raw/chaos_*_incident.json $RF/raw/fastcheck_*.json $B/check/raw/ 2>/dev/null
if [ $rc = 0 ] && [ $frc = 0 ] && [ "${1:-0}" -ge 4 ] && [ "${1:-0}" = "${2:-x}" ]; then status "PASS: $1/$2 incidents had a preliminary within 2 s and the AI report on the same incident; fastcheck $fc"
else rollback; status "FAIL -> rolled back: chaos rc=$rc fastcheck rc=$frc, ok $1/$2"; fi
unlock; log "=== rag_deploy done"
