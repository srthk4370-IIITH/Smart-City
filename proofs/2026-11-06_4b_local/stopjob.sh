# stopjob.sh: stop the detached fit4b_probe job (process group) and any trainer it started (CONT so a paused one can exit)
P=$(cat ~/detached/fit4b_probe.pid); kill -- -$P 2>/dev/null
for p in $(pgrep -f "train_rsn3.py.*fit4b"); do kill -TERM $p; kill -CONT $p; done
sleep 6; pgrep -fa "train_rsn3|fit_probe" | cut -c1-80; free -m | sed -n 2p; nvidia-smi --query-gpu=memory.used --format=csv,noheader
