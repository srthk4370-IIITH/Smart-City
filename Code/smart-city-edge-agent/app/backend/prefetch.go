package main

// Agents during the gate wait (owner 2026-11-27: "agents during the gate wait"; accuracy first).
//
// When a batch opens, the NPU usually sits idle for at least one reading (5 min) while the batch waits for related
// sensors. The opener's domain agent is run then, on the window it has at that moment ("prefetch"). At batch close the
// window has 1-3 newer readings, so the prefetched answer is NOT the same input as the real run. Hence two modes:
//
//	htpd_profile agent_prefetch=shadow  the prefetch runs, the real agent still runs at close, and the two answers are
//	                                    compared (pattern + status) and logged to state/prefetch_shadow.jsonl. No
//	                                    latency change; this is the evidence for "1".
//	htpd_profile agent_prefetch=1       reuse: at close, the prefetched answer replaces the agent call when the sensor's
//	                                    rule finding (status + pattern) is unchanged and the prefetch is <= 3 readings
//	                                    old (~3 s saved per reused agent). The incident log says so.
//	absent / 0                          off.
//
// One prefetch at a time, never while an analysis runs (htpd serves one request at a time; a prefetch can delay the
// first agent call of a new alert by one agent call, ~3 s, at most).

import (
	"context"
	"encoding/json"
	"fmt"
	"log"
	"os"
	"path/filepath"
	"sync"
	"time"
)

type pfEntry struct {
	End  int64
	Sig  string
	Call AgentCall
	At   time.Time
}

var pfS struct {
	sync.Mutex
	m map[string]pfEntry
}

var pfRun sync.Mutex

func prefetchMode() string {
	switch profStr("agent_prefetch") {
	case "shadow":
		return "shadow"
	case "1", "on", "reuse":
		return "reuse"
	}
	return ""
}

func pfSig(f Finding) string { return f.Status + "/" + f.Pattern }

// PrefetchAgent: engine hook (Engine.OnBatchOpen), called in its own goroutine.
func (r *Reasoner) PrefetchAgent(c Candidate) {
	if prefetchMode() == "" || r == nil || r.genie == nil || r.eng == nil {
		return
	}
	// night sweep 2026-11-27 #104: a sensor that matures inside an open batch while an analysis runs used to be
	// dropped for good (the engine hands each sensor over once). Now it waits for the NPU to free up, as long as
	// the batch has not closed on it yet (then the real agent run makes the prefetch pointless).
	if !r.pfWaitIdle(c, pfIdleWait) {
		return
	}
	pfRun.Lock() // one prefetch at a time; the others wait their turn (a batch may mature several sensors at once)
	defer pfRun.Unlock()
	if !r.pfWaitIdle(c, pfIdleWait) {
		return
	}
	thermalYield(context.Background(), "prefetch", thermalYieldMax) // #88: non-urgent NPU work waits for a hot NPU to cool

	s := r.sensorRef("S1", c, "")
	ai, ok := r.agentPrompt(s)
	if !ok {
		return
	}
	inc := &Incident{ID: "PREFETCH", Sensors: []SensorRef{s}, quiet: true}
	am := r.genie.AgentModel()
	ctx, cancel := context.WithTimeout(context.Background(), 2*time.Minute)
	defer cancel()
	var res GenieResult
	agPrompt := ai.Prompt + AgentPrefill
	t0 := time.Now()
	if agentTools() {
		res, agPrompt = r.runAgentTools(ctx, inc, s, am, ai, false, true)
	} else {
		res = r.genie.Run(ctx, am, ai.Prompt+AgentPrefill, AgentPrefill, 90*time.Second, nil)
		res.Text = AgentPrefill + res.Text
	}
	if res.Error != "" {
		return
	}
	call := checkAgentWin(s, res, agPrompt, ai.Xs, ai.HVRule)
	call.CallMetrics = metricsOf(res)
	applyConfidenceRecal(&call, s.End, ai.Prompt)
	if !call.Valid || call.Parsed == nil {
		return
	}
	pfS.Lock()
	if pfS.m == nil {
		pfS.m = map[string]pfEntry{}
	}
	pfS.m[key(c.Node, c.Metric)] = pfEntry{End: c.End, Sig: pfSig(c.Finding), Call: call, At: time.Now()}
	pfS.Unlock()
	log.Printf("prefetch: %s %s agent done in %.1fs during the gate wait (%s): %s/%s", c.Node, c.Metric,
		time.Since(t0).Seconds(), prefetchMode(), call.Parsed.Pattern, call.Parsed.Status)
}

