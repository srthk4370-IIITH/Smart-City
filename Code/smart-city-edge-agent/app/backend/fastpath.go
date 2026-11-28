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
		if c.Fast && r.openHostFor(c) {
			c.Fast = false // the sensor already belongs to an open incident: a new critical episode re-runs and escalates it
		}
		switch {
		case c.Fast:
			fast = append(fast, c)
		case c.Early:
			early = append(early, c)
		default:
			rest = append(rest, c)
		}
	}
	// night sweep 2026-11-27 #59: the building / domain / confirmed-link rule of the gate batch (batchsplit.go) applies to
	// fast and early candidates too: an SB00 power-factor and a KH03 heat early look were merged into one incident
	if len(fast) > 0 {
		for _, g := range splitUnrelated(fast) {
			r.openFast(g)
		}
	}
	if len(early) > 0 {
		for _, g := range splitUnrelated(early) {
			r.queueEarly(g)
		}
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
	rc := r.retrievalPreliminary(inc)
	r.mu.Lock()
	inc.Severity = "critical"
	inc.FastPath = true
	for _, c := range todo {
		r.fastInc[key(c.Node, c.Metric)] = inc
	}
	r.mu.Unlock()
	r.preliminary(inc, rc)
	// night sweep 2026-11-27 #38: the wording follows the live gate rule (it said "8 readings" after the gate became 4 of 8)
	r.log(inc, fmt.Sprintf("Critical fast path: %s beyond its critical limit for %d readings - incident opened at once with the rules report; "+
		"the AI analysis follows %s and updates this incident", inc.Sensors[0].Node+" "+inc.Sensors[0].Metric, trigRules().FastReadings, gateRuleText()))
	r.persist(inc)
	return inc
}

// gateRuleText: the live AI gate rule in words (#38), e.g. "once the sensor is abnormal in 4 of its last 8 readings".
func gateRuleText() string {
	tr := trigRules()
	return fmt.Sprintf("once the sensor is abnormal in %d of its last %d readings", tr.AbnormalOfWindow, tr.PersistReadings)
}

// adoptFast: the AI batch for a sensor that already has a fast incident runs on that incident (same ID, created
// time and timeline); its sensors, title and report are rebuilt from the mature windows. nil = no fast incident.
func (r *Reasoner) adoptFast(cands []Candidate, mode int) *Incident {
	r.mu.Lock()
	var inc *Incident
	for _, c := range cands {
		if f := r.fastInc[key(c.Node, c.Metric)]; f != nil {
			if c.End-f.CreatedSim > int64(Window)*bucketSec && !incidentOpenWF(f) {
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
	if inc.DataStatus == "needs_more_data" {
		inc.DataStatus, inc.RefineNote = "", ""
	}
	wasEarly := inc.RefineStage == "provisional"
	if wasEarly {
		// owner 2026-11-27: the full reading is independent of the early look, as if it never happened. Its
		// severity, title and report go; it stays in Revisions (history) only, which the reasoner does not read.
		inc.RefineStage = ""
		inc.Severity, inc.SeverityFinal, inc.SeverityWhy, inc.SeverityKept = fresh.Severity, false, "", false
		if inc.FastPath && sevRank("critical") > sevRank(inc.Severity) {
			inc.Severity = "critical"
		}
		inc.Agents, inc.Retrieved, inc.RuleTitle = nil, nil, ""
	}
	inc.Sensors, inc.Roles, inc.Title, inc.Mode1 = fresh.Sensors, fresh.Roles, fresh.Title, fresh.Mode1
	inc.Injected = inc.Injected || fresh.Injected
	if !wasEarly && sevRank(fresh.Severity) > sevRank(inc.Severity) {
		inc.Severity = fresh.Severity
	}
	r.mu.Unlock()
	// sweep 2026-11-27: the early run said "at 8 readings" right after "shorter than 8 readings"
	if wasEarly {
		r.log(inc, fmt.Sprintf("Full reading at the AI gate: %d sensor(s), made independently of the early look (its verdict is not an input)", len(cands)))
	} else if inc.ShortRunAt != 0 && !inc.earlyAdopted {
		inc.earlyAdopted = true
		r.log(inc, fmt.Sprintf("AI analysis of the fast-path incident: %d sensor(s), early run on the readings so far", len(cands)))
	} else {
		r.log(inc, fmt.Sprintf("AI analysis of the fast-path incident: %d sensor(s), %s", len(cands), gateRuleText()))
	}
	return inc
}
