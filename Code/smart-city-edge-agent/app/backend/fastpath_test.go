package main

import (
	"math"
	"testing"
)

// Critical fast path (fastpath.go): a measured indoor-CO2 feed (critical limit 1500 ppm), one reading per 5-min bucket.

type fpEvent struct {
	reading int // 1-based index of the scenario reading at which the engine emitted the candidate
	c       Candidate
}

// feedCO2 drives dqNode/dqMetric with base for nBase readings, then the scenario values; returns the candidates
// for that sensor with the scenario reading index they were emitted at (0 = during the baseline).
func feedCO2(t *testing.T, e *Engine, nBase int, base float64, vals []float64) []fpEvent {
	t.Helper()
	var out []fpEvent
	cur := 0
	e.onEvent = func(cs []Candidate) {
		for _, c := range cs {
			if c.Node == dqNode && c.Metric == dqMetric {
				out = append(out, fpEvent{cur, c})
			}
		}
	}
	wall := int64(2_000_000_000)
	step := func(v float64) {
		wall += bucketSec
		if _, err := e.IngestReading(Reading{Node: dqNode, Metric: dqMetric, Value: fp(v), Ts: float64(wall)}, wall); err != nil {
			t.Fatal(err)
		}
		e.Tick()
	}
	for i := 0; i < nBase; i++ {
		step(base + 6*math.Sin(float64(i))) // a live sensor wobbles; an exactly constant feed is a flatline fault
	}
	for i, v := range vals {
		cur = i + 1
		step(v + 2*math.Sin(float64(i)))
	}
	return out
}

func fpSplit(ev []fpEvent) (fast, ai []fpEvent) {
	for _, x := range ev {
		if x.c.Fast {
			fast = append(fast, x)
		} else {
			ai = append(ai, x)
		}
	}
	return
}

func rep(v float64, n int) []float64 {
	out := make([]float64, n)
	for i := range out {
		out[i] = v
	}
	return out
}

// A critical step: the incident opens at the 2nd critical reading (rules-only preliminary report), the AI runs at
// persistReadings and updates THAT incident - one incident in total.
func TestFastPathCriticalStep(t *testing.T) {
	e := dqEngine(t)
	ev := feedCO2(t, e, 60, 600, rep(1800, 14))
	fast, ai := fpSplit(ev)
	if len(fast) != 1 || fast[0].reading != fastReadings {
		t.Fatalf("fast path: %+v, want one candidate at reading %d", fast, fastReadings)
	}
	if fast[0].c.Finding.Status != "critical" {
		t.Fatalf("fast candidate status %s", fast[0].c.Finding.Status)
	}
	if len(ai) != 1 || ai[0].reading < persistReadings || ai[0].reading > persistReadings+batchReadings {
		t.Fatalf("AI gate: %+v, want one candidate at reading %d..%d", ai, persistReadings, persistReadings+batchReadings)
	}
	dir := t.TempDir()
	r := NewReasoner(NewGenieRunner(dir, dir, true), e, dir, func(string, any) {})
	r.Mode = 1
	if rest := r.splitFast([]Candidate{fast[0].c}); len(rest) != 0 {
		t.Fatal("fast candidate passed on to the AI queue")
	}
	if len(r.incidents) != 1 || !r.incidents[0].FastPath || r.incidents[0].Final == nil || !r.incidents[0].Final.Preliminary ||
		r.incidents[0].Severity != "critical" {
		t.Fatalf("fast incident not opened with a preliminary critical report: %+v", r.incidents)
	}
	id := r.incidents[0].ID
	inc := r.Process([]Candidate{ai[0].c}, 1)
	if len(r.incidents) != 1 || inc.ID != id {
		t.Fatalf("AI analysis opened a second incident (%d incidents, %s vs %s)", len(r.incidents), inc.ID, id)
	}
	if len(r.fastInc) != 0 {
		t.Fatal("fast incident still pending after the AI analysis")
	}
}

// A warning-only drift (never beyond the critical limit) keeps today's behaviour: no fast path, AI at persistReadings.
func TestFastPathWarningDriftUnchanged(t *testing.T) {
	e := dqEngine(t)
	var vals []float64
	for i := 1; i <= 16; i++ {
		vals = append(vals, 1000+20*float64(i)) // 1020 .. 1320 ppm: warning (>= 1000), never critical (1500)
	}
	fast, ai := fpSplit(feedCO2(t, e, 60, 600, vals))
	if len(fast) != 0 {
		t.Fatalf("warning drift took the fast path: %+v", fast)
	}
	if len(ai) != 1 || ai[0].reading < persistReadings {
		t.Fatalf("AI gate: %+v, want one candidate at >= %d readings", ai, persistReadings)
	}
}

// Chatter at the critical limit: single readings above it never open a fast incident, and one episode opens at most one.
func TestFastPathDeadbandChatter(t *testing.T) {
	e := dqEngine(t)
	var alt []float64
	for i := 0; i < 8; i++ {
		alt = append(alt, 1510, 1490) // never 2 critical readings in a row
	}
	fast, _ := fpSplit(feedCO2(t, e, 60, 600, alt))
	if len(fast) != 0 {
		t.Fatalf("alternating chatter at the limit opened a fast incident: %+v", fast)
	}
	e2 := dqEngine(t)
	var pairs []float64
	for i := 0; i < 5; i++ {
		pairs = append(pairs, 1510, 1510, 1490) // repeated 2-reading critical runs inside one episode
	}
	fast, _ = fpSplit(feedCO2(t, e2, 60, 600, pairs))
	if len(fast) != 1 {
		t.Fatalf("one chattering episode opened %d fast incidents, want 1", len(fast))
	}
}
