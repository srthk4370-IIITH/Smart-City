# One-time admin cleanup (run elevated). Safe and reversible where possible; log next to this file.
#  1) disable the all-users AnyDesk auto-start (Task Manager-style "Disabled" flag; the shortcut is kept)
#  2) compact the WSL virtual disk: returns the free space inside it (~50 GB) to C:. Nothing inside is deleted.
#     DiskPart cannot compact a sparse VHDX, so the sparse flag is cleared first - only if C: can absorb
#     the sparse holes (checked below), otherwise it stops without changing anything.
$log = "$PSScriptRoot\admin_cleanup.log"
function L($m) { $l = "[{0:HH:mm:ss}] {1}" -f (Get-Date), $m; $l; Add-Content $log $l }
L "start (admin: $(([Security.Principal.WindowsPrincipal][Security.Principal.WindowsIdentity]::GetCurrent()).IsInRole('Administrators')))"

# 1) AnyDesk auto-start (common startup folder)
$ap = "HKLM:\Software\Microsoft\Windows\CurrentVersion\Explorer\StartupApproved\StartupFolder"
if (-not (Test-Path $ap)) { New-Item $ap -Force | Out-Null }
Set-ItemProperty $ap -Name "AnyDesk.lnk" -Value ([byte[]](3,0,0,0,0,0,0,0,0,0,0,0)) -Type Binary
L "AnyDesk auto-start disabled"

# 2) compact the WSL disk
Add-Type -Namespace N -Name F -MemberDefinition '[DllImport("kernel32.dll", CharSet=CharSet.Unicode)] public static extern uint GetCompressedFileSizeW(string f, out uint hi);'
$vhd = "$env:SystemDrive\Users\hp\AppData\Local\wsl\{ee2e2fda-f5af-4cca-a123-4c0d0487e0d8}\ext4.vhdx"
wsl --shutdown; Start-Sleep 5
$len = (Get-Item $vhd).Length
$hi = 0; $lo = [N.F]::GetCompressedFileSizeW($vhd, [ref]$hi); $alloc = [double]$hi * 4GB + $lo
$holes = $len - $alloc; $free = (Get-PSDrive C).Free
L ("vhdx size {0:N1} GB, allocated {1:N1} GB, sparse holes {2:N1} GB, C: free {3:N1} GB" -f ($len/1GB), ($alloc/1GB), ($holes/1GB), ($free/1GB))
if ($holes -gt ($free - 5GB)) { L "STOP: clearing the sparse flag could fill C: - nothing changed"; exit 1 }
fsutil sparse setflag "$vhd" 0 | Out-Null
L "sparse flag cleared"
$s = "$env:TEMP\sce_compact.txt"
"select vdisk file=`"$vhd`"`r`nattach vdisk readonly`r`ncompact vdisk`r`ndetach vdisk`r`nexit" | Set-Content $s -Encoding ascii
diskpart /s $s | Select-String "percent|successfully|error" | ForEach-Object { L $_.Line.Trim() }
L ("done: vhdx now {0:N1} GB, C: free {1:N1} GB" -f ((Get-Item $vhd).Length/1GB), ((Get-PSDrive C).Free/1GB))
