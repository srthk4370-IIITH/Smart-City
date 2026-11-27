package main

// Promotion of context sensors (coordinator, 2026-11-17, board INC-0010 / INC-0011). A sensor that was only context
// (or whose agent ran on the young window) when an incident opened can turn abnormal later. The event gate (persist
// rule, once per episode) already marks it alerted; here the candidate is NOT given an incident of its own while the
// incident that holds the sensor is open (not resolved or closed): the sensor becomes a domain sensor of that
// incident, its NPU agent reads its current window, the context agents of its related sensors are refreshed, and the
// reasoner writes the whole incident again (one revision, one timeline entry). At most one such re-run per incident per
// promoDebounce readings; sensors that turn abnormal meanwhile are batched into the next one. A closed incident (or one
// older than promoMaxAge) does not take the sensor: the normal gate opens a new incident as before.

import (
	"context"
	"fmt"
	"sort"
	"strings"
	"time"
)

const (
	promoDebounce = 2  // readings between two promotion re-runs of one incident
	promoMaxAge   = 72 // readings (6 h) after the incident opened during which it still takes late sensors
	// promoMaxFlagAge: an incident left open longer than this (24 h) no longer absorbs a NEW episode of its own
	// flagged sensor; the episode opens a fresh incident (and alert). Sweep 2026-11-27: a 6-day-old open pH
	// incident swallowed a new critical episode silently ("promotion re-check: no change", no alert).
	promoMaxFlagAge = 288
)

type promoJob struct {
	cands  map[string]Candidate
	sim    int64
	queued bool
	rose   map[string]string // sensor key -> the verdict its agent had given (escalation re-ask)
}

// promotionHost: the index of the sensor in inc when inc is open and still takes the candidate.
func promotionHost(inc *Incident, c Candidate) (int, bool) {
	if inc.Mode != 3 || inc.quiet {
		return 0, false
	}
	switch inc.State {
	case "running", "done", "done_with_errors", "failed": // failed = the process died mid-run: it hosts its sensor again and is re-run (polish_events.go)
	default:
		return 0, false
	}
	if w := wfOf(inc); w == wfClosed || inc.ClosedAt != 0 { // a resolved incident is still open: the sensor turning abnormal again reopens it
		return 0, false
	}
	age := c.End - inc.CreatedSim
	if age < 0 {
		return 0, false
	}
	for i, s := range inc.Sensors {
		if s.Node == c.Node && s.Metric == c.Metric {
			// the 6 h cap is for late context sensors; a sensor that is already one of the incident's own flagged
			// sensors joins it however old the (still open) incident is, instead of opening a duplicate
			if s.Context && age > promoMaxAge*bucketSec {
				return 0, false
			}
			if !s.Context && age > promoMaxFlagAge*bucketSec {
				return 0, false
			}
			return i, true
		}
	}
	return 0, false
}

// promoteOpen takes the candidates whose sensor belongs to an open incident out of the normal alert path and books
// their promotion; the rest go on as new incidents.
func (r *Reasoner) promoteOpen(cands []Candidate) []Candidate {
	if r.Mode == 1 {
		return cands
	}
	var rest []Candidate
	var sim int64
	r.mu.Lock()
	if r.promos == nil {
		r.promos = map[string]*promoJob{}
	}
	for _, c := range cands {
		var host *Incident
		for k := len(r.incidents) - 1; k >= 0 && host == nil; k-- { // newest first
			if _, ok := promotionHost(r.incidents[k], c); ok {
				host = r.incidents[k]
			}
		}
		if host == nil || r.fastInc[key(c.Node, c.Metric)] != nil {
			rest = append(rest, c)
			continue
		}
		job := r.promos[host.ID]
		if job == nil {
			job = &promoJob{cands: map[string]Candidate{}}
			r.promos[host.ID] = job
		}
		job.cands[key(c.Node, c.Metric)] = c
		if c.End > job.sim {
			job.sim = c.End
		}
		if c.End > sim {
			sim = c.End
		}
	}
	r.mu.Unlock()
	if sim > 0 {
		r.releasePromos(sim)
	}
	return rest
}

