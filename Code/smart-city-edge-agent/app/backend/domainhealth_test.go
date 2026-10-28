package main

import (
	"encoding/json"
	"strings"
	"testing"
)

// Domain health (domainhealth.go): rollup, AI raise, faults apart, staleness, trend, steps.

const hsim = int64(1_700_000_000)

func hs(role, node, metric, status string) SensorState {
	v := 1.0
	pat := "stable"
	if role == "hvac" {
		pat = "context"
	}
	return SensorState{Node: node, Metric: metric, Role: role, Status: status, Pattern: pat, Last: &v, Updated: hsim, DataOK: true}
}

func hfind(h HealthOut, d string) DomainHealth {
	for _, x := range h.Domains {
		if x.Domain == d {
			return x
		}
	}
	return DomainHealth{}
}

func baseStates() []SensorState {
	return []SensorState{
		hs("air_quality", "AQ1", "co2", "normal"), hs("air_quality", "AQ1", "temp", "normal"),
		hs("water", "W1", "level", "normal"), hs("water", "W1", "flow", "normal"),
		hs("power", "P1", "power_kw", "normal"), hs("occupancy", "O1", "occ", "normal"),
		hs("weather", "WX", "temp", "normal"), hs("hvac", "H1", "power_kw", "normal"),
	}
}

func TestHealthRollupWorstOf(t *testing.T) {
	st := baseStates()
	st[0].Status, st[1].Status = "warning", "critical"
	st[2].Status = "warning"
	h := buildHealth(hsim, 1, st, nil, map[string]*healthMark{})
	if len(h.Domains) != 6 {
		t.Fatalf("want 6 domains, got %d", len(h.Domains))
	}
	aq := hfind(h, "air_quality")
	if aq.Headline != "critical" || aq.Status != "critical" || aq.Counts["warning"] != 1 || aq.Counts["critical"] != 1 || aq.Sensors != 2 {
		t.Fatalf("air rollup: %+v", aq)
	}
	if w := hfind(h, "water"); w.Headline != "warning" {
		t.Fatalf("water: %+v", w)
	}
	if p := hfind(h, "power"); p.Headline != "normal" || p.Trend != "steady" || len(p.Steps) != 0 {
		t.Fatalf("power: %+v", p)
	}
	if h.Worst != "critical" {
		t.Fatalf("worst %s", h.Worst)
	}
}

func TestHealthFaultSeparateFromProcess(t *testing.T) {
	st := baseStates()
	st[2].Status = "sensor_fault"
	h := buildHealth(hsim, 1, st, nil, map[string]*healthMark{})
	w := hfind(h, "water")
	if w.Status != "normal" || w.Faults != 1 || w.Headline != "sensor_fault" {
		t.Fatalf("fault must not be a process status: %+v", w)
	}
	if len(w.Steps) == 0 || w.Steps[0].Source != "playbook" || !strings.Contains(w.Steps[0].Text, "sensor") {
		t.Fatalf("fault playbook: %+v", w.Steps)
	}
	// a real warning outranks the fault on the headline, and the fault stays counted
	st[3].Status = "warning"
	w = hfind(buildHealth(hsim, 1, st, nil, map[string]*healthMark{}), "water")
	if w.Headline != "warning" || w.Faults != 1 {
		t.Fatalf("warning + fault: %+v", w)
	}
}

func TestHealthContextSensorsNeverRaise(t *testing.T) {
	st := baseStates()
	st[7].Status = "critical" // HVAC context sensor (v1): shown for context only
	h := buildHealth(hsim, 1, st, nil, map[string]*healthMark{})
	hv := hfind(h, "hvac")
	if hv.Headline != "normal" || hv.Context != 1 || hv.Sensors != 0 || !hv.ContextOnly {
		t.Fatalf("context sensor raised hvac: %+v", hv)
	}
	if h.Worst != "normal" {
		t.Fatalf("worst %s", h.Worst)
	}
	// a context sensor warming up does not make the domain stale either
	st[7].Status, st[7].DataOK, st[7].Last = "insufficient_data", false, nil
	if hv = hfind(buildHealth(hsim, 1, st, nil, map[string]*healthMark{}), "hvac"); !hv.Fresh {
		t.Fatalf("context staleness counted: %+v", hv)
	}
}

