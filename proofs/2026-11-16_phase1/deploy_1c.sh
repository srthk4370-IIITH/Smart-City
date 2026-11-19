# phase1c: APK only (failover + corrected clock), campus_url -> ordered list; verify live readings; rollback = previous APK
source <(sed -n '11,36p' /mnt/c/Users/hp/Desktop/qidk/proofs/2026-11-16_phase1/deploy_phase1.sh)
B=$P/SmartCityEdge.phase1c.apk; (cd $P && md5sum -c SmartCityEdge.phase1c.apk.md5) || { st "1b ABORT md5"; exit 1; }
"$A" shell pm path com.iiith.smartcityedge | tr -d '\r' | sed 's/package://' | head -1 > $I/prev_apk_path.txt
"$A" pull "$(cat $I/prev_apk_path.txt)" $I/phase1_prev.apk > /dev/null
st "1c: stop"; stop_app | tail -1
"$A" install -r -d "$(wslpath -w $B)" | tr -d '\r' | tail -1
sh_ "sed -i 's#^campus_url=.*#campus_url=http://10.2.203.214:9999,http://127.0.0.1:9999#' $W/htpd_profile"
start_app && st "1c: app up" || { st "1c: app NOT up -> rollback APK"; stop_app >/dev/null; "$A" install -r -d "$(wslpath -w $I/phase1_prev.apk)"; start_app; exit 2; }
sleep 180
S1=$(sh_ "curl -s -m 10 http://127.0.0.1:8000/api/prod/status")
st "1c: link=$(echo "$S1" | grep -o '"campus_link_label":"[^"]*"') clock=$(echo "$S1" | grep -o '"corrected":"[^"]*"' | head -1)"
st "1c: health=$(sh_ "curl -s -m 10 http://127.0.0.1:8000/api/health" | head -c 260)"
st "1c: agent.log tail: $(sh_ "tail -n 3 $W/state/agent.log" | cut -c1-140 | tr '\n' '|')"
echo DEPLOY1C_DONE
