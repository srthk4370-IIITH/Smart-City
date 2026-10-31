#!/usr/bin/env bash
# Run the heat_r2 rows through the app's Go gate (checkReportV3For + weatherOnlyIncident), WSL, CPU, ~1 min.
# A COPY of app/backend (non-test .go, embedded .txt, go.mod/go.sum) + heat_r2_validate_test.go is built in a temp dir;
# the repo's backend is never touched. Writes data/heat_r2/go_gate.json.
#   bash proofs/2026-10-29_rsn_v3/pipeline/heat_r2_go_check.sh [DATA_DIR]
set -euo pipefail
HERE=$(cd "$(dirname "$0")" && pwd)
V3=$(cd "$HERE/.." && pwd)
REPO=$(cd "$V3/../.." && pwd)
BE=$REPO/Code/smart-city-edge-agent/app/backend
DATA=${1:-$V3/data/heat_r2}
GO=${GO:-$(command -v go || echo "$HOME/go-sdk/go/bin/go")}
TMP=$(mktemp -d /tmp/heat_r2_gate.XXXXXX)
trap 'rm -rf "$TMP"' EXIT
for f in "$BE"/*.go; do case "$f" in *_test.go) ;; *) cp "$f" "$TMP/";; esac; done
cp "$BE"/*.txt "$BE"/go.mod "$TMP/"
[ -f "$BE/go.sum" ] && cp "$BE/go.sum" "$TMP/"
cp "$HERE/heat_r2_validate_test.go" "$TMP/"
(cd "$TMP" && GOMAXPROCS=2 HEAT_R2_ROWS="$DATA/train.jsonl,$DATA/dev.jsonl" HEAT_R2_OUT="$TMP/go_gate.json" \
  nice -n 15 "$GO" test -p 1 -tags heatr2 -count=1 -run TestHeatR2Gate -v . 2>&1 | tail -n 5) | tee "$TMP/log.txt"
cp "$TMP/go_gate.json" "$DATA/go_gate.json"
grep -q -- "--- PASS: TestHeatR2Gate" "$TMP/log.txt"
