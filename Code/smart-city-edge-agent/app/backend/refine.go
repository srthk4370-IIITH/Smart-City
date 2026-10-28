package main

// Early alert + refined re-analysis.
//
// The event gate calls the domain agents once a sensor has been abnormal for persistReadings (8)
// readings, so the event sits in the last ~40 min of the 4-hour window the agents read. Measured on
// the QIDK NPU (proofs/2026-10-16_placement_study/RESULTS.md), the agent's pattern accuracy grows
// with the readings since onset: 40 min 42%, 1 h 57%, 1.5 h 67%, 2 h 76%, 3 h 88% (status 62% ->
// 86%). Steps, flatlines and exponential rises are reliable from 1.5 h; gradual rises, oscillation
// and erratic data only from 3 h. Spikes and dips are best early: by 3 h a spike has often left the
// part of the window the agent weighs and is called "stable".
//
// So the early alert stays exactly as it is, and every finished Mode-3 incident is analysed twice
// more, on the windows that end 18 readings (1.5 h) and 36 readings (3 h) after its original window
// end, in sensor time. A refinement re-reads the flagged sensors whether or not they are still
// abnormal (a stuck sensor can look quiet), refreshes the related context sensors the same way, and
// runs the same agents, synthesizer, policy gate and fallbacks as the first analysis (analyse in
// reason.go). Then the reasoner's severity and title are decided again (severity.go, title.go).
//
// Exception: when the early finding for a sensor was a spike or a dip and the refined one is steady,
// the event is over, not misread, so the finding shown so far is kept and the revision says so.
//
// Elevate / curb (user, 2026-10-21: "automatic rechecking should curb or elevate the current
// warnings"): a refinement raises a sensor's status whenever its refined view is worse. It lowers
// ("curbs") it only when BOTH the refined AI finding and the deterministic rule on the fresh window
// read lower, and then only to the worse of the two, so a single misread cannot hide a live problem;
// otherwise the previous status is kept (the 2026-10-16 keep-the-worst rule). The incident's
// severity follows; the SSE "incident" event says "elevated" or "curbed" so the app can re-alert.
//
// Mode 2 is not refined: it has no per-sensor findings (one call reads every sensor), so there is
// nothing for a longer view to correct sensor by sensor. Mode 1 has no AI.
//
// Refinements are analysis only. They never touch the event gate (alerted, re-arm, reportedSev), never
// reopen an operator's decision, and wait behind every new alert and requested analysis in the one
// NPU queue; a running refinement steps aside between NPU calls when an alert arrives.

import (
	"context"
	"fmt"
	"math"
	"strings"
	"time"
)

const (
	refine1Readings = 18 // 1.5 h of 5-minute readings after the original window end
	refine2Readings = 36 // 3 h
)

// Revision is one analysis of an incident, kept so the operator can see how the view changed.
type Revision struct {
	Stage    string      `json:"stage"`   // early | 1.5h | 3h
	SimEnd   int64       `json:"sim_end"` // sensor time the windows ended
	Wall     string      `json:"wall"`    // when the analysis finished (device clock, IST)
	Severity string      `json:"severity"`
	Title    string      `json:"title"`
	Label    string      `json:"label"`
	NPUCalls int         `json:"npu_calls"`
	Ms       float64     `json:"ms"`
	Sensors  []RevSensor `json:"sensors"` // flagged sensors only
}

// RevSensor is one flagged sensor's finding at a revision.
type RevSensor struct {
	Ref     string `json:"ref"`
	Metric  string `json:"metric"`
	Pattern string `json:"pattern"`
	Status  string `json:"status"`
	Kept    bool   `json:"kept,omitempty"`    // the spike/dip exception: previous finding kept, event over
	NoData  bool   `json:"no_data,omitempty"` // no complete window at this stage: previous finding kept
	Curbed  bool   `json:"curbed,omitempty"`  // status lowered: refined AI view and fresh rule both read lower
	Note    string `json:"note,omitempty"`
}

// refinable: finished Mode-3 incidents (see the file header for Mode 1 and 2).
func refinable(inc *Incident) bool {
	return inc.Mode == 3 && (inc.State == "done" || inc.State == "done_with_errors")
}

