package main

import (
	"os"
	"path/filepath"
	"strings"
	"sync"
	"testing"
	"time"
)

// Early alert + refined re-analysis (refine.go), on the real engine and pipeline with scripted
// agents: the mock Genie answers the CO2 agent with whatever the test sets for the current stage.

type refineRig struct {
	t      *testing.T
	eng    *Engine
	r      *Reasoner
	mu     sync.Mutex
	co2    string // the CO2 agent's next answer: "pattern/status"
	onCall func() // runs on every agent call (preemption test)
	events []map[string]any
}

func newRefineRig(t *testing.T) *refineRig {
	t.Helper()
	cool := filepath.Join(t.TempDir(), "thermal")
	os.WriteFile(cool, []byte("cool"), 0o644)
	t.Setenv("SCE_THERMAL_FAKE", cool)
	eng, err := NewEngine("../device")
	if err != nil {
		t.Fatal(err)
	}
	rg := &refineRig{t: t, eng: eng, co2: "step_increase/warning"}
	dir := t.TempDir()
	g := NewGenieRunner(dir, dir, true)
	rg.r = NewReasoner(g, eng, dir, func(kind string, v any) {
		if m, ok := v.(map[string]any); ok && kind == "incident" {
			rg.mu.Lock()
			rg.events = append(rg.events, m)
			rg.mu.Unlock()
		}
	})
	old := mockGen
	mockGen = func(prompt string) (string, error) {
		rg.mu.Lock()
		ans, hook := rg.co2, rg.onCall
		rg.mu.Unlock()
		if hook != nil {
			hook()
		}
		if !strings.Contains(prompt, "METRIC: co2") {
			return mockGenerate(prompt)
		}
		p := strings.SplitN(ans, "/", 2)
		return `{"pattern": "` + p[0] + `", "status": "` + p[1] + `", "observations": ["CO2 now [E1]"], "likely_cause": "ventilation_insufficient", "confidence": 0.8, "action": "inspect_ventilation"}`, nil
	}
	t.Cleanup(func() { mockGen = old })
	return rg
}

func (rg *refineRig) answer(a string) { rg.mu.Lock(); rg.co2 = a; rg.mu.Unlock() }

// alert analyses the CO2 sensor of the first air sensor now, as the event gate would (Mode 3).
func (rg *refineRig) alert() *Incident {
	e := rg.eng
	e.mu.RLock()
	node := "SR-AQ-KH03-03"
	xs, ok := e.Window(node, "co2", e.sim)
	end := e.sim
	e.mu.RUnlock()
	if !ok {
		rg.t.Fatal("no co2 window")
	}
	f := RuleFinding("air_quality", "co2", node, xs, end)
	return rg.r.Process([]Candidate{{node, "co2", "air_quality", f, xs, end, false, false, false}}, 3)
}

// readings advances sensor time by n readings, polling the refinement scheduler like main.go does.
func (rg *refineRig) readings(n int) {
	for i := 0; i < n; i++ {
		rg.eng.Tick()
		_, _, sim := rg.eng.SimBase()
		rg.r.RefineTick(sim)
	}
}

// settle waits until the NPU queue is idle and returns a consistent copy of the incident.
func (rg *refineRig) settle(id string) Incident {
	rg.t.Helper()
	for t0 := time.Now(); time.Since(t0) < 30*time.Second; time.Sleep(20 * time.Millisecond) {
		rg.r.mu.RLock()
		idle := !rg.r.active && len(rg.r.refines) == 0
		rg.r.mu.RUnlock()
		if idle {
			break
		}
	}
	rg.r.mu.RLock()
	defer rg.r.mu.RUnlock()
	for _, i := range rg.r.incidents {
		if i.ID == id {
			return *i
		}
	}
	rg.t.Fatalf("%s gone", id)
	return Incident{}
}

func co2Finding(inc Incident) Finding { return finalFindings(&inc)["S1"] }

