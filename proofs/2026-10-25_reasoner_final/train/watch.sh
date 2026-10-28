#!/usr/bin/env bash
# emits: first step line, every checkpoint line, and any failure/exit line of the reasoner run
L=~/smartcity_runs/reasoner_v1/run1/train.log; M=~/smartcity_runs/reasoner_v1/master.log
touch $L $M
tail -n0 -F $L $M 2>/dev/null | grep --line-buffered -E "step 5/|checkpoint step [0-9]*00 |checkpoint step|TRAINING DONE|EXIT|Error|error|out of memory|WATCHDOG|RAM PAUSE|RUN DONE|rc=" | grep --line-buffered -vE "checkpoint step [0-9]*(25|50|75)$"