func TestHealthStaleness(t *testing.T) {
	st := baseStates()
	st[4].Updated = hsim - 3*bucketSec // power reading 15 min old
	st[5].Status, st[5].DataOK, st[5].Last = "insufficient_data", false, nil
	h := buildHealth(hsim, 1, st, nil, map[string]*healthMark{})
	p := hfind(h, "power")
	if p.Fresh || len(p.Stale) != 1 || p.Headline != "normal" {
		t.Fatalf("stale power: %+v", p)
	}
	o := hfind(h, "occupancy")
	if o.Fresh || o.Headline != "insufficient_data" {
		t.Fatalf("warming-up occupancy: %+v", o)
	}
	if a := hfind(h, "air_quality"); !a.Fresh {
		t.Fatalf("fresh air marked stale: %+v", a)
	}
}

func TestHealthTrend(t *testing.T) {
	marks := map[string]*healthMark{}
	st := baseStates()
	buildHealth(hsim, 1, st, nil, marks)
	st[0].Status = "warning"
	aq := hfind(buildHealth(hsim+bucketSec, 1, st, nil, marks), "air_quality")
	if aq.Trend != "elevated" || aq.TrendFrom != "normal" || aq.Since != hsim+bucketSec {
		t.Fatalf("elevated: %+v", aq)
	}
	// no change: arrow held for healthTrendHold, then steady; since unchanged
	aq = hfind(buildHealth(hsim+2*bucketSec, 1, st, nil, marks), "air_quality")
	if aq.Trend != "elevated" {
		t.Fatalf("held: %+v", aq)
	}
	aq = hfind(buildHealth(hsim+bucketSec+healthTrendHold+bucketSec, 1, st, nil, marks), "air_quality")
	if aq.Trend != "steady" || aq.Since != hsim+bucketSec {
		t.Fatalf("steady: %+v", aq)
	}
	st[0].Status = "normal"
	aq = hfind(buildHealth(hsim+20*bucketSec, 1, st, nil, marks), "air_quality")
	if aq.Trend != "curbed" || aq.TrendFrom != "warning" {
		t.Fatalf("curbed: %+v", aq)
	}
}

func inc(id string, roles []string, sev string) *Incident {
	return &Incident{ID: id, State: "done", Approval: "pending", CreatedSim: hsim - 3600, Severity: sev, SeverityFinal: true,
		Roles: roles, Title: id + " title"}
}

func TestHealthIncidentsAndAIRaise(t *testing.T) {
	st := baseStates()
	st[2].Status = "warning"
	i1 := inc("INC-0001", []string{"water"}, "critical")
	i1.RefineStage = "1.5h"
	i1.Revisions = []Revision{{Stage: "early", Severity: "warning"}, {Stage: "1.5h", Severity: "critical"}}
	old := inc("INC-0002", []string{"water"}, "critical")
	old.CreatedSim = hsim - healthOpenSec - 1 // too old to be open
	done := inc("INC-0003", []string{"water"}, "critical")
	done.Approval = "dismissed"
	other := inc("INC-0004", []string{"water"}, "critical")
	other.SimEpoch = 99 // earlier sensor history
	h := buildHealth(hsim, 1, st, []*Incident{i1, old, done, other}, map[string]*healthMark{})
	w := hfind(h, "water")
	if len(w.Incidents) != 1 || w.Incidents[0].ID != "INC-0001" || w.Incidents[0].Change != "elevated" || w.Incidents[0].Stage != "1.5h" {
		t.Fatalf("open incidents: %+v", w.Incidents)
	}
	if w.Status != "critical" || w.LiveStatus != "warning" || !w.ByAI {
		t.Fatalf("AI raise: %+v", w)
	}
	// the AI never invents a status: live normal stays normal, the incident is still listed
	st[2].Status = "normal"
	w = hfind(buildHealth(hsim, 1, st, []*Incident{i1}, map[string]*healthMark{}), "water")
	if w.Headline != "normal" || w.ByAI || len(w.Incidents) != 1 {
		t.Fatalf("no live abnormal: %+v", w)
	}
	// and never lowers a live warning
	i1.Severity = "normal"
	st[2].Status = "warning"
	w = hfind(buildHealth(hsim, 1, st, []*Incident{i1}, map[string]*healthMark{}), "water")
	if w.Headline != "warning" {
		t.Fatalf("AI lowered live warning: %+v", w)
	}
}