func TestRefineDueAt18And36Readings(t *testing.T) {
	rg := newRefineRig(t)
	inc := rg.alert()
	base := inc.CreatedSim
	got := rg.settle(inc.ID)
	if got.RefineStage != "early" || got.NextRefineSim != base+18*bucketSec || len(got.Revisions) != 1 {
		t.Fatalf("after alert: stage %q next %d (want %d) revisions %d", got.RefineStage, got.NextRefineSim, base+18*bucketSec, len(got.Revisions))
	}
	if f := co2Finding(got); f.Pattern != "step_increase" || got.Severity != "warning" {
		t.Fatalf("early finding %s/%s severity %s", f.Pattern, f.Status, got.Severity)
	}

	rg.answer("exponential_increase/critical")
	rg.readings(17)
	if got = rg.settle(inc.ID); got.RefineStage != "early" {
		t.Fatalf("refined after 17 readings: %q", got.RefineStage)
	}
	rg.readings(1)
	got = rg.settle(inc.ID)
	if got.RefineStage != "1.5h" || len(got.Revisions) != 2 || got.Revisions[1].SimEnd != base+18*bucketSec {
		t.Fatalf("at 18 readings: stage %q revisions %d", got.RefineStage, len(got.Revisions))
	}
	if got.Sensors[0].End != base+18*bucketSec || got.NextRefineSim != base+36*bucketSec {
		t.Fatalf("window end %d next %d", got.Sensors[0].End, got.NextRefineSim)
	}
	// the pattern is corrected; the AI's "critical" is NOT applied: the rig's CO2 is calm now (rule and
	// readings normal), so a raise would rest on history alone (visibleNow; TestRefineRaisesWhenVisible)
	if f := co2Finding(got); f.Pattern != "exponential_increase" || f.Status != "warning" || got.Severity != "warning" || !strings.Contains(got.Title, "exponential") {
		t.Fatalf("1.5 h finding %s/%s severity %s title %q", f.Pattern, f.Status, got.Severity, got.Title)
	}
	if rs := got.Revisions[1].Sensors[0]; !rs.Kept || !strings.Contains(rs.Note, "not raised to critical") {
		t.Fatalf("1.5 h revision note %+v", rs)
	}
	if r0 := got.Revisions[0].Sensors[0]; r0.Pattern != "step_increase" || r0.Status != "warning" {
		t.Fatalf("early revision lost: %+v", r0)
	}

	rg.answer("gradual_increase/warning")
	rg.readings(17)
	if got = rg.settle(inc.ID); got.RefineStage != "1.5h" {
		t.Fatalf("3 h refinement early: %q", got.RefineStage)
	}
	rg.readings(1)
	got = rg.settle(inc.ID)
	if got.RefineStage != "3h" || got.NextRefineSim != 0 || len(got.Revisions) != 3 || got.Revisions[2].SimEnd != base+36*bucketSec {
		t.Fatalf("at 36 readings: stage %q next %d revisions %d", got.RefineStage, got.NextRefineSim, len(got.Revisions))
	}
	// same severity again: the corrected pattern is shown, the status stays (no curb, no raise)
	if f := co2Finding(got); f.Pattern != "gradual_increase" || f.Status != "warning" || got.Severity != "warning" {
		t.Fatalf("3 h finding %s/%s severity %s", f.Pattern, f.Status, got.Severity)
	}
	if rs := got.Revisions[2].Sensors[0]; rs.Kept || rs.Curbed {
		t.Fatalf("3 h revision note %+v", rs)
	}
	rg.readings(40)
	if got = rg.settle(inc.ID); len(got.Revisions) != 3 {
		t.Fatalf("refined again after 3 h: %d revisions", len(got.Revisions))
	}
	rg.mu.Lock()
	n := 0
	for _, ev := range rg.events {
		if ev["id"] == inc.ID && ev["refined"] != nil {
			n++
		}
	}
	rg.mu.Unlock()
	if n != 2 {
		t.Fatalf("%d refinement SSE events, want 2", n)
	}
}

