#!/bin/bash
# owner 2026-11-19 #13: old test chat sessions moved to state/cleared_20261119 (not deleted)
source <(sed -n '11,36p' /mnt/c/Users/hp/Desktop/qidk/proofs/2026-11-16_phase1/deploy_phase1.sh)
stop_app; sh_ "cd $W/state && mkdir -p cleared_20261119 && mv chats.json cleared_20261119/ && ls cleared_20261119"; start_app && echo CHATS_CLEARED
