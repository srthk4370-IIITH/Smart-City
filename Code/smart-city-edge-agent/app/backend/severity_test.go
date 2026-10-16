package main

import (
	"os"
	"path/filepath"
	"strings"
	"testing"
)

// The incident that motivated severity.go: several "step decrease" sensors flagged critical by the
// rules, every domain agent judged them normal - the incident stayed "critical" in the list.
func sevIncident() *Incident {
	stepDown := func(ref, role, st string) SensorRef {
		return SensorRef{Ref: ref, Role: role, Rule: Finding{Pattern: "step_decrease", Status: st}}
	}
	inc := &Incident{ID: "INC-0001", Mode: 3, State: "done", Severity: "critical", Sensors: []SensorRef{
		stepDown("S1", "power", "critical"), stepDown("S2", "water", "critical"), stepDown("S3", "air_quality", "warning"),
		{Ref: "S4", Role: "weather", Context: true, Rule: Finding{Pattern: "spike", Status: "critical"}},
	}}
	for _, s := range inc.Sensors {
		inc.Agents = append(inc.Agents, AgentCall{Ref: s.Ref, Role: s.Role, Valid: true,
			Parsed: &Finding{Pattern: "step_decrease", Status: "normal"}})
	}
	inc.Final = &ReportCall{Valid: true, Parsed: &Report{Label: "normal_operation"}}
	return inc
}

func TestAgentsSayNormalIncidentNotCritical(t *testing.T) {
	inc := sevIncident()
	finaliseSeverity(inc)
	if inc.Severity != "normal" || !inc.SeverityFinal || inc.Final.Parsed.Severity != "normal" {
		t.Fatalf("severity=%q final=%v report=%q, want normal from the agents", inc.Severity, inc.SeverityFinal, inc.Final.Parsed.Severity)
	}
}

func TestReasonerSeverityStub(t *testing.T) {
	cases := []struct {
		name string
		edit func(*Incident)
		want string
	}{
		{"worst agent status wins", func(i *Incident) { i.Agents[1].Parsed.Status = "warning" }, "warning"},
		{"warning outranks sensor fault", func(i *Incident) {
			i.Agents[0].Parsed.Status, i.Agents[1].Parsed.Status = "sensor_fault", "warning"
		}, "warning"},
		{"sensor fault alone", func(i *Incident) { i.Agents[2].Parsed.Status = "sensor_fault" }, "sensor_fault"},
		{"rejected agent falls back to its rule finding", func(i *Incident) { i.Agents[0].Valid = false }, "critical"},
		{"missing agent falls back to its rule finding", func(i *Incident) { i.Agents = i.Agents[1:] }, "critical"},
		{"related context sensor does not raise it", func(i *Incident) { i.Agents[3].Parsed.Status = "critical" }, "normal"},
		{"reasoner's own severity preferred", func(i *Incident) { i.Final.Parsed.Severity = "High" }, "critical"},
		{"unrecognised reasoner severity ignored", func(i *Incident) { i.Final.Parsed.Severity = "purple" }, "normal"},
		{"rejected report's severity ignored", func(i *Incident) {
			i.Final.Valid, i.Final.Parsed.Severity = false, "critical"
		}, "normal"},
		{"mode 1: rule findings", func(i *Incident) { i.Mode, i.Agents, i.Final = 1, nil, nil }, "critical"},
	}
	for _, c := range cases {
		inc := sevIncident()
		c.edit(inc)
		if got := reasonerSeverity(inc); got != c.want {
			t.Errorf("%s: got %q want %q", c.name, got, c.want)
		}
	}
	if got := ruleSeverity(sevIncident().Sensors); got != "critical" {
		t.Errorf("ruleSeverity=%q", got)
	}
}

// A severity key in the reasoner's JSON is kept (normalised) when recognisable; a bad one is
// dropped without failing an otherwise sound report.
func TestCheckReportSeverity(t *testing.T) {
	sensors := []SensorRef{{Ref: "S1", Role: "power", Rule: Finding{Status: "critical"}, Evidence: []Evidence{{ID: "E1"}}}}
	base := `{"root_cause": "Load drop", "label": "power_load_anomaly", "affected_domains": ["power"], "evidence": ["S1.E1"], "confidence": 0.7, "action": "monitor", "explanation": "Drop [S1.E1]."`
	for raw, want := range map[string]string{
		base + `}`:                        "",
		base + `, "severity": "Fine"}`:    "normal",
		base + `, "severity": "WARNING"}`: "warning",
		base + `, "severity": "banana"}`:  "",
		base + `, "severity": 3}`:         "",
	} {
		rc := (&Reasoner{}).checkReport(GenieResult{Text: raw}, "", sensors)
		if !rc.Valid || rc.Parsed == nil {
			t.Fatalf("%s: rejected %v", raw, rc.Errors)
		}
		if rc.Parsed.Severity != want {
			t.Errorf("%s: severity %q want %q", raw, rc.Parsed.Severity, want)
		}
	}
}

// Incidents stored before severity_final existed are given the reasoner's severity on load;
// one that never finished keeps the provisional rule severity.
func TestLoadBackfillsSeverity(t *testing.T) {
	dir := t.TempDir()
	os.MkdirAll(filepath.Join(dir, "state"), 0o755)
	store := filepath.Join(dir, "state", "incidents.jsonl")
	agents := `"agents":[{"ref":"S1","valid":true,"parsed":{"pattern":"step_decrease","status":"normal"}}]`
	sensors := `"sensors":[{"ref":"S1","role":"power","rule_finding":{"pattern":"step_decrease","status":"critical"}}]`
	lines := []string{
		`{"id":"INC-0001","mode":3,"state":"done","severity":"critical",` + sensors + `,` + agents + `}`,
		`{"id":"INC-0002","mode":3,"state":"running","severity":"critical",` + sensors + `}`,
	}
	os.WriteFile(store, []byte(strings.Join(lines, "\n")+"\n"), 0o644)
	r := &Reasoner{store: store}
	r.load()
	if a := r.incidents[0]; a.Severity != "normal" || !a.SeverityFinal {
		t.Fatalf("done incident: severity %q final %v", a.Severity, a.SeverityFinal)
	}
	if b := r.incidents[1]; b.State != "failed" || b.Severity != "critical" || b.SeverityFinal {
		t.Fatalf("unfinished incident: state %s severity %q final %v", b.State, b.Severity, b.SeverityFinal)
	}
}
