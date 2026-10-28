package main

// Critical fast path (2026-10-28, owner: "reduce real-world latency to the absolute minimum").
//
// Real sensors report one reading per 5-min bucket, so the AI gate (persistReadings = 8) plus the batch window
// (batchReadings = 3) put 40-55 min of sensor time between a real event and its incident. A sensor whose fresh
// readings are beyond its CRITICAL limit for fastReadings (2) readings in a row now opens the incident at once:
// rules-only preliminary report, severity critical from the rules, no NPU call. The domain agents and the
// reasoner still run when the sensor reaches persistReadings (the windows the agents were trained on) and they
// update THAT incident instead of opening a second one. Everything else is unchanged: the ISA-18.2 deadband and
// off-delay, maintenance and data-quality gates (the fast path sits after them in Engine.detect), batching of
// co-abnormal sensors for the AI, one alert per episode (a sensor opens at most one fast incident per episode,
// fastCooldown), the workflow (the incident waits for a person only after the AI analysis), and the refinements.
// Metrics without limits (power_kw, tank level, flow) have no fast path.

import "fmt"

// splitFast opens a fast incident for every Fast candidate and returns the others (the normal AI path).
func (r *Reasoner) splitFast(cands []Candidate) []Candidate {
	var fast, early, rest []Candidate
	for _, c := range cands {
		switch {
		case c.Fast:
			fast = append(fast, c)
		case c.Early:
			early = append(early, c)
		default:
			rest = append(rest, c)
		}
	}
	if len(fast) > 0 {
		r.openFast(fast)
	}
	if len(early) > 0 {
		r.queueEarly(early)
	}
	return rest
}

// openFast: one incident for the sensors that crossed their critical limit in the same reading, shown at once
// with the deterministic (rules) report marked preliminary. Synchronous and CPU only (microseconds of rules).
func (r *Reasoner) openFast(cands []Candidate) *Incident {
	r.mu.Lock()
	if r.fastInc == nil {
		r.fastInc = map[string]*Incident{}
	}
	var todo []Candidate
	for _, c := range cands {
		if _, open := r.fastInc[key(c.Node, c.Metric)]; !open {
			todo = append(todo, c)
		}
	}
	r.mu.Unlock()
	if len(todo) == 0 {
		return nil
	}
	inc := r.newIncident(todo, r.Mode)
	rc := fallbackReport(inc.Sensors, nil, nil)
	r.mu.Lock()
	inc.Severity = "critical"
	inc.FastPath = true
	for _, c := range todo {
		r.fastInc[key(c.Node, c.Metric)] = inc
	}
	r.mu.Unlock()
	r.preliminary(inc, rc)
	r.log(inc, fmt.Sprintf("Critical fast path: %s beyond its critical limit for %d readings - incident opened at once with the rules report; "+
		"the AI analysis follows when the event has lasted %d readings and updates this incident", inc.Sensors[0].Node+" "+inc.Sensors[0].Metric, fastReadings, persistReadings))
	r.persist(inc)
	return inc
}

// adoptFast: the AI batch for a sensor that already has a fast incident runs on that incident (same ID, created
// time and timeline); its sensors, title and report are rebuilt from the mature windows. nil = no fast incident.
func (r *Reasoner) adoptFast(cands []Candidate, mode int) *Incident {
	r.mu.Lock()
	var inc *Incident
	for _, c := range cands {
		if f := r.fastInc[key(c.Node, c.Metric)]; f != nil {
			if c.End-f.CreatedSim > int64(Window)*bucketSec {
				delete(r.fastInc, key(c.Node, c.Metric)) // stale: that episode ended without reaching the AI gate
				continue
			}
			inc = f
			break
		}
	}
	if inc != nil {
		for k, f := range r.fastInc {
			if f == inc {
				delete(r.fastInc, k)
			}
		}
	}
	r.mu.Unlock()
	if inc == nil {
		return nil
	}
	fresh := r.buildIncident(cands, mode)
	r.mu.Lock()
	inc.Mode, inc.State = mode, "running"
	if inc.RefineStage == "provisional" {
		inc.RefineStage = "" // the full analysis becomes the "early" stage; the provisional one stays in Revisions
	}
	inc.Sensors, inc.Roles, inc.Title, inc.Mode1 = fresh.Sensors, fresh.Roles, fresh.Title, fresh.Mode1
	inc.Injected = inc.Injected || fresh.Injected
	if sevRank(fresh.Severity) > sevRank(inc.Severity) {
		inc.Severity = fresh.Severity
	}
	r.mu.Unlock()
	r.log(inc, fmt.Sprintf("AI analysis of the fast-path incident: %d sensor(s) at %d readings", len(cands), persistReadings))
	return inc
}
