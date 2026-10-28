package main

import (
	"math"
	"testing"
)

// dqEngine: a real engine with exact readings (no jitter), stopped so tests drive Tick by hand.
func dqEngine(t *testing.T) *Engine {
	t.Helper()
	eng, err := NewEngine("../device")
	if err != nil {
		t.Fatal(err)
	}
	eng.NoiseScale = 0
	return eng
}

func fp(v float64) *float64 { return &v }

func stateOf(e *Engine, node, metric string) SensorState {
	e.mu.RLock()
	defer e.mu.RUnlock()
	return *e.states[key(node, metric)]
}

const dqNode, dqMetric = "SR-AQ-KH03-03", "co2"

// A device posting readings with timestamps: buckets are means of real readings, a silent device leaves
// gaps (never a held / invented value), and a long silence is insufficient_data with a reason.
func TestDQMeasuredFeedNoInventedData(t *testing.T) {
	e := dqEngine(t)
	now := int64(2_000_000_000)
	// switching to the measured feed drops the simulated pre-fill
	if st, err := e.IngestReading(Reading{Node: dqNode, Metric: dqMetric, Value: fp(600), Ts: float64(now)}, now); err != nil || st != "accepted" {
		t.Fatalf("ingest: %v %v", st, err)
	}
	e.Tick()
	k := key(dqNode, dqMetric)
	if n := len(e.series[k]); n != 1 {
		t.Fatalf("simulated history must be dropped: %d buckets", n)
	}
	// two readings in one bucket -> their mean
	now += 300
	e.IngestReading(Reading{Node: dqNode, Metric: dqMetric, Value: fp(600), Ts: float64(now - 60)}, now)
	e.IngestReading(Reading{Node: dqNode, Metric: dqMetric, Value: fp(700), Ts: float64(now)}, now)
	e.Tick()
	if v := e.series[k][e.sim]; v != 650 {
		t.Fatalf("bucket mean = %v, want 650", v)
	}
	// silence: no reading appears
	for i := 0; i < 5; i++ {
		e.Tick()
	}
	if _, ok := e.series[k][e.sim]; ok {
		t.Fatal("a silent measured sensor got a reading")
	}
	st := stateOf(e, dqNode, dqMetric)
	if st.Status != "insufficient_data" || st.Quality != "stale" || st.Feed != "measured" {
		t.Fatalf("silent device: status %s quality %s feed %s (%s)", st.Status, st.Quality, st.Feed, st.QualityWhy)
	}
}

// A gateway outage then a backlog burst: late readings land in their own buckets (not the arrival
// bucket), duplicates (QoS1 redelivery) are dropped, the 4 h window becomes complete again.
func TestDQBurstAfterReconnectBackfills(t *testing.T) {
	e := dqEngine(t)
	now := int64(2_000_000_000)
	// 4 h of history arrives as one batch at connect (oldest first)
	for i := Window - 1; i >= 0; i-- {
		ts := now - int64(i)*300
		if st, _ := e.IngestReading(Reading{Node: dqNode, Metric: dqMetric, Value: fp(600 + float64(i%3)), Ts: float64(ts)}, now); st != "late" && st != "accepted" {
			t.Fatalf("backfill %d: %s", i, st)
		}
	}
	e.Tick()
	if st := stateOf(e, dqNode, dqMetric); !st.DataOK || st.Quality != "good" {
		t.Fatalf("after backfill: ok=%v quality=%s (%s) coverage %.2f", st.DataOK, st.Quality, st.QualityWhy, st.Coverage)
	}
	// outage of 30 min (6 buckets): nothing posted
	for i := 0; i < 6; i++ {
		now += 300
		e.Tick()
	}
	if st := stateOf(e, dqNode, dqMetric); st.Status != "insufficient_data" {
		t.Fatalf("30 min outage should be insufficient_data, got %s", st.Status)
	}
	// reconnect: the gateway flushes the 6 missed readings plus a duplicate of one of them
	for i := 5; i >= 0; i-- {
		e.IngestReading(Reading{Node: dqNode, Metric: dqMetric, Value: fp(610), Ts: float64(now - int64(i)*300 - 1)}, now+5)
	}
	if st, _ := e.IngestReading(Reading{Node: dqNode, Metric: dqMetric, Value: fp(610), Ts: float64(now - 1)}, now+5); st != "duplicate" {
		t.Fatalf("redelivered reading: %s, want duplicate", st)
	}
	now += 300
	e.IngestReading(Reading{Node: dqNode, Metric: dqMetric, Value: fp(611), Ts: float64(now)}, now)
	e.Tick()
	st := stateOf(e, dqNode, dqMetric)
	if !st.DataOK || st.Ingest == nil || st.Ingest.Duplicates != 1 || st.Ingest.Backfilled < 6 {
		t.Fatalf("after burst: ok=%v ingest=%+v (%s)", st.DataOK, st.Ingest, st.QualityWhy)
	}
}

