#!/bin/bash
echo "$(date -Is) 2b retry APK phase1k after board reboot" >> ~/detached/go_1k.log
bash /mnt/c/Users/hp/Desktop/qidk/proofs/2026-11-16_phase1/deploy_1k.sh >> ~/detached/deploy_1k.log 2>&1
echo "$(date -Is) apk retry rc=$? DONE" >> ~/detached/go_1k.log