// An early spike that the longer window reads as stable is over, not wrong: it is kept.
func TestRefineKeepsEarlySpikeWhenEventOver(t *testing.T) {
	rg := newRefineRig(t)
	rg.answer("spike/critical")
	inc := rg.alert()
	rg.answer("stable/normal")
	rg.readings(18)
	got := rg.settle(inc.ID)
	if got.RefineStage != "1.5h" {
		t.Fatalf("stage %q", got.RefineStage)
	}
	rs := got.Revisions[1].Sensors[0]
	// the spike stays as the finding (history), its status curbed: the calm window's rule agrees
	if f := co2Finding(got); f.Pattern != "spike" || f.Status != "normal" || !rs.Kept || !rs.Curbed || !strings.Contains(rs.Note, "event over") {
		t.Fatalf("spike not kept: finding %s severity %s revision %+v", f.Pattern, got.Severity, rs)
	}
	// the window shown with the kept finding is the one it came from
	if got.Sensors[0].End != got.CreatedSim {
		t.Fatalf("kept finding shown with window ending %d, not the early %d", got.Sensors[0].End, got.CreatedSim)
	}
	// a refined view that is NOT steady replaces the spike's pattern; its "warning" is not applied while
	// the CO2 is calm now (nothing visible to raise on)
	rg.answer("step_increase/warning")
	rg.readings(18)
	got = rg.settle(inc.ID)
	if f := co2Finding(got); f.Pattern != "step_increase" || f.Status != "normal" || !strings.Contains(got.Revisions[2].Sensors[0].Note, "not raised to warning") {
		t.Fatalf("3 h: %s/%s severity %s note %q", f.Pattern, f.Status, got.Severity, got.Revisions[2].Sensors[0].Note)
	}
}

// A refinement raises a status when the problem is visible now: with a real ventilation failure on the
// rig's CO2 sensor, the rule on the fresh window is abnormal and the AI's "critical" is applied.
func TestRefineRaisesWhenVisible(t *testing.T) {
	rg := newRefineRig(t)
	for _, sc := range Scenarios {
		if sc.ID == "ventilation_failure" {
			rg.eng.Inject(sc)
		}
	}
	rg.readings(20) // let the rise build in the window
	rg.answer("step_increase/warning")
	inc := rg.alert()
	rg.answer("exponential_increase/critical")
	rg.readings(18)
	got := rg.settle(inc.ID)
	if got.Severity != "critical" || got.Revisions[1].Sensors[0].Kept {
		t.Fatalf("raise blocked: severity %s rule %s %+v", got.Severity, got.Sensors[0].Rule.Status, got.Revisions[1].Sensors[0])
	}
}

// A decision taken before a refinement stays: the refinement is recorded and shown, never re-asked.
// The event gate's per-sensor state is not touched either.
func TestRefineKeepsApprovalAndGate(t *testing.T) {
	rg := newRefineRig(t)
	inc := rg.alert()
	rg.r.SetApproval(inc.ID, "approved", "ok by ops")
	st := rg.eng.states[key("SR-AQ-KH03-03", "co2")]
	rg.eng.mu.Lock()
	st.alerted, st.reportedSev = true, 1
	rg.eng.mu.Unlock()
	rg.answer("exponential_increase/critical")
	rg.readings(18)
	got := rg.settle(inc.ID)
	if got.RefineStage != "1.5h" || got.Approval != "approved" || got.ApprovalNote != "ok by ops" {
		t.Fatalf("stage %q approval %q note %q", got.RefineStage, got.Approval, got.ApprovalNote)
	}
	rg.eng.mu.RLock()
	defer rg.eng.mu.RUnlock()
	if !st.alerted || st.reportedSev != 1 {
		t.Fatalf("gate state changed: alerted=%v reportedSev=%d", st.alerted, st.reportedSev)
	}
}

