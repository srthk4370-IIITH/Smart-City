package main

import "testing"

// chaos.py 2026-10-27 injected crowded_room, then ventilation_failure 3 min later WITHOUT a clear. Both hold the
// KH03 CO2 node (crowded_room falls back to SR-AQ-KH03-03); the stacked held ramp masked the exponential rise and
// no ventilation incident opened (the run picked an unrelated occupancy incident 566 s later instead).
// Now the held ventilation injection supersedes the old one and the CO2 rises to critical. It still opens no NEW
// incident: the sensor's reported episode never cleared, so by design the escalation belongs to the open
// incident's refinements (refine.go), not to a second incident. chaos.py now clears + resets between scenarios.
func TestVentilationAfterHeldCrowdedRoom(t *testing.T) {
	g := newGateRig(t)
	g.inject(t, "crowded_room")
	g.ticks(60)
	before := len(g.events)
	tg := g.inject(t, "ventilation_failure")[0]
	n := 0
	for _, in := range g.eng.injects {
		if in.Node == tg.Node && in.Metric == tg.Metric {
			n++
		}
	}
	if n != 1 {
		t.Fatalf("%d injections on %s %s after ventilation_failure, want 1 (superseded)", n, tg.Node, tg.Metric)
	}
	g.ticks(40)
	if st := g.eng.states[key(tg.Node, tg.Metric)]; st == nil || st.Status != "critical" {
		t.Fatalf("ventilation_failure after a held crowded_room: CO2 status %v, want critical", st)
	}
	if ev := g.eventsFor(tg.Node, tg.Metric, before); len(ev) != 0 {
		t.Fatalf("escalation on an open reported episode opened %d new incident(s), want 0 (refinements own it)", len(ev))
	}
}