// Bad / out-of-range / unset-clock / future-clock readings.
func TestDQIngestQualityRules(t *testing.T) {
	e := dqEngine(t)
	now := int64(2_000_000_000)
	cases := []struct {
		rd   Reading
		want string
	}{
		{Reading{Value: fp(-999), Ts: float64(now)}, "rejected_range"}, // a sentinel never becomes a 0 dip
		{Reading{Value: fp(600), Ts: float64(now + 1), Quality: "bad"}, "rejected_bad"},
		{Reading{Value: fp(600), Ts: 1007849}, "accepted+clock"},             // uptime counter, not unix time
		{Reading{Value: fp(600), Ts: float64(now + 3600)}, "accepted+clock"}, // device clock 1 h ahead
		{Reading{Value: fp(600), Ts: float64(now - 30*3600)}, "too_old"},
	}
	for i, c := range cases {
		c.rd.Node, c.rd.Metric = dqNode, dqMetric
		if got, err := e.IngestReading(c.rd, now); err != nil || got != c.want {
			t.Errorf("case %d: %q %v, want %q", i, got, err, c.want)
		}
	}
	if _, err := e.IngestReading(Reading{Node: dqNode, Metric: dqMetric, Value: fp(1), Quality: "meh"}, now); err == nil {
		t.Error("unknown quality accepted")
	}
}

// Legacy held API value (no ts): once the device is silent for 15 min of wall time it stops producing
// readings instead of becoming a fabricated flatline.
func TestDQHeldAPIValueGoesStale(t *testing.T) {
	e := dqEngine(t)
	if _, err := e.SetSensor(dqNode, dqMetric, 700, "api"); err != nil {
		t.Fatal(err)
	}
	e.Tick()
	k := key(dqNode, dqMetric)
	if _, ok := e.series[k][e.sim]; !ok {
		t.Fatal("fresh held value must be sampled")
	}
	e.bank[k].SetAt = nowTime().Unix() - apiHoldSec - 1
	e.Tick()
	if _, ok := e.series[k][e.sim]; ok {
		t.Fatal("a held value 15 min old was still turned into a reading")
	}
	// clamping is kept for the legacy path, but flagged
	e.SetSensor(dqNode, dqMetric, 1e9, "api")
	e.Tick()
	if st := stateOf(e, dqNode, dqMetric); st.Ingest == nil || st.Ingest.Clamped != 1 {
		t.Fatalf("clamp not counted: %+v", st.Ingest)
	}
}

// One single-reading glitch does not open an incident; two glitches (a dropout fault) and a real
// event still do. The AI's window is never modified.
func TestDQGlitchFilterGateOnly(t *testing.T) {
	xs := make([]float64, Window)
	for i := range xs {
		xs[i] = 600 + float64(i%2)
	}
	xs[30] = 4800
	ys, at := glitchFree("air_quality", "co2", xs)
	if ys == nil || at != 30 || ys[30] != (xs[29]+xs[31])/2 || xs[30] != 4800 {
		t.Fatalf("glitch not removed: at=%d", at)
	}
	if f := RuleFinding("air_quality", "co2", "n", xs, 0); sevRank(f.Status) == 0 {
		t.Fatalf("test premise: the raw glitch window should be abnormal, got %s", f.Status)
	}
	xs[36] = 4800
	if ys, _ := glitchFree("air_quality", "co2", xs); ys != nil {
		t.Fatal("two glitches are a fault pattern, not one glitch")
	}
	if ys, _ := glitchFree("power", "power_kw", xs); ys != nil {
		t.Fatal("power must never be filtered (load surges are real)")
	}

	// through the engine: a one-reading 4800 ppm glitch never reaches the AI
	e := dqEngine(t)
	e.NoiseScale = 1 // real jitter (exact values would read as a flatline sensor fault)
	var got []Candidate
	e.onEvent = func(c []Candidate) { got = append(got, c...) }
	e.SetSensor(dqNode, dqMetric, 4800, "slider")
	e.Tick()
	e.SetSensor(dqNode, dqMetric, e.bank[key(dqNode, dqMetric)].Default, "slider")
	for i := 0; i < 20; i++ {
		e.Tick()
	}
	for _, c := range got {
		if c.Node == dqNode && c.Metric == dqMetric {
			t.Fatalf("a single glitch opened an incident: %+v", c.Finding)
		}
	}
	if st := stateOf(e, dqNode, dqMetric); st.Quality != "uncertain" || st.Status != "normal" {
		t.Fatalf("glitch: status %s quality %s (%s)", st.Status, st.Quality, st.QualityWhy)
	}
	// a sustained rise still alerts
	e.SetSensor(dqNode, dqMetric, 1700, "slider")
	for i := 0; i < 20; i++ {
		e.Tick()
	}
	found := false
	for _, c := range got {
		found = found || (c.Node == dqNode && c.Metric == dqMetric)
	}
	if !found {
		t.Fatal("a sustained CO2 rise did not alert")
	}
}