// eventOver is the exception rule: an early spike or dip that the longer window reads as steady.
func eventOver(earlyPattern string, refined Finding) bool {
	if earlyPattern != "spike" && earlyPattern != "dip" {
		return false
	}
	return refined.Pattern == "stable" || (normSeverity(refined.Status) == "normal" && steadyPatterns[refined.Pattern])
}

// curbTo is the status a sensor may be lowered to from was, given the refined AI status got and the
// deterministic rule's status on the same fresh window: only when both read lower, and only to the
// worse of the two. ok is false when the previous status must be kept.
func curbTo(was, got, rule string) (string, bool) {
	w, g, r := reportRank[normSeverity(was)], reportRank[normSeverity(got)], reportRank[normSeverity(rule)]
	if g >= w || r >= w {
		return "", false
	}
	if r > g {
		return normSeverity(rule), true
	}
	return normSeverity(got), true
}

// recoveredSince reports whether a sensor's event is over in its refined window: the last 30 min of
// readings are within the metric's limits and back at the pre-onset baseline (mean within 3 sd of the
// readings before the onset, or 10% of their level). onset is the AI's HH:MM; at least 1 h of baseline
// before it is required. since is the last reading that was still off the baseline (HH:MM).
func recoveredSince(s SensorRef, xs []float64, onset string) (string, bool) {
	const recent, minBase = 6, 12
	n := len(xs)
	age := onsetAge(onset, n, s.End)
	if onset == "" || age < 0 || n-age < minBase || age <= recent {
		return "", false
	}
	base, last := xs[:n-age], xs[n-recent:]
	mb := mean(base)
	sd := 0.0
	for _, x := range base {
		sd += (x - mb) * (x - mb)
	}
	sd = math.Sqrt(sd / float64(len(base)))
	tol := math.Max(3*sd, 0.1*math.Abs(mb))
	for _, x := range last {
		if valueAbnormal(s.Role, s.Metric, x) || math.Abs(x-mb) > tol {
			return "", false
		}
	}
	k := n - recent
	for k > n-age && math.Abs(xs[k-1]-mb) <= tol {
		k--
	}
	return time.Unix(s.End-int64(n-1-k)*bucketSec, 0).In(IST).Format("15:04"), true
}

// eventResolved: the refined AI view says the event is no longer active AND the readings agree
// (recoveredSince over hist, the sensor's history up to the window end: the AI dates the onset from a
// window up to 12 h long). Two independent signals, so one misread cannot clear a live alarm.
func eventResolved(s SensorRef, hist []float64, got Finding) (string, bool) {
	if got.EventActive == nil || *got.EventActive {
		return "", false
	}
	if len(hist) < len(s.Xs) {
		hist = s.Xs
	}
	return recoveredSince(s, hist, got.Onset)
}

// visibleNow: the problem shows in the present, not only in history - the deterministic rule on the
// fresh 4 h window is abnormal, or one of the last 30 min of readings is beyond a limit. A refinement
// raises a status only then: a longer window still holds an old event that the AI may grade again
// (device 2026-10-21: a cleared throttle re-read as "step decrease, critical" with power flat at baseline).
func visibleNow(s SensorRef) bool {
	if reportRank[normSeverity(s.Rule.Status)] > 0 {
		return true
	}
	for k := len(s.Xs) - 6; k < len(s.Xs); k++ {
		if k >= 0 && valueAbnormal(s.Role, s.Metric, s.Xs[k]) {
			return true
		}
	}
	return false
}

// keepStatus sets sensor i's shown status (agent finding, or the rule view when its agent was rejected)
// to st without touching the refined pattern. Copies: findings share Finding pointers with sh.Agents.
func keepStatus(sh *Incident, findings []AgentCall, i int, st string) {
	ref := sh.Sensors[i].Ref
	if f := findings[i].Parsed; f != nil && findings[i].Valid {
		c := *f
		c.Status = st
		findings[i].Parsed = &c
		for j := range sh.Agents {
			if sh.Agents[j].Ref == ref {
				sh.Agents[j].Parsed = &c
			}
		}
		return
	}
	sh.Sensors[i].Rule.Status = st
}

