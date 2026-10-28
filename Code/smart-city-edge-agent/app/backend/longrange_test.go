package main

import (
	"encoding/json"
	"math"
	"os"
	"testing"
)

// The Go detectors must give the same findings as training/window_study/longrange.py, whose
// thresholds were tuned and evaluated offline (proofs/2026-10-16_longrange).
func TestLongRangeMatchesPython(t *testing.T) {
	raw, err := os.ReadFile("testdata/longrange_fixtures.json")
	if err != nil {
		t.Fatal(err)
	}
	var fx struct {
		Params map[string]float64 `json:"params"`
		Cases  []struct {
			Role, Metric string
			Xs           []float64
			Findings     []map[string]any
		} `json:"cases"`
	}
	if err := json.Unmarshal(raw, &fx); err != nil {
		t.Fatal(err)
	}
	if fx.Params["kL"] != lrKL || fx.Params["kD"] != lrKD || fx.Params["rD"] != lrRD || fx.Params["kQ"] != lrKQ {
		t.Fatalf("Go thresholds differ from the tuned Python ones: %v", fx.Params)
	}
	fired := 0
	for i, c := range fx.Cases {
		got := longRange(c.Role, c.Metric, c.Xs)
		var want []map[string]any
		for _, f := range c.Findings {
			if f["kind"] == "level_shift" || f["kind"] == "slow_drift" {
				want = append(want, f)
			}
		}
		if len(got) != len(want) {
			t.Fatalf("case %d %s/%s: Go %v, Python %v", i, c.Role, c.Metric, got, want)
		}
		for j := range got {
			if got[j].Kind != want[j]["kind"] || math.Abs(got[j].Delta-want[j]["delta"].(float64)) > 1e-6*math.Max(1, math.Abs(got[j].Delta)) {
				t.Fatalf("case %d: Go %+v, Python %v", i, got[j], want[j])
			}
		}
		fired += len(got)
	}
	if fired == 0 {
		t.Fatal("fixtures exercise no detector")
	}
}

func TestLongRangeNeedsHistory(t *testing.T) {
	xs := make([]float64, lrMinPoints-1)
	if f := longRange("air_quality", "co2", xs); f != nil {
		t.Fatalf("verdict on %d points: %v", len(xs), f)
	}
	if f := longRange("occupancy", "occ", make([]float64, 144)); f != nil {
		t.Fatal("occupancy has no long-range check")
	}
}
