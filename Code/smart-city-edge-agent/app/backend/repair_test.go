package main

import (
	"encoding/json"
	"testing"
)

func TestDropUnmatchedBrackets(t *testing.T) {
	raw := `{"root_cause": "CO2 rose", "label": "occupancy_driven_load", "affected_domains": ["occupancy"], "evidence": ["S5.S1"], "confidence": 0.85, "action": "review_schedule", "explanation": "CO2 exceeded the limit [S1.E1]."]}`
	fixed, n := dropUnmatchedBrackets(raw)
	var rep Report
	if n != 1 || json.Unmarshal([]byte(fixed), &rep) != nil || rep.Label != "occupancy_driven_load" || rep.Explanation != "CO2 exceeded the limit [S1.E1]." {
		t.Fatalf("n=%d fixed=%s", n, fixed)
	}
	ok := `{"a": ["x]"], "b": "[y]"}`
	if out, n := dropUnmatchedBrackets(ok); n != 0 || out != ok {
		t.Fatalf("valid JSON changed: %s", out)
	}
}
