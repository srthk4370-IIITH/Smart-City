cd /mnt/c/Users/hp/Desktop/qidk/proofs/2026-10-31_agents_latency
NREQ=6 nice -n 10 python3 host_ag.py > host/host_ag.out 2>&1
echo HOST_DONE >> host/host_ag.out
