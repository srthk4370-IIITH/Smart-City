D=/mnt/c/Users/hp/Desktop/qidk/proofs/2026-11-16_phase1
TAG=phase1h nice -n 15 bash $D/build_phase1.sh | tail -1 | grep -q "done ok" || { echo "BUILD FAILED"; exit 1; }
echo "built; waiting for app test waves to finish"
while ! grep -q WAVES_DONE ~/detached/app_waves.log 2>/dev/null; do sleep 60; done
bash $D/deploy_1h.sh
