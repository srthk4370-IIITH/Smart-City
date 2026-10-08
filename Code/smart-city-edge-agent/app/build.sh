#!/usr/bin/env bash
# Build edge-agent for the QIDK (static linux/arm64; runs on Android as the shell user) and for the host.
set -euo pipefail
HERE="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
export PATH="$HOME/go-sdk/go/bin:$PATH"
cd "$HERE/backend"
go vet ./...
CGO_ENABLED=0 GOOS=linux GOARCH=arm64 go build -trimpath -ldflags "-s -w" -o "$HERE/device/edge-agent" .
go build -o "$HERE/device/edge-agent-host" .
echo "built: $(ls -la "$HERE/device/edge-agent" | awk '{print $5}') bytes arm64 + host binary"
