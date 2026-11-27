package main

// Provisional early AI (2026-10-28, owner: "check if the 40 min delay in the AI report can be reduced"). Default OFF.
//
//	htpd_profile: ai_early_k=4                 abnormal readings before the provisional AI run (0/absent = off)
//	              ai_early_shapes=step,flatline shapes the gate-length study cleared at that k
//	              (spike, step, trend, flatline, noisy, fault, limit)
//
// When a sensor has been abnormal for ai_early_k readings with a cleared shape, the domain agents + reasoner run on
// that young window as refine stage "provisional" (UI badge). The incident is the fast-path incident when one is
// open, else a new one with the rules report; the normal persistReadings run then updates the same incident
// (adoptFast), and the 1.5 h / 3 h refinements follow as before. NPU priority: event-gate alerts and requested jobs
// first, provisional runs next, refinements last; a provisional run stops between NPU calls when an alert waits.

import (
	"context"
	"fmt"
	"strconv"
	"strings"
	"sync"
	"time"
)

var earlyCfg struct {
	sync.Mutex
	at     time.Time
	k      int
	shapes map[string]bool
}

// earlyAIConfig: (ai_early_k, allowed shapes), re-read from htpd_profile at most every 10 s.
func earlyAIConfig() (int, map[string]bool) {
	earlyCfg.Lock()
	defer earlyCfg.Unlock()
	if time.Since(earlyCfg.at) < 10*time.Second {
		return earlyCfg.k, earlyCfg.shapes
	}
	p := htpdProfile()
	k, _ := strconv.Atoi(strings.TrimSpace(p["ai_early_k"]))
	if k < 0 || k >= trigRules().AbnormalOfWindow {
		k = 0
	}
	sh := map[string]bool{}
	for _, s := range strings.Split(p["ai_early_shapes"], ",") {
		if s = strings.TrimSpace(s); s != "" {
			sh[s] = true
		}
	}
	earlyCfg.at, earlyCfg.k, earlyCfg.shapes = time.Now(), k, sh
	return k, sh
}

// shapeOf maps a rule finding to the gate-study shape families.
func shapeOf(f Finding) string {
	switch {
	case f.Pattern == "flatline":
		return "flatline"
	case f.Pattern == "erratic":
		return "noisy"
	case f.Status == "sensor_fault":
		return "fault"
	case f.Pattern == "spike" || f.Pattern == "dip":
		return "spike"
	case strings.HasPrefix(f.Pattern, "step"):
		return "step"
	case strings.HasPrefix(f.Pattern, "gradual") || f.Pattern == "exponential_increase":
		return "trend"
	case f.Status == "warning" || f.Status == "critical":
		// owner 2026-11-27: a value past its limit with no trend shape (board run: power factor 0.81 "stable" below
		// 0.85) still gets an early look; k=3 readings keep a single spike out
		return "limit"
	}
	return ""
}

func earlyShapeOK(f Finding, shapes map[string]bool) bool {
	s := shapeOf(f)
	return s != "" && shapes[s]
}

// earlyJob: a provisional AI run waiting for the NPU.
type earlyJob struct {
	inc   *Incident
	cands []Candidate
}

