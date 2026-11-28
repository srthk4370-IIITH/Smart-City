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

func TestAgreeLines(t *testing.T) {
	ramp := func(a, b float64) []float64 {
		xs := make([]float64, 12)
		for i := range xs {
			xs[i] = a + (b-a)*float64(i)/11
		}
		return xs
	}
	ss := []SensorRef{
		{Ref: "S1", Node: "SR-AQ-KH03-03", Metric: "temp", Role: "air_quality", Location: "KH building, level 03, indoor air sensor 03", Xs: ramp(24.6, 34.5)},
		{Ref: "S2", Node: "AC-KH03", Metric: "room_temp", Role: "hvac", Location: "KH building, level 03, AC units", Context: true, Xs: ramp(24.1, 33.5)},
		{Ref: "S3", Node: "WE-VN04-00", Metric: "temp", Role: "weather", Location: "VN building, level 04, weather station", Xs: ramp(25, 30)},
		{Ref: "S4", Node: "SR-AQ-SB00-01", Metric: "temp", Role: "air_quality", Location: "SB building, level 00, indoor air sensor 01", Xs: ramp(22, 30)},
	}
	got := agreeLines(ss)
	want := "AGREE: S1 temp and S2 room_temp are two independent temperature sensors in the same area (KH building, level 03); both rose over the window: S1 24.6 -> 34.5 C, S2 24.1 -> 33.5 C (now 1.0 C apart)."
	if len(got) != 1 || got[0] != want {
		t.Fatalf("%q", got)
	}
	flat := []SensorRef{ss[0], {Ref: "S2", Node: "AC-KH03", Metric: "room_temp", Role: "hvac", Location: ss[1].Location, Xs: ramp(24, 24.2)}}
	if l := agreeLines(flat); len(l) != 0 {
		t.Fatalf("one sensor rising is not agreement: %q", l)
	}
}

// 2026-11-28 re-run INC-0016: sensor_fault verdict on a corroborated heat rise -> title/root cause/explanation replaced.
func TestCorroboratedRiseStrongVerdictReplaced(t *testing.T) {
	ramp := func(a, b float64) []float64 {
		xs := make([]float64, 8)
		for i := range xs {
			xs[i] = a + (b-a)*float64(i)/7
		}
		return xs
	}
	inc := &Incident{Sensors: []SensorRef{
		{Node: "SR-AQ-KH03-03", Metric: "temp", Xs: ramp(24.6, 31.8)},
		{Node: "AC-KH03", Metric: "room_temp", Context: true, Xs: ramp(23.7, 30.8)},
		{Node: "AC-KH03", Metric: "ac_units_on", Context: true, Xs: []float64{2, 2, 0, 0, 0, 0, 0, 0}},
	}}
	rep := &Report{Severity: "sensor_fault", Label: "sensor_fault", Title: "Point sensor reading not credible (KH building, level 03)",
		RootCause:   "A local heat source or a fault on one point sensor; the AC's own sensor reads normal and the room power has not changed.",
		Explanation: "Do not read the room as heated: one small sensor disagrees with the AC sensor (30.8 C) and with the room power."}
	contextFixReport(rep, inc)
	if rep.Severity == "sensor_fault" || rep.Title != "" || strings.Contains(rep.RootCause, "reads normal") ||
		strings.Contains(rep.Explanation, "Do not read") || !strings.Contains(rep.RootCause, "AC units are off") || rep.Label != "hvac_or_thermal_issue" {
		t.Fatalf("%+v", rep)
	}
}

// 2026-11-28 re-run INC-0019: a per-unit AC room sensor gets the room air sensor and the AC units as context.
func TestContextForPerUnitACSensor(t *testing.T) {
	e := dqEngine(t)
	role := e.Meta.Nodes["AC-KH03"].Role
	if role == "" {
		t.Fatal("no AC-KH03 in the sensor bank")
	}
	e.mu.RLock()
	end := e.sim
	e.mu.RUnlock()
	picks := e.ContextFor([]Candidate{{Node: "AC-KH03", Metric: "room_temp", Role: role, End: end}}, 6)
	got := map[string]bool{}
	for _, p := range picks {
		got[p.Cand.Node+"/"+p.Cand.Metric] = true
	}
	if !got["SR-AQ-KH03-03/temp"] {
		t.Fatalf("room air sensor missing from context: %v (role %s)", got, role)
	}
}
