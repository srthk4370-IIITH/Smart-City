mkdir -p /root/detached
setsid nohup bash /mnt/c/Users/hp/Desktop/qidk/proofs/2026-11-13_weight_edit/ramwatch.sh > /root/detached/ramwatch.log 2>&1 < /dev/null &
echo $! > /root/detached/ramwatch.pid; echo "started $(cat /root/detached/ramwatch.pid)"
