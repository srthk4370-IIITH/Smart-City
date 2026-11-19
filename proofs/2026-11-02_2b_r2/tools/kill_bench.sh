#!/usr/bin/env bash
# kill_bench.sh: stop every r2 benchmark process (driver, laptop_train wrappers, trainer), then show what's left.
for p in $(pgrep -f 'bench_r2'); do echo "kill driver $p"; kill $p; done
for p in $(pgrep -f 'r2bench'); do echo "kill r2bench proc $p: $(ps -o args= -p $p | cut -c1-80)"; kill -CONT $p 2>/dev/null; kill $p; done
sleep 15
for p in $(pgrep -f 'r2bench'); do echo "force $p"; kill -9 $p; done
pgrep -af 'train_rsn3|laptop_train|bench' | grep -v pgrep | cut -c1-120
echo done
