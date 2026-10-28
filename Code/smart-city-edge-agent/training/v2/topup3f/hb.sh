#!/usr/bin/env bash
# touch the 3f HEARTBEAT every 2 min for $1 minutes (relaunched by the controlling agent at each poll; a previous loop is replaced)
pkill -f "[h]b.sh loop" ; exec -a "hb.sh loop" bash -c "for i in \$(seq 1 \$(( $1 / 2 ))); do touch ~/smartcity_runs/agents_v2_topup3f/HEARTBEAT; sleep 120; done"