// endedBy is when the sensor's window last read beyond its warning limit (HH:MM sensor time), or the
// window end when it has no limits or none of its readings crossed one.
func endedBy(s SensorRef) string {
	t := s.End
	for k := len(s.Xs) - 1; k >= 0; k-- {
		if valueAbnormal(s.Role, s.Metric, s.Xs[k]) {
			if k < len(s.Xs)-1 {
				t = s.End - int64(len(s.Xs)-2-k)*bucketSec
			}
			break
		}
	}
	return time.Unix(t, 0).In(IST).Format("15:04")
}

// revisionOf summarises what inc shows now. Caller holds r.mu (or owns inc).
func revisionOf(inc *Incident, stage string, simEnd int64, notes map[string]RevSensor, calls int, ms float64) Revision {
	lab := inc.Mode1.Label
	if inc.Final != nil && inc.Final.Parsed != nil {
		lab = inc.Final.Parsed.Label
	}
	rev := Revision{Stage: stage, SimEnd: simEnd, Wall: nowTime().In(IST).Format("2006-01-02 15:04:05"), Severity: inc.Severity,
		Title: inc.Title, Label: lab, NPUCalls: calls, Ms: ms}
	ff := finalFindings(inc)
	for _, s := range inc.Sensors {
		f, ok := ff[s.Ref]
		if !ok {
			continue
		}
		rs := RevSensor{Ref: s.Ref, Metric: s.Metric, Pattern: f.Pattern, Status: f.Status}
		if n, ok := notes[s.Ref]; ok {
			rs.Kept, rs.NoData, rs.Curbed, rs.Note = n.Kept, n.NoData, n.Curbed, n.Note
		}
		rev.Sensors = append(rev.Sensors, rs)
	}
	return rev
}

// scheduleRefine records the early analysis and books the 1.5 h refinement. Called by Process once
// the early analysis has finished; epoch and shift are the engine's when the incident was created.
// Caller holds r.mu.
func (r *Reasoner) scheduleRefine(inc *Incident, epoch, shift int64) {
	if !refinable(inc) || inc.RefineStage != "" {
		return
	}
	inc.RefineStage = "early"
	inc.SimEpoch, inc.SimShift = epoch, shift
	inc.NextRefineSim = inc.CreatedSim + refine1Readings*bucketSec
	inc.Revisions = append(inc.Revisions, revisionOf(inc, "early", inc.CreatedSim, nil, inc.NPUCalls, inc.TotalMs))
}

// nextStage names the refinement inc.NextRefineSim is booked for.
func nextStage(inc *Incident) string {
	if inc.RefineStage == "early" && !hasStage(inc, "1.5h") {
		return "1.5h"
	}
	return "3h"
}

func hasStage(inc *Incident, stage string) bool {
	for _, v := range inc.Revisions {
		if v.Stage == stage {
			return true
		}
	}
	return false
}

// RefineTick runs on every engine poll (sensor time sim). It queues refinements that have come due
// and starts the queue if the NPU is idle. Cheap when nothing is due: one pass over the incidents.
// Due times are derived from the stored incidents, so a restart loses none of them; but the sensor
// history is not stored, so an incident from an earlier epoch (backend restart, clock restart) can no
// longer be re-read and its refinements are dropped with a note.
func (r *Reasoner) RefineTick(sim int64) {
	if r.eng == nil {
		return
	}
	epoch, shift, _ := r.eng.SimBase()
	var stale []*Incident
	r.mu.Lock()
	if r.refineQ == nil {
		r.refineQ = map[string]bool{}
	}
	for _, inc := range r.incidents {
		if inc.NextRefineSim == 0 || inc.State == "running" {
			continue
		}
		if inc.SimEpoch != epoch {
			inc.NextRefineSim = 0
			inc.RefineNote = "Not refined: the sensor history it needs is gone (the backend or the sensor clock restarted after the alert)."
			stale = append(stale, inc)
			continue
		}
		if inc.SimShift != shift { // SetClock moved every reading; the booking moves with them
			inc.NextRefineSim += shift - inc.SimShift
			inc.SimShift = shift
		}
		if inc.NextRefineSim <= sim && !r.refineQ[inc.ID] {
			r.refines = append(r.refines, inc.ID)
			r.refineQ[inc.ID] = true
		}
	}
	var w work
	start := len(r.refines) > 0 && !r.active && !r.coolWait && !r.refineHeld()
	if start {
		w, _ = r.next()
		r.active = true
		r.lastNPU = time.Now()
	}
	r.mu.Unlock()
	for _, inc := range stale {
		r.persist(inc)
		r.notify("incident", map[string]any{"id": inc.ID, "state": inc.State})
	}
	if start {
		go r.loop(w)
	}
}