// HandleRises: alerted sensors whose rule status rose above what was reported. When the incident holding the sensor
// as a DOMAIN sensor has an agent/final verdict below the new rule status, its agent is re-asked through the promotion
// path (same debounce, one revision). The engine already raised reportedSev, so a sensor is re-asked once per level.
func (r *Reasoner) HandleRises(cands []Candidate) {
	if r.Mode == 1 {
		return
	}
	var sim int64
	r.mu.Lock()
	for _, c := range cands {
		for k := len(r.incidents) - 1; k >= 0; k-- { // newest first
			inc := r.incidents[k]
			i, ok := promotionHost(inc, c)
			if !ok {
				continue
			}
			if inc.Sensors[i].Context || r.fastInc[key(c.Node, c.Metric)] != nil {
				break
			}
			had := "normal"
			if f, ok := finalFindings(inc)[inc.Sensors[i].Ref]; ok {
				had = f.Status
			}
			if sevRank(c.Finding.Status) <= sevRank(had) {
				break
			}
			if r.promos == nil {
				r.promos = map[string]*promoJob{}
			}
			job := r.promos[inc.ID]
			if job == nil {
				job = &promoJob{cands: map[string]Candidate{}}
				r.promos[inc.ID] = job
			}
			if job.rose == nil {
				job.rose = map[string]string{}
			}
			job.cands[key(c.Node, c.Metric)] = c
			job.rose[key(c.Node, c.Metric)] = had
			if c.End > sim {
				sim = c.End
			}
			break
		}
	}
	r.mu.Unlock()
	if sim > 0 {
		r.releasePromos(sim)
	}
}

// releasePromos queues the promotions that are due at sensor time sim and starts the NPU queue if it is idle.
func (r *Reasoner) releasePromos(sim int64) {
	r.mu.Lock()
	ids := make([]string, 0, len(r.promos))
	for id := range r.promos {
		ids = append(ids, id)
	}
	sort.Strings(ids)
	for _, id := range ids {
		job := r.promos[id]
		if job.queued {
			continue
		}
		due := int64(0)
		for _, inc := range r.incidents {
			if inc.ID == id && inc.promoSim != 0 {
				due = inc.promoSim + promoDebounce*bucketSec
			}
		}
		if sim >= due {
			job.queued = true
			r.promoQ = append(r.promoQ, id)
		}
	}
	var w work
	start := len(r.promoQ) > 0 && !r.active && !r.coolWait && !r.refineHeld()
	if start {
		w, _ = r.next()
		r.active = true
		r.lastNPU = time.Now()
	}
	r.mu.Unlock()
	if start {
		safeGo("analysis loop", func() { r.loop(w) })
	}
}

