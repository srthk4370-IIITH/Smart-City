package main

import (
	"strings"
	"testing"
)

func titleInc() *Incident {
	return &Incident{
		Title: "3 sensors alarming: CO2 sensor fault, PM2.5 critical, Power warning",
		Sensors: []SensorRef{
			{Ref: "S1", Metric: "co2", Location: "KH building", Rule: Finding{Pattern: "flatline", Status: "sensor_fault"}},
			{Ref: "S2", Metric: "pm25", Location: "KN building", Rule: Finding{Pattern: "spike", Status: "critical"}},
			{Ref: "S3", Metric: "power_kw", Location: "SB00", Rule: Finding{Pattern: "step_increase", Status: "warning"}},
			{Ref: "S4", Metric: "rh", Location: "KH building", Context: true, Rule: Finding{Pattern: "stable", Status: "normal"}},
		},
	}
}

func TestTitleFollowsAgents(t *testing.T) {
	inc := titleInc()
	inc.Agents = []AgentCall{
		{Ref: "S1", Valid: true, Parsed: &Finding{Pattern: "stable", Status: "normal"}},
		{Ref: "S2", Valid: true, Parsed: &Finding{Pattern: "spike", Status: "critical"}},
		{Ref: "S3", Valid: true, Parsed: &Finding{Pattern: "step_increase", Status: "warning"}},
	}
	inc.Final = &ReportCall{Valid: true, Parsed: &Report{Label: "weather_driven"}}
	finaliseSeverity(inc)
	if strings.Contains(inc.Title, "CO2") {
		t.Fatalf("CO2 was judged normal by its agent but is still in the title: %q", inc.Title)
	}
	if want := "Weather driven: PM2.5 critical, Power warning"; inc.Title != want {
		t.Fatalf("title %q, want %q", inc.Title, want)
	}
	if !strings.HasPrefix(inc.RuleTitle, "3 sensors alarming") {
		t.Fatalf("rule title not kept: %q", inc.RuleTitle)
	}
	finaliseSeverity(inc) // idempotent: the rules' title is not overwritten by the AI's
	if !strings.HasPrefix(inc.RuleTitle, "3 sensors alarming") {
		t.Fatalf("rule title overwritten on second call: %q", inc.RuleTitle)
	}
}

func TestTitleAllClearAndSingle(t *testing.T) {
	inc := titleInc()
	inc.Agents = []AgentCall{
		{Ref: "S1", Valid: true, Parsed: &Finding{Pattern: "stable", Status: "normal"}},
		{Ref: "S2", Valid: true, Parsed: &Finding{Pattern: "stable", Status: "normal"}},
		{Ref: "S3", Valid: true, Parsed: &Finding{Pattern: "gradual_increase", Status: "normal"}},
	}
	if got := reasonerTitle(inc); got != "All clear: 3 sensors checked (CO2, PM2.5, Power)" {
		t.Fatalf("all clear title %q", got)
	}
	inc.Agents[1].Parsed = &Finding{Pattern: "stable", Status: "critical"} // steady shape, abnormal value
	if got := reasonerTitle(inc); got != "PM2.5 critical: KN building" {
		t.Fatalf("single confirmed title %q", got)
	}
	inc.Agents[1].Valid = false // rejected by the policy gate: the rule finding stands
	if got := reasonerTitle(inc); got != "PM2.5 spike: KN building" {
		t.Fatalf("fallback title %q", got)
	}
}

func TestTitleFromReasoner(t *testing.T) {
	inc := titleInc()
	inc.Final = &ReportCall{Valid: true, Parsed: &Report{Title: "  Dust storm   raises PM across campus " + strings.Repeat("x", 200)}}
	got := reasonerTitle(inc)
	if !strings.HasPrefix(got, "Dust storm raises PM across campus") || len([]rune(got)) != 120 {
		t.Fatalf("reasoner title not used/capped: %q (%d)", got, len([]rune(got)))
	}
	inc.Final.Valid = false
	if strings.HasPrefix(reasonerTitle(inc), "Dust") {
		t.Fatal("title from a report that failed the policy gate was used")
	}
}

// An isolated incident whose agent says "stable/normal" while the 12 h check sees a slow drift (the
// tank-leak run on the QIDK, INC-0610): the incident is a warning and the title says why.
func TestLongRangeRaisesNormalAgent(t *testing.T) {
	inc := &Incident{Title: "Tank level stable: KH building",
		Sensors: []SensorRef{{Ref: "S1", Metric: "level", Location: "KH building", Rule: Finding{Pattern: "stable", Status: "warning"},
			LongRange: []LongRange{{ID: "E9", Kind: "slow_drift", Delta: -65}}}}}
	inc.Agents = []AgentCall{{Ref: "S1", Valid: true, Parsed: &Finding{Pattern: "stable", Status: "normal"}}}
	finaliseSeverity(inc)
	if inc.Severity != "warning" {
		t.Fatalf("severity %q, want warning from the 12 h drift", inc.Severity)
	}
	if inc.Title != "Tank level slow drift (12 h view): KH building" {
		t.Fatalf("title %q", inc.Title)
	}
	inc.Sensors[0].LongRange = nil
	finaliseSeverity(inc)
	if inc.Severity != "normal" || inc.Title != "Tank level judged normal: KH building" {
		t.Fatalf("without 12 h finding: %q %q", inc.Severity, inc.Title)
	}
}
