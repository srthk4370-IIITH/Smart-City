#!/usr/bin/env bash
# Host (WSL CPU) repro of the rsn_v2 board hang: htpd v8x3 host build, split-3 request q11, with
#   pass A: HTPD_PICK_BOUNDED=0 (= v8x2 pick path), HTPD_PICK_DEBUG=1, timeout 900 s
#   pass B: bounded pick (v8x3 default), same request
# usage: host_repro.sh <model.gguf> <req.json> <tag>   -> v8x3/host_<tag>_{A,B}.{log,json}
O=/mnt/c/Users/hp/Desktop/qidk/proofs/2026-10-28_master/v8x3; H=~/gpu_work/htpd_v8x3_host/htpd; M=$1; Q=$2; T=$3
PS=/mnt/c/Windows/System32/WindowsPowerShell/v1.0/powershell.exe
for pass in ${PASSES:-A B}; do
  until [ "$($PS -NoProfile -Command "[int](Get-Counter '\Memory\Available MBytes').CounterSamples.CookedValue" | tr -dc 0-9)" -ge 2000 ]; do sleep 30; done
  b=1; [ $pass = A ] && b=0
  HTPD_PICK_BOUNDED=$b HTPD_PICK_DEBUG=1 HTPD_REASON_TIMEOUT_MS=${TMO:-900000} HTPD_REASON_DISK_CACHE=0 nice -n 10 $H -m $M --device CPU -t ${THR:-6} \
    --agents 1 --agent-ctx 512 --synth-ctx 1024 --port 18091 --reasoner-model $M --reason-streams 3 > $O/host_${T}_$pass.log 2>&1 &
  hp=$!
  for i in $(seq 1 300); do grep -q "htpd: ready in" $O/host_${T}_$pass.log && break; sleep 1; done
  python3 - $Q $O/host_${T}_$pass.json <<'P'
import json, socket, sys, time
req = open(sys.argv[1]).read().strip(); s = socket.create_connection(("127.0.0.1", 18091), timeout=3600)
t = time.time(); s.sendall((req + "\n").encode()); buf = b""
while True:
    c = s.recv(1 << 16)
    if not c: break
    buf += c
    if b"\n" in buf:
        for ln in buf.split(b"\n"):
            if ln.strip() and b'"outputs"' in ln: open(sys.argv[2], "wb").write(ln); print("wall %.1f s" % (time.time() - t)); sys.exit(0)
        buf = buf.split(b"\n")[-1]
P
  kill $hp; wait $hp 2>/dev/null
  grep -E "reason stream|reason picks|timeout|split at|pick slow" $O/host_${T}_$pass.log | head -40 > $O/host_${T}_$pass.summary
done
echo HOST_REPRO_DONE >> $O/host_${T}_B.summary
