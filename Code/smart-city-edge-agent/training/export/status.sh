#!/usr/bin/env bash
# One-line-per-fact status of the running export. Avoids inline awk/quoting through nested shells.
LOG=${1:-$HOME/qaihm_work/mcl_export.log}

if pgrep -f qai-hub-models >/dev/null; then echo "export: RUNNING"; else echo "export: NOT RUNNING"; fi
if pgrep -f disk_guard >/dev/null; then echo "guard : UP"; else echo "guard : DOWN"; fi
[ -f "$HOME/qaihm_work/disk_guard.log" ] && echo "GUARD FIRED: $(cat "$HOME/qaihm_work/disk_guard.log")"

echo "mem   : $(free -m | sed -n '2p' | tr -s ' ' | cut -d' ' -f3)/$(free -m | sed -n '2p' | tr -s ' ' | cut -d' ' -f2) MB"
echo "swap  : $(free -m | sed -n '3p' | tr -s ' ' | cut -d' ' -f3)/$(free -m | sed -n '3p' | tr -s ' ' | cut -d' ' -f2) MB"
echo "rss   : $(ps -eo rss,comm --sort=-rss | sed -n '2p' | tr -s ' ')"
echo "ext4  : $(df -h / | tail -1 | tr -s ' ' | cut -d' ' -f3) used"
echo "C:    : $(df -h /mnt/c | tail -1 | tr -s ' ' | cut -d' ' -f4) free"

echo "--- phase ---"
tr '\r' '\n' < "$LOG" 2>/dev/null \
  | grep -oiE 'Uploading [A-Za-z0-9_]+\.aimet\.zip|LINKING_MODELS|OPTIMIZING_MODEL|CREATED|Downloaded model|DONE' \
  | uniq | tail -4
echo "--- last line ---"
tr '\r' '\n' < "$LOG" 2>/dev/null | grep -vE '^\s*$' | tail -1 | cut -c1-110
