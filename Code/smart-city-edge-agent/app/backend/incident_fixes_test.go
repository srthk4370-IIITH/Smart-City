package main

import "testing"

func TestSeverityGuardTrendOnly(t *testing.T) {
	r := &Reasoner{notify: func(string, any) {}}
	mk := func(last float64) *Incident {
		xs := make([]float64, Window)
		for i := range xs {
			xs[i] = last
		}
		return &Incident{ID: "INC-T", Sensors: []SensorRef{{Ref: "S1", Role: "air_quality", Metric: "co2", Xs: xs,
			Rule: Finding{Status: "warning", Pattern: "gradual_increase"}}}}
	}
	rep := Report{Severity: "normal", Title: "x"}
	r.severityGuard(mk(800), &rep) // inside the 1000 ppm limit: trend only, the AI wins
	if rep.Severity != "normal" || rep.Title != "Watching: CO2 gradual increase, AI judged normal" || rep.SeverityBasis.Final != "normal" || rep.SeverityBasis.Guard == "" {
		t.Fatalf("trend-only: %+v %q", rep.SeverityBasis, rep.Title)
	}
	rep = Report{Severity: "normal", Title: "x"}
	r.severityGuard(mk(1100), &rep) // crosses the warning limit: guard stays
	if rep.Severity != "warning" || rep.SeverityBasis.Final != "warning" {
		t.Fatalf("limit crossed: %+v", rep.SeverityBasis)
	}
}

func TestCleanTitleRefs(t *testing.T) {
	for in, want := range map[string]string{
		"Air quality warning, level 03: S1 warns": "Air quality warning, level 03: one sensor warns",
		"S1 and S2 warn":            "2 sensors warn",
		"Power load stepped up: KH": "Power load stepped up: KH",
	} {
		if got := cleanTitleRefs(in); got != want {
			t.Fatalf("%q -> %q, want %q", in, got, want)
		}
	}
}

func TestReportChecklistBecomesSteps(t *testing.T) {
	inc := &Incident{ID: "INC-C", Severity: "warning", Sensors: []SensorRef{{Ref: "S1", Node: "N1", Metric: "co2", Rule: Finding{Status: "warning"}}},
		Final: &ReportCall{Valid: true, Parsed: &Report{Severity: "warning", Action: "inspect_ventilation", RootCause: "x",
			Checklist: []V3ChecklistItem{{Action: "inspect_ventilation", Target: "N1", Why: "a"}, {Action: "check_sensor", Target: "N1", Why: "b"}}}}}
	inc.Owner = "op"
	mergeSteps(inc, "early")
	if len(inc.Steps) != 2 || inc.Steps[1].Action != "check_sensor" || inc.Steps[1].Source != "report" {
		t.Fatalf("steps: %+v", inc.Steps)
	}
	inc.Steps[1].State = "done"
	// refine: S1 reads normal; the ticked step stays, the open one it caused is withdrawn
	inc.Agents = []AgentCall{{Ref: "S1", Valid: true, Parsed: &Finding{Status: "normal"}}}
	inc.Final = &ReportCall{Valid: true, Parsed: &Report{Severity: "warning", Action: "monitor", Checklist: []V3ChecklistItem{{Action: "inspect_ventilation", Target: "N1"}}}}
	mergeSteps(inc, "1.5h")
	if inc.Steps[0].State != "withdrawn" || inc.Steps[1].State != "done" {
		t.Fatalf("after refine: %+v", inc.Steps)
	}
}

func TestCriticalFastPathEarlyAIImmediately(t *testing.T) {
	r := &Reasoner{notify: func(string, any) {}}
	crit := &Incident{FastPath: true, Sensors: []SensorRef{{Ref: "S1", Rule: Finding{Status: "critical"}}}}
	if w := r.shortEventWait(crit); w != 0 {
		t.Fatalf("critical fast path waits %v, want 0 (early AI on history)", w)
	}
	warn := &Incident{FastPath: true, Sensors: []SensorRef{{Ref: "S1", Rule: Finding{Status: "warning"}}}}
	if w := r.shortEventWait(warn); w != shortEventMin {
		t.Fatalf("non-critical wait %v, want %v", w, shortEventMin)
	}
}
