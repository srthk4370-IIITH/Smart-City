package main

import "testing"

// deploy22 (owner 2026-10-31): after a sensor silence the 4 h window has gaps; a CRITICAL reading skips the
// window-coverage gate and opens the fast incident at once (the AI still waits for real coverage), a non-critical
// reading is still gated.
func gapRun(t *testing.T, silent int, v float64, prior bool) (fastAfter int, any bool, st SensorState, fastSev string) {
	t.Helper()
	e := dqEngine(t)
	e.NoiseScale = 1
	k := key(dqNode, dqMetric)
	def := e.bank[k].Default
	var got []Candidate
	e.onEvent = func(c []Candidate) { got = append(got, c...) }
	e.SetSensor(dqNode, dqMetric, def, "api")
	feed := func(v float64, n int) {
		e.SetSensor(dqNode, dqMetric, v, "api")
		for i := 0; i < n; i++ {
			e.bank[k].SetAt = nowTime().Unix()
			e.Tick()
		}
	}
	feed(def, 60)
	if prior { // an earlier reported critical episode on this sensor (the board: fastcheck ran before the silence)
		feed(v, 30)
		feed(def, 60)
	}
	e.bank[k].SetAt = nowTime().Unix() - apiHoldSec - 1 // the held value goes stale: no readings
	for i := 0; i < silent; i++ {
		e.Tick()
	}
	if _, ok := e.Window(dqNode, dqMetric, e.sim); ok {
		t.Fatal("test premise: the window must have a coverage gap after the silence")
	}
	got = nil
	e.SetSensor(dqNode, dqMetric, v, "api")
	for i := 1; i <= 3; i++ {
		e.Tick()
		for _, c := range got {
			if c.Node == dqNode && c.Metric == dqMetric {
				any = true
				if !c.Fast {
					t.Errorf("silent %d: a non-fast (AI) candidate from a gap-filled window", silent)
				}
				if c.Fast && fastAfter == 0 {
					fastAfter, fastSev = i, c.Finding.Status
				}
			}
		}
	}
	return fastAfter, any, stateOf(e, dqNode, dqMetric), fastSev
}

func TestCriticalSkipsCoverageGate(t *testing.T) {
	crit := Metrics["air_quality/co2"].Crit + 200
	warn := Metrics["air_quality/co2"].Warn + 100
	for _, prior := range []bool{false, true} {
		for _, silent := range []int{4, 17 * 60} { // 17 min of sensor time (4 buckets) and 17 min wall at 1 s/bucket
			if n, _, st, sev := gapRun(t, silent, crit, prior); n == 0 || n > fastReadings || sev != "critical" {
				t.Errorf("prior %v silent %d: critical fast incident after %d readings (want <= %d), finding %q; status %s %s", prior, silent, n, fastReadings, sev, st.Status, st.QualityWhy)
			}
			if _, any, st, _ := gapRun(t, silent, warn, prior); any || st.Status != "insufficient_data" {
				t.Errorf("silent %d: non-critical reading passed the gate (event %v, status %s)", silent, any, st.Status)
			}
		}
	}
}
