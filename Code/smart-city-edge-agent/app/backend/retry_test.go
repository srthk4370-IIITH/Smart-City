package main

import (
	"context"
	"os"
	"path/filepath"
	"strings"
	"testing"
	"time"
)

// Fake genie that fails context creation (QIDK err 1002) the first N runs, then answers.
const flakyGenie = `#!/bin/sh
n=$(cat "$0.count" 2>/dev/null || echo 0); n=$((n+1)); echo $n > "$0.count"
if [ $n -le FAILS ]; then
  echo '[ERROR] "Could not create context from binary for context index = 2 : err 1002"' >&2
  echo 'Failed to free device: 14003' >&2; exit 1
fi
printf '[BEGIN]: stable", "status": "normal", "observations": ["ok [E1]"], "likely_cause": "normal_conditions", "confidence": 0.9, "action": "none"}[END]'
`

func runFlaky(t *testing.T, fails string) GenieResult {
	dir := t.TempDir()
	bin := filepath.Join(dir, "genie")
	os.WriteFile(bin, []byte(strings.Replace(flakyGenie, "FAILS", fails, 1)), 0o755)
	g := &GenieRunner{runtime: dir, binary: bin, promptDir: dir}
	g.lastErr.Store("")
	return g.Run(context.Background(), ModelBundle{Dir: dir, Config: "c.json"}, "p"+AgentPrefill, AgentPrefill, 20*time.Second, nil)
}

func TestHTPRetryRecovers(t *testing.T) {
	res := runFlaky(t, "2") // first attempt + first retry fail, second retry works (old code gave up here)
	if res.Error != "" || res.Retries != 2 || !strings.Contains(res.Text, `"action": "none"}`) {
		t.Fatalf("retries=%d err=%q text=%q", res.Retries, res.Error, res.Text)
	}
}

func TestHTPRetryGivesUpAsHardware(t *testing.T) {
	if testing.Short() {
		t.Skip("takes ~25 s")
	}
	res := runFlaky(t, "9")
	if res.Retries != 3 || !strings.HasPrefix(res.Error, "NPU unavailable") {
		t.Fatalf("retries=%d err=%q", res.Retries, res.Error)
	}
}
