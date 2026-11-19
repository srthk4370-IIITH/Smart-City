D=/mnt/c/Users/hp/Desktop/qidk/proofs/2026-11-16_phase1
TAG=phase1i nice -n 15 bash $D/build_phase1.sh | tail -1 | grep -q "done ok" || { echo "BUILD FAILED"; exit 1; }
