# board RTC stops while the board sleeps -> rewrite files/clock_offset_s = laptop UTC - device UTC, restart app
source <(sed -n '11,36p' /mnt/c/Users/hp/Desktop/qidk/proofs/2026-11-16_phase1/deploy_phase1.sh)
dev=$(sh_ "date +%s" | tr -d '\r'); now=$(date +%s); off=$((now-dev))
st "fix_clock: device $dev laptop $now offset $off s"
"$A" shell "run-as com.iiith.smartcityedge sh -c 'echo $off > files/clock_offset_s; cat files/clock_offset_s'" | tr -d '\r'
stop_app | tail -1; start_app && st "fix_clock: app up"; sleep 60
st "fix_clock: $(sh_ "curl -s -m 10 http://127.0.0.1:8000/api/prod/status" | grep -o '"campus_link_label":"[^"]*"\|"corrected":"[^"]*"' | head -2 | tr '\n' ' ')"
echo FIXCLOCK_DONE
