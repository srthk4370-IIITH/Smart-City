# phase1t (owner 2026-11-20): 4-of-8 AI gate, data-quality threshold, Home watch line, fog clock, QR share fix, qr_viewer -> smart-city-esw.pages.dev/report/; phase1k + single ingest device path, plain daily digest, chat corrected clock, no "dismiss" text on criticals; phase1j + flatline on raw readings (no false sensor_fault on idle meters) + honest AI-wait text; phase1i + reasoner faultGuard (sensor_fault needs a rule or agent fault finding); injection fixes (engine.go/server.go), network clock sync (clocknet.go), EdgeService prefers backend clock_offset_s. Rollback = previous APK.
source <(sed -n '11,36p' /mnt/c/Users/hp/Desktop/qidk/proofs/2026-11-16_phase1/deploy_phase1.sh)
B=$P/SmartCityEdge.phase1t.apk; (cd $P && md5sum -c SmartCityEdge.phase1t.apk.md5) || { st "1t ABORT md5"; exit 1; }
mkdir -p $I
"$A" shell pm path com.iiith.smartcityedge | tr -d '\r' | sed 's/package://' | head -1 > $I/prev_apk_path.txt
"$A" pull "$(cat $I/prev_apk_path.txt)" "$(wslpath -w $I)\phase1_prev.apk" > /dev/null
st "1t: stop"; stop_app | tail -1
"$A" install -r -d "$(wslpath -w $B)" | tr -d '\r' | tail -1
start_app && st "1t: app up" || { st "1t: app NOT up -> rollback APK"; stop_app >/dev/null; "$A" install -r -d "$(wslpath -w $I/phase1_prev.apk)"; start_app; exit 2; }
sleep 180
S1=$(sh_ "curl -s -m 10 http://127.0.0.1:8000/api/prod/status")
st "1t: link=$(echo "$S1" | grep -o '"campus_link_label":"[^"]*"') clock=$(echo "$S1" | grep -o '"corrected":"[^"]*"' | head -1)"
st "1t: health=$(sh_ "curl -s -m 10 http://127.0.0.1:8000/api/health" | head -c 260)"
st "1t: agent.log tail: $(sh_ "tail -n 3 $W/state/agent.log" | cut -c1-140 | tr '\n' '|')"
echo DEPLOY1T_DONE
