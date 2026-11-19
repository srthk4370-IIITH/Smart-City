# Phase 1 deploy over USB relay (board has no Wi-Fi): laptop services + campus API via adb reverse on 127.0.0.1
cd /mnt/c/Users/hp/Desktop/qidk/proofs/2026-11-16_phase1
export LAPTOP_IP=127.0.0.1 CAMPUS_URL=http://127.0.0.1:9999
bash deploy_phase1.sh --go; echo "DEPLOY_RC=$?"
