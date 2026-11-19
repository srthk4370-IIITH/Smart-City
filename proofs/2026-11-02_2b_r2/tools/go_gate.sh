#!/usr/bin/env bash
# go_gate.sh OUT.jsonl ROWS1.jsonl[,ROWS2...]: run gold incident reports through the app's Go gate (copy of app/backend, never touched).
set -euo pipefail
HERE=$(cd "$(dirname "$0")" && pwd)
REPO=$(cd "$HERE/../../.." && pwd)
BE=$REPO/Code/smart-city-edge-agent/app/backend
GO=${GO:-$(command -v go || echo "$HOME/go-sdk/go/bin/go")}
TMP=$(mktemp -d /tmp/r2_gate.XXXXXX); trap 'rm -rf "$TMP"' EXIT
for f in "$BE"/*.go; do case "$f" in *_test.go) ;; *) cp "$f" "$TMP/";; esac; done
cp "$BE"/*.txt "$BE"/go.mod "$TMP/"; [ -f "$BE/go.sum" ] && cp "$BE/go.sum" "$TMP/"
cp "$HERE/r2_gate_test.go" "$TMP/"
(cd "$TMP" && GOMAXPROCS=2 R2_ROWS="$2" R2_OUT="$1" nice -n 15 "$GO" test -p 1 -tags r2gate -count=1 -run TestR2Gate -timeout 60m -v . 2>&1 | tail -n 4)