var (
	pfIdleWait = 10 * time.Minute // longest a matured sensor waits for a running analysis to finish
	pfPoll     = 5 * time.Second
)

// pfWaitIdle waits (bounded) until no analysis runs; false when the wait ran out or the sensor already alerted
// (its batch closed and the real agent ran, or runs, on it).
func (r *Reasoner) pfWaitIdle(c Candidate, max time.Duration) bool {
	t0 := time.Now()
	for {
		r.mu.RLock()
		busy := r.active
		r.mu.RUnlock()
		if r.eng != nil {
			r.eng.mu.RLock()
			st := r.eng.states[key(c.Node, c.Metric)]
			alerted := st != nil && st.alerted
			r.eng.mu.RUnlock()
			if alerted {
				return false
			}
		}
		if !busy {
			return true
		}
		if time.Since(t0) >= max {
			return false
		}
		time.Sleep(pfPoll)
	}
}

// prefetchTake: the prefetched answer for sensor s when it may be reused (mode reuse, same rule finding, <= 3
// readings old); the entry is consumed either way so a stale one never lingers.
func prefetchTake(s SensorRef) (AgentCall, pfEntry, bool) {
	pfS.Lock()
	e, ok := pfS.m[key(s.Node, s.Metric)]
	if ok {
		delete(pfS.m, key(s.Node, s.Metric))
	}
	pfS.Unlock()
	if !ok || s.End < e.End || s.End-e.End > 3*bucketSec || time.Since(e.At) > 30*time.Minute {
		return AgentCall{}, e, false
	}
	return e.Call, e, true
}

// prefetchShadowLog: compare the real agent answer with the prefetched one (shadow mode evidence).
func (r *Reasoner) prefetchShadowLog(inc *Incident, s SensorRef, e pfEntry, real AgentCall) {
	if e.Call.Parsed == nil || real.Parsed == nil {
		return
	}
	agree := e.Call.Parsed.Status == real.Parsed.Status && e.Call.Parsed.Pattern == real.Parsed.Pattern
	row := map[string]any{"t": nowTime().Unix(), "incident": inc.ID, "sensor": s.Node + "/" + s.Metric,
		"readings_newer": (s.End - e.End) / bucketSec, "rule_same": pfSig(s.Rule) == e.Sig,
		"prefetch": e.Call.Parsed.Pattern + "/" + e.Call.Parsed.Status, "real": real.Parsed.Pattern + "/" + real.Parsed.Status,
		"agree": agree, "prefetch_conf": e.Call.Parsed.Confidence, "real_conf": real.Parsed.Confidence}
	b, _ := json.Marshal(row)
	if r.store != "" {
		if f, err := os.OpenFile(filepath.Join(filepath.Dir(r.store), "prefetch_shadow.jsonl"), os.O_APPEND|os.O_CREATE|os.O_WRONLY, 0o644); err == nil {
			f.Write(append(b, '\n'))
			f.Close()
		}
	}
	r.log(inc, fmt.Sprintf("Prefetch shadow: the answer from the gate wait (%d reading(s) older) %s the real agent (%s vs %s)",
		(s.End-e.End)/bucketSec, map[bool]string{true: "agrees with", false: "differs from"}[agree], row["prefetch"], row["real"]))
}
