package main

import (
	"context"
	"os"
	"path/filepath"
	"strings"
	"testing"
	"time"
)

// Fake genie-t2t-run: echoes the prompt, streams a JSON answer token by token, then rambles for ~6 s.
const fakeGenie = `#!/bin/sh
echo "[PROMPT]: whatever"
printf "[BEGIN]: "
for t in 'stable", ' '"status": ' '"normal", ' '"observations": ' '["CO2 {braces} in \"text\" [E1]"], ' '"likely_cause": ' '"normal_conditions", ' '"confidence": 0.9, ' '"action": "none"}' ; do
  printf '%s' "$t"; sleep 0.1
done
i=0; while [ $i -lt 60 ]; do printf ' ramble'; sleep 0.1; i=$((i+1)); done
echo "[END]"
`

func TestStreamingEarlyStop(t *testing.T) {
	dir := t.TempDir()
	bin := filepath.Join(dir, "genie-t2t-run-2.50")
	os.WriteFile(bin, []byte(fakeGenie), 0o755)
	os.WriteFile(filepath.Join(dir, "smartcity_agent.json"), []byte("{}"), 0o644)
	g := &GenieRunner{runtime: dir, binary: bin, promptDir: dir}
	g.lastErr.Store("")
	var chunks []string
	t0 := time.Now()
	res := g.Run(context.Background(), ModelBundle{Dir: dir, Config: "smartcity_agent.json"}, "prompt"+AgentPrefill, AgentPrefill,
		30*time.Second, func(s string) { chunks = append(chunks, s) })
	el := time.Since(t0)
	full := AgentPrefill + res.Text
	t.Logf("elapsed %.2fs ttft %.0fms tokens %d early %v\n%s", el.Seconds(), res.TTFTMs, res.GenTokens, res.EarlyStopped, full)
	if res.Error != "" {
		t.Fatal(res.Error)
	}
	if !res.EarlyStopped || el > 4*time.Second {
		t.Fatalf("expected early stop well before the 7 s ramble, took %v", el)
	}
	if strings.Contains(full, "ramble") || !strings.HasSuffix(full, `"action": "none"}`) {
		t.Fatalf("answer not cut at JSON end: %q", full)
	}
	js, ok := extractJSON(full)
	if !ok || js != full {
		t.Fatalf("json extraction mismatch")
	}
	if len(chunks) < 5 {
		t.Fatalf("expected streamed chunks, got %d", len(chunks))
	}
}
