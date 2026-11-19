V=/mnt/c/Users/hp/Desktop/qidk/proofs/2026-10-29_latency/v8x5/htpd
strings $V | grep "htpd" | sort > /tmp/sv; strings /tmp/b_26d/htpd | grep "htpd" | sort > /tmp/sb; diff /tmp/sv /tmp/sb | head -20
strings $V | grep -i "/mnt\|/home" | head
