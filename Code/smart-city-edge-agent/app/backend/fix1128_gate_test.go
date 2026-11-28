package main

// Night sweep 2026-11-27 workstream A (engine / gate): #1 #41 #43 #55 #59 #77 #78 #80 #84 #95 #105 #109 #110.

import (
	"math"
	"os"
	"path/filepath"
	"strings"
	"testing"
	"time"
)

const (
	gtPH   = "WM-WD-KH98-00|ph"
	gtCO2  = "SR-AQ-KH03-03|co2"
	gtTemp = "SR-AQ-KH03-03|temp"
	gtTDS  = "WM-WD-KH98-00|tds"
)

// gtFeed drives several measured feeds one reading per tick. vals[k](i) is the value of sensor k at scenario reading i
// (i <= 0: baseline). It returns every candidate with the scenario reading it was emitted at.
type gtEv struct {
	reading int
	c       Candidate
}

func gtFeed(t *testing.T, e *Engine, nBase, n int, vals map[string]func(i int) float64, each func(i int)) []gtEv {
	t.Helper()
	var out []gtEv
	cur := 0
	e.onEvent = func(cs []Candidate) {
		for _, c := range cs {
			out = append(out, gtEv{cur, c})
		}
	}
	wall := int64(2_000_000_000)
	for i := -nBase + 1; i <= n; i++ {
		cur = i
		wall += bucketSec
		for k, f := range vals {
			p := strings.SplitN(k, "|", 2)
			if _, err := e.IngestReading(Reading{Node: p[0], Metric: p[1], Value: fp(f(i)), Ts: float64(wall)}, wall); err != nil {
				t.Fatal(err)
			}
		}
		e.Tick()
		if each != nil && i > 0 {
			each(i)
		}
	}
	return out
}

func gtWobble(base, amp float64) func(int) float64 {
	return func(i int) float64 { return base + amp*math.Sin(float64(i)) }
}

// first gate (AI batch) candidate of sensor k at or after reading from; 0 = none
func gtGate(ev []gtEv, k string, from int) int {
	for _, x := range ev {
		if key(x.c.Node, x.c.Metric) == k && !x.c.Fast && !x.c.Early && x.reading >= from {
			return x.reading
		}
	}
	return 0
}

// #77: a sensor whose current reading is normal (two-reading CO2 spike, back to normal) must not hold the batch of a
// maturing pH warning in the same building.
func TestGateNormalAgainSensorDoesNotHold(t *testing.T) {
	e := dqEngine(t)
	ev := gtFeed(t, e, 60, 14, map[string]func(int) float64{
		gtPH: func(i int) float64 {
			if i >= 1 {
				return 8.7 + 0.01*math.Sin(float64(i)) // warning (8.5..9.0)
			}
			return 7.2 + 0.03*math.Sin(float64(i))
		},
		gtCO2: func(i int) float64 {
			if i == 1 || i == 2 {
				return 2600
			}
			return 600 + 6*math.Sin(float64(i))
		},
	}, nil)
	got := gtGate(ev, gtPH, 1)
	if got == 0 || got > defaultAbnormalOfWindow+1 {
		t.Fatalf("pH gate candidate at reading %d, want <= %d (the normal-again CO2 spike must not hold the batch)", got, defaultAbnormalOfWindow+1)
	}
	if r := gtGate(ev, gtCO2, 1); r != 0 && r <= got {
		t.Errorf("the normal-again CO2 spike was reported with the pH batch (reading %d)", r)
	}
}

// #77 + #78 + #84: a mature temperature warning waits for a young CO2 sensor that is abnormal NOW (the gate view names
// it); when the temperature then goes critical the fast path opens its incident and the batch closes at once.
func TestGateCriticalMemberLeavesAtOnce(t *testing.T) {
	e := dqEngine(t)
	var heldBy string
	var waitEta int64 = -1
	var waiting []string
	ev := gtFeed(t, e, 60, 12, map[string]func(int) float64{
		gtTemp: func(i int) float64 {
			switch {
			case i >= 7:
				return 35 + 0.05*math.Sin(float64(i)) // critical (>= 34)
			case i >= 1:
				return 31 + 0.05*math.Sin(float64(i)) // warning
			}
			return 25 + 0.1*math.Sin(float64(i))
		},
		gtCO2: func(i int) float64 {
			if i >= 4 {
				return 1200 + 5*math.Sin(float64(i)) // warning, starts 3 readings later: young while temp matures
			}
			return 600 + 6*math.Sin(float64(i))
		},
	}, func(i int) {
		if i != 5 {
			return
		}
		g := e.GateView()
		for _, w := range g["watching"].([]gateWatch) {
			if w.Node+"|"+w.Metric == gtTemp {
				heldBy, waitEta = w.HeldBy, w.EtaS
			}
		}
		if b, ok := g["batch"].(map[string]any); ok {
			waiting, _ = b["waiting_for"].([]string)
		}
	})
	if heldBy != keySite(gtCO2) || waitEta <= 0 {
		t.Errorf("gate view at reading 5: held_by %q eta %d, want the young CO2 and a real wait", heldBy, waitEta)
	}
	if len(waiting) != 1 || waiting[0] != keySite(gtCO2) {
		t.Errorf("batch waiting_for %v", waiting)
	}
	if g := gtGate(ev, gtTemp, 1); g != 7 {
		t.Errorf("temperature gate candidate at reading %d, want 7 (its first critical reading closes the batch)", g)
	}
}

