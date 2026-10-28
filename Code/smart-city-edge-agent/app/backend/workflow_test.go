package main

// Approval lifecycle (workflow.go): state machine, event log, auto-close, re-acknowledge on worse,
// the 30-day repair rule, list grouping, health counting and the HTTP API (old endpoints included).

import (
	"encoding/json"
	"fmt"
	"net/http/httptest"
	"os"
	"path/filepath"
	"strings"
	"sync"
	"testing"
	"time"
)

// wfClock pins the people clock (wfNow) for one test.
type wfClock struct{ now time.Time }

func newWfClock(t *testing.T) *wfClock {
	c := &wfClock{now: time.Date(2026, 10, 23, 10, 0, 0, 0, IST)}
	old := wfNow
	wfNow = func() time.Time { return c.now }
	t.Cleanup(func() { wfNow = old })
	return c
}

func (c *wfClock) add(d time.Duration) { c.now = c.now.Add(d) }

type wfRig struct {
	t      *testing.T
	r      *Reasoner
	dir    string
	mu     sync.Mutex
	events []map[string]any
}

func newWfRig(t *testing.T) *wfRig {
	rg := &wfRig{t: t, dir: t.TempDir()}
	rg.r = NewReasoner(nil, nil, rg.dir, func(kind string, v any) {
		if m, ok := v.(map[string]any); ok && kind == "incident" {
			rg.mu.Lock()
			rg.events = append(rg.events, m)
			rg.mu.Unlock()
		}
	})
	return rg
}

// add puts a finished Mode-3 incident on node/metric through created -> analysed, as Process does.
func (rg *wfRig) add(id, node, metric, sev string) *Incident {
	inc := &Incident{ID: id, Mode: 3, State: "running", Approval: "pending", Severity: sev, SeverityFinal: true,
		Roles: []string{"air_quality"}, CreatedSim: 100000, CreatedWall: wfNow().In(IST).Format("2006-01-02 15:04:05"),
		Title: id + " title",
		Sensors: []SensorRef{{Ref: "S1", Node: node, Metric: metric, Role: "air_quality", Location: "KH building, level 03, room 03",
			Rule: Finding{Pattern: "step_increase", Status: sev}}},
		Agents: []AgentCall{{Ref: "S1", Valid: true, Parsed: &Finding{Pattern: "step_increase", Status: sev, Action: "inspect_ventilation"}}},
	}
	if sev == "sensor_fault" {
		inc.Sensors[0].Rule.Pattern = "flatline"
		inc.Agents[0].Parsed = &Finding{Pattern: "flatline", Status: sev, Action: "check_sensor"}
	}
	rg.r.mu.Lock()
	rg.r.incidents = append(rg.r.incidents, inc)
	wfCreated(inc)
	inc.State = "done"
	rg.r.wfAnalysedLocked(inc, 7)
	rg.r.mu.Unlock()
	rg.r.persist(inc)
	return inc
}

