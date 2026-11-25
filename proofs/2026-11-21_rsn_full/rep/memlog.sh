#!/bin/bash
# memlog.sh: every 60 s, UTC time + WSL used/available MB + swap used MB (to diagnose VM deaths)
while sleep 60; do echo "$(date -u +%T) $(free -m | awk '/Mem/{print "used",$3,"avail",$7} /Swap/{print "swap",$3}' | tr '\n' ' ')"; done
