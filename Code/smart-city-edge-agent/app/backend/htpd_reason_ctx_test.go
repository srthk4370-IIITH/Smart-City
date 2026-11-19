package main

import (
	"os"
	"path/filepath"
	"testing"
)

// reason_ctx unset = htpd's default (no --reason-ctx, args string unchanged); set = passed through; out of range = ignored.
func TestHtpdReasonCtx(t *testing.T) {
	dir := t.TempDir()
	old := htpdWorkDir
	htpdWorkDir = dir
	defer func() { htpdWorkDir = old }()
	for _, c := range []struct {
		prof string
		want int
	}{{"", 0}, {"reason_ctx=8192\n", 8192}, {"reason_ctx=100\n", 0}, {"reason_ctx=abc\n", 0}} {
		if err := os.WriteFile(filepath.Join(dir, "htpd_profile"), []byte(c.prof), 0o644); err != nil {
			t.Fatal(err)
		}
		if got := htpdReasonCtx(); got != c.want {
			t.Fatalf("profile %q: reason_ctx %d, want %d", c.prof, got, c.want)
		}
	}
}
