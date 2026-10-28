package main

import (
	"strings"
	"testing"
)

// A level shift 6 h ago that the 4 h window only shows as a flat new level: the incident's sensor
// carries the 12 h finding, the reasoner prompt shows it as S1.E9, and the policy gate accepts a
// report citing it (HANDBOOK 2.38).
func TestLongRangeReachesReasoner(t *testing.T) {
	eng, err := NewEngine("../device")
	if err != nil {
		t.Fatal(err)
	}
	k := eng.bankOrder[0]
	sn := eng.bank[k]
	m := Metrics[sn.Role+"/"+sn.Metric]
	if sn.Role == "occupancy" {
		t.Skip("first bank sensor is occupancy")
	}
	base := (m.Lo + m.Hi) / 4
	if m.HasLimits && m.Dir == "high" {
		base = m.Warn / 2
	}
	step := 20 * m.Floor
	if step == 0 {
		step = 0.5 * base
	}
	end := eng.sim
	eng.series[k] = map[int64]float64{}
	for i := 0; i < 160; i++ {
		v := base + 0.01*m.Floor*float64(i%3)
		if i >= 160-72 { // the shift happened 6 h ago and stayed
			v += step
		}
		eng.series[k][end-int64(159-i)*bucketSec] = v
	}
	if xs := eng.HistoryAt(sn.Node, sn.Metric, end, lrPoints); len(xs) != lrPoints {
		t.Fatalf("history %d points, want %d", len(xs), lrPoints)
	}
	r := &Reasoner{eng: eng}
	xs, _ := eng.Window(sn.Node, sn.Metric, end)
	s := r.sensorRef("S1", Candidate{sn.Node, sn.Metric, sn.Role, Finding{Pattern: "stable", Status: "warning"}, xs, end, false, false, false}, "")
	if len(s.LongRange) == 0 || s.LongRange[0].Kind != "level_shift" || s.LongRange[0].ID != "E9" {
		t.Fatalf("long-range finding missing: %+v", s.LongRange)
	}
	if ago := float64(s.LongRange[0].AgoPts) * 5 / 60; ago < 5 || ago > 7 {
		t.Fatalf("shift dated %.1f h ago, want ~6", ago)
	}
	sensors := []SensorRef{s}
	if p := singlePrompt(sensors); !strings.Contains(p, "S1.E9 12 h view: level shifted") {
		t.Fatalf("single prompt lacks the 12 h line:\n%s", p)
	}
	if p := synthPrompt(sensors, nil); !strings.Contains(p, "  S1.E9 12 h view: level shifted") {
		t.Fatalf("synth prompt lacks the 12 h line:\n%s", p)
	}
	raw := `{"root_cause": "Level moved hours ago [S1.E9]", "label": "` + ReportLabels[0] + `", "affected_domains": ["` + sn.Role +
		`"], "evidence": ["S1.E9", "S1.E1"], "confidence": 0.7, "action": "monitor", "explanation": "Shift [S1.E9]."}`
	rc := r.checkReport(GenieResult{Text: raw}, "", sensors)
	for _, e := range rc.Errors {
		if strings.Contains(e, "S1.E9") {
			t.Fatalf("policy rejected the 12 h evidence id: %v", rc.Errors)
		}
	}
	// related (context) sensors get no 12 h check
	if c := r.sensorRef("S2", Candidate{sn.Node, sn.Metric, sn.Role, Finding{}, xs, end, false, false, false}, "related"); c.LongRange != nil {
		t.Fatal("context sensor got long-range findings")
	}
}
