package main

import (
	"os"
	"path/filepath"
	"testing"
)

// Event-gate regression tests for the load_surge scenario (a 2-reading +30 kW spike on a room meter).
// It never raised an incident in refine_check.py (proofs/2026-10-21_v2_app/refine_console.txt), which
// injects scenarios back to back WITHOUT a reset: power_throttling holds the same meter (SR-EM-KH04-01;
// SR-EM-KH04-02 is not a live sensor) and its reported episode never returned to normal, so the gate
// absorbed the new spike into the old episode.

func scenarioByID(t *testing.T, id string) Scenario {
	t.Helper()
	for _, sc := range Scenarios {
		if sc.ID == id {
			return sc
		}
	}
	t.Fatalf("no scenario %s", id)
	return Scenario{}
}

type gateRig struct {
	eng    *Engine
	events []Candidate
}

func newGateRig(t *testing.T) *gateRig {
	t.Helper()
	cool := filepath.Join(t.TempDir(), "thermal")
	os.WriteFile(cool, []byte("cool"), 0o644)
	t.Setenv("SCE_THERMAL_FAKE", cool)
	eng, err := NewEngine("../device")
	if err != nil {
		t.Fatal(err)
	}
	g := &gateRig{eng: eng}
	eng.onEvent = func(c []Candidate) { g.events = append(g.events, c...) }
	g.ticks(3)
	return g
}

func (g *gateRig) ticks(n int) {
	for i := 0; i < n; i++ {
		g.eng.Tick()
	}
}

// inject mirrors /api/inject: PickTargets, then Inject. Returns the picked targets.
func (g *gateRig) inject(t *testing.T, id string) []Target {
	sc := scenarioByID(t, id)
	sc.Targets = g.eng.PickTargets(sc.Targets)
	g.eng.Inject(sc)
	return sc.Targets
}

// eventsFor returns the gated events for node/metric from event index from on.
func (g *gateRig) eventsFor(node, metric string, from int) []Candidate {
	var out []Candidate
	for _, c := range g.events[from:] {
		if c.Node == node && c.Metric == metric {
			out = append(out, c)
		}
	}
	return out
}

func checkSurge(t *testing.T, c Candidate) {
	t.Helper()
	if c.Finding.Pattern != "spike" || (c.Finding.Status != "warning" && c.Finding.Status != "critical") {
		t.Fatalf("load surge reported as %s/%s, want spike/warning|critical", c.Finding.Pattern, c.Finding.Status)
	}
}

func TestLoadSurgeRaisesEvent(t *testing.T) {
	g := newGateRig(t)
	tg := g.inject(t, "load_surge")[0]
	if tg.Node != "SR-EM-KH04-01" {
		t.Fatalf("load_surge picked %s, want the live room meter SR-EM-KH04-01", tg.Node)
	}
	g.ticks(30) // spike at readings 5-6, +8 readings persistence, +batch
	ev := g.eventsFor(tg.Node, tg.Metric, 0)
	if len(ev) != 1 {
		t.Fatalf("load surge: %d events within 30 readings, want 1", len(ev))
	}
	checkSurge(t, ev[0])
	g.ticks(120)
	if n := len(g.eventsFor(tg.Node, tg.Metric, 0)); n != 1 {
		t.Fatalf("load surge re-alerted: %d events, want 1", n)
	}
}

// The refine_check.py sequence: power_throttling held on the same meter, then load_surge, no reset/clear.
func TestLoadSurgeOnReportedThrottle(t *testing.T) {
	g := newGateRig(t)
	th := g.inject(t, "power_throttling")[0]
	g.ticks(50)
	if n := len(g.eventsFor(th.Node, th.Metric, 0)); n != 1 {
		t.Fatalf("power_throttling: %d events, want 1", n)
	}
	before := len(g.events)
	tg := g.inject(t, "load_surge")[0]
	if tg.Node != th.Node {
		t.Fatalf("test premise: load_surge picked %s, throttling ran on %s", tg.Node, th.Node)
	}
	g.ticks(30)
	ev := g.eventsFor(tg.Node, tg.Metric, before)
	if len(ev) != 1 {
		t.Fatalf("load surge on a reported, still-held throttle: %d events within 30 readings, want 1", len(ev))
	}
	checkSurge(t, ev[0])
	g.ticks(170)
	if n := len(g.eventsFor(tg.Node, tg.Metric, before)); n != 1 {
		t.Fatalf("load surge re-alerted: %d events, want 1", n)
	}
}

// A held event must stay ONE incident while its old onset slides out of the 4 h window (an exponential
// rise leaving the window reads as a narrow dip at the window start - not a new transient).
func TestHeldEventsDoNotReAlert(t *testing.T) {
	for _, id := range []string{"ventilation_failure", "power_throttling", "tank_leak", "pump_cycling", "stuck_sensor"} {
		g := newGateRig(t)
		tg := g.inject(t, id)[0]
		g.ticks(200)
		if n := len(g.eventsFor(tg.Node, tg.Metric, 0)); n != 1 {
			t.Errorf("%s held for 200 readings: %d events on %s %s, want 1", id, n, tg.Node, tg.Metric)
		}
	}
}

func TestCalmBoardNoEvents(t *testing.T) {
	g := newGateRig(t)
	g.ticks(600)
	if len(g.events) != 0 {
		c := g.events[0]
		t.Fatalf("calm board raised %d events, first %s %s %s/%s", len(g.events), c.Node, c.Metric, c.Finding.Pattern, c.Finding.Status)
	}
}

func TestNewTransient(t *testing.T) {
	const end = int64(1_000_000_200)
	flat := func(v float64) []float64 {
		xs := make([]float64, Window)
		for i := range xs {
			xs[i] = v
		}
		return xs
	}
	at := func(i int) int64 { return end - int64(Window-1-i)*bucketSec }
	xs := flat(3)
	xs[30], xs[31] = 33, 33
	if !newTransient("spike", xs, end, at(29)) {
		t.Error("2-reading spike after the report: want a new transient")
	}
	if newTransient("spike", xs, end, at(30)) {
		t.Error("spike that began at/before the report is the reported event")
	}
	if newTransient("step_increase", xs, end, 0) {
		t.Error("only spike/dip patterns are transients")
	}
	xs = flat(3)
	for i := 20; i < 26; i++ {
		xs[i] = 33
	}
	if newTransient("spike", xs, end, 0) {
		t.Error("a 6-reading excursion (released hold) is not a transient")
	}
	xs = flat(1750)
	xs[0], xs[1] = 900, 1300 // tail of an old rise leaving the window
	if newTransient("dip", xs, end, 0) {
		t.Error("an old event's tail at the window start is not a new transient")
	}
}