// runPromote: the promotion re-run of one incident. Runs in the NPU loop.
func (r *Reasoner) runPromote(id string) {
	r.mu.Lock()
	job := r.promos[id]
	var inc *Incident
	for _, i := range r.incidents {
		if i.ID == id {
			inc = i
		}
	}
	if job == nil || inc == nil {
		r.mu.Unlock()
		r.nextEventZone(id, 0)
		return
	}
	delete(r.promos, id)
	keys := make([]string, 0, len(job.cands))
	for k := range job.cands {
		keys = append(keys, k)
	}
	sort.Strings(keys)
	cur := append([]SensorRef(nil), inc.Sensors...)
	var flagged []Candidate
	var late []Candidate // the incident closed meanwhile: these take the normal path
	for _, k := range keys {
		c := job.cands[k]
		if _, ok := promotionHost(inc, c); ok {
			flagged = append(flagged, c)
		} else {
			late = append(late, c)
		}
	}
	if len(late) > 0 {
		r.mergePending(late)
	}
	if len(flagged) == 0 {
		r.mu.Unlock()
		r.nextEventZone(id, 0)
		return
	}
	wasFailed := inc.State == "failed" // re-run after a restart (polish_events.go)
	prevSev, ruleTitle := inc.Severity, inc.RuleTitle
	if ruleTitle == "" {
		ruleTitle = inc.Title
	}
	roles, injected, stage, created := append([]string(nil), inc.Roles...), inc.Injected, inc.RefineStage, inc.CreatedSim
	r.mu.Unlock()

	end := int64(0)
	notes := map[string]RevSensor{}
	var said []string
	sev := prevSev
	for _, c := range flagged {
		if c.End > end {
			end = c.End
		}
		for i := range cur {
			if cur[i].Node == c.Node && cur[i].Metric == c.Metric {
				was := cur[i].Context
				cur[i] = r.sensorRef(cur[i].Ref, c, "") // domain sensor, window as the gate saw it
				roles = appendUnique(roles, c.Role)
				injected = injected || c.Injected
				if sevRank(c.Finding.Status) > sevRank(sev) {
					sev = c.Finding.Status
				}
				name := nice[c.Metric]
				if name == "" {
					name = c.Metric
				}
				how := "promoted to domain agent"
				if !was {
					how = "domain agent re-run on its current window"
				}
				notes[cur[i].Ref] = RevSensor{Note: how}
				if had, rose := job.rose[key(c.Node, c.Metric)]; rose && !was {
					notes[cur[i].Ref] = RevSensor{Note: "agent re-run after the rule status rose"}
					said = append(said, fmt.Sprintf("Sensor %s rose to %s (agent had said %s): agent re-run, report updated", name, sevWord(c.Finding.Status), sevWord(had)))
				} else {
					again := ""
					if !was {
						again = " again (new episode)"
					}
					said = append(said, fmt.Sprintf("Sensor %s turned %s%s: %s, report updated", name, sevWord(c.Finding.Status), again, how))
				}
			}
		}
	}
	for i := range cur { // context agents again, on the newest window
		if !cur[i].Context {
			continue
		}
		if xs, ok := r.eng.WindowAt(cur[i].Node, cur[i].Metric, end); ok {
			cur[i] = r.sensorRef(cur[i].Ref, Candidate{cur[i].Node, cur[i].Metric, cur[i].Role,
				contextFinding(cur[i].Role, cur[i].Metric, cur[i].Node, xs, end), xs, end, cur[i].Injected, false, false}, cur[i].Why)
		}
	}
	for _, p := range r.eng.ContextFor(flagged, 4) { // related sensors of the promoted ones, as the orchestrator picks them
		dup := false
		for _, s := range cur {
			dup = dup || (s.Node == p.Cand.Node && s.Metric == p.Cand.Metric)
		}
		if !dup {
			cur = append(cur, r.sensorRef(fmt.Sprintf("S%d", len(cur)+1), p.Cand, p.Why))
		}
	}

	sh := &Incident{ID: id, Mode: 3, State: "running", CreatedSim: created, Title: ruleTitle, Roles: roles, Injected: injected,
		Sensors: cur, Severity: sev, RefineStage: stage, quiet: true, preempt: r.urgentWaiting}
	sh.Mode1 = mode1Report(cur)
	t0 := time.Now()
	trace("promote %s: %d sensor(s)", id, len(flagged))
	if !r.analyse(context.Background(), sh, 3, t0, nil) {
		r.mu.Lock()
		if r.promos == nil {
			r.promos = map[string]*promoJob{}
		}
		if cur, ok := r.promos[id]; ok { // more arrived meanwhile: merge
			for k, c := range job.cands {
				if _, have := cur.cands[k]; !have {
					cur.cands[k] = c
				}
			}
			job = cur
		}
		job.queued = false
		r.promos[id] = job // an alert needs the NPU first: restart after it (answers are cached)
		r.mu.Unlock()
		return
	}
	ms := float64(time.Since(t0).Milliseconds())

	r.mu.Lock()
	sh.State = "done"
	surfaceDisagreements(sh)
	finaliseSeverity(sh)
	if reportRank[normSeverity(prevSev)] > reportRank[normSeverity(sh.Severity)] && promoCritical(sh) {
		sh.Severity = prevSev // a sensor's critical is never dropped silently by a promotion
		if sh.Final != nil && sh.Final.Parsed != nil {
			sh.Final.Parsed.Severity = prevSev
		}
	}
	if inc.EventMode && reportRank[normSeverity(prevSev)] > reportRank[normSeverity(sh.Severity)] && r.zonesLeftLocked(id) {
		sh.Severity = prevSev // event mode: the other zones have not been read by the AI yet
		if sh.Final != nil && sh.Final.Parsed != nil {
			sh.Final.Parsed.Severity = prevSev
		}
	}
	prev := revisionOf(inc, inc.RefineStage, 0, nil, 0, 0)
	inc.Sensors, inc.Agents, inc.Final, inc.Mode1, inc.Roles, inc.Injected = sh.Sensors, sh.Agents, sh.Final, sh.Mode1, sh.Roles, sh.Injected
	inc.Severity, inc.SeverityFinal, inc.Title = sh.Severity, true, sh.Title
	if inc.RuleTitle == "" {
		inc.RuleTitle = ruleTitle
	}
	consistentTitle(inc)
	inc.State = "done"
	if inc.Final == nil || !inc.Final.Valid {
		inc.State = "done_with_errors"
	}
	inc.NPUCalls += sh.NPUCalls
	inc.promoSim = end
	if inc.ShortRunAt != 0 && !inc.shortFull {
		inc.shortFull = true
		inc.Timeline = append(inc.Timeline, TimelineItem{nowTime().In(IST).Format("15:04:05"), "Full 8-reading analysis replaces the early one"})
	}
	rev := revisionOf(inc, "promotion", end, notes, sh.NPUCalls, ms)
	why := r.noteSeverityChangeLocked(inc, prev, &rev, false)
	inc.Revisions = append(inc.Revisions, rev)
	for _, m := range said {
		inc.Timeline = append(inc.Timeline, TimelineItem{nowTime().In(IST).Format("15:04:05"), m})
	}
	msg := strings.Join(said, "; ")
	var wfEv map[string]any
	if wasFailed {
		inc.Workflow = wfAnalysing
		r.wfAnalysedLocked(inc, inc.LiveEpoch)
		inc.Timeline = append(inc.Timeline, TimelineItem{nowTime().In(IST).Format("15:04:05"), "Re-run automatically after a restart: the earlier analysis did not finish"})
		wfEv = map[string]any{"workflow": inc.Workflow}
	} else {
		wfEv = r.wfAfterRecheckLocked(inc, prev.Severity, rev)
		r.reopenAgainLocked(inc, wfEv, said)
	}
	r.mu.Unlock()
	r.persist(inc)
	ev := map[string]any{"id": inc.ID, "state": inc.State, "msg": msg, "promoted": true}
	if why != "" {
		ev["severity_why"] = why
	}
	for k, v := range wfEv {
		ev[k] = v
	}
	if reportRank[normSeverity(inc.Severity)] > reportRank[normSeverity(prev.Severity)] {
		ev["change"] = "elevated"
	}
	r.notify("incident", ev)
	r.nextEventZone(id, end) // event mode: the next zone
	r.releasePromos(end)     // sensors that turned abnormal meanwhile
}

// promoCritical: a domain sensor of the incident is critical now (its agent, or its rule when it has none).
func promoCritical(inc *Incident) bool {
	for _, f := range finalFindings(inc) {
		if normSeverity(f.Status) == "critical" {
			return true
		}
	}
	return false
}