// Refinements queue behind new alerts and requested analyses, and a running one steps aside.
func TestRefineNeverPreemptsNewIncident(t *testing.T) {
	rg := newRefineRig(t)
	r := rg.r
	alert := []Candidate{{Node: "n", Metric: "co2"}}
	r.mu.Lock()
	r.refines, r.refineQ = []string{"INC-0001"}, map[string]bool{"INC-0001": true}
	r.jobs = []job{{cands: alert, mode: 3}}
	r.pending = alert
	w1, _ := r.next()
	w2, _ := r.next()
	w3, _ := r.next()
	_, more := r.next()
	r.mu.Unlock()
	if w1.refine != "" || w1.cands == nil || w2.refine != "" || w3.refine != "INC-0001" || more {
		t.Fatalf("order: %+v %+v %+v more=%v", w1, w2, w3, more)
	}

	// an alert arriving while the refinement's agents run: it stops before the next NPU call
	inc := rg.alert()
	rg.settle(inc.ID)
	rg.mu.Lock()
	rg.onCall = func() {
		r.mu.Lock()
		r.pending = alert
		r.mu.Unlock()
	}
	rg.mu.Unlock()
	rg.eng.mu.Lock()
	rg.eng.Playing = true
	rg.eng.mu.Unlock()
	for i := 0; i < 18; i++ {
		rg.eng.Tick()
	}
	r.mu.Lock()
	r.requeueRefine(inc.ID)
	r.mu.Unlock()
	r.mu.Lock()
	w, _ := r.next()
	r.mu.Unlock()
	r.runRefine(w.refine)
	r.mu.RLock()
	stage, queued, pend := inc.RefineStage, r.refineQ[inc.ID], r.pending != nil
	r.mu.RUnlock()
	if stage != "early" || !queued || !pend {
		t.Fatalf("did not step aside: stage %q requeued %v alert waiting %v", stage, queued, pend)
	}
	// once the alert has been taken, the refinement runs
	rg.mu.Lock()
	rg.onCall = nil
	rg.mu.Unlock()
	r.mu.Lock()
	r.pending = nil
	w, _ = r.next()
	r.mu.Unlock()
	r.runRefine(w.refine)
	if got := rg.settle(inc.ID); got.RefineStage != "1.5h" {
		t.Fatalf("after the alert: stage %q", got.RefineStage)
	}
}

// Revisions are stored with the incident; incidents stored before refinements existed still load,
// and a restart (new sensor history) drops due refinements with a note instead of reading new data.
func TestRefinePersistenceAndBackCompat(t *testing.T) {
	rg := newRefineRig(t)
	inc := rg.alert()
	rg.answer("exponential_increase/critical")
	rg.readings(18)
	rg.settle(inc.ID)
	old := `{"id":"INC-0099","mode":3,"state":"done","severity":"critical","severity_final":true,"title":"old","sensors":[],"agents":[]}`
	f, _ := os.OpenFile(rg.r.store, os.O_APPEND|os.O_WRONLY, 0o644)
	f.WriteString(old + "\n")
	f.Close()

	r2 := &Reasoner{store: rg.r.store, eng: rg.eng, Mode: 3, notify: func(string, any) {}}
	r2.load()
	var a, b *Incident
	for _, i := range r2.incidents {
		switch i.ID {
		case inc.ID:
			a = i
		case "INC-0099":
			b = i
		}
	}
	if a == nil || b == nil {
		t.Fatalf("reload lost incidents: %v %v", a, b)
	}
	if a.RefineStage != "1.5h" || len(a.Revisions) != 2 || a.Revisions[0].Stage != "early" || a.NextRefineSim == 0 {
		t.Fatalf("reloaded: stage %q revisions %d next %d", a.RefineStage, len(a.Revisions), a.NextRefineSim)
	}
	if b.RefineStage != "" || b.NextRefineSim != 0 || b.Revisions != nil || b.Title != "old" {
		t.Fatalf("old incident: %+v", b)
	}
	// backend restart: the engine's history is new, so the 3 h refinement cannot be read
	rg.eng.mu.Lock()
	rg.eng.reset()
	rg.eng.mu.Unlock()
	_, _, sim := rg.eng.SimBase()
	r2.RefineTick(sim)
	if a.NextRefineSim != 0 || !strings.Contains(a.RefineNote, "history") || len(r2.refines) != 0 {
		t.Fatalf("stale refinement kept: next %d note %q queued %d", a.NextRefineSim, a.RefineNote, len(r2.refines))
	}
}

