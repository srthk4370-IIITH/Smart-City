#!/usr/bin/env bash
# P1 backend deploy (proofs/deploy_and_test.sh: clean stop of app + htpd, install, refine/recheck/chaos) then E1 board stories.
D=/c/Users/hp/Desktop/qidk/proofs/2026-10-25_domain_plan; O=$D/board_p1
export MSYS_NO_PATHCONV=1 PYTHONIOENCODING=utf-8
timeout 10800 bash /c/Users/hp/Desktop/qidk/proofs/deploy_and_test.sh $O > $O/deploy.log 2>&1
echo "deploy rc $?" >> $O/deploy.log
SIM_OUT=$(cd $O && pwd -W) timeout 5400 py -3 -u $D/scripts/sim_e1.py > $O/sim_console.txt 2>&1
echo "sim rc $?" >> $O/deploy.log
echo BOARD_P1_DONE >> $O/deploy.log