func (rg *wfRig) get(id string) Incident {
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

func evNames(inc Incident) string {
	var p []string
	for _, e := range inc.Events {
		p = append(p, e.Actor+":"+e.Event)
	}
	return strings.Join(p, ",")
}

func wantCode(t *testing.T, err error, code int, what string) {
	t.Helper()
	we, ok := err.(*WfError)
	if !ok || we.Code != code {
		t.Fatalf("%s: want %d, got %v", what, code, err)
	}
}

func TestWorkflowStateMachineAndEvents(t *testing.T) {
	newWfClock(t)
	rg := newWfRig(t)
	inc := rg.add("INC-0001", "N1", "co2", "warning")
	got := rg.get("INC-0001")
	if got.Workflow != wfNeeds || got.NeedsSince == 0 || len(got.Steps) != 1 || got.Steps[0].Action != "inspect_ventilation" || got.Steps[0].State != "open" {
		t.Fatalf("after analysis: wf %q steps %+v", got.Workflow, got.Steps)
	}
	// analysing: no decision is possible
	rg.r.mu.Lock()
	inc.State = "running"
	rg.r.mu.Unlock()
	_, err := rg.r.Ack(inc.ID, "Ravi")
	wantCode(t, err, 409, "ack while running")
	rg.r.mu.Lock()
	inc.State = "done"
	rg.r.mu.Unlock()
	_, err = rg.r.Ack(inc.ID, "  ")
	wantCode(t, err, 400, "ack without a name")
	_, err = rg.r.Ack(inc.ID, strings.Repeat("x", 41))
	wantCode(t, err, 400, "long name")
	if _, err = rg.r.Ack(inc.ID, " Ravi  K "); err != nil {
		t.Fatal(err)
	}
	got = rg.get(inc.ID)
	if got.Workflow != wfInProgress || got.Owner != "Ravi K" || got.AckedAt == 0 || got.Severity != "warning" || got.State != "done" {
		t.Fatalf("ack: wf %q owner %q sev %q state %q", got.Workflow, got.Owner, got.Severity, got.State)
	}
	// checklist: done with a note, a step of their own, an unknown step and state
	if _, err = rg.r.SetStep(inc.ID, "s1", "Ravi K", "done", "dampers reopened"); err != nil {
		t.Fatal(err)
	}
	_, err = rg.r.SetStep(inc.ID, "s9", "Ravi K", "done", "")
	wantCode(t, err, 404, "unknown step")
	_, err = rg.r.SetStep(inc.ID, "s1", "Ravi K", "maybe", "")
	wantCode(t, err, 400, "bad state")
	if _, err = rg.r.AddStep(inc.ID, "Asha", "Call the AHU vendor"); err != nil {
		t.Fatal(err)
	}
	for i := 0; i < 4; i++ {
		if _, err = rg.r.AddStep(inc.ID, "Asha", fmt.Sprintf("extra %d", i)); err != nil {
			t.Fatal(err)
		}
	}
	_, err = rg.r.AddStep(inc.ID, "Asha", "one too many")
	wantCode(t, err, 409, "sixth own step")
	got = rg.get(inc.ID)
	if got.Steps[0].State != "done" || got.Steps[0].By != "Ravi K" || got.Steps[0].Note != "dampers reopened" ||
		got.Steps[1].Source != "operator" || got.Steps[1].Text != "Call the AHU vendor" || got.Owner != "Ravi K" {
		t.Fatalf("steps %+v owner %q", got.Steps[:2], got.Owner)
	}
	// close: an outcome is required, a note for false alarm / no action needed
	_, err = rg.r.Close(inc.ID, "Ravi K", "", "", false)
	wantCode(t, err, 400, "close without outcome")
	_, err = rg.r.Close(inc.ID, "Ravi K", "fixed", "", false)
	wantCode(t, err, 400, "unknown outcome")
	_, err = rg.r.Close(inc.ID, "Ravi K", "false_alarm", " ", false)
	wantCode(t, err, 400, "false alarm without note")
	if _, err = rg.r.Close(inc.ID, "Ravi K", "fixed_by_action", "", false); err != nil {
		t.Fatal(err)
	}
	got = rg.get(inc.ID)
	if got.Workflow != wfClosed || got.Outcome != "fixed_by_action" || got.ClosedBy != "Ravi K" || got.ClosedAt == 0 || got.Approval != "approved" {
		t.Fatalf("close: %+v", got.WorkflowState)
	}
	// closed is final
	_, err = rg.r.Ack(inc.ID, "Asha")
	wantCode(t, err, 409, "ack after close")
	_, err = rg.r.SetStep(inc.ID, "s2", "Asha", "done", "")
	wantCode(t, err, 409, "step after close")
	_, err = rg.r.Close(inc.ID, "Asha", "false_alarm", "no", true)
	wantCode(t, err, 409, "dismiss after close")
	// the log: one row per click and transition, in order, with who
	want := "system:created,reasoner:analysed,Ravi K:ack,Ravi K:step_done,Asha:step_added,Asha:step_added,Asha:step_added,Asha:step_added,Asha:step_added,Ravi K:closed"
	if evNames(got) != want {
		t.Fatalf("events\n got %s\nwant %s", evNames(got), want)
	}
	for i, e := range got.Events {
		if e.Seq != i+1 || e.At == 0 {
			t.Fatalf("event %d: %+v", i, e)
		}
	}
	if got.Events[3].StepID != "s1" || got.Events[3].Note != "dampers reopened" || got.Events[9].Outcome != "fixed_by_action" {
		t.Fatalf("event detail: %+v %+v", got.Events[3], got.Events[9])
	}
	// SSE: each click told the dashboard, with the workflow
	rg.mu.Lock()
	last := rg.events[len(rg.events)-1]
	rg.mu.Unlock()
	if last["workflow"] != wfClosed || last["id"] != inc.ID {
		t.Fatalf("sse %+v", last)
	}
	// persisted with the incident: a restart reloads steps and the whole log
	r2 := NewReasoner(nil, nil, rg.dir, func(string, any) {})
	var re *Incident
	for _, i := range r2.incidents {
		if i.ID == inc.ID {
			re = i
		}
	}
	if re == nil || evNames(*re) != want || len(re.Steps) != 6 || re.Workflow != wfClosed {
		t.Fatalf("reload: %+v", re)
	}
}

func TestWorkflowTickingAStepAcknowledges(t *testing.T) {
	newWfClock(t)
	rg := newWfRig(t)
	inc := rg.add("INC-0002", "N1", "co2", "warning")
	if _, err := rg.r.SetStep(inc.ID, "s1", "Meena", "not_needed", "already fine"); err != nil {
		t.Fatal(err)
	}
	got := rg.get(inc.ID)
	if got.Workflow != wfInProgress || got.Owner != "Meena" || !strings.HasSuffix(evNames(got), "Meena:ack,Meena:step_not_needed") {
		t.Fatalf("auto-ack: wf %q owner %q events %s", got.Workflow, got.Owner, evNames(got))
	}
	if _, err := rg.r.SetStep(inc.ID, "s1", "Meena", "open", ""); err != nil {
		t.Fatal(err)
	}
	if got = rg.get(inc.ID); got.Steps[0].State != "open" || !strings.HasSuffix(evNames(got), "Meena:step_reopened") {
		t.Fatalf("reopen: %+v %s", got.Steps[0], evNames(got))
	}
}

func TestWorkflowApproveAndDismissCompat(t *testing.T) {
	newWfClock(t)
	rg := newWfRig(t)
	a := rg.add("INC-0003", "N1", "co2", "warning")
	if _, err := rg.r.ApproveAll(a.ID, "", "ok by ops"); err != nil {
		t.Fatal(err)
	}
	got := rg.get(a.ID)
	if got.Approval != "approved" || got.ApprovalNote != "ok by ops" || got.Workflow != wfInProgress || got.Owner != "operator" ||
		!got.Steps[0].Accepted || got.Steps[0].State != "open" || !strings.HasSuffix(evNames(got), "operator:ack,operator:approve_all") {
		t.Fatalf("approve all: %+v %s", got.WorkflowState, evNames(got))
	}
	b := rg.add("INC-0004", "N2", "co2", "warning")
	_, err := rg.r.Close(b.ID, "", "", "", true)
	wantCode(t, err, 400, "dismiss without a note")
	_, err = rg.r.Close(b.ID, "", "fixed_by_action", "x", true)
	wantCode(t, err, 400, "dismiss as fixed")
	if _, err = rg.r.Close(b.ID, "", "", "not needed", true); err != nil {
		t.Fatal(err)
	}
	got = rg.get(b.ID)
	if got.Workflow != wfClosed || got.Outcome != "no_action_needed" || got.Approval != "dismissed" || got.ApprovalNote != "not needed" {
		t.Fatalf("dismiss: %+v", got.WorkflowState)
	}
	c := rg.add("INC-0005", "N3", "co2", "warning")
	if _, err = rg.r.Close(c.ID, "Ravi", "false_alarm", "sensor bumped", true); err != nil {
		t.Fatal(err)
	}
	if got = rg.get(c.ID); got.Outcome != "false_alarm" || !strings.HasSuffix(evNames(got), "Ravi:dismissed") {
		t.Fatalf("dismiss false alarm: %+v", got.WorkflowState)
	}
	// SetApproval (old callers) maps onto the lifecycle too
	d := rg.add("INC-0006", "N4", "co2", "warning")
	rg.r.SetApproval(d.ID, "approved", "")
	if got = rg.get(d.ID); got.Workflow != wfInProgress {
		t.Fatalf("SetApproval approved: %q", got.Workflow)
	}
	rg.r.SetApproval(d.ID, "dismissed", "no")
	if got = rg.get(d.ID); got.Workflow != wfClosed || got.Outcome != "no_action_needed" {
		t.Fatalf("SetApproval dismissed: %+v", got.WorkflowState)
	}
	// an interrupted analysis may only be dismissed
	e := rg.add("INC-0007", "N5", "co2", "warning")
	rg.r.mu.Lock()
	e.State = "failed"
	rg.r.mu.Unlock()
	_, err = rg.r.ApproveAll(e.ID, "", "")
	wantCode(t, err, 409, "approve failed")
	if _, err = rg.r.Close(e.ID, "", "", "rerun later", true); err != nil {
		t.Fatal(err)
	}
}

func TestWorkflowReminderOnceAfter15Min(t *testing.T) {
	clk := newWfClock(t)
	rg := newWfRig(t)
	crit := rg.add("INC-0010", "N1", "co2", "critical")
	warn := rg.add("INC-0011", "N2", "co2", "warning")
	clk.add(14 * time.Minute)
	rg.r.workflowTick(1, 7, nil)
	if rg.get(crit.ID).Reminded {
		t.Fatal("reminded before 15 min")
	}
	clk.add(time.Minute)
	rg.r.workflowTick(2, 7, nil)
	rg.r.workflowTick(3, 7, nil)
	got := rg.get(crit.ID)
	if !got.Reminded || strings.Count(evNames(got), "system:reminder") != 1 {
		t.Fatalf("reminder once: %s", evNames(got))
	}
	if rg.get(warn.ID).Reminded {
		t.Fatal("a warning is not reminded")
	}
	rg.mu.Lock()
	n := 0
	for _, e := range rg.events {
		if e["change"] == "reminder" && e["id"] == crit.ID {
			n++
		}
	}
	rg.mu.Unlock()
	if n != 1 {
		t.Fatalf("reminder SSE events: %d", n)
	}
	// acknowledged incidents are never reminded
	c2 := rg.add("INC-0012", "N3", "co2", "critical")
	rg.r.Ack(c2.ID, "Ravi")
	clk.add(time.Hour)
	rg.r.workflowTick(4, 7, nil)
	if rg.get(c2.ID).Reminded {
		t.Fatal("acknowledged incident reminded")
	}
}

func liveState(node, metric, status string, normalRun, abnormalFor int) SensorState {
	return SensorState{Node: node, Metric: metric, Status: status, normalRun: normalRun, AbnormalFor: abnormalFor, Quality: "good"}
}

func TestWorkflowLiveResolveAndAutoClose(t *testing.T) {
	clk := newWfClock(t)
	rg := newWfRig(t)
	inc := rg.add("INC-0020", "N1", "co2", "warning")
	// still abnormal, or normal for too short: not resolved; another history epoch: never
	rg.r.workflowTick(10, 7, []SensorState{liveState("N1", "co2", "warning", 0, 3)})
	rg.r.workflowTick(11, 7, []SensorState{liveState("N1", "co2", "normal", 5, 0)})
	rg.r.workflowTick(12, 8, []SensorState{liveState("N1", "co2", "normal", 9, 0)})
	if wf := rg.get(inc.ID).Workflow; wf != wfNeeds {
		t.Fatalf("resolved too early: %s", wf)
	}
	rg.r.workflowTick(13, 7, []SensorState{liveState("N1", "co2", "normal", 6, 0)})
	got := rg.get(inc.ID)
	if got.Workflow != wfResolved || got.SuggestOutcome != "resolved_on_its_own" || got.ResolvedSim != 13 || got.Severity != "warning" {
		t.Fatalf("live resolve: %+v", got.WorkflowState)
	}
	// abnormal again: back to needs decision
	rg.r.workflowTick(14, 7, []SensorState{liveState("N1", "co2", "critical", 0, 1)})
	if got = rg.get(inc.ID); got.Workflow != wfNeeds || !strings.Contains(evNames(got), "system:abnormal_again") {
		t.Fatalf("abnormal again: %q %s", got.Workflow, evNames(got))
	}
	rg.r.workflowTick(15, 7, []SensorState{liveState("N1", "co2", "normal", 6, 0)})
	clk.add(23*time.Hour + 59*time.Minute)
	rg.r.workflowTick(16, 7, []SensorState{liveState("N1", "co2", "normal", 99, 0)})
	if got = rg.get(inc.ID); got.Workflow != wfResolved {
		t.Fatalf("closed before 24 h: %q", got.Workflow)
	}
	clk.add(time.Minute)
	rg.r.workflowTick(17, 7, []SensorState{liveState("N1", "co2", "normal", 99, 0)})
	got = rg.get(inc.ID)
	if got.Workflow != wfClosed || got.Outcome != "resolved_on_its_own" || got.OutcomeNote != "auto" || got.ClosedBy != "system" ||
		!strings.HasSuffix(evNames(got), "system:auto_closed") {
		t.Fatalf("auto-close: %+v %s", got.WorkflowState, evNames(got))
	}

	// an owner with a step still open blocks the auto-close until the step is ticked
	b := rg.add("INC-0021", "N2", "co2", "warning")
	rg.r.Ack(b.ID, "Ravi")
	rg.r.workflowTick(20, 7, []SensorState{liveState("N2", "co2", "normal", 6, 0)})
	clk.add(25 * time.Hour)
	rg.r.workflowTick(21, 7, []SensorState{liveState("N2", "co2", "normal", 99, 0)})
	if got = rg.get(b.ID); got.Workflow != wfResolved {
		t.Fatalf("auto-closed with an open step: %q", got.Workflow)
	}
	rg.r.SetStep(b.ID, "s1", "Ravi", "done", "")
	if got = rg.get(b.ID); got.SuggestOutcome != "fixed_by_action" {
		t.Fatalf("suggested outcome after a step: %q", got.SuggestOutcome)
	}
	rg.r.workflowTick(22, 7, []SensorState{liveState("N2", "co2", "normal", 99, 0)})
	if got = rg.get(b.ID); got.Workflow != wfClosed || got.Outcome != "fixed_by_action" || got.OutcomeNote != "auto" {
		t.Fatalf("auto-close after the step (pre-filled outcome): %+v", got.WorkflowState)
	}
	// out of service sensors are not judged
	c := rg.add("INC-0022", "N3", "co2", "warning")
	st := liveState("N3", "co2", "normal", 50, 0)
	st.Quality = "maintenance"
	rg.r.workflowTick(23, 7, []SensorState{st})
	if got = rg.get(c.ID); got.Workflow != wfNeeds {
		t.Fatalf("resolved from an out-of-service sensor: %q", got.Workflow)
	}
}

func TestWorkflowRecheckReackAndResolve(t *testing.T) {
	newWfClock(t)
	rg := newWfRig(t)
	inc := rg.add("INC-0030", "N1", "co2", "warning")
	rg.r.Ack(inc.ID, "Ravi")
	// the 1.5 h re-check raises it and adds an agent step: back to needs decision, re-alert
	rg.r.mu.Lock()
	inc.Severity, inc.RefineStage = "critical", "1.5h"
	inc.Final = &ReportCall{Valid: true, Parsed: &Report{Severity: "critical", Action: "request_facility_review", RootCause: "CO2 rising fast [E3]. More text."}}
	ev := rg.r.wfAfterRecheckLocked(inc, "warning", Revision{Stage: "1.5h", Sensors: []RevSensor{{Ref: "S1", Status: "critical"}}})
	rg.r.mu.Unlock()
	got := rg.get(inc.ID)
	if ev["reack"] != true || got.Workflow != wfNeeds || got.WorseAt == 0 || got.Owner != "Ravi" || got.Severity != "critical" {
		t.Fatalf("re-ack: ev %+v wf %q", ev, got.Workflow)
	}
	var added *Step
	for i := range got.Steps {
		if got.Steps[i].Action == "request_facility_review" {
			added = &got.Steps[i]
		}
	}
	if added == nil || !added.New || added.Stage != "1.5h" || added.Why != "CO2 rising fast." {
		t.Fatalf("new step: %+v", got.Steps)
	}
	if !strings.Contains(evNames(got), "reasoner:recheck_elevated,system:step_added") {
		t.Fatalf("events %s", evNames(got))
	}
	// re-acknowledge, then the 3 h re-check finds the readings back to normal
	rg.r.Ack(inc.ID, "Ravi")
	rg.r.mu.Lock()
	inc.Severity, inc.RefineStage = "normal", "3h"
	ev = rg.r.wfAfterRecheckLocked(inc, "critical", Revision{Stage: "3h", SimEnd: 555, Sensors: []RevSensor{{Ref: "S1", Status: "normal"}}})
	rg.r.mu.Unlock()
	got = rg.get(inc.ID)
	if got.Workflow != wfResolved || ev["workflow_change"] != "resolved" || got.ResolvedSim != 555 || got.SuggestOutcome != "resolved_on_its_own" {
		t.Fatalf("resolved: ev %+v %+v", ev, got.WorkflowState)
	}
	// a re-check after close is logged but reopens nothing
	rg.r.Close(inc.ID, "Ravi", "resolved_on_its_own", "", false)
	rg.r.mu.Lock()
	inc.Severity = "critical"
	rg.r.wfAfterRecheckLocked(inc, "normal", Revision{Stage: "3h", Sensors: []RevSensor{{Ref: "S1", Status: "critical"}}})
	rg.r.mu.Unlock()
	if got = rg.get(inc.ID); got.Workflow != wfClosed || !strings.HasSuffix(evNames(got), "reasoner:recheck_after_close") {
		t.Fatalf("after close: %q %s", got.Workflow, evNames(got))
	}
	// an unacknowledged incident that gets worse just re-alerts (no reack flag)
	b := rg.add("INC-0031", "N2", "co2", "warning")
	rg.r.mu.Lock()
	b.Severity = "critical"
	ev = rg.r.wfAfterRecheckLocked(b, "warning", Revision{Stage: "1.5h", Sensors: []RevSensor{{Ref: "S1", Status: "critical"}}})
	rg.r.mu.Unlock()
	if ev["reack"] != nil || rg.get(b.ID).Workflow != wfNeeds {
		t.Fatalf("unacked worse: %+v", ev)
	}
}

// The real refinement pipeline: an acknowledged incident that a 1.5 h re-check finds critical goes
// back to needs decision and the SSE event asks the app to re-alert.
func TestRefineReackOnWorse(t *testing.T) {
	rg := newRefineRig(t)
	for _, sc := range Scenarios { // a real rise, so the refinement may raise it (TestRefineRaisesWhenVisible)
		if sc.ID == "ventilation_failure" {
			rg.eng.Inject(sc)
		}
	}
	rg.readings(20)
	rg.answer("step_increase/warning")
	inc := rg.alert()
	if got := rg.settle(inc.ID); got.Workflow != wfNeeds {
		t.Fatalf("after alert: %q", got.Workflow)
	}
	if _, err := rg.r.Ack(inc.ID, "Ravi"); err != nil {
		t.Fatal(err)
	}
	rg.answer("exponential_increase/critical")
	rg.readings(18)
	got := rg.settle(inc.ID)
	if got.RefineStage != "1.5h" || got.Workflow != wfNeeds || got.Owner != "Ravi" || !strings.Contains(evNames(got), "reasoner:recheck_elevated") {
		t.Fatalf("stage %q wf %q events %s", got.RefineStage, got.Workflow, evNames(got))
	}
	rg.mu.Lock()
	defer rg.mu.Unlock()
	for _, e := range rg.events {
		if e["id"] == inc.ID && e["change"] == "elevated" && e["reack"] == true && e["workflow"] == wfNeeds {
			return
		}
	}
	t.Fatalf("no re-ack event: %+v", rg.events)
}

func TestRepairRule30Days(t *testing.T) {
	clk := newWfClock(t)
	rg := newWfRig(t)
	// a fault, recalibrated and closed as repaired
	a := rg.add("INC-0040", "N1", "co2", "sensor_fault")
	rg.r.Ack(a.ID, "Ravi")
	rg.r.SetStep(a.ID, "s1", "Ravi", "done", "recalibrated")
	rg.r.Close(a.ID, "Ravi", "sensor_repaired", "", false)
	// the fault comes back 10 days later: "Replace the sensor" is added by the rule
	clk.add(10 * 24 * time.Hour)
	b := rg.add("INC-0041", "N1", "co2", "sensor_fault")
	got := rg.get(b.ID)
	var rep *Step
	for i := range got.Steps {
		if got.Steps[i].Action == "replace_sensor" {
			rep = &got.Steps[i]
		}
	}
	if rep == nil || rep.Source != "rule" || !strings.Contains(rep.Why, "INC-0040") || !strings.Contains(rep.Why, "23 Oct") {
		t.Fatalf("replace step: %+v", got.Steps)
	}
	if !strings.Contains(evNames(got), "system:step_added") {
		t.Fatalf("rule not logged: %s", evNames(got))
	}
	// replace done -> the close outcome is pre-filled as sensor replaced
	rg.r.SetStep(b.ID, rep.ID, "Ravi", "done", "")
	if got = rg.get(b.ID); got.SuggestOutcome != "sensor_replaced" {
		t.Fatalf("suggest: %q", got.SuggestOutcome)
	}
	// another sensor, or a repair older than 30 days: no rule
	c := rg.add("INC-0042", "N9", "co2", "sensor_fault")
	clk.add(31 * 24 * time.Hour)
	d := rg.add("INC-0043", "N1", "co2", "sensor_fault")
	for _, id := range []string{c.ID, d.ID} {
		for _, s := range rg.get(id).Steps {
			if s.Action == "replace_sensor" {
				t.Fatalf("%s got the rule step", id)
			}
		}
	}
	// a repair through a done sensor step on an incident that then resolved counts too
	e := rg.add("INC-0044", "N7", "co2", "sensor_fault")
	rg.r.SetStep(e.ID, "s1", "Asha", "done", "")
	rg.r.workflowTick(1, 7, []SensorState{liveState("N7", "co2", "normal", 6, 0)})
	clk.add(2 * 24 * time.Hour)
	f := rg.add("INC-0045", "N7", "co2", "sensor_fault")
	found := false
	for _, s := range rg.get(f.ID).Steps {
		found = found || s.Action == "replace_sensor"
	}
	if !found {
		t.Fatal("step-done repair not remembered")
	}
	// a warning on a repaired sensor is not a fault: no rule
	g := rg.add("INC-0046", "N7", "co2", "warning")
	for _, s := range rg.get(g.ID).Steps {
		if s.Action == "replace_sensor" {
			t.Fatal("rule on a non-fault")
		}
	}
	// History of this sensor: earlier incidents, steps and outcomes, newest first, recurrence marked
	h, err := rg.r.History(b.ID)
	if err != nil || len(h) != 1 || len(h[0].Incidents) != 1 || h[0].Incidents[0].ID != "INC-0040" ||
		h[0].Incidents[0].Outcome != "sensor_repaired" || h[0].Incidents[0].Recurred != "" || len(h[0].Incidents[0].Steps) != 1 {
		t.Fatalf("history: %+v %v", h, err)
	}
	h, _ = rg.r.History(d.ID)
	if len(h[0].Incidents) != 2 || h[0].Incidents[0].ID != "INC-0041" || h[0].Incidents[1].ID != "INC-0040" {
		t.Fatalf("history order: %+v", h[0].Incidents)
	}
}

func TestRecurredWithin7Days(t *testing.T) {
	clk := newWfClock(t)
	rg := newWfRig(t)
	a := rg.add("INC-0050", "N1", "co2", "warning")
	rg.r.Close(a.ID, "Ravi", "fixed_by_action", "", false)
	clk.add(3 * 24 * time.Hour)
	rg.add("INC-0051", "N1", "co2", "warning")
	clk.add(time.Hour)
	c := rg.add("INC-0052", "N1", "co2", "warning")
	h, _ := rg.r.History(c.ID)
	if len(h[0].Incidents) != 2 || h[0].Incidents[1].Recurred != "INC-0051" || h[0].Incidents[0].Recurred != "" {
		t.Fatalf("recurred: %+v", h[0].Incidents)
	}
}

func TestGroupIncidents(t *testing.T) {
	base := time.Date(2026, 10, 23, 10, 0, 0, 0, IST)
	mk := func(id string, min int, node, role, pattern string) *Incident {
		return &Incident{ID: id, CreatedWall: base.Add(time.Duration(min) * time.Minute).Format("2006-01-02 15:04:05"),
			Sensors: []SensorRef{{Ref: "S1", Node: node, Metric: "m", Role: role, Rule: Finding{Pattern: pattern}},
				{Ref: "S2", Node: "CTX", Metric: "m", Role: role, Context: true, Rule: Finding{Pattern: "spike"}}}}
	}
	// newest first, as Reasoner.List returns them
	list := []*Incident{
		mk("INC-0009", 200, "Z", "water", "dip"),           // alone (nothing near in time)
		mk("INC-0008", 100, "B", "power", "spike"),         // same domain+pattern as 0007, 20 min apart
		mk("INC-0007", 80, "C", "power", "spike"),          //
		mk("INC-0006", 70, "A", "air_quality", "flatline"), // same sensor as 0005, 25 min
		mk("INC-0005", 45, "A", "air_quality", "flatline"), // chains to 0004 (25 min)
		mk("INC-0004", 20, "A", "air_quality", "flatline"),
		mk("INC-0003", 15, "D", "air_quality", "stable"),    // stable pattern: no domain key; other sensor
		mk("INC-0002", -40, "A", "air_quality", "flatline"), // 60 min before 0004: not grouped
		mk("INC-0001", -45, "E", "air_quality", "dip"),      // other pattern, other sensor
	}
	g := groupIncidents(list)
	want := map[string]GroupInfo{
		"INC-0009": {"INC-0009", 1}, "INC-0008": {"INC-0008", 2}, "INC-0007": {"INC-0008", 2},
		"INC-0006": {"INC-0006", 3}, "INC-0005": {"INC-0006", 3}, "INC-0004": {"INC-0006", 3},
		"INC-0003": {"INC-0003", 1}, "INC-0002": {"INC-0002", 1}, "INC-0001": {"INC-0001", 1},
	}
	for id, w := range want {
		if g[id] != w {
			t.Errorf("%s: got %+v want %+v", id, g[id], w)
		}
	}
	// context sensors never group (INC-0003's context sensor "CTX" is shared by everyone)
	if g["INC-0003"].Size != 1 {
		t.Fatal("grouped through a context sensor")
	}
}

func TestHealthCountsEveryOpenWorkflow(t *testing.T) {
	newWfClock(t)
	st := baseStates()
	st[2].Status = "warning"
	mk := func(id string) *Incident { return inc(id, []string{"water"}, "critical") }
	needs, prog, res, closed := mk("INC-0001"), mk("INC-0002"), mk("INC-0003"), mk("INC-0004")
	prog.Approval, prog.Workflow, prog.Owner = "approved", wfInProgress, "Ravi"
	res.Workflow = wfResolved
	closed.Workflow, closed.Outcome = wfClosed, "fixed_by_action"
	oldOwned := mk("INC-0005")
	oldOwned.CreatedSim, oldOwned.Workflow, oldOwned.Owner = hsim-healthOpenSec-1, wfInProgress, "Asha"
	oldUnowned := mk("INC-0006")
	oldUnowned.CreatedSim = hsim - healthOpenSec - 1
	w := hfind(buildHealth(hsim, 1, st, []*Incident{needs, prog, res, closed, oldOwned, oldUnowned}, map[string]*healthMark{}), "water")
	var got []string
	for _, i := range w.Incidents {
		got = append(got, i.ID+"/"+i.Workflow+"/"+i.Owner)
	}
	if strings.Join(got, ",") != "INC-0005/in_progress/Asha,INC-0003/resolved/,INC-0002/in_progress/Ravi,INC-0001/needs_decision/" {
		t.Fatalf("tile incidents: %v", got)
	}
	// out-of-service sensors are shown, never alarmed
	st[2].Quality, st[2].QualityWhy = "maintenance", "out of service: calibration"
	w = hfind(buildHealth(hsim, 1, st, nil, map[string]*healthMark{}), "water")
	if w.LiveStatus != "normal" || w.OutOfSvc != 1 || w.Counts["warning"] != 0 || len(w.DataQuality) != 1 {
		t.Fatalf("maintenance: %+v", w)
	}
}

func TestLegacyIncidentsMigrate(t *testing.T) {
	newWfClock(t)
	dir := t.TempDir()
	os.MkdirAll(filepath.Join(dir, "state"), 0o755)
	mk := func(id, approval, state string) string {
		i := Incident{ID: id, Mode: 3, State: state, Approval: approval, ApprovalNote: "old note", Severity: "warning", SeverityFinal: true,
			Roles:   []string{"air_quality"},
			Sensors: []SensorRef{{Ref: "S1", Node: "N1", Metric: "co2", Role: "air_quality"}},
			Agents:  []AgentCall{{Ref: "S1", Valid: true, Parsed: &Finding{Status: "warning", Action: "inspect_ventilation"}}}}
		b, _ := json.Marshal(i)
		return string(b)
	}
	lines := strings.Join([]string{mk("INC-0001", "approved", "done"), mk("INC-0002", "dismissed", "done"), mk("INC-0003", "pending", "done"),
		mk("INC-0004", "pending", "running")}, "\n")
	os.WriteFile(filepath.Join(dir, "state", "incidents.jsonl"), []byte(lines+"\n"), 0o644)
	r := NewReasoner(nil, nil, dir, func(string, any) {})
	by := map[string]*Incident{}
	for _, i := range r.incidents {
		by[i.ID] = i
	}
	if i := by["INC-0001"]; i.Workflow != wfInProgress || !i.Legacy || len(i.Steps) != 1 || !i.Steps[0].Accepted {
		t.Fatalf("approved: %+v", i.WorkflowState)
	}
	if i := by["INC-0002"]; i.Workflow != wfClosed || i.Outcome != "no_action_needed" || i.OutcomeNote != "old note" || !i.Legacy {
		t.Fatalf("dismissed: %+v", i.WorkflowState)
	}
	if i := by["INC-0003"]; i.Workflow != wfNeeds || i.Legacy || i.Steps[0].Accepted {
		t.Fatalf("pending: %+v", i.WorkflowState)
	}
	if i := by["INC-0004"]; i.State != "failed" || i.Workflow != wfInterrupted {
		t.Fatalf("running: %q %+v", i.State, i.WorkflowState)
	}
}

// The HTTP API: the new lifecycle endpoints, the old approve/dismiss, events, history and the list.
func TestWorkflowHTTP(t *testing.T) {
	newWfClock(t)
	rg := newWfRig(t)
	a := rg.add("INC-0001", "N1", "co2", "warning")
	b := rg.add("INC-0002", "N1", "co2", "warning")
	h := (&Server{rsn: rg.r, dir: rg.dir}).routes()
	call := func(method, path, body string) (int, map[string]any, string) {
		req := httptest.NewRequest(method, path, strings.NewReader(body))
		req.RemoteAddr = "127.0.0.1:5000"
		req.Header.Set("Content-Type", "application/json")
		w := httptest.NewRecorder()
		h.ServeHTTP(w, req)
		var m map[string]any
		json.Unmarshal(w.Body.Bytes(), &m)
		return w.Code, m, w.Body.String()
	}
	if c, _, s := call("POST", "/api/incidents/INC-0001/ack", `{}`); c != 400 {
		t.Fatalf("ack without operator: %d %s", c, s)
	}
	if c, m, s := call("POST", "/api/incidents/INC-0001/ack", `{"operator":"Ravi"}`); c != 200 || m["incident"].(map[string]any)["workflow"] != wfInProgress {
		t.Fatalf("ack: %d %s", c, s)
	}
	if c, _, s := call("POST", "/api/incidents/INC-0001/steps/s1", `{"operator":"Ravi","state":"done","note":"ok"}`); c != 200 {
		t.Fatalf("step: %d %s", c, s)
	}
	if c, _, s := call("POST", "/api/incidents/INC-0001/steps", `{"operator":"Ravi","text":"Tell the warden"}`); c != 200 {
		t.Fatalf("add step: %d %s", c, s)
	}
	if c, _, s := call("POST", "/api/incidents/INC-0001/close", `{"operator":"Ravi","outcome":"false_alarm"}`); c != 400 {
		t.Fatalf("close false alarm without note: %d %s", c, s)
	}
	if c, _, s := call("POST", "/api/incidents/INC-0001/close", `{"operator":"Ravi","outcome":"fixed_by_action","note":"done"}`); c != 200 {
		t.Fatalf("close: %d %s", c, s)
	}
	if c, _, _ := call("POST", "/api/incidents/INC-0001/approve", `{}`); c != 409 {
		t.Fatalf("approve after close: %d", c)
	}
	// the old endpoints, as tools/stress_app.py drives them
	if c, _, _ := call("POST", "/api/incidents/INC-0002/dismiss", `{"note":"   "}`); c != 400 {
		t.Fatalf("blank dismiss: %d", c)
	}
	if c, _, s := call("POST", "/api/incidents/INC-0002/approve", `{"note":"stress test"}`); c != 200 {
		t.Fatalf("approve: %d %s", c, s)
	}
	_, m, _ := call("GET", "/api/incidents/INC-0002", "")
	if m["approval"] != "approved" || m["workflow"] != wfInProgress {
		t.Fatalf("approve recorded: %v %v", m["approval"], m["workflow"])
	}
	if c, _, _ := call("POST", "/api/incidents/INC-0002/dismiss", `{"note":"not needed"}`); c != 200 {
		t.Fatalf("dismiss: %d", c)
	}
	_, m, _ = call("GET", "/api/incidents/INC-0002/events", "")
	evs := m["events"].([]any)
	if len(evs) < 4 || evs[len(evs)-1].(map[string]any)["event"] != "dismissed" {
		t.Fatalf("events: %+v", evs)
	}
	_, m, _ = call("GET", "/api/incidents/INC-0002/history", "")
	sh := m["sensors"].([]any)[0].(map[string]any)
	if past := sh["incidents"].([]any); len(past) != 1 || past[0].(map[string]any)["id"] != "INC-0001" || past[0].(map[string]any)["outcome"] != "fixed_by_action" {
		t.Fatalf("history: %+v", sh)
	}
	if c, _, _ := call("POST", "/api/incidents/INC-0002/steps/s1", `{"operator":"x","state":"done"}`); c != 409 {
		t.Fatalf("step on closed: %d", c)
	}
	if c, _, _ := call("POST", "/api/incidents/INC-0002/frobnicate", `{}`); c != 400 {
		t.Fatalf("unknown action: %d", c)
	}
	// the list carries the lifecycle and the grouping (same sensor, created together)
	req := httptest.NewRequest("GET", "/api/incidents", nil)
	w := httptest.NewRecorder()
	h.ServeHTTP(w, req)
	var list []map[string]any
	json.Unmarshal(w.Body.Bytes(), &list)
	if len(list) != 2 || list[0]["id"] != "INC-0002" || list[0]["workflow"] != wfClosed || list[1]["outcome"] != "fixed_by_action" ||
		list[0]["group"] != "INC-0002" || list[1]["group"] != "INC-0002" || list[1]["group_size"].(float64) != 2 {
		t.Fatalf("list: %+v", list)
	}
	_ = a
	_ = b
}
