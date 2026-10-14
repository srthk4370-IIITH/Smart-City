package main

import (
	"strings"
	"testing"
)

// A CLI re-run after genied died repeats the same tokens; only the unseen tail may reach the dashboard.
func TestSkipStreamed(t *testing.T) {
	var got strings.Builder
	f := skipStreamed(func(s string) { got.WriteString(s) }, len(`{"pattern": "st`))
	for _, tk := range []string{`{"pat`, `tern": `, `"stable", `, `"status": `, `"normal"}`} {
		f(tk)
	}
	if got.String() != `able", "status": "normal"}` {
		t.Fatalf("got %q", got.String())
	}
}
