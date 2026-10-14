package main

import (
	"encoding/json"
	"testing"
)

// The scanner must fire only on a genuine top-level "action" key, and the truncated text plus "}"
// must always parse, because the policy gate will try to read it.
func TestTrailScannerFindsTopLevelAction(t *testing.T) {
	body := `{"pattern": "spike", "status": "warning", "observations": ["CO2 rose [E1]"], ` +
		`"likely_cause": "occupancy_load", "confidence": 0.82, "action": "monitor"}`
	ts := newTrailScanner()
	cut := ts.feed(body, "action")
	if cut < 0 {
		t.Fatal("did not find the action key")
	}
	trimmed := body[:cut] + "}"
	var m map[string]any
	if err := json.Unmarshal([]byte(trimmed), &m); err != nil {
		t.Fatalf("trimmed JSON does not parse: %v\n%s", err, trimmed)
	}
	if _, present := m["action"]; present {
		t.Fatal("action should have been cut off")
	}
	for _, k := range []string{"pattern", "status", "observations", "likely_cause", "confidence"} {
		if _, ok := m[k]; !ok {
			t.Fatalf("lost field %q: %s", k, trimmed)
		}
	}
}

// Fed one byte at a time, indices must still be absolute and correct.
func TestTrailScannerChunked(t *testing.T) {
	body := `{"pattern": "dip", "confidence": 0.5, "action": "none"}`
	ts := newTrailScanner()
	cut := -1
	for i := 0; i < len(body) && cut < 0; i++ {
		cut = ts.feed(body[i:i+1], "action")
	}
	if cut < 0 {
		t.Fatal("not found when streamed byte by byte")
	}
	var m map[string]any
	if err := json.Unmarshal([]byte(body[:cut]+"}"), &m); err != nil {
		t.Fatalf("chunked trim does not parse: %v", err)
	}
}

// The word must not trigger inside strings, nested objects, or as a value.
func TestTrailScannerIgnoresDecoys(t *testing.T) {
	for _, body := range []string{
		`{"pattern": "spike", "observations": ["take action now [E1]"], "confidence": 0.3}`,
		`{"pattern": "spike", "meta": {"action": "nested"}, "confidence": 0.3}`,
		`{"pattern": "action", "confidence": 0.3}`,
	} {
		ts := newTrailScanner()
		if cut := ts.feed(body, "action"); cut >= 0 {
			t.Fatalf("false positive on %s (cut=%d)", body, cut)
		}
	}
}

// No comma seen yet means nothing safe to cut at.
func TestTrailScannerNoLeadingComma(t *testing.T) {
	ts := newTrailScanner()
	if cut := ts.feed(`{"action": "none"}`, "action"); cut >= 0 {
		t.Fatalf("should not cut when action is the first field, got %d", cut)
	}
}
