package main

import (
	"strings"
	"testing"
)

func TestRepairV3ReportFormatSlips(t *testing.T) {
	known := "S1 S2 S1.E1 S1.E3 S2.E4 last = 34.5 C"
	base := `"title":"Room hot: KH building, level 03","label":"hvac_or_thermal_issue","root_cause":"AC off","causal_chain":"x",` +
		`"observations":[{"text":"Room 34.5 C","src":["S1-E1"]}],"affected_domains":["hvac"],"suspect_sensors":[],"confidence":0.8,` +
		`"monitor_next":"x","needs_more_data":false,"needs_deeper":false,"explanation":"x"`
	cases := []struct{ name, js, wantRepair, wantFirst string }{
		{"warning, monitor only", `{"severity":"warning",` + base + `,"evidence":["S1.E1"],"agent_checks":[],"checklist":[{"action":"monitor","target":"S1","why":"w"}]}`,
			"policy", "inspect_hvac"},
		{"critical, inspect later", `{"severity":"critical",` + base + `,"evidence":["S1.E1"],"agent_checks":[],"checklist":[{"action":"monitor","target":"S1","why":"w"},{"action":"inspect_hvac","target":"S2","why":"w"}]}`,
			"policy", "inspect_hvac"},
		{"bad verdict + empty evidence + id format", `{"severity":"critical",` + base + `,"evidence":[],"agent_checks":[{"ref":"S1","claim":"c","verdict":"rejected","fact":"f","src":["S1.E1"]}],"checklist":[{"action":"inspect_hvac","target":"S1","why":"w"}]}`,
			"agent_check 1 dropped", "inspect_hvac"},
		{"sensor fault", `{"severity":"sensor_fault",` + base + `,"evidence":["S1.E3","S1.card"],"agent_checks":[],"checklist":[{"action":"inspect_hvac","target":"S1","why":"w"}]}`,
			"unknown id(s) S1.card dropped", "check_sensor"},
	}
	for _, c := range cases {
		r, errs, reps := checkReportV3(c.js, known)
		if len(errs) != 0 {
			t.Errorf("%s: still rejected %v (repairs %v)", c.name, errs, reps)
			continue
		}
		if !strings.Contains(strings.Join(reps, "; "), c.wantRepair) || r.Checklist[0].Action != c.wantFirst {
			t.Errorf("%s: repairs %v first %q", c.name, reps, r.Checklist[0].Action)
		}
	}
	// still rejected: an invented number and missing confidence
	bad := strings.Replace(`{"severity":"warning",`+base+`,"evidence":["S1.E1"],"agent_checks":[],"checklist":[{"action":"inspect_hvac","target":"S1","why":"w"}]}`, `"Room 34.5 C"`, `"Room 41.2 C"`, 1)
	bad = strings.Replace(bad, `"confidence":0.8,`, ``, 1)
	if _, errs, _ := checkReportV3(bad, known); len(errs) < 2 {
		t.Errorf("invented number / missing confidence not rejected: %v", errs)
	}
}