// refineHeld: low-priority work waits while the board is hot (one watcher resumes the queue once it
// cools, as for alerts) or while the operator has chosen rules-only mode. Caller holds r.mu.
func (r *Reasoner) refineHeld() bool {
	if r.Mode == 1 {
		return true
	}
	if hot, _, _ := ThermalHot(); hot {
		if !r.coolWait {
			r.coolWait = true
			go r.runWhenCool()
		}
		return true
	}
	return false
}

// requeueRefine puts a refinement back at the head of its queue. Caller holds r.mu.
func (r *Reasoner) requeueRefine(id string) {
	if r.refineQ == nil {
		r.refineQ = map[string]bool{}
	}
	if !r.refineQ[id] {
		r.refines = append([]string{id}, r.refines...)
		r.refineQ[id] = true
	}
}

// urgentWaiting: an alert or a requested analysis is waiting for the NPU.
func (r *Reasoner) urgentWaiting() bool {
	r.mu.RLock()
	defer r.mu.RUnlock()
	return r.pending != nil || len(r.jobs) > 0
}

// runRefine re-analyses one incident on its windows at the booked stage. Runs in the NPU loop.
func (r *Reasoner) runRefine(id string) {
	epoch, shift, now := r.eng.SimBase()
	r.mu.Lock()
	if r.Mode == 1 || r.urgentLocked() {
		r.requeueRefine(id)
		r.mu.Unlock()
		return
	}
	var inc *Incident
	for _, i := range r.incidents {
		if i.ID == id {
			inc = i
		}
	}
	if inc == nil || inc.NextRefineSim == 0 || !refinable(inc) || inc.SimEpoch != epoch {
		r.mu.Unlock()
		return
	}
	end := inc.NextRefineSim + (shift - inc.SimShift)
	if end > now {
		r.mu.Unlock() // the clock was moved back after it was queued: RefineTick queues it again when due
		return
	}
	stage := nextStage(inc)
	cur := append([]SensorRef(nil), inc.Sensors...)
	curAgent := map[string]AgentCall{}
	for _, a := range inc.Agents {
		curAgent[a.Ref] = a
	}
	curFind := finalFindings(inc)
	early := map[string]string{} // ref -> pattern of the EARLY finding
	for ref, f := range curFind {
		early[ref] = f.Pattern
	}
	for _, v := range inc.Revisions {
		if v.Stage == "early" {
			for _, s := range v.Sensors {
				early[s.Ref] = s.Pattern
			}
		}
	}
	ruleTitle := inc.RuleTitle
	if ruleTitle == "" {
		ruleTitle = inc.Title
	}
	created := inc.CreatedSim
	prevEnd := created // where the windows of the current findings ended
	for _, v := range inc.Revisions {
		if v.SimEnd > prevEnd {
			prevEnd = v.SimEnd
		}
	}
	r.mu.Unlock()

	// fresh windows for every sensor of the incident, flagged and related, ending at the stage time
	notes := map[string]RevSensor{}
	sensors := make([]SensorRef, 0, len(cur))
	fresh := 0
	for _, s := range cur {
		xs, ok := r.eng.WindowAt(s.Node, s.Metric, end)
		var hf Finding
		if hvacAgentSensor(s.Role, s.Node, s.Metric) && !s.Context {
			xs, hf, ok = r.eng.HVACUnitFindingAt(s.Node, end) // v2 HVAC unit: its own rule
		}
		if !ok {
			sensors = append(sensors, s) // gaps: keep what this sensor showed so far
			if !s.Context {
				notes[s.Ref] = RevSensor{NoData: true, Note: noWindowNote(r.eng.GapReasonAt(s.Node, s.Metric, end))}
			}
			continue
		}
		var f Finding
		if s.Context {
			f = contextFinding(s.Role, s.Metric, s.Node, xs, end)
		} else if hvacAgentSensor(s.Role, s.Node, s.Metric) {
			f = hf
			fresh++
		} else {
			f = RuleFinding(s.Role, s.Metric, s.Node, xs, end)
			fresh++
		}
		sr := r.sensorRef(s.Ref, Candidate{s.Node, s.Metric, s.Role, f, xs, end, s.Injected, false, false}, s.Why)
		if agentV2() && !s.Context {
			// v2 window policy (features_v2.go WindowN): by the early call's shape, the latest status
			// (sensor fault) and the event age, so the window keeps the onset plus 1 h of baseline
			was, ok := curFind[s.Ref]
			// the worse of the fresh rule status and the sensor's latest finding; a sensor fault wins
			status := f.Status
			if ok && (normSeverity(was.Status) == "sensor_fault" ||
				(normSeverity(status) != "sensor_fault" && reportRank[normSeverity(was.Status)] > reportRank[normSeverity(status)])) {
				status = was.Status
			}
			sr.WinN = WindowN(stage, early[s.Ref], status, eventAge(was, ok, prevEnd, created, end))
			r.applyV2Evidence(&sr) // evidence at the policy length
		}
		sensors = append(sensors, sr)
	}
	if fresh == 0 {
		r.mu.Lock()
		inc.RefineNote = fmt.Sprintf("%s refinement skipped: no sensor had a complete window at %s.", stageText(stage), time.Unix(end, 0).In(IST).Format("15:04"))
		r.advance(inc, stage, end, shift)
		r.mu.Unlock()
		r.persist(inc)
		r.notify("incident", map[string]any{"id": inc.ID, "state": inc.State})
		return
	}

	sh := &Incident{ID: inc.ID, Mode: 3, State: "running", CreatedSim: inc.CreatedSim, Title: ruleTitle, Roles: inc.Roles,
		Injected: inc.Injected, Sensors: sensors, quiet: true, preempt: r.urgentWaiting}
	sh.Mode1 = mode1Report(sensors)
	// after the agents, before the synthesizer: put back the previous finding where the exception
	// rule applies or the window was missing, so the report is written from what will be shown
	hold := func(findings []AgentCall) {
		for i := range sh.Sensors {
			s := sh.Sensors[i]
			if s.Context {
				continue
			}
			curbAfter := "" // status to lower the kept spike/dip finding to, once it is put back
			if _, gap := notes[s.Ref]; !gap {
				got := s.Rule
				if findings[i].Parsed != nil && findings[i].Valid {
					got = *findings[i].Parsed
				}
				var hist []float64
				if r.eng != nil {
					hist = r.eng.HistoryAt(s.Node, s.Metric, s.End, v2Hist)
				}
				if was, ok := curFind[s.Ref]; ok {
					if since, done := eventResolved(s, hist, got); done {
						// resolved: back to baseline per the AI and the readings; the pattern stays as history.
						// A sensor already resolved stays so: a later, longer window still holds the old event
						// and its status describes that event, not the present (device 2026-10-21: re-raised)
						keepStatus(sh, findings, i, "normal")
						if reportRank[normSeverity(was.Status)] > 0 {
							notes[s.Ref] = RevSensor{Curbed: true, Note: fmt.Sprintf("resolved: %s -> normal, %s back to baseline since %s (AI: event no longer active)",
								sevWord(was.Status), strings.ReplaceAll(got.Pattern, "_", " "), since)}
						} else {
							notes[s.Ref] = RevSensor{Note: fmt.Sprintf("still resolved: back to baseline since %s (AI: event no longer active)", since)}
						}
						continue
					}
				}
				if was, ok := curFind[s.Ref]; ok && reportRank[normSeverity(got.Status)] > reportRank[normSeverity(was.Status)] && !visibleNow(s) {
					keepStatus(sh, findings, i, was.Status)
					notes[s.Ref] = RevSensor{Kept: true, Note: fmt.Sprintf("not raised to %s: readings and rule are normal now (the AI graded an older part of its %d-reading window)",
						sevWord(got.Status), imax(s.WinN, LadderAlert))}
					continue
				}
				if !eventOver(early[s.Ref], got) {
					// a lower refined status sticks only when the fresh rule agrees (curbTo); otherwise the
					// previous one is kept (keep the worst, 2026-10-16: a recovered load read "step decrease")
					if was, ok := curFind[s.Ref]; ok && reportRank[normSeverity(got.Status)] < reportRank[normSeverity(was.Status)] {
						if to, curb := curbTo(was.Status, got.Status, s.Rule.Status); curb {
							keepStatus(sh, findings, i, to)
							notes[s.Ref] = RevSensor{Curbed: true, Note: fmt.Sprintf("curbed %s -> %s: refined view (%s %s) and rule (%s) both read lower; beyond limits last at %s",
								sevWord(was.Status), sevWord(to), strings.ReplaceAll(got.Pattern, "_", " "), sevWord(got.Status), sevWord(s.Rule.Status), endedBy(s))}
						} else {
							keepStatus(sh, findings, i, was.Status)
							notes[s.Ref] = RevSensor{Kept: true, Note: fmt.Sprintf("%s kept from %s: the rule on the fresh window still reads %s (refined view: %s %s)",
								sevWord(was.Status), stageText(prevStage(inc)), sevWord(s.Rule.Status),
								strings.ReplaceAll(got.Pattern, "_", " "), sevWord(got.Status))}
						}
					}
					continue
				}
				freshRule := s.Rule.Status
				was := curFind[s.Ref]
				notes[s.Ref] = RevSensor{Kept: true, Note: fmt.Sprintf("kept %s %s: event over (refined view: %s)",
					stageText(prevStage(inc)), strings.ReplaceAll(was.Pattern, "_", " "), strings.ReplaceAll(got.Pattern, "_", " "))}
				if to, curb := curbTo(was.Status, got.Status, freshRule); curb {
					curbAfter = to
					n := notes[s.Ref]
					n.Curbed, n.Note = true, n.Note+fmt.Sprintf("; status curbed %s -> %s (refined view and rule both read lower)", sevWord(was.Status), sevWord(to))
					notes[s.Ref] = n
				}
			}
			for _, c := range cur {
				if c.Ref == s.Ref {
					sh.Sensors[i] = c
				}
			}
			a, had := curAgent[s.Ref]
			if !had {
				a = AgentCall{Ref: s.Ref, Role: s.Role} // no agent finding before either: the rule view stands
			}
			findings[i] = a
			k := -1
			for j := range sh.Agents {
				if sh.Agents[j].Ref == s.Ref {
					k = j
				}
			}
			switch {
			case k >= 0 && had:
				sh.Agents[k] = a
			case k >= 0:
				sh.Agents = append(sh.Agents[:k], sh.Agents[k+1:]...)
			case had:
				sh.Agents = append(sh.Agents, a)
			}
			if curbAfter != "" {
				keepStatus(sh, findings, i, curbAfter)
			}
		}
	}
	t0 := time.Now()
	trace("refine %s %s: windows to %s", id, stage, time.Unix(end, 0).In(IST).Format("15:04"))
	if !r.analyse(context.Background(), sh, 3, t0, hold) {
		r.mu.Lock()
		r.requeueRefine(id) // an alert arrived: it goes first, this restarts after it (answers are cached)
		r.mu.Unlock()
		trace("refine %s %s: stepped aside for an alert", id, stage)
		return
	}
	ms := float64(time.Since(t0).Milliseconds())

	r.mu.Lock()
	sh.State = "done"
	surfaceDisagreements(sh)
	finaliseSeverity(sh)
	prev := revisionOf(inc, inc.RefineStage, 0, nil, 0, 0)
	inc.Sensors, inc.Agents, inc.Final, inc.Mode1 = sh.Sensors, sh.Agents, sh.Final, sh.Mode1
	inc.Severity, inc.SeverityFinal, inc.Title = sh.Severity, true, sh.Title
	if inc.RuleTitle == "" {
		inc.RuleTitle = ruleTitle
	}
	inc.State = "done"
	if inc.Final == nil || !inc.Final.Valid {
		inc.State = "done_with_errors"
	}
	// the operator's decision (Approval) is left as it is: the refined view is recorded and shown,
	// it does not ask for a second decision
	inc.RefineStage = stage
	inc.RefineNote = ""
	rev := revisionOf(inc, stage, end, notes, sh.NPUCalls, ms)
	inc.Revisions = append(inc.Revisions, rev)
	r.advance(inc, stage, end, shift)
	msg := fmt.Sprintf("Refined at %s (windows to %s sensor time, %d NPU call(s), %.1fs): %s", stageText(stage),
		time.Unix(end, 0).In(IST).Format("15:04"), sh.NPUCalls, ms/1000, strings.Join(revChanges(prev, rev), "; "))
	inc.Timeline = append(inc.Timeline, TimelineItem{time.Now().Format("15:04:05"), msg})
	wfEv := r.wfAfterRecheckLocked(inc, prev.Severity, rev) // workflow.go: re-acknowledge on worse, resolved
	r.mu.Unlock()
	r.persist(inc)
	ev := map[string]any{"id": inc.ID, "state": inc.State, "msg": msg, "refined": stage}
	for k, v := range wfEv {
		ev[k] = v
	}
	switch a, b := reportRank[normSeverity(prev.Severity)], reportRank[normSeverity(inc.Severity)]; {
	case b > a:
		ev["change"] = "elevated"
	case b < a:
		ev["change"] = "curbed"
	}
	r.notify("incident", ev)
}