func TestHealthStepsFromAgentsAndReport(t *testing.T) {
	st := baseStates()
	st[0].Status = "warning"
	i := inc("INC-0005", []string{"air_quality", "power"}, "warning")
	i.Sensors = []SensorRef{{Ref: "S1", Role: "air_quality"}, {Ref: "S2", Role: "power"}, {Ref: "S3", Role: "air_quality", Context: true}}
	i.Agents = []AgentCall{
		{Ref: "S1", Valid: true, Parsed: &Finding{Status: "warning", Action: "inspect_ventilation"}},
		{Ref: "S2", Valid: true, Parsed: &Finding{Status: "warning", Action: "inspect_electrical"}}, // other domain
		{Ref: "S3", Valid: true, Parsed: &Finding{Status: "warning", Action: "inspect_hvac"}},       // context sensor
		{Ref: "S1", Valid: false, Parsed: &Finding{Status: "warning", Action: "check_sensor"}},      // invalid
	}
	i.Final = &ReportCall{Valid: true, Parsed: &Report{Severity: "warning", Action: "Request Facility Review"}}
	aq := hfind(buildHealth(hsim, 1, st, []*Incident{i}, map[string]*healthMark{}), "air_quality")
	var acts []string
	for _, s := range aq.Steps {
		acts = append(acts, s.Action+"/"+s.Source)
		if s.Ref != "INC-0005" {
			t.Fatalf("step without incident: %+v", s)
		}
	}
	if strings.Join(acts, ",") != "request_facility_review/report,inspect_ventilation/agent" {
		t.Fatalf("steps: %v", acts)
	}
	// a non-whitelisted (actuating) action is dropped and the playbook takes over
	i.Final.Parsed.Action = "shut_down_ahu"
	i.Agents = i.Agents[:1]
	i.Agents[0].Parsed.Action = "turn_off_power"
	aq = hfind(buildHealth(hsim, 1, st, []*Incident{i}, map[string]*healthMark{}), "air_quality")
	if len(aq.Steps) != 3 || aq.Steps[0].Source != "playbook" || aq.Steps[0].Action != "" {
		t.Fatalf("playbook fallback: %+v", aq.Steps)
	}
	b, _ := json.Marshal(aq.Steps)
	if blocksActuation(string(b)) {
		t.Fatalf("playbook reads as actuation: %s", b)
	}
}

func TestHealthPlaybookCoverage(t *testing.T) {
	for _, d := range healthDomains {
		for _, lv := range []string{"warning", "critical", "sensor_fault"} {
			s := domainSteps(d, lv, nil)
			if len(s) == 0 || len(s) > healthMaxSteps {
				t.Fatalf("%s %s: %d steps", d, lv, len(s))
			}
			for _, x := range s {
				if blocksActuation(x.Text) {
					t.Fatalf("%s %s actuation wording: %q", d, lv, x.Text)
				}
			}
		}
	}
	for a, txt := range actionStep {
		if !actionAllowed(a) {
			t.Fatalf("step for non-whitelisted action %s", a)
		}
		if a != "switch_off_ac" && blocksActuation(txt) {
			t.Fatalf("%s actuation wording: %q", a, txt)
		}
	}
}

func TestHealthTrackerOnEngine(t *testing.T) {
	eng, err := NewEngine("../device")
	if err != nil {
		t.Fatal(err)
	}
	ht := NewHealthTracker()
	h, changed := ht.Update(eng, nil)
	if !changed || len(h.Domains) != 6 {
		t.Fatalf("first update: changed=%v %s", changed, healthSummary(h))
	}
	if _, changed = ht.Update(eng, nil); changed {
		t.Fatal("unchanged state reported as a change")
	}
}
