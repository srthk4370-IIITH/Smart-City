# Launch the full laptop distillation detached (proofs/detach.sh) + a hidden wsl.exe keepalive: .wslconfig has
# instanceIdleTimeout=15 s, which shuts the distro down (killing detached jobs) once no wsl.exe session is open.
$D = '/mnt/c/Users/hp/Desktop/qidk/proofs/2026-10-29_rsn_v3/distill_laptop'
wsl bash /mnt/c/Users/hp/Desktop/qidk/proofs/detach.sh rsn3_distill $D/run_distill.sh $D 14 --workers 7
Start-Process -WindowStyle Hidden -FilePath wsl.exe -ArgumentList "bash $D/keepalive.sh rsn3_distill 15"
