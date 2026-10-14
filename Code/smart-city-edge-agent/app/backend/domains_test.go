package main

import "testing"

// Stress pass 3, INC-0114: the synthesizer listed only [weather] while power, water and air-quality
// sensors in the same incident were critical. Policy completes the list from the rule view.
func TestAffectedDomainsCompletedFromAbnormalSensors(t *testing.T) {
	raw := `{"root_cause": "Storm front", "label": "weather_driven", "affected_domains": ["weather"], "evidence": ["S1.E1"], "confidence": 0.7, "action": "monitor", "explanation": "Storm [S1.E1]."}`
	sensors := []SensorRef{
		{Ref: "S1", Role: "weather", Rule: Finding{Status: "warning"}},
		{Ref: "S2", Role: "power", Rule: Finding{Status: "critical"}},
		{Ref: "S3", Role: "water", Rule: Finding{Status: "critical"}},
		{Ref: "S4", Role: "occupancy", Rule: Finding{Status: "normal"}},
		{Ref: "S5", Role: "air_quality", Rule: Finding{Status: "critical"}, Context: true},
	}
	rc := (&Reasoner{}).checkReport(GenieResult{Text: raw}, "", sensors)
	if rc.Parsed == nil {
		t.Fatalf("not parsed: %v", rc.Errors)
	}
	got := rc.Parsed.AffectedDomains
	want := []string{"weather", "power", "water"}
	if len(got) != len(want) {
		t.Fatalf("domains=%v want %v (repairs=%v)", got, want, rc.Repairs)
	}
	for i := range want {
		if got[i] != want[i] {
			t.Fatalf("domains=%v want %v", got, want)
		}
	}
	if rc.Parsed.Label != "weather_driven" {
		t.Fatalf("label changed to %s", rc.Parsed.Label)
	}
}
