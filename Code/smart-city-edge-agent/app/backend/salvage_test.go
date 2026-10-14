package main

import (
	"os"
	"testing"
)

// A real synthesizer output from the QIDK (incident INC-0050, app stress test 2026-10-14): the
// object was closed with `]` instead of `}`, so policy found "no complete JSON object" and the
// report was rejected. The salvage must recover it - and then validate it like any other report.
func TestSalvageObjectClosedWithBracket(t *testing.T) {
	raw, err := os.ReadFile("testdata/synth_closed_with_bracket.txt")
	if err != nil {
		t.Fatal(err)
	}
	if _, ok := extractJSON(string(raw)); ok {
		t.Fatal("fixture should be malformed as captured")
	}
	r := &Reasoner{}
	rc := r.checkReport(GenieResult{Text: string(raw)}, "", nil)
	found := false
	for _, rep := range rc.Repairs {
		if rep == "object closed with ']' instead of '}'" {
			found = true
		}
	}
	if !found {
		t.Fatalf("expected the bracket repair, got repairs=%v errors=%v", rc.Repairs, rc.Errors)
	}
	if rc.Parsed == nil || rc.Parsed.Label == "" {
		t.Fatalf("report not parsed after repair: %+v errors=%v", rc.Parsed, rc.Errors)
	}
	t.Logf("recovered: label=%s action=%s (errors after full validation: %v)", rc.Parsed.Label, rc.Parsed.Action, rc.Errors)
}
