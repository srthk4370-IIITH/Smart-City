# phase1d (owner 2026-11-17): APK (retrieval ignores unconfirmed sensor_fault, small-value resolution, site tree branches) + clear all incidents (moved to state/cleared_20261117, not deleted)
source <(sed -n '11,36p' /mnt/c/Users/hp/Desktop/qidk/proofs/2026-11-16_phase1/deploy_phase1.sh)
B=$P/SmartCityEdge.phase1d.apk; (cd $P && md5sum -c SmartCityEdge.phase1d.apk.md5) || { st "1d ABORT md5"; exit 1; }
"$A" shell pm path com.iiith.smartcityedge | tr -d '\r' | sed 's/package://' | head -1 > $I/prev_apk_path.txt
"$A" pull "$(cat $I/prev_apk_path.txt)" $I/phase1_prev.apk > /dev/null
st "1d: stop"; stop_app | tail -1
sh_ "cd $W/state && mkdir -p cleared_20261117 && ls -la | grep -i incid; for f in incidents*.jsonl; do [ -e \"\$f\" ] && mv \"\$f\" cleared_20261117/; done; ls cleared_20261117"
"$A" install -r -d "$(wslpath -w $B)" | tr -d '\r' | tail -1
start_app && st "1d: app up" || { st "1d: app NOT up -> rollback APK"; stop_app >/dev/null; "$A" install -r -d "$(wslpath -w $I/phase1_prev.apk)"; start_app; exit 2; }
sleep 180
S1=$(sh_ "curl -s -m 10 http://127.0.0.1:8000/api/prod/status")
st "1d: link=$(echo "$S1" | grep -o '"campus_link_label":"[^"]*"') clock=$(echo "$S1" | grep -o '"corrected":"[^"]*"' | head -1)"
st "1d: health=$(sh_ "curl -s -m 10 http://127.0.0.1:8000/api/health" | head -c 260)"
st "1d: agent.log tail: $(sh_ "tail -n 3 $W/state/agent.log" | cut -c1-140 | tr '\n' '|')"
echo DEPLOY1D_DONE
