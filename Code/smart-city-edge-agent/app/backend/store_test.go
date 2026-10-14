package main

import (
	"fmt"
	"os"
	"path/filepath"
	"strings"
	"testing"
)

// Power cut mid-append: a torn last line must not lose earlier versions, must not make an ID be
// reused, and must be compacted away. Retention archives the oldest incidents instead of deleting.
func TestStoreTornLineCompactionAndRetention(t *testing.T) {
	dir := t.TempDir()
	os.MkdirAll(filepath.Join(dir, "state"), 0o755)
	store := filepath.Join(dir, "state", "incidents.jsonl")
	var b strings.Builder
	for i := 1; i <= 60; i++ {
		fmt.Fprintf(&b, `{"id":"INC-%04d","state":"running"}`+"\n", i)
		fmt.Fprintf(&b, `{"id":"INC-%04d","state":"done"}`+"\n", i)
	}
	b.WriteString(`{"id":"INC-0061","state":"do`) // torn
	os.WriteFile(store, []byte(b.String()), 0o644)
	os.Setenv("SCE_MAX_INCIDENTS", "50")
	defer os.Unsetenv("SCE_MAX_INCIDENTS")

	r := &Reasoner{store: store}
	r.load()
	if r.seq != 60 {
		t.Fatalf("seq=%d want 60", r.seq)
	}
	if len(r.incidents) != 50 || r.incidents[0].ID != "INC-0011" {
		t.Fatalf("kept %d, first %s", len(r.incidents), r.incidents[0].ID)
	}
	for _, inc := range r.incidents {
		if inc.State != "done" {
			t.Fatalf("%s state %s, want newest version", inc.ID, inc.State)
		}
	}
	raw, _ := os.ReadFile(store)
	if n := strings.Count(string(raw), "\n"); n != 50 {
		t.Fatalf("store has %d lines after compaction, want 50", n)
	}
	arch, _ := os.ReadFile(archivePath(store))
	if n := strings.Count(string(arch), "\n"); n != 10 || !strings.Contains(string(arch), "INC-0001") {
		t.Fatalf("archive has %d lines", n)
	}
	// reload: same result, nothing duplicated
	r2 := &Reasoner{store: store}
	r2.load()
	if len(r2.incidents) != 50 || r2.seq != 60 {
		t.Fatalf("reload: %d incidents seq %d", len(r2.incidents), r2.seq)
	}
}
