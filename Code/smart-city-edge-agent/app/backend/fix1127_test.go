package main

import (
	"math"
	"strings"
	"testing"
	"time"
)

func TestContextFixReport(t *testing.T) {
	ramp := func(a, b float64) []float64 {
		xs := make([]float64, 8)
		for i := range xs {
			xs[i] = a + (b-a)*float64(i)/7
		}
		return xs
	}
	inc := &Incident{Sensors: []SensorRef{
		{Node: "SR-AQ-KH03-03", Metric: "temp", Role: "air_quality", Xs: ramp(24, 30)},
		{Node: "AC-KH03", Metric: "room_temp", Role: "hvac", Context: true, Xs: ramp(24, 29)},
		{Node: "AC-KH03", Metric: "ac_units_on", Role: "hvac", Context: true, Xs: []float64{3, 3, 0, 0, 0, 0, 0, 0}},
	}}
	rep := &Report{Severity: "sensor_fault", Label: "sensor_fault", Title: "Sensor jump on KH level 03 temperature",
		Explanation: "AC running; stop the AC units.", Checklist: []V3ChecklistItem{{Action: "inspect_hvac", Why: "Turn off the AC"}}}
	rs := contextFixReport(rep, inc)
	if len(rs) != 2 {
		t.Fatalf("repairs %v", rs)
	}
	if rep.Severity == "sensor_fault" || rep.Label == "sensor_fault" || rep.Title != "" {
		t.Errorf("fault wording kept: %+v", rep)
	}
	if strings.Contains(strings.ToLower(rep.Explanation), "stop the ac") || strings.Contains(rep.Checklist[0].Why, "Turn off") {
		t.Errorf("AC wording kept: %q / %q", rep.Explanation, rep.Checklist[0].Why)
	}
	// AC on: no AC rewrite
	inc.Sensors[2].Xs = []float64{3, 3, 3, 3, 3, 3, 3, 3}
	rep2 := &Report{Severity: "warning", Explanation: "Stop the AC to save power."}
	if rs := contextFixReport(rep2, inc); len(rs) != 0 || rep2.Explanation != "Stop the AC to save power." {
		t.Errorf("AC on rewritten: %v %q", rs, rep2.Explanation)
	}
	// outdoor dust
	out := &Incident{Sensors: []SensorRef{{Node: "WS-01", Metric: "pm10", Role: "weather", Location: "outdoor weather station"}}}
	rep3 := &Report{Checklist: []V3ChecklistItem{{Why: "Ventilate the room and open windows"}}}
	if rs := contextFixReport(rep3, out); len(rs) != 1 || strings.Contains(strings.ToLower(rep3.Checklist[0].Why), "ventilate") {
		t.Errorf("outdoor: %v %q", rs, rep3.Checklist[0].Why)
	}
	// indoor PM: ventilate stays
	in := &Incident{Sensors: []SensorRef{{Node: "SR-AQ-KH03-03", Metric: "pm25", Role: "air_quality", Location: "KH building, level 03, indoor air sensor 03"}}}
	rep4 := &Report{Checklist: []V3ChecklistItem{{Why: "Ventilate the room"}}}
	if rs := contextFixReport(rep4, in); len(rs) != 0 {
		t.Errorf("indoor rewritten: %v", rs)
	}
}

func TestRelatedSensorsTree(t *testing.T) {
	cfg := &SiteConfig{Nodes: []SiteNode{
		{ID: "campus", Kind: "campus"},
		{ID: "KH", Kind: "building", Parent: "campus"}, {ID: "SB", Kind: "building", Parent: "campus"},
		{ID: "KH/L03", Kind: "floor", Parent: "KH"}, {ID: "KH/L98", Kind: "floor", Parent: "KH"}, {ID: "SB/L01", Kind: "floor", Parent: "SB"},
		{ID: "AQ1", Kind: "equipment", Parent: "KH/L03"}, {ID: "W1", Kind: "equipment", Parent: "KH/L98"}, {ID: "P1", Kind: "equipment", Parent: "SB/L01"}, {ID: "W2", Kind: "equipment", Parent: "SB/L01"},
		{ID: "AQ1/co2", Kind: "sensor", Parent: "AQ1"}, {ID: "W1/ph", Kind: "sensor", Parent: "W1"}, {ID: "P1/pf", Kind: "sensor", Parent: "P1"}, {ID: "W2/ph", Kind: "sensor", Parent: "W2"},
	}}
	cfg.Links = []SiteLink{{From: "P1", To: "KH", Type: "supplies", Inferred: true}}
	ix := NewSiteIndex(cfg)
	cases := []struct {
		a, b, ra, rb string
		want         bool
	}{
		{"AQ1/co2", "W1/ph", "air_quality", "water", true}, // same building
		{"AQ1/co2", "P1/pf", "air_quality", "power", false}, // other building, other domain
		{"W1/ph", "W2/ph", "water", "water", true},          // other building, same domain
	}
	for _, c := range cases {
		if got := relatedSensors(ix, c.a, c.b, c.ra, c.rb); got != c.want {
			t.Errorf("%s-%s: %v want %v", c.a, c.b, got, c.want)
		}
	}
	cfg2 := *cfg
	cfg2.Links = []SiteLink{{From: "P1", To: "AQ1", Type: "supplies"}} // confirmed link: related
	if !relatedSensors(NewSiteIndex(&cfg2), "AQ1/co2", "P1/pf", "air_quality", "power") {
		t.Error("confirmed supplies link should relate")
	}
	if d, dm, ok := siteDistance(ix, "AQ1/co2", "P1/pf"); !ok || d != 8 || dm != 8 {
		t.Errorf("distance %d of %d", d, dm)
	}
}