// #78: the fast path fires after maturity too. The temperature (KH) is mature but waits for its own young CO2, unrelated
// to the open pH batch (other building, other domain); it then goes critical: the fast path opens its incident.
func TestFastPathAfterMaturity(t *testing.T) {
	cfg := &SiteConfig{Nodes: []SiteNode{
		{ID: "campus", Kind: "campus"},
		{ID: "KH", Kind: "building", Parent: "campus"}, {ID: "WT", Kind: "building", Parent: "campus"},
		{ID: "SR-AQ-KH03-03", Kind: "equipment", Parent: "KH"}, {ID: "WM-WD-KH98-00", Kind: "equipment", Parent: "WT"},
		{ID: "SR-AQ-KH03-03/temp", Kind: "sensor", Parent: "SR-AQ-KH03-03"}, {ID: "SR-AQ-KH03-03/co2", Kind: "sensor", Parent: "SR-AQ-KH03-03"},
		{ID: "WM-WD-KH98-00/ph", Kind: "sensor", Parent: "WM-WD-KH98-00"}, {ID: "WM-WD-KH98-00/tds", Kind: "sensor", Parent: "WM-WD-KH98-00"},
	}}
	old := siteS
	siteS = &siteStore{cfg: cfg, ix: NewSiteIndex(cfg)}
	t.Cleanup(func() { siteS = old })
	e := dqEngine(t)
	step := func(from int, base, amp, v float64) func(int) float64 {
		return func(i int) float64 {
			if i >= from {
				return v + amp*0.2*math.Sin(float64(i))
			}
			return base + amp*math.Sin(float64(i))
		}
	}
	ev := gtFeed(t, e, 60, 9, map[string]func(int) float64{
		gtPH:  step(1, 7.2, 0.03, 8.7),
		gtTDS: step(4, 150, 2, 600),
		gtCO2: step(4, 600, 6, 1200),
		gtTemp: func(i int) float64 {
			switch {
			case i >= 5:
				return 35 + 0.05*math.Sin(float64(i))
			case i >= 2:
				return 31 + 0.05*math.Sin(float64(i))
			}
			return 25 + 0.1*math.Sin(float64(i))
		},
	}, nil)
	fastAt := 0
	for _, x := range ev {
		if x.c.Fast && key(x.c.Node, x.c.Metric) == gtTemp && fastAt == 0 {
			fastAt = x.reading
		}
	}
	if fastAt != 6 {
		t.Fatalf("temperature fast path at reading %d, want 6 (2nd critical reading, after maturity)", fastAt)
	}
}

// #109: an impossible CO2 value (below the physical floor, status sensor_fault) counts toward the gate whatever the
// window shape (an earlier spike made it "spike").
func TestGateSensorFaultCountsWhateverPattern(t *testing.T) {
	e := dqEngine(t)
	sawSpike := false
	ev := gtFeed(t, e, 60, 26, map[string]func(int) float64{
		gtCO2: func(i int) float64 {
			switch {
			case i == 1 || i == 2:
				return 2600
			case i >= 15:
				return 300 + 2*math.Sin(float64(i))
			}
			return 450 + 6*math.Sin(float64(i))
		},
	}, func(i int) {
		if st := stateOf(e, dqNode, dqMetric); i >= 15 && st.Pattern == "spike" && st.Status == "sensor_fault" {
			sawSpike = true
		}
	})
	g := gtGate(ev, gtCO2, 15)
	if g == 0 || g > 15+defaultAbnormalOfWindow+1 {
		t.Fatalf("impossible CO2 gate candidate at reading %d (spike-shaped window seen: %v)", g, sawSpike)
	}
	t.Logf("spike-shaped sensor_fault window seen: %v; gate at reading %d", sawSpike, g)
}