// An agent answer that fails the policy gate (a batched runaway) is re-run once, alone and past the
// prompt cache; the valid solo answer replaces it. A second invalid answer keeps the first.
func TestInvalidAgentSoloRerun(t *testing.T) {
	for _, c := range []struct {
		name      string
		bad       int // how many CO2 calls return garbage
		wantValid bool
	}{{"recovers", 1, true}, {"stays invalid", 2, false}} {
		t.Run(c.name, func(t *testing.T) {
			rg := newRefineRig(t)
			var mu sync.Mutex
			calls := 0
			inner := mockGen
			mockGen = func(prompt string) (string, error) {
				if strings.Contains(prompt, "METRIC: co2") {
					mu.Lock()
					calls++
					n := calls
					mu.Unlock()
					if n <= c.bad {
						return `step 0, 0 1-1` + strings.Repeat("\n1 1", 40), nil
					}
				}
				return inner(prompt)
			}
			inc := rg.alert()
			got := rg.settle(inc.ID)
			mu.Lock()
			n := calls
			mu.Unlock()
			if n != 2 {
				t.Fatalf("CO2 agent calls = %d, want 2 (batched + one solo re-run)", n)
			}
			var co2 *AgentCall
			for i := range got.Agents {
				if got.Agents[i].Ref == got.Sensors[0].Ref {
					if co2 != nil {
						t.Fatalf("two agent calls recorded for one sensor")
					}
					co2 = &got.Agents[i]
				}
			}
			if co2 == nil || co2.Valid != c.wantValid {
				t.Fatalf("agent call %+v, want valid=%v", co2, c.wantValid)
			}
		})
	}
}

// curbTo lowers a status only when the refined AI view AND the fresh rule both read lower, and only to
// the worse of the two; anything else keeps the previous status.
func TestCurbTo(t *testing.T) {
	for _, c := range []struct {
		was, got, rule, to string
		ok                 bool
	}{
		{"critical", "warning", "normal", "warning", true},   // both lower: the worse of the two
		{"critical", "normal", "warning", "warning", true},   // the rule still sees a warning
		{"critical", "normal", "normal", "normal", true},     // recovered
		{"critical", "normal", "critical", "", false},        // rule still critical: AI misread, keep
		{"warning", "normal", "warning", "", false},          // rule unchanged: keep
		{"warning", "critical", "normal", "", false},         // not lower: that is an elevation
		{"sensor_fault", "normal", "normal", "normal", true}, // the sensor recovered
		{"critical", "sensor_fault", "sensor_fault", "sensor_fault", true},
	} {
		to, ok := curbTo(c.was, c.got, c.rule)
		if ok != c.ok || to != c.to {
			t.Errorf("curbTo(%s,%s,%s) = %q,%v want %q,%v", c.was, c.got, c.rule, to, ok, c.to, c.ok)
		}
	}
}

// A refined view whose event is over (AI event_active=false) curbs to normal only when the readings
// are back at the pre-onset baseline for the last 30 min as well.
func TestEventResolved(t *testing.T) {
	end := time.Date(2026, 10, 12, 18, 0, 0, 0, IST).Unix()
	mk := func(tail float64) SensorRef {
		xs := make([]float64, 48) // 4 h of CO2: 450 baseline, event from reading 30, last 6 = tail
		for i := range xs {
			xs[i] = 450 + float64(i%3)
			if i >= 30 && i < 42 {
				xs[i] = 1300
			}
			if i >= 42 {
				xs[i] = tail
			}
		}
		return SensorRef{Role: "air_quality", Metric: "co2", Xs: xs, End: end}
	}
	onset := idxTimeN(end, 48, 30)
	no, yes := false, true
	if since, ok := eventResolved(mk(452), nil, Finding{EventActive: &no, Onset: onset}); !ok || since != idxTimeN(end, 48, 42) {
		t.Fatalf("recovered: %q %v", since, ok)
	}
	if _, ok := eventResolved(mk(1250), nil, Finding{EventActive: &no, Onset: onset}); ok {
		t.Fatalf("still high but called resolved")
	}
	if _, ok := eventResolved(mk(452), nil, Finding{EventActive: &yes, Onset: onset}); ok {
		t.Fatalf("AI says active: must not resolve")
	}
	if _, ok := eventResolved(mk(452), nil, Finding{EventActive: &no}); ok {
		t.Fatalf("no onset: no baseline, must not resolve")
	}
}
