package main

import "testing"

// K-of-window AI gate (owner decision 2026-11-20): the AI is called when abnormal_of_window of the last
// persist_readings readings are abnormal, not persist_readings in a row.

func aiReadings(ev []fpEvent) (n int, first int) {
	_, ai := fpSplit(ev)
	if len(ai) > 0 {
		first = ai[0].reading
	}
	return len(ai), first
}

// A (1800 ppm, critical) alternating with N (600): A,N,A,N,A,N,A = 4 abnormal of 7 -> AI by the 7th reading (the rules keep flagging the spike shape on the N readings, so it can be earlier).
func TestKOfWindowFlapping(t *testing.T) {
	e := dqEngine(t)
	a, n := 1800.0, 600.0
	ev := feedCO2(t, e, 60, 600, []float64{a, n, a, n, a, n, a, n, n, n, n, n})
	cnt, first := aiReadings(ev)
	if cnt != 1 || first < 4 || first > 7+batchReadings {
		t.Fatalf("flapping: %d AI candidates, first at %d, want one at 4..%d", cnt, first, 7+batchReadings)
	}
}

// 1..K-1 stray abnormal readings never call the AI; neither do abnormal readings spread wider than the window.
func TestKOfWindowStrayAndGaps(t *testing.T) {
	for _, vals := range [][]float64{
		{1800, 600, 600, 600, 600, 600, 600, 600, 600, 600, 600, 600},
		{1100, 600, 600, 600, 600, 600, 600, 600, 600, 600, 600, 600},
		{1800, 600, 600, 600, 600, 600, 600, 600, 600, 600, 600, 600},
		// abnormal readings 9 apart: only one is ever inside the last 8
		{1800, 600, 600, 600, 600, 600, 600, 600, 600, 600, 600, 600, 600, 600, 600, 600, 600, 600, 600, 600, 600},
	} {
		e := dqEngine(t)
		if cnt, first := aiReadings(feedCO2(t, e, 60, 600, vals)); cnt != 0 {
			t.Errorf("%v: AI called at reading %d, want never", vals, first)
		}
	}
}

func TestKOfWindowCount(t *testing.T) {
	st := &SensorState{}
	b := int64(bucketSec)
	st.abTimes = []int64{0, 2 * b, 4 * b, 6 * b} // readings 1,3,5,7 abnormal; 2,4,6 normal or missing
	if n := st.winCount(6*b, 8); n != 4 {
		t.Fatalf("count %d, want 4", n)
	}
	if n := st.winCount(9*b, 8); n != 3 { // reading at 0 left the window of 8
		t.Fatalf("count after ageing %d, want 3", n)
	}
	if n := st.winCount(40*b, 8); n != 0 {
		t.Fatalf("count after a long gap %d, want 0", n)
	}
}

func TestKOfWindowEditableValidated(t *testing.T) {
	d := defaultTrigger
	if d.AbnormalOfWindow != 4 || len(d.Validate()) != 0 {
		t.Fatalf("default %+v %v", d, d.Validate())
	}
	for _, k := range []int{1, 9} {
		x := d
		x.AbnormalOfWindow = k
		if len(x.Validate()) == 0 {
			t.Errorf("abnormal_of_window %d accepted with window 8", k)
		}
	}
	x := d
	x.AbnormalOfWindow = 8
	if len(x.Validate()) != 0 {
		t.Errorf("abnormal_of_window 8 rejected: %v", x.Validate())
	}
}
