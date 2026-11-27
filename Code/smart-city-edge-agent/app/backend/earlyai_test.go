package main

import (
	"os"
	"path/filepath"
	"testing"
	"time"
)

// earlyProfile switches the provisional early AI on for one test (htpd_profile in a temp work dir).
func earlyProfile(t *testing.T, prof string) {
	t.Helper()
	old := htpdWorkDir
	htpdWorkDir = t.TempDir()
	if err := os.WriteFile(filepath.Join(htpdWorkDir, "htpd_profile"), []byte(prof), 0o644); err != nil {
		t.Fatal(err)
	}
	earlyCfg.Lock()
	earlyCfg.at = time.Time{}
	earlyCfg.Unlock()
	t.Cleanup(func() {
		htpdWorkDir = old
		earlyCfg.Lock()
		earlyCfg.at = time.Time{}
		earlyCfg.Unlock()
	})
}

func earlySplit(ev []fpEvent) (early, ai []fpEvent) {
	for _, x := range ev {
		switch {
		case x.c.Early:
			early = append(early, x)
		case !x.c.Fast:
			ai = append(ai, x)
		}
	}
	return
}

// A warning step with ai_early_k=3: provisional AI at reading 4, the full AI at 8 updates the SAME incident -> one
// incident, two AI revisions (provisional, then the early-alert stage the refinements continue from).
func TestEarlyAIOneIncidentTwoRevisions(t *testing.T) {
	earlyProfile(t, "ai_early_k=3\nai_early_shapes=step,trend\n")
	e := dqEngine(t)
	early, ai := earlySplit(feedCO2(t, e, 60, 600, rep(1200, 14)))
	if len(early) != 1 || early[0].reading != 3 {
		t.Fatalf("provisional candidates %+v, want one at reading 3", early)
	}
	if len(ai) != 1 || ai[0].reading < defaultAbnormalOfWindow {
		t.Fatalf("AI gate moved: %+v", ai)
	}
	dir := t.TempDir()
	r := NewReasoner(NewGenieRunner(dir, dir, true), e, dir, func(string, any) {})
	r.active = true // drive the NPU queue by hand
	if rest := r.splitFast([]Candidate{early[0].c}); len(rest) != 0 {
		t.Fatal("provisional candidate went to the alert queue")
	}
	w, ok := r.next()
	if !ok || w.early == nil {
		t.Fatalf("no provisional job queued: %+v", w)
	}
	r.runEarly(*w.early)
	if len(r.incidents) != 1 || r.incidents[0].RefineStage != "provisional" || len(r.incidents[0].Revisions) != 1 {
		t.Fatalf("provisional run: %d incidents, stage %q, %d revisions", len(r.incidents), r.incidents[0].RefineStage, len(r.incidents[0].Revisions))
	}
	id := r.incidents[0].ID
	inc := r.Process([]Candidate{ai[0].c}, 3)
	if len(r.incidents) != 1 || inc.ID != id {
		t.Fatalf("full analysis opened a second incident")
	}
	if len(inc.Revisions) != 2 || inc.Revisions[0].Stage != "provisional" || inc.Revisions[1].Stage != "early" || inc.RefineStage != "early" {
		t.Fatalf("revisions %+v stage %q", inc.Revisions, inc.RefineStage)
	}
}

// Off by default; and with it on, a shape that is not cleared gets no provisional run and the gate stays at 8.
func TestEarlyAIGateUnchanged(t *testing.T) {
	e := dqEngine(t)
	early, ai := earlySplit(feedCO2(t, e, 60, 600, rep(1200, 14)))
	if len(early) != 0 || len(ai) != 1 || ai[0].reading < defaultAbnormalOfWindow {
		t.Fatalf("default (off): early %+v ai %+v", early, ai)
	}
	earlyProfile(t, "ai_early_k=3\nai_early_shapes=flatline\n")
	e2 := dqEngine(t)
	early, ai = earlySplit(feedCO2(t, e2, 60, 600, rep(1200, 14)))
	if len(early) != 0 || len(ai) != 1 || ai[0].reading < defaultAbnormalOfWindow {
		t.Fatalf("uncleared shape: early %+v ai %+v", early, ai)
	}
}