// queueEarly: the incident for a provisional run (the open fast-path incident, else a new rules-report incident that
// the persistReadings run will adopt) and its place in the NPU queue.
func (r *Reasoner) queueEarly(cands []Candidate) {
	if r.Mode == 1 {
		return // rules-only mode never calls the NPU
	}
	r.mu.Lock()
	if r.fastInc == nil {
		r.fastInc = map[string]*Incident{}
	}
	var inc *Incident
	for _, c := range cands {
		if f := r.fastInc[key(c.Node, c.Metric)]; f != nil {
			inc = f
			break
		}
	}
	r.mu.Unlock()
	if inc == nil {
		inc = r.newIncident(cands, r.Mode)
		rc := r.retrievalPreliminary(inc)
		r.mu.Lock()
		for _, c := range cands {
			r.fastInc[key(c.Node, c.Metric)] = inc
		}
		r.mu.Unlock()
		r.preliminary(inc, rc)
		r.persist(inc)
	}
	r.log(inc, fmt.Sprintf("Early look queued: %s abnormal on a young window (shape %s); the full reading follows at the AI gate, independently",
		cands[0].Node+" "+cands[0].Metric, shapeOf(cands[0].Finding)))
	r.mu.Lock()
	r.early = append(r.early, earlyJob{inc, cands})
	var w work
	start := !r.active && !r.coolWait
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

// runEarly: the provisional analysis on the young window. Skipped when the full analysis already took the incident.
func (r *Reasoner) runEarly(j earlyJob) {
	r.mu.Lock()
	still := false
	for _, c := range j.cands {
		if r.fastInc[key(c.Node, c.Metric)] == j.inc {
			still = true
		}
	}
	r.mu.Unlock()
	if !still {
		return
	}
	inc := j.inc
	fresh := r.buildIncident(j.cands, r.Mode)
	r.mu.Lock()
	inc.Sensors, inc.Roles, inc.Mode1 = fresh.Sensors, fresh.Roles, fresh.Mode1
	inc.State, inc.Agents = "running", nil
	inc.preempt = func() bool { r.mu.RLock(); defer r.mu.RUnlock(); return r.pending != nil }
	r.mu.Unlock()
	t0 := time.Now()
	ok := r.analyse(context.Background(), inc, r.Mode, t0, nil)
	r.mu.Lock()
	inc.preempt = nil
	inc.State = "done"
	if ok {
		inc.RefineStage = "provisional"
		inc.Revisions = append(inc.Revisions, revisionOf(inc, "provisional", j.cands[0].End, nil, inc.NPUCalls, float64(time.Since(t0).Milliseconds())))
	}
	r.mu.Unlock()
	if ok {
		r.log(inc, fmt.Sprintf("Early look ready (young window, %.1fs): a first idea to judge by; the full reading replaces it", time.Since(t0).Seconds()))
	} else {
		r.log(inc, "Early look stopped: an alert needed the NPU")
	}
	r.persist(inc)
}

// earlyUnconfirmedAfter: an early look whose sensors never reached the AI gate within this much sensor time closes
// itself (the gate needs persist_readings; the cooldown lets a slow episode still mature).
func earlyUnconfirmedAfter() int64 {
	tr := trigRules()
	return int64(tr.PersistReadings+tr.FastCooldown) * bucketSec
}

// closeUnconfirmedEarlyLocked (caller holds r.mu): owner 2026-11-27, an early look is a guess to judge; when the full
// reading never comes, the incident closes as "not confirmed" instead of waiting 3 days. Fast-path incidents
// (critical readings) are left alone.
func (r *Reasoner) closeUnconfirmedEarlyLocked(inc *Incident, sim int64, now time.Time) bool {
	if inc.RefineStage != "provisional" || inc.FastPath || inc.State != "done" || sim-inc.CreatedSim < earlyUnconfirmedAfter() {
		return false
	}
	if inc.Owner != "" && openSteps(inc) > 0 {
		return false
	}
	for k, f := range r.fastInc {
		if f == inc {
			delete(r.fastInc, k) // a later episode opens a new incident
		}
	}
	inc.Workflow, inc.Outcome, inc.ClosedAt, inc.ClosedBy = wfClosed, "no_action_needed", now.Unix(), "system"
	inc.OutcomeNote = "auto: early look not confirmed (the full reading never reached the AI gate)"
	if inc.Approval == "" || inc.Approval == "pending" {
		inc.Approval = "dismissed"
	}
	inc.event("system", "auto_closed", "", "no_action_needed", "auto", "early look not confirmed by the full reading")
	inc.Timeline = append(inc.Timeline, TimelineItem{nowTime().In(IST).Format("15:04:05"),
		"Early look not confirmed: the sensor did not reach the AI gate; closed automatically"})
	return true
}

// earlyEtaOf: for an early look, the soonest full-reading ETA among its flagged sensors (-1 = unknown / not early).
func earlyEtaOf(gw []gateWatch, inc *Incident) int64 {
	if inc.RefineStage != "provisional" {
		return -1
	}
	best := int64(-1)
	for _, s := range inc.Sensors {
		if s.Context {
			continue
		}
		for _, w := range gw {
			if w.Node == s.Node && w.Metric == s.Metric && (best < 0 || w.EtaS < best) {
				best = w.EtaS
			}
		}
	}
	return best
}
