# watch_eq.ps1: while my CPU test runs, kill it if Windows available RAM < 1500 MB (never let it pause the live run)
param([int]$Min = 1500)
$env:MSYS_NO_PATHCONV = 1
while ($true) {
  Start-Sleep -Seconds 3
  $av = (Get-CimInstance Win32_PerfFormattedData_PerfOS_Memory).AvailableMBytes
  $alive = wsl bash /mnt/c/Users/hp/Desktop/qidk/proofs/2026-11-06_4b_local/speed/alive_eq.sh
  if ($alive -ne 'y') { "test ended"; break }
  if ($av -lt $Min) { "RAM $av MB < ${Min}: killing test"; wsl bash /mnt/c/Users/hp/Desktop/qidk/proofs/2026-11-06_4b_local/speed/kill_eq.sh; break }
}
