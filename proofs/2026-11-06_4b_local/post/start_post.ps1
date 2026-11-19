# start_post.ps1: start the 4B r3 post-training chain detached in WSL plus a hidden keepalive wsl.exe (as baton/start_auto.ps1),
# so .wslconfig instanceIdleTimeout (15 s) does not shut WSL down while it waits for the end of training.
#   powershell -ExecutionPolicy Bypass -File C:\Users\hp\Desktop\qidk\proofs\2026-11-06_4b_local\post\start_post.ps1
# Stop: wsl touch /mnt/c/Users/hp/Desktop/qidk/proofs/2026-11-06_4b_local/post/STOP (the keepalive ends with the chain).
$D = '/mnt/c/Users/hp/Desktop/qidk/proofs/2026-11-06_4b_local/post'
$P = '/mnt/c/Users/hp/Desktop/qidk/proofs'
wsl.exe bash -c "rm -f $D/STOP; bash $P/detach.sh post_4b $D/post_chain.sh"
Start-Process -WindowStyle Hidden wsl.exe -ArgumentList "bash $P/2026-10-29_rsn_v3/distill_laptop/keepalive.sh post_4b 720"
Write-Output "post_4b chain started (log: wsl ~/detached/post_4b.log; status: [post_4b] in proofs/2026-10-29_rsn_v3/kaggle/STATUS.md)"
