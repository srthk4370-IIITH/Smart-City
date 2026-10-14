#!/usr/bin/env bash
# Abort the export if the Windows C: drive gets dangerously low.
#
# The first attempt filled C: to 0 bytes, which killed the WSL VM mid-export
# (Wsl/Service/CreateInstance/E_UNEXPECTED). The export writes multi-GB upload zips and downloads
# compiled parts into the WSL ext4 image, and with sparseVhd the image grows on C: as it does.
# Losing the export is cheap; losing the VM is not.
#
#   setsid nohup bash disk_guard.sh 3 &     # abort below 3 GB free on C:
MIN_GB=${1:-3}
while true; do
  # /mnt/c is the Windows volume; df reports its real free space
  free_kb=$(df -k /mnt/c 2>/dev/null | tail -1 | tr -s ' ' | cut -d' ' -f4)
  [ -z "$free_kb" ] && { sleep 30; continue; }
  free_gb=$((free_kb / 1024 / 1024))
  if [ "$free_gb" -lt "$MIN_GB" ]; then
    echo "$(date) DISK GUARD: only ${free_gb} GB free on C:, aborting export" >> ~/qaihm_work/disk_guard.log
    pkill -f "qai-hub-models export"
    pkill -f export_mcl.sh
    exit 1
  fi
  sleep 30
done