func sevWord(s string) string { return strings.ReplaceAll(normSeverity(s), "_", " ") }

// urgentLocked is urgentWaiting for a caller that holds r.mu.
func (r *Reasoner) urgentLocked() bool { return r.pending != nil || len(r.jobs) > 0 }

// advance books the next refinement after stage, or none after the last. Caller holds r.mu.
func (r *Reasoner) advance(inc *Incident, stage string, end, shift int64) {
	inc.SimShift = shift
	if stage == "1.5h" {
		inc.NextRefineSim = end + (refine2Readings-refine1Readings)*bucketSec
		if inc.RefineStage == "early" {
			// 1.5 h skipped: mark it so nextStage moves on to 3 h
			inc.Revisions = append(inc.Revisions, Revision{Stage: "1.5h", SimEnd: end, Wall: nowTime().In(IST).Format("2006-01-02 15:04:05"),
				Severity: inc.Severity, Title: inc.Title, Sensors: skippedSensors(inc)})
		}
		return
	}
	inc.NextRefineSim = 0
}

// skippedSensors: a stage that could not be re-read shows the previous findings, marked as such.
func skippedSensors(inc *Incident) []RevSensor {
	var out []RevSensor
	ff := finalFindings(inc)
	for _, s := range inc.Sensors {
		if f, ok := ff[s.Ref]; ok {
			out = append(out, RevSensor{Ref: s.Ref, Metric: s.Metric, Pattern: f.Pattern, Status: f.Status, NoData: true, Note: "not re-read: no complete window"})
		}
	}
	return out
}

