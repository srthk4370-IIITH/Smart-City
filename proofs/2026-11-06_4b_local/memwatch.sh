#!/usr/bin/env bash
# memwatch.sh: leak check for the live 4B trainer. Every 5 min: trainer RSS split (anon/file/shmem), WSL MemAvailable,
# Windows available MB, last logged step -> ~/detached/memwatch.tsv. Stops when the trainer is gone for 30 min.
O=~/detached/memwatch.tsv; PS=/mnt/c/Windows/System32/WindowsPowerShell/v1.0/powershell.exe; gone=0
[ -s $O ] || echo -e "time\tpid\trss_mb\tanon_mb\tfile_mb\tshmem_mb\twsl_avail_mb\twin_avail_mb\tstep" > $O
while sleep 300; do
  p=$(pgrep -f "python.*train_rsn3.py.*rsn3_4b_r3" | head -1)
  if [ -z "$p" ]; then gone=$((gone+1)); [ $gone -ge 6 ] && exit 0; continue; fi; gone=0
  g() { awk -v k="$1" '$1==k":"{print int($2/1024)}' /proc/$p/status; }
  w=$(timeout 30 $PS -NoProfile -Command "(Get-CimInstance Win32_PerfFormattedData_PerfOS_Memory).AvailableMBytes" </dev/null 2>/dev/null | tr -dc 0-9)
  s=$(grep -oE "step [0-9]+/" ~/smartcity_runs/rsn3_4b_r3/train.log | tail -1 | tr -dc 0-9)
  echo -e "$(date +%H:%M)\t$p\t$(g VmRSS)\t$(g RssAnon)\t$(g RssFile)\t$(g RssShmem)\t$(awk '/MemAvailable/{print int($2/1024)}' /proc/meminfo)\t$w\t$s" >> $O
done