// NPU priority: event-gate alerts, then requested jobs, then provisional runs, then refinements.
func TestEarlyAIPriority(t *testing.T) {
	dir := t.TempDir()
	e := dqEngine(t)
	r := NewReasoner(NewGenieRunner(dir, dir, true), e, dir, func(string, any) {})
	r.early = []earlyJob{{inc: &Incident{ID: "INC-E"}}}
	r.refines, r.refineQ = []string{"INC-R"}, map[string]bool{"INC-R": true}
	r.pending = []Candidate{{Node: "n", Metric: "co2"}}
	r.jobs = []job{{cands: []Candidate{{Node: "j", Metric: "co2"}}, mode: 3}}
	var order []string
	for {
		w, ok := r.next()
		if !ok {
			break
		}
		switch {
		case w.early != nil:
			order = append(order, "early")
		case w.refine != "":
			order = append(order, "refine")
		case w.cands[0].Node == "n":
			order = append(order, "alert")
		default:
			order = append(order, "job")
		}
	}
	if len(order) != 4 || order[0] != "alert" || order[1] != "job" || order[2] != "early" || order[3] != "refine" {
		t.Fatalf("NPU order %v", order)
	}
}

// Owner 2026-11-27: the full reading is independent of the early look - as if it never happened. The early verdict
// (severity, final flag) does not carry over, the reasoner's re-check list leaves it out, retrieval never learns
// from it, and an early look the gate never confirms closes by itself.
func TestEarlyLookIndependentOfFullReading(t *testing.T) {
	earlyProfile(t, "ai_early_k=3\nai_early_shapes=step,trend\n")
	e := dqEngine(t)
	early, ai := earlySplit(feedCO2(t, e, 60, 600, rep(1200, 14)))
	if len(early) != 1 || len(ai) != 1 {
		t.Fatalf("early %d ai %d", len(early), len(ai))
	}
	dir := t.TempDir()
	r := NewReasoner(NewGenieRunner(dir, dir, true), e, dir, func(string, any) {})
	r.active = true
	r.splitFast([]Candidate{early[0].c})
	w, _ := r.next()
	r.runEarly(*w.early)
	inc := r.incidents[0]
	if _, ok := retDocOf(inc); ok {
		t.Fatal("retrieval would learn from an early look")
	}
	// pretend the early look said critical, decided
	r.mu.Lock()
	inc.Severity, inc.SeverityFinal, inc.SeverityWhy = "critical", true, "early look"
	r.mu.Unlock()
	if in := r.buildV3Input(inc, nil); len(in.Recheck) != 0 {
		t.Fatalf("early look in the reasoner input: %v", in.Recheck)
	}
	got := r.adoptFast([]Candidate{ai[0].c}, 3)
	if got != inc {
		t.Fatal("gate did not adopt the early incident")
	}
	fresh := r.buildIncident([]Candidate{ai[0].c}, 3)
	if inc.Severity != fresh.Severity || inc.SeverityFinal || inc.SeverityWhy != "" || inc.RefineStage != "" {
		t.Fatalf("early verdict carried over: sev %q (rules %q) final %v why %q stage %q", inc.Severity, fresh.Severity, inc.SeverityFinal, inc.SeverityWhy, inc.RefineStage)
	}
	if len(inc.Revisions) != 1 || inc.Revisions[0].Stage != "provisional" {
		t.Fatalf("early look not kept as history: %+v", inc.Revisions)
	}
}

func TestEarlyLookUnconfirmedCloses(t *testing.T) {
	r := NewReasoner(NewGenieRunner(t.TempDir(), t.TempDir(), true), nil, t.TempDir(), func(string, any) {})
	inc := &Incident{ID: "INC-9", State: "done", RefineStage: "provisional", CreatedSim: 1000}
	r.fastInc = map[string]*Incident{"X|co2": inc}
	r.incidents = []*Incident{inc}
	now := time.Now()
	if r.closeUnconfirmedEarlyLocked(inc, 1000+earlyUnconfirmedAfter()-1, now) {
		t.Fatal("closed before the gate could still confirm it")
	}
	if !r.closeUnconfirmedEarlyLocked(inc, 1000+earlyUnconfirmedAfter(), now) || wfOf(inc) != wfClosed || len(r.fastInc) != 0 {
		t.Fatalf("not closed: wf %q fastInc %d", wfOf(inc), len(r.fastInc))
	}
	fp := &Incident{ID: "INC-10", State: "done", RefineStage: "provisional", FastPath: true, CreatedSim: 1000}
	if r.closeUnconfirmedEarlyLocked(fp, 1e9, now) {
		t.Fatal("a fast-path (critical) incident was closed as an unconfirmed early look")
	}
	if got := earlyEtaOf([]gateWatch{{Node: "N", Metric: "co2", EtaS: 600}}, &Incident{RefineStage: "provisional", Sensors: []SensorRef{{Node: "N", Metric: "co2"}}}); got != 600 {
		t.Fatalf("eta %d", got)
	}
}

func TestShapeOfLimitFamily(t *testing.T) {
	if s := shapeOf(Finding{Pattern: "stable", Status: "warning"}); s != "limit" {
		t.Fatalf("limit breach shape %q", s)
	}
	if s := shapeOf(Finding{Pattern: "stable", Status: "normal"}); s != "" {
		t.Fatalf("normal reading got shape %q", s)
	}
}
