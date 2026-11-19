# peek.sh: short progress view of the fit probe job
D=/mnt/c/Users/hp/Desktop/qidk/proofs/2026-11-06_4b_local
tail -c 300 ~/detached/fit4b_probe.log; echo; cat $D/logs/summary.txt 2>/dev/null
for f in $(ls -t $D/logs/*.log | grep -v -e watch -e diag | head -1); do echo "== $f"; grep -v -e Loading -e Triton -e causal_conv $f | tail -4 | cut -c1-300; done
tail -1 $(ls -t $D/logs/watch_*.log | head -1) 2>/dev/null; free -m | awk 'NR==2{print "avail", $7}'