// #55: no early look once the fast path opened an incident in the episode.
func TestNoEarlyLookAfterFastPath(t *testing.T) {
	earlyProfile(t, "ai_early_k=3\nai_early_shapes=step,limit,trend,spike\n")
	e := dqEngine(t)
	ev := gtFeed(t, e, 60, 8, map[string]func(int) float64{
		gtPH: func(i int) float64 {
			if i >= 1 {
				return 9.6 + 0.02*math.Sin(float64(i))
			}
			return 7.2 + 0.03*math.Sin(float64(i))
		},
	}, nil)
	fast, early := 0, 0
	for _, x := range ev {
		if key(x.c.Node, x.c.Metric) != gtPH {
			continue
		}
		if x.c.Fast {
			fast++
		}
		if x.c.Early {
			early++
		}
	}
	if fast != 1 || early != 0 {
		t.Fatalf("fast %d early %d, want 1 and 0", fast, early)
	}
	// reasoner side: an early candidate for a sensor whose fast incident lost its mapping (short-window run) opens nothing
	dir := t.TempDir()
	r := NewReasoner(NewGenieRunner(dir, dir, true), e, dir, func(string, any) {})
	r.active = true
	c := ev[0].c
	for _, x := range ev {
		if x.c.Fast {
			c = x.c
		}
	}
	r.splitFast([]Candidate{c})
	if len(r.incidents) != 1 {
		t.Fatalf("%d incidents after the fast path", len(r.incidents))
	}
	r.mu.Lock()
	r.incidents[0].State = "done"
	delete(r.fastInc, key(c.Node, c.Metric))
	r.mu.Unlock()
	ec := c
	ec.Fast, ec.Early = false, true
	r.splitFast([]Candidate{ec})
	if len(r.incidents) != 1 || len(r.early) != 0 {
		t.Fatalf("early look made %d incidents, %d early jobs", len(r.incidents), len(r.early))
	}
}

// #59: early looks in different buildings and domains are separate incidents.
func TestEarlyLooksSplitByBuilding(t *testing.T) {
	cfg := &SiteConfig{Nodes: []SiteNode{
		{ID: "campus", Kind: "campus"},
		{ID: "KH", Kind: "building", Parent: "campus"}, {ID: "SB", Kind: "building", Parent: "campus"},
		{ID: "KH/L03", Kind: "floor", Parent: "KH"}, {ID: "SB/L00", Kind: "floor", Parent: "SB"},
		{ID: "SR-AQ-KH03-03", Kind: "equipment", Parent: "KH/L03"}, {ID: "EM-CR-SB00-00", Kind: "equipment", Parent: "SB/L00"},
		{ID: "SR-AQ-KH03-03/temp", Kind: "sensor", Parent: "SR-AQ-KH03-03"}, {ID: "EM-CR-SB00-00/pf", Kind: "sensor", Parent: "EM-CR-SB00-00"},
	}}
	old := siteS
	siteS = &siteStore{cfg: cfg, ix: NewSiteIndex(cfg)}
	t.Cleanup(func() { siteS = old })
	e := dqEngine(t)
	dir := t.TempDir()
	r := NewReasoner(NewGenieRunner(dir, dir, true), e, dir, func(string, any) {})
	r.active = true
	xs := rep(31, Window)
	a := Candidate{Node: "SR-AQ-KH03-03", Metric: "temp", Role: "air_quality", Finding: Finding{Pattern: "step_increase", Status: "warning"}, Xs: xs, End: 1000, Early: true}
	b := Candidate{Node: "EM-CR-SB00-00", Metric: "pf", Role: "power", Finding: Finding{Pattern: "stable", Status: "warning"}, Xs: rep(0.8, Window), End: 1000, Early: true}
	r.splitFast([]Candidate{a, b})
	if len(r.incidents) != 2 || len(r.early) != 2 || r.early[0].inc == r.early[1].inc {
		t.Fatalf("%d incidents, %d early jobs: want two separate early looks", len(r.incidents), len(r.early))
	}
}

// #80: a measured feed repeating exactly the same value for 30 min is a stuck sensor; a live wobble is not.
func TestExactConstantFaultsAt30Min(t *testing.T) {
	e := dqEngine(t)
	var at int
	gtFeed(t, e, 60, 12, map[string]func(int) float64{
		gtTDS: func(i int) float64 {
			if i >= 1 {
				return 152
			}
			return 150 + 2*math.Sin(float64(i))
		},
	}, func(i int) {
		if st := stateOf(e, "WM-WD-KH98-00", "tds"); at == 0 && st.Status == "sensor_fault" {
			at = i
		}
	})
	if at == 0 || at > exactConstantMin {
		t.Fatalf("stuck TDS flagged at reading %d, want by %d", at, exactConstantMin)
	}
}

