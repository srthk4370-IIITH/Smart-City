package main

import (
	"context"
	"encoding/json"
	"os"
	"path/filepath"
	"strings"
	"testing"
	"time"
)

// Without chat_prompt=r3 the r3 APK must behave as deploy32 (split7): the archive index is not read, search_knowledge
// is the offline stub, the r3-only tools are unknown, and the prompt is the 15-tool (adaptive) or 9-tool header.
func TestChatR3OffIsDeploy32(t *testing.T) {
	t.Setenv("SCE_CHAT_PROMPT", "")
	dir := t.TempDir()
	old := htpdWorkDir
	htpdWorkDir = dir // no htpd_profile here
	defer func() { htpdWorkDir = old }()
	now := time.Date(2026, 10, 14, 12, 0, 0, 0, IST)
	r := &Reasoner{store: filepath.Join(dir, "incidents.jsonl")}
	r.incidents = []*Incident{{ID: "INC-0002", Title: "live", Severity: "warning", CreatedSim: now.Add(-time.Hour).Unix()}}
	b, _ := json.Marshal(&Incident{ID: "INC-0001", Title: "archived", Severity: "warning", CreatedSim: now.Add(-48 * time.Hour).Unix()})
	if err := os.WriteFile(archivePath(r.store), append(b, '\n'), 0o644); err != nil {
		t.Fatal(err)
	}
	tools := chatTools{r: r, now: now}
	if n := len(tools.incidents()); n != 1 {
		t.Fatalf("default mode read the archive index: %d incidents, want 1", n)
	}
	k := tools.Exec(context.Background(), "search_knowledge", map[string]any{"query": "pH"})
	if !strings.Contains(k, `"available":false`) {
		t.Fatalf("search_knowledge is not the deploy32 stub: %s", k)
	}
	for _, name := range []string{"fog_status", "fog_search_history", "fog_analytics", "co_occurring_incidents", "recurring_issues", "compare_periods"} {
		if s := tools.Exec(context.Background(), name, map[string]any{}); !strings.Contains(s, "unknown tool") {
			t.Fatalf("%s exists without chat_prompt=r3: %s", name, s)
		}
	}
	if p := chatStaticPrefixMode(now, true); !strings.HasPrefix(p, chatHeader15) || strings.Contains(p, "fog_status") {
		t.Fatal("adaptive prompt without r3 is not the 15-tool header")
	}
	if p := chatStaticPrefixMode(now, false); !strings.HasPrefix(p, chatHeader) {
		t.Fatal("rsn_v1 prompt is not the 9-tool header")
	}
	t.Setenv("SCE_REASONER_MODEL", "/data/local/tmp/gpu/qwen35_reasoner_q4_0.gguf") // live rsn_v1: label unchanged
	if l := reasonerModelLabel(); l != "qwen3.5-4b" {
		t.Fatalf("live label %q", l)
	}
	t.Setenv("SCE_REASONER_MODEL", "/data/local/tmp/gpu/rsn_v3_4b_r3_q4_0.gguf")
	if l := reasonerModelLabel(); l != "qwen3.5-4b rsn_v3" {
		t.Fatalf("r3 label %q", l)
	}
	// and with r3 on, the archive index and the 21-tool header are used
	t.Setenv("SCE_CHAT_PROMPT", "r3")
	if n := len(tools.incidents()); n != 2 {
		t.Fatalf("r3 mode: %d incidents, want 2 (archive index)", n)
	}
	if p := chatStaticPrefixMode(now, true); !strings.HasPrefix(p, chatHeaderR3) {
		t.Fatal("r3 prompt is not the 21-tool header")
	}
}
