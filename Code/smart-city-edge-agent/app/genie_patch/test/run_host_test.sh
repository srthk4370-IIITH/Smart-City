#!/bin/bash
# Compiles test/sched_test.cpp against the STOCK and the PATCHED scheduler and runs both.
# Usage (WSL): bash run_host_test.sh <stock Genie dir> <patched Genie dir>
set -e
HERE="$(cd "$(dirname "$0")" && pwd)"
STOCK="${1:-$HOME/genie_patch_build/orig}"
PATCHED="${2:-$HOME/genie_patch_build/sdk/examples/Genie/Genie}"
SDKINC="${SDKINC:-$HOME/qairt/qairt/2.50.0.260828/include/Genie}"
OUT="${OUT:-/tmp/genie_sched_test}"
mkdir -p "$OUT"
build() { # $1 = Genie dir, $2 = out binary, $3 = extra define
  local S="$1/src"
  g++ -std=c++20 -O1 -g -pthread $3 -DFMT_HEADER_ONLY \
    -I "$S" -I "$S/qualla/include" -I "$S/qualla/include/qualla" -I "$S/qualla/engines" -I "$S/trace/include" -I "$S/quantization/include" -I "$S/resource-manager/include" -I "$S/pipeline" -I "$SDKINC" -I "$SDKINC/../QNN" \
    "$S/qualla/engines/inference-scheduler.cpp" "$HERE/sched_test.cpp" "$HERE/env_stub.cpp" -o "$2"
}
build "$STOCK" "$OUT/stock" ""
build "$PATCHED" "$OUT/patched" "-DPATCHED"
for args in "2 600 100 20 300" "2 500 150 30 900" "3 550 120 15 200" "4 400 100 15 200"; do
  echo "== args: $args"
  echo -n "stock  : "; timeout 120 "$OUT/stock" $args || echo "(exit $?)"
  echo -n "patched: "; timeout 120 "$OUT/patched" $args || echo "(exit $?)"
done
