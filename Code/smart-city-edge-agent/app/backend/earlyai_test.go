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

// A warning step with ai_early_k=4: provisional AI at reading 4, the full AI at 8 updates the SAME incident -> one
// incident, two AI revisions (provisional, then the early-alert stage the refinements continue from).
func TestEarlyAIOneIncidentTwoRevisions(t *testing.T) {
	earlyProfile(t, "ai_early_k=4\nai_early_shapes=step,trend\n")
	e := dqEngine(t)
	early, ai := earlySplit(feedCO2(t, e, 60, 600, rep(1200, 14)))
	if len(early) != 1 || early[0].reading != 4 {
		t.Fatalf("provisional candidates %+v, want one at reading 4", early)
	}
	if len(ai) != 1 || ai[0].reading < persistReadings {
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
	if len(early) != 0 || len(ai) != 1 || ai[0].reading < persistReadings {
		t.Fatalf("default (off): early %+v ai %+v", early, ai)
	}
	earlyProfile(t, "ai_early_k=4\nai_early_shapes=flatline\n")
	e2 := dqEngine(t)
	early, ai = earlySplit(feedCO2(t, e2, 60, 600, rep(1200, 14)))
	if len(early) != 0 || len(ai) != 1 || ai[0].reading < persistReadings {
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
