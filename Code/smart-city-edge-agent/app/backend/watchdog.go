package main

import (
	"fmt"
	"time"
)

// Incident watchdog. A critical fast-path incident is opened at once with the rules report; its AI analysis starts
// when the event has lasted persistReadings readings. If the sensor stops sending (a dead campus feed) that gate is
// never reached and the incident sat in "running / AI analysing" forever. Two bounded waits end that:
//   - a fast-path incident whose AI has not started after dataWaitMax is marked needs_more_data: the alert and the
//     rules report stay, nothing is invented, and the AI (and the refine stages) still run when readings return;
//   - any incident "running" longer than runMax with no analysis working on it falls back to the rules report.
const (
	dataWaitMax = 5 * time.Minute
	runMax      = 30 * time.Minute
)

// StartWatchdog sweeps once a minute.
func (r *Reasoner) StartWatchdog() {
	go func() {
		for {
			time.Sleep(time.Minute)
			r.watchdogSweep(time.Now(), dataWaitMax, runMax)
		}
	}()
}

// watchdogSweep returns how many incidents it moved out of "running".
func (r *Reasoner) watchdogSweep(now time.Time, wait, hard time.Duration) int {
	r.mu.RLock()
	queued := map[*Incident]bool{}
	for _, j := range r.early {
		queued[j.inc] = true
	}
	fast := map[*Incident]bool{}
	for _, f := range r.fastInc {
		fast[f] = true
	}
	var cand []*Incident
	for _, inc := range r.incidents {
		if inc.State == "running" && !inc.openedAt.IsZero() && !queued[inc] {
			cand = append(cand, inc)
		}
	}
	active := r.active
	r.mu.RUnlock()
	n := 0
	for _, inc := range cand {
		r.mu.RLock()
		age := now.Sub(inc.openedAt)
		idle := inc.NPUCalls == 0 && len(inc.Agents) == 0
		r.mu.RUnlock()
		switch {
		case fast[inc] && idle && age >= wait:
			r.markNeedsMoreData(inc, fmt.Sprintf("no new readings for %d min - the AI analysis could not start", int(age.Minutes())))
			n++
		case !active && age >= hard:
			r.failOverToRules(inc, fmt.Sprintf("analysis did not finish in %d min", int(age.Minutes())))
			n++
		}
	}
	return n
}

// markNeedsMoreData ends the "analysing" state of an incident whose AI cannot run for lack of data. The incident stays
// in r.fastInc, so the AI analysis (adoptFast) and its refine stages run when readings come back.
func (r *Reasoner) markNeedsMoreData(inc *Incident, why string) {
	r.mu.Lock()
	inc.State = "done"
	inc.DataStatus = "needs_more_data"
	inc.RefineNote = "insufficient data: " + why
	if inc.Final != nil && inc.Final.Preliminary {
		inc.Final.Note = "Rules report only - insufficient data for the AI analysis (" + why + ")."
	}
	if inc.Workflow == wfAnalysing || inc.Workflow == "" {
		inc.Workflow, inc.NeedsSince = wfNeeds, wfNow().Unix()
		inc.event("system", "needs_more_data", "", "", "", why)
	}
	r.mu.Unlock()
	r.log(inc, "Insufficient data: "+why+". The alert and the rules report stay; the AI analysis runs when readings return.")
	r.persist(inc)
}

// failOverToRules: a run that never finished becomes the rules report, ready for a decision (a person can rerun it).
func (r *Reasoner) failOverToRules(inc *Incident, why string) {
	if inc.Final == nil {
		r.preliminary(inc, r.retrievalPreliminary(inc))
	}
	r.mu.Lock()
	inc.State = "done_with_errors"
	if inc.Workflow == wfAnalysing || inc.Workflow == "" {
		inc.Workflow, inc.NeedsSince = wfNeeds, wfNow().Unix()
		inc.event("system", "watchdog", "", "", "", why)
	}
	r.mu.Unlock()
	r.log(inc, "Watchdog: "+why+"; showing the rules report.")
	r.persist(inc)
}