// #110 + #95: now_status follows the current reading; the window keeps the event; the fact line says when it ended.
func TestNowStatusAndReturnedToNormal(t *testing.T) {
	e := dqEngine(t)
	gtFeed(t, e, 60, 12, map[string]func(int) float64{
		gtPH: func(i int) float64 {
			if i >= 1 && i <= 8 {
				return 9.6 + 0.02*math.Sin(float64(i))
			}
			return 7.2 + 0.03*math.Sin(float64(i))
		},
	}, func(i int) {
		st := stateOf(e, "WM-WD-KH98-00", "ph")
		if i == 4 && st.NowStatus != "critical" {
			t.Errorf("reading 4: now_status %q", st.NowStatus)
		}
	})
	st := stateOf(e, "WM-WD-KH98-00", "ph")
	if st.NowStatus != "normal" {
		t.Errorf("recovered pH now_status %q (window status %q)", st.NowStatus, st.Status)
	}
	_, _, sim := e.SimBase()
	f := e.ReturnedToNormalFact("WM-WD-KH98-00", "ph", sim)
	want := "returned to normal at " + time.Unix(sim-3*bucketSec, 0).In(IST).Format("15:04") + " after 8 abnormal readings"
	if f != want {
		t.Errorf("fact %q, want %q", f, want)
	}
	if f := returnedToNormalFact("water", "ph", "", []float64{7, 9.6, 9.6}, 0); f != "" {
		t.Errorf("still abnormal: %q", f)
	}
}

// #105: one staleness rule.
func TestSensorStaleOneRule(t *testing.T) {
	if sensorStale(1000, 1000+2*bucketSec) || !sensorStale(1000, 1000+3*bucketSec) || !sensorStale(0, 5) {
		t.Fatal("sensorStale: stale after 3 missed readings")
	}
	st := SensorState{Last: fp(1), DataOK: true, Status: "normal", Updated: 1000}
	if staleSensor(st, 1000+2*bucketSec) || !staleSensor(st, 1000+3*bucketSec) {
		t.Error("domain health uses another rule")
	}
	if nowStatusOf(&st, 1000+3*bucketSec) != "no_data" {
		t.Error("a stale reading has now_status no_data")
	}
}

// #43: a panic inside the engine tick or the workflow tick does not leave the lock held.
func TestTickPanicReleasesLocks(t *testing.T) {
	e := dqEngine(t)
	e.mu.Lock()
	e.states["boom|x"] = nil // detect dereferences it
	e.mu.Unlock()
	safeIter("tick", e.Tick)
	if !e.mu.TryLock() {
		t.Fatal("engine lock still held after a recovered panic")
	}
	delete(e.states, "boom|x")
	e.mu.Unlock()
	dir := t.TempDir()
	r := NewReasoner(NewGenieRunner(dir, dir, true), e, dir, func(string, any) {})
	r.incidents = append(r.incidents, nil)
	safeIter("workflow", func() { r.workflowTick(0, 0, nil) })
	if !r.mu.TryLock() {
		t.Fatal("reasoner lock still held after a recovered workflow panic")
	}
	r.mu.Unlock()
}

// #41: the id counter survives with the state, so ids are never reused after incidents leave the store file.
func TestIncidentIDCounterKept(t *testing.T) {
	dir := t.TempDir()
	r := NewReasoner(NewGenieRunner(dir, dir, true), nil, dir, func(string, any) {})
	for i := 0; i < 3; i++ {
		r.mu.Lock()
		r.seq++
		inc := &Incident{ID: "INC-" + strings.Repeat("0", 3) + string(rune('1'+i)), State: "done"}
		r.incidents = append(r.incidents, inc)
		r.mu.Unlock()
		r.persist(inc)
	}
	// the store loses the newest incident (restore of an older file): the counter still says 3
	if err := os.WriteFile(r.store, []byte(`{"id":"INC-0001","state":"done"}`+"\n"), 0o644); err != nil {
		t.Fatal(err)
	}
	r2 := NewReasoner(NewGenieRunner(dir, dir, true), nil, dir, func(string, any) {})
	if r2.seq != 3 {
		t.Fatalf("seq %d after reload, want 3 (%s)", r2.seq, filepath.Base(seqPath(r.store)))
	}
}

// #1: the live engine reports its catch-up and stops waiting for an unreachable campus API after liveHoldMax.
func TestLiveCatchUp(t *testing.T) {
	e := dqEngine(t)
	old := liveHoldMax
	liveHoldMax = 0
	t.Cleanup(func() { liveHoldMax = old })
	e.SetLive(12 * time.Hour)
	c := e.CatchingUp()
	if c == nil || c["total"] < 143 || c["done"] != 0 {
		t.Fatalf("catching_up %v", c)
	}
	time.Sleep(time.Millisecond)
	e.Tick()
	if c := e.CatchingUp(); c != nil {
		t.Fatalf("still catching up after one poll: %v", c)
	}
}
