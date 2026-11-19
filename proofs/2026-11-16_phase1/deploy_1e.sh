# phase1e (owner 2026-11-17): new nav, Cards and rules page, card-driven rule thresholds + /api/rules, effDec in rules, htpd crash retry + warm gate. Rollback = previous APK.
source <(sed -n '11,36p' /mnt/c/Users/hp/Desktop/qidk/proofs/2026-11-16_phase1/deploy_phase1.sh)
B=$P/SmartCityEdge.phase1e.apk; (cd $P && md5sum -c SmartCityEdge.phase1e.apk.md5) || { st "1e ABORT md5"; exit 1; }
mkdir -p $I
"$A" shell pm path com.iiith.smartcityedge | tr -d '\r' | sed 's/package://' | head -1 > $I/prev_apk_path.txt
"$A" pull "$(cat $I/prev_apk_path.txt)" "$(wslpath -w $I)\phase1_prev.apk" > /dev/null
st "1e: stop"; stop_app | tail -1
"$A" install -r -d "$(wslpath -w $B)" | tr -d '\r' | tail -1
start_app && st "1e: app up" || { st "1e: app NOT up -> rollback APK"; stop_app >/dev/null; "$A" install -r -d "$(wslpath -w $I/phase1_prev.apk)"; start_app; exit 2; }
sleep 180
S1=$(sh_ "curl -s -m 10 http://127.0.0.1:8000/api/prod/status")
st "1e: link=$(echo "$S1" | grep -o '"campus_link_label":"[^"]*"') clock=$(echo "$S1" | grep -o '"corrected":"[^"]*"' | head -1)"
st "1e: health=$(sh_ "curl -s -m 10 http://127.0.0.1:8000/api/health" | head -c 260)"
st "1e: agent.log tail: $(sh_ "tail -n 3 $W/state/agent.log" | cut -c1-140 | tr '\n' '|')"
echo DEPLOY1E_DONE