func TestPrefetchTake(t *testing.T) {
	p := Finding{Pattern: "step_increase", Status: "warning"}
	put := func(end int64) {
		pfS.Lock()
		if pfS.m == nil {
			pfS.m = map[string]pfEntry{}
		}
		pfS.m[key("N", "co2")] = pfEntry{End: end, Sig: pfSig(p), Call: AgentCall{Parsed: &p, Valid: true}, At: time.Now()}
		pfS.Unlock()
	}
	put(1000)
	if _, _, ok := prefetchTake(SensorRef{Node: "N", Metric: "co2", End: 1000 + 2*bucketSec}); !ok {
		t.Error("2 readings newer should be reusable")
	}
	if _, _, ok := prefetchTake(SensorRef{Node: "N", Metric: "co2", End: 1000}); ok {
		t.Error("entry must be consumed")
	}
	put(1000)
	if _, e, ok := prefetchTake(SensorRef{Node: "N", Metric: "co2", End: 1000 + 5*bucketSec}); ok || e.Call.Parsed == nil {
		t.Error("5 readings newer: not reusable, but the entry is returned for the shadow log")
	}
}

func TestPlaceAndSpark(t *testing.T) {
	if p := placeOf("KH building, level 03, indoor air sensor 03"); p != "KH building, level 03" {
		t.Error(p)
	}
	if p := placeOf("SB substation, feeder 2"); p != "SB substation" {
		t.Error(p)
	}
	xs := make([]float64, 48)
	for i := range xs {
		xs[i] = float64(i)
	}
	xs[3] = math.NaN()
	if sp := sparkOfWindow(xs, 24); len(sp) != 24 {
		t.Error(len(sp))
	}
}

func TestChatVisible(t *testing.T) {
	if v := chatVisible("I should call site_status", true); v != "" {
		t.Errorf("thinking shown: %q", v)
	}
	if v := chatVisible("hmm</think>\n\nThe campus is normal.", true); v != "The campus is normal." {
		t.Errorf("%q", v)
	}
	if v := chatVisible("<tool_call>{\"name\":\"x\"}", false); v != "" {
		t.Errorf("tool call shown: %q", v)
	}
	if v := chatVisible("<think>a</think>Answer", false); v != "Answer" {
		t.Errorf("%q", v)
	}
}

func TestCorroboratedRiseRun3Wording(t *testing.T) {
	ramp := func(a, b float64) []float64 {
		xs := make([]float64, 8)
		for i := range xs {
			xs[i] = a + (b-a)*float64(i)/7
		}
		return xs
	}
	inc := &Incident{Sensors: []SensorRef{
		{Node: "SR-AQ-KH03-03", Metric: "temp", Xs: ramp(25, 34)},
		{Node: "AC-KH03", Metric: "room_temp", Context: true, Xs: ramp(24, 33.5)},
	}}
	rep := &Report{Severity: "sensor_fault", Title: "Suspect room temperature readings (one sensor): KH building, level 03",
		Explanation: "A sensor problem, not a hot room: the reference AC unit reads 33.5 C and rises smoothly. Check the sensor. The AC is off."}
	contextFixReport(rep, inc)
	if rep.Title != "" || strings.Contains(rep.Explanation, "sensor problem") || strings.Contains(rep.Explanation, "Check the sensor") || !strings.Contains(rep.Explanation, "The AC is off.") {
		t.Errorf("%q / %q", rep.Title, rep.Explanation)
	}
}