// prevStage is the stage whose finding is shown before this refinement.
func prevStage(inc *Incident) string { return inc.RefineStage }

func stageText(stage string) string {
	switch stage {
	case "1.5h":
		return "1.5 h"
	case "3h":
		return "3 h"
	}
	return stage
}

// revChanges lists what a revision changed, for the activity log ("CO2: spike/critical -> step
// increase/warning", "PM2.5: kept early spike: event over").
func revChanges(prev, cur Revision) []string {
	was := map[string]RevSensor{}
	for _, s := range prev.Sensors {
		was[s.Ref] = s
	}
	var out []string
	if prev.Severity != cur.Severity {
		out = append(out, fmt.Sprintf("severity %s -> %s", prev.Severity, cur.Severity))
	}
	for _, s := range cur.Sensors {
		name := nice[s.Metric]
		if name == "" {
			name = s.Metric
		}
		p := was[s.Ref]
		switch {
		case s.Kept || s.NoData || s.Curbed:
			out = append(out, name+": "+s.Note)
		case p.Pattern != s.Pattern || p.Status != s.Status:
			out = append(out, fmt.Sprintf("%s: %s/%s -> %s/%s", name, strings.ReplaceAll(p.Pattern, "_", " "), p.Status,
				strings.ReplaceAll(s.Pattern, "_", " "), s.Status))
		}
	}
	if len(out) == 0 {
		out = []string{"no change"}
	}
	return out
}

// noWindowNote: why a refinement kept the previous finding of a sensor without a usable window.
func noWindowNote(why string) string {
	if why == "" {
		return "no complete window at this stage, previous finding kept"
	}
	return "insufficient data at this stage (" + why + "), previous finding kept"
}