// A value hovering at the warning limit (ISA-18.2 chattering): it still alerts once, and the dips just
// under the limit do not end the episode into a flood of incidents.
func TestDQChatterAtLimitOneIncident(t *testing.T) {
	e := dqEngine(t)
	n := 0
	e.onEvent = func(c []Candidate) {
		for _, x := range c {
			if x.Node == dqNode && x.Metric == dqMetric {
				n++
			}
		}
	}
	warn := Metrics["air_quality/co2"].Warn
	for i := 0; i < 120; i++ { // 10 h: 5 readings above the limit, 1 just under, repeating
		v := warn + 30
		if i%6 == 5 {
			v = warn - 20 // inside the 5% deadband
		}
		e.SetSensor(dqNode, dqMetric, v, "slider")
		e.Tick()
	}
	if n != 1 {
		t.Fatalf("chattering sensor opened %d incidents, want 1", n)
	}
	st := stateOf(e, dqNode, dqMetric)
	if !st.alerted || st.clearedAt != 0 {
		t.Fatalf("episode should still be open: alerted=%v clearedAt=%d", st.alerted, st.clearedAt)
	}
}

// Maintenance holds the gate and records nothing; a replacement drops the old sensor's history so the
// new level is not compared with the old one, and the sensor waits for a full new window.
func TestDQMaintenanceAndReplacement(t *testing.T) {
	e := dqEngine(t)
	var got []Candidate
	e.onEvent = func(c []Candidate) { got = append(got, c...) }
	if _, err := e.SetMaintenance(dqNode, dqMetric, 60, "calibration", false); err != nil {
		t.Fatal(err)
	}
	e.SetSensor(dqNode, dqMetric, 2500, "slider") // technician's test gas
	for i := 0; i < 10; i++ {
		e.Tick()
	}
	if len(got) != 0 {
		t.Fatalf("maintenance raised %d candidates", len(got))
	}
	if st := stateOf(e, dqNode, dqMetric); st.Quality != "maintenance" {
		t.Fatalf("quality %s, want maintenance", st.Quality)
	}
	k := key(dqNode, dqMetric)
	if v, ok := e.series[k][e.sim]; ok && v == 2500 {
		t.Fatal("a reading during maintenance was recorded")
	}
	// end maintenance with a replacement: history before now is dropped
	e.SetSensor(dqNode, dqMetric, 450, "slider")
	if _, err := e.SetMaintenance(dqNode, dqMetric, 0, "", true); err != nil {
		t.Fatal(err)
	}
	e.Tick()
	st := stateOf(e, dqNode, dqMetric)
	if st.DataOK || st.Status != "insufficient_data" || st.QualityWhy == "" {
		t.Fatalf("after replacement: ok=%v status=%s why=%q", st.DataOK, st.Status, st.QualityWhy)
	}
	for i := 0; i < Window; i++ {
		e.Tick()
	}
	if st := stateOf(e, dqNode, dqMetric); !st.DataOK {
		t.Fatalf("a full new window should be usable: %s", st.QualityWhy)
	}
}

// The domain health lists sensors whose data is not good.
func TestDQHealthShowsDataQuality(t *testing.T) {
	sts := []SensorState{
		{Node: "a", Metric: "co2", Role: "air_quality", Status: "normal", Quality: "good", DataOK: true, Last: fp(1), Updated: 100},
		{Node: "b", Metric: "co2", Role: "air_quality", Status: "insufficient_data", Quality: "stale", QualityWhy: "no reading for 25 min"},
	}
	h := buildHealth(100, 0, sts, nil, map[string]*healthMark{})
	for _, d := range h.Domains {
		if d.Domain == "air_quality" {
			if len(d.DataQuality) != 1 || d.DataQuality[0].Quality != "stale" {
				t.Fatalf("data quality: %+v", d.DataQuality)
			}
			return
		}
	}
	t.Fatal("no air_quality domain")
}

var _ = math.Abs
