#!/usr/bin/env bash
# touch the reasoner HEARTBEAT every 60 s for $1 minutes (run by the controlling agent as its own background task)
for i in $(seq 1 ${1:-50}); do touch ~/smartcity_runs/reasoner_v1/HEARTBEAT; sleep 60; done; echo "hb loop ended"
