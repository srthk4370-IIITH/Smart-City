package main

import (
	"strings"
	"testing"
)

// Escalation re-ask (promote.go HandleRises, engine riseRun): a reported domain sensor whose rule status rises above
// what was reported / what its agent said is re-asked once per level, through the promotion path.

func riseCandidate(t *testing.T, rg *refineRig, inc Incident, status string) Candidate {
	t.Helper()
	s := inc.Sensors[0]
	_, _, now := rg.eng.SimBase()
	xs, ok := rg.eng.WindowAt(s.Node, s.Metric, now)
	if !ok {
		t.Fatal("no window")
	}
	f := RuleFinding(s.Role, s.Metric, s.Node, xs, now)
	f.Status = status
	return Candidate{s.Node, s.Metric, s.Role, f, xs, now, false, false, false}
}

// agent said normal, rule rises to warning: one re-run, one revision, timeline entry; no re-run without a rise.
func TestEscalationReaskWhenRuleRisesAboveAgent(t *testing.T) {
	rg := newRefineRig(t)
	rg.answer("stable/normal")
	inc := rg.alert()
	first := rg.settle(inc.ID)
	revs := len(first.Revisions)

	c := riseCandidate(t, rg, first, "normal")
	rg.r.HandleRises([]Candidate{c}) // not risen: rule normal is not above the agent's normal
	got := rg.settle(inc.ID)
	if len(got.Revisions) != revs || len(rg.r.promos) != 0 {
		t.Fatalf("re-run without a rise: revisions %d -> %d", revs, len(got.Revisions))
	}

	rg.answer("step_increase/warning")
	rg.readings(2)
	c = riseCandidate(t, rg, first, "warning")
	rg.r.HandleRises([]Candidate{c})
	got = rg.settle(inc.ID)
	if len(rg.r.incidents) != 1 || len(got.Revisions) != revs+1 || got.Revisions[revs].Stage != "promotion" {
		t.Fatalf("revisions %d -> %d, incidents %d", revs, len(got.Revisions), len(rg.r.incidents))
	}
	ok := false
	for _, tl := range got.Timeline {
		ok = ok || (strings.Contains(tl.Msg, "rose to warning (agent had said normal): agent re-run, report updated"))
	}
	if !ok {
		t.Fatalf("no escalation timeline entry: %+v", got.Timeline)
	}
	if f := co2Finding(got); sevRank(f.Status) < 1 {
		t.Fatalf("agent not re-run: %+v", f)
	}
	// the agent now agrees: the same level does not ask again
	rg.r.HandleRises([]Candidate{c})
	if again := rg.settle(inc.ID); len(again.Revisions) != revs+1 {
		t.Fatalf("looped: revisions %d", len(again.Revisions))
	}
}

// engine side: 2 fresh readings above reportedSev emit exactly one rise; reportedSev follows so it does not loop.
func TestEngineEmitsRiseOnce(t *testing.T) {
	g := newGateRig(t)
	tg := g.inject(t, "ventilation_failure")[0]
	var rises []Candidate
	g.eng.onRise = func(c []Candidate) { rises = append(rises, c...) }
	k := key(tg.Node, tg.Metric)
	for i := 0; i < 120 && len(g.eventsFor(tg.Node, tg.Metric, 0)) == 0; i++ {
		g.ticks(1)
	}
	if len(g.eventsFor(tg.Node, tg.Metric, 0)) == 0 {
		t.Fatal("no event")
	}
	g.eng.mu.Lock()
	st := g.eng.states[k]
	st.reportedSev, st.riseRun = -1, 0 // reported one level below what the rules say now
	g.eng.mu.Unlock()
	g.ticks(1)
	if len(rises) != 0 {
		t.Fatal("rise after a single reading")
	}
	g.ticks(1)
	g.ticks(10)
	seen := map[int]int{}
	for _, c := range rises {
		seen[sevRank(c.Finding.Status)]++
	}
	if len(rises) == 0 {
		t.Fatal("no rise")
	}
	for r, n := range seen {
		if n != 1 {
			t.Fatalf("rank %d emitted %d times (loop)", r, n)
		}
	}
}
