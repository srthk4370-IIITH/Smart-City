package main

import "testing"

// faultGuard: sensor_fault needs a rule or agent fault finding; otherwise reported at the rules' level (>= warning).
func TestFaultGuard(t *testing.T) {
	r := &Reasoner{notify: func(string, any) {}}
	ok := AgentCall{Ref: "S1", Valid: true, Parsed: &Finding{Status: "sensor_fault"}}
	warnAgent := AgentCall{Ref: "S1", Valid: true, Parsed: &Finding{Status: "warning"}}
	for i, c := range []struct {
		rule, ctxRule, sev string
		calls              []AgentCall
		want, title, label string
	}{
		{"warning", "", "sensor_fault", []AgentCall{warnAgent}, "warning", "", "unknown"},                    // flat alone: guarded
		{"normal", "", "sensor_fault", nil, "warning", "", "unknown"},                                        // at least warning
		{"critical", "", "sensor_fault", nil, "critical", "", "unknown"},                                     // the rules' level
		{"normal", "sensor_fault", "sensor_fault", nil, "warning", "", "unknown"},                            // a context sensor does not count
		{"sensor_fault", "", "sensor_fault", nil, "sensor_fault", "Sensor fault: S1", "sensor_fault"},        // rule agrees
		{"warning", "", "sensor_fault", []AgentCall{ok}, "sensor_fault", "Sensor fault: S1", "sensor_fault"}, // agent agrees
		{"warning", "", "warning", nil, "warning", "Sensor fault: S1", "sensor_fault"},                       // not a fault report: untouched
	} {
		inc := &Incident{ID: "INC-T", Sensors: []SensorRef{{Ref: "S1", Rule: Finding{Status: c.rule}}}}
		if c.ctxRule != "" {
			inc.Sensors = append(inc.Sensors, SensorRef{Ref: "S2", Context: true, Rule: Finding{Status: c.ctxRule}})
		}
		rep := Report{Severity: c.sev, Title: "Sensor fault: S1", Label: "sensor_fault"}
		r.severityGuard(inc, &rep)
		r.faultGuard(inc, &rep, c.calls)
		if rep.Severity != c.want || rep.Title != c.title || rep.Label != c.label || rep.SeverityBasis.Final != c.want {
			t.Fatalf("case %d: got sev %s title %q label %s basis %+v", i, rep.Severity, rep.Title, rep.Label, rep.SeverityBasis)
		}
	}
}
