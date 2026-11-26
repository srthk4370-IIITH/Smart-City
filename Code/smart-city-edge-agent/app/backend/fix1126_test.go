package main

import "testing"

// paper fixes 2026-11-26: all-normal skip rule and the trailing-comma repair
func TestAllNormal(t *testing.T) {
	n := Finding{Status: "normal"}
	w := Finding{Status: "warning"}
	s := func(rule Finding, ctx bool) SensorRef { return SensorRef{Rule: rule, Context: ctx} }
	ok := func(f Finding) AgentCall { return AgentCall{Parsed: &f, Valid: true} }
	if !allNormal([]SensorRef{s(n, false), s(w, true)}, []AgentCall{ok(n), ok(w)}) {
		t.Fatal("flagged agent+rule normal (context warning ignored) should skip")
	}
	if allNormal([]SensorRef{s(n, false)}, []AgentCall{ok(w)}) {
		t.Fatal("agent warning must go to the reasoner")
	}
	if allNormal([]SensorRef{s(w, false)}, []AgentCall{ok(n)}) {
		t.Fatal("rule warning (disagreement) must go to the reasoner")
	}
	if !allNormal([]SensorRef{s(n, false)}, []AgentCall{{Valid: false}}) {
		t.Fatal("invalid agent: rule status stands in")
	}
	if allNormal([]SensorRef{s(n, true)}, nil) {
		t.Fatal("no flagged sensor: no skip")
	}
}

func TestTrailingCommaRe(t *testing.T) {
	in := `{"a": [1, 2, ], "b": {"c": 1,  }, }`
	if got := trailingCommaRe.ReplaceAllString(in, "$1"); got != `{"a": [1, 2], "b": {"c": 1}}` {
		t.Fatal(got)
	}
}
