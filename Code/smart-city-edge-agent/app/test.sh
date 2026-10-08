#!/usr/bin/env bash
set -euo pipefail
export PATH="$HOME/go-sdk/go/bin:$PATH"
cd "$(dirname "${BASH_SOURCE[0]}")/backend" && go test -v -run "Parity|Streaming" ./... 2>&1 | tail -15
