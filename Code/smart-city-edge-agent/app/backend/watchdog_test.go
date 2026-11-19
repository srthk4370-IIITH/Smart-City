package main

import (
	"testing"
	"time"
)

func TestWatchdogFastIncidentNeedsMoreData(t *testing.T) {
	e := dqEngine(t)
	fast, ai := fpSplit(feedCO2(t, e, 60, 600, func() []float64 {
		var v []float64
		for i := 1; i <= 16; i++ {
			v = append(v, 1400+30*float64(i))
		}
		return v
	}()))
	if len(fast) != 1 || len(ai) != 1 {
		t.Skip("fixture changed")
	}
	dir := t.TempDir()
	r := NewReasoner(NewGenieRunner(dir, dir, true), e, dir, func(string, any) {})
	r.Mode = 1
	r.splitFast([]Candidate{fast[0].c})
	inc := r.incidents[0]
	if n := r.watchdogSweep(time.Now(), 5*time.Minute, 30*time.Minute); n != 0 {
		t.Fatalf("swept too early: %d", n)
	}
	if n := r.watchdogSweep(time.Now().Add(6*time.Minute), 5*time.Minute, 30*time.Minute); n != 1 {
		t.Fatalf("swept %d", n)
	}
	if inc.State == "running" || inc.DataStatus != "needs_more_data" || inc.Workflow != wfNeeds || inc.Final == nil || inc.Severity != "critical" {
		t.Fatalf("not parked: state %s ds %s wf %s", inc.State, inc.DataStatus, inc.Workflow)
	}
	if len(r.fastInc) == 0 {
		t.Fatal("fast incident dropped: AI could not adopt it when data returns")
	}
	// data returns: the AI gate adopts the same incident
	if got := r.Process([]Candidate{ai[0].c}, 1); got.ID != inc.ID || got.State == "running" {
		t.Fatalf("AI did not resume on %s: %s %s", inc.ID, got.ID, got.State)
	}
}

func TestWatchdogHardTimeoutFailsOverToRules(t *testing.T) {
	dir := t.TempDir()
	r := NewReasoner(NewGenieRunner(dir, dir, true), nil, dir, func(string, any) {})
	inc := &Incident{ID: "INC-9999", State: "running", openedAt: time.Now().Add(-time.Hour), Approval: "pending"}
	inc.Workflow = wfAnalysing
	r.incidents = append(r.incidents, inc)
	if n := r.watchdogSweep(time.Now(), 5*time.Minute, 30*time.Minute); n != 1 {
		t.Fatalf("swept %d", n)
	}
	if inc.State != "done_with_errors" || inc.Workflow != wfNeeds {
		t.Fatalf("state %s wf %s", inc.State, inc.Workflow)
	}
}
