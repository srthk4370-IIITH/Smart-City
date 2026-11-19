source <(sed -n '11,36p' /mnt/c/Users/hp/Desktop/qidk/proofs/2026-11-16_phase1/deploy_phase1.sh)
st "restart_app (clock offset fixed, relay fixed)"; stop_app | tail -1; start_app && st "app up" || st "app NOT up"
sleep 120; st "after restart: $(sh_ "curl -s -m 10 http://127.0.0.1:8000/api/prod/status" | grep -o '"clock":{[^}]*}' | cut -c1-200)"
st "health: $(sh_ "curl -s -m 10 http://127.0.0.1:8000/api/health" | head -c 300)"
echo RESTART_DONE
