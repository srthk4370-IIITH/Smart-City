package main

import (
	"encoding/json"
	"fmt"
	"math"
	"os"
	"path/filepath"
	"strings"
	"testing"
	"time"
)

// D4 confidence recalibration (features_v2.go ConfidenceRecalV2 / RecalibrateConfidence / applyConfidenceRecal).
// Table and fixtures: proofs/2026-10-21_v2_research/calibration/c1_fit.py.

// Every v2 pattern resolves to a full set of contiguous onset-age rows (-1, then 1..144) with a probability.
func TestD4TableCoversEveryPatternAndAge(t *testing.T) {
	if len(ConfidenceRecalV2) == 0 {
		t.Fatal("D4 table is empty")
	}
	if _, ok := ConfidenceRecalV2["*"]; !ok {
		t.Fatal(`D4 table has no "*" fallback rows`)
	}
	for p, rows := range ConfidenceRecalV2 {
		if len(rows) == 0 || rows[0].MinAge != -1 || rows[0].MaxAge != -1 {
			t.Fatalf("%s: first row must be the no-onset row (-1..-1): %+v", p, rows)
		}
		next := 1
		for _, r := range rows[1:] {
			if r.MinAge != next || r.MaxAge < r.MinAge {
				t.Fatalf("%s: age rows not contiguous at %d: %+v", p, next, r)
			}
			next = r.MaxAge + 1
		}
		if next <= v2MaxN {
			t.Fatalf("%s: ages up to %d not covered (last %d)", p, v2MaxN, next-1)
		}
		for _, r := range rows {
			if r.Conf <= 0 || r.Conf >= 1 || math.IsNaN(r.Conf) {
				t.Fatalf("%s: confidence %v outside (0,1)", p, r.Conf)
			}
		}
	}
	for _, role := range []string{"air_quality", "water", "power", "occupancy", "weather", "hvac"} {
		for _, p := range PatternsV2(role) {
			f := Finding{Pattern: p, Confidence: -7}
			for _, n := range []int{0, 48, 96, 144} {
				if c := RecalibrateConfidence(f, n, 0); c < 0 || c > 1 {
					t.Fatalf("%s/%s n=%d: no calibrated value (%v)", role, p, n, c)
				}
			}
		}
	}
}

// The onset age the Go side computes matches the one the calibration was fitted on (Python onset_age on the
// held-out placement_s24 device answers), and the returned confidence is the table cell for it.
func TestD4MatchesPythonFixtures(t *testing.T) {
	b, err := os.ReadFile(filepath.Join("testdata", "d4_calib_fixtures.json"))
	if err != nil {
		t.Fatal(err)
	}
	var fx []struct {
		Pattern, Onset string
		N              int
		EndHM          string `json:"end_hm"`
		Age            int
		Conf, Raw      float64
	}
	if err := json.Unmarshal(b, &fx); err != nil || len(fx) < 100 {
		t.Fatalf("fixtures: %v (%d)", err, len(fx))
	}
	for i, x := range fx {
		var hh, mm int
		fmt.Sscanf(x.EndHM, "%d:%d", &hh, &mm)
		end := time.Date(2025, 11, 16, hh, mm, 0, 0, IST).Unix()
		age := -1
		if x.Onset != "" {
			age = onsetAge(x.Onset, x.N, end)
		}
		if age != x.Age {
			t.Fatalf("fixture %d %+v: Go onset age %d, Python %d", i, x, age, x.Age)
		}
		got := RecalibrateConfidence(Finding{Pattern: x.Pattern, Onset: x.Onset, Confidence: x.Raw}, x.N, end)
		if math.Abs(got-x.Conf) > 1e-9 {
			t.Fatalf("fixture %d %+v: calibrated %v, want %v", i, x, got, x.Conf)
		}
	}
}

func TestD4AgeBuckets(t *testing.T) {
	end := time.Date(2025, 11, 16, 12, 0, 0, 0, IST).Unix()
	cell := func(p string, age int) float64 {
		for _, r := range ConfidenceRecalV2[p] {
			if age >= r.MinAge && age <= r.MaxAge {
				return r.Conf
			}
		}
		t.Fatalf("no row %s %d", p, age)
		return 0
	}
	cases := []struct {
		onset string
		n     int
		age   int
	}{
		{"12:00", 48, 1},  // onset at the last reading
		{"11:40", 48, 5},  // 20 min
		{"11:35", 48, 6},  // bucket edge
		{"11:30", 48, 7},  // next bucket
		{"08:05", 48, 48}, // window start
		{"08:00", 48, -1}, // just outside a 4 h window
		{"08:00", 96, 49}, // inside an 8 h one
		{"11:42", 48, -1}, // off the 5-min grid
		{"", 48, -1},      // no onset
		{"11:40", 0, -1},  // window length unknown
	}
	for _, c := range cases {
		f := Finding{Pattern: "spike", Onset: c.onset, Confidence: 0.33}
		if got, want := RecalibrateConfidence(f, c.n, end), cell("spike", c.age); got != want {
			t.Fatalf("onset %q n=%d: got %v, want the age-%d cell %v", c.onset, c.n, got, c.age, want)
		}
	}
	// a pattern with no rows of its own uses "*"; enum spelling is normalised
	if got, want := RecalibrateConfidence(Finding{Pattern: "no_such_pattern", Onset: "11:40"}, 48, end), cell("*", 5); got != want {
		t.Fatalf("fallback: %v want %v", got, want)
	}
	if got, want := RecalibrateConfidence(Finding{Pattern: "Step Increase", Onset: "11:40"}, 48, end), cell("step_increase", 5); got != want {
		t.Fatalf("normalised pattern: %v want %v", got, want)
	}
}

// Through the policy gate with a real v2 prompt: the v2 agent's shown confidence is the table value for
// its (pattern, onset age at the prompt's window length); v1 and rejected answers are left alone.
func TestD4AppliedToAgentCall(t *testing.T) {
	end := time.Date(2025, 11, 16, 12, 0, 0, 0, IST).Unix()
	hist := make([]float64, v2Hist)
	for i := range hist {
		hist[i] = 50 + 0.1*math.Sin(float64(i))
		if i >= v2Hist-20 {
			hist[i] += 15 // a step 20 readings before the end
		}
	}
	ai := BuildAgentPromptV2("air_quality", "SR-AQ-KN00-00", "KN building", "rh", hist[v2Hist-96:], end, hist)
	if !strings.Contains(ai.Prompt, ", 96 x 5 min") {
		t.Fatalf("prompt has no 96-reading WINDOW line:\n%s", ai.Prompt)
	}
	s := SensorRef{Ref: "S1", Role: "air_quality", Node: "SR-AQ-KN00-00", Metric: "rh", End: end, Evidence: ai.Evidence, WinN: 96}
	onset := idxTimeN(end, 96, 96-20) // age 20
	out := `{"pattern": "step_increase", "status": "warning", "observations": ["Humidity stepped up [E5,E1]"], ` +
		`"likely_cause": "humidity_control_issue", "confidence": 0.3, "event_active": true, "onset": "` + onset + `"}`
	want := RecalibrateConfidence(Finding{Pattern: "step_increase", Onset: onset}, 96, end)
	if onsetAge(onset, 96, end) != 20 || want == 0.3 {
		t.Fatalf("test setup: age %d, cell %v", onsetAge(onset, 96, end), want)
	}

	withAgentVersion(t, "v2")
	call := checkAgent(s, GenieResult{Text: out}, ai.Prompt+AgentPrefill)
	if !call.Valid {
		t.Fatalf("answer rejected: %v", call.Errors)
	}
	applyConfidenceRecal(&call, s.End, ai.Prompt)
	if call.Parsed.Confidence != want {
		t.Fatalf("v2 shown confidence %v, want calibrated %v", call.Parsed.Confidence, want)
	}
	if !strings.Contains(call.Raw, `"confidence": 0.3`) {
		t.Fatal("the model's own confidence must stay in Raw")
	}

	bad := checkAgent(s, GenieResult{Text: strings.Replace(out, "E5", "E99", 1)}, ai.Prompt)
	applyConfidenceRecal(&bad, s.End, ai.Prompt)
	if bad.Valid || bad.Parsed.Confidence != 0.3 {
		t.Fatalf("rejected answer touched: valid=%v conf=%v", bad.Valid, bad.Parsed.Confidence)
	}

	agentVer = "v1"
	v1 := AgentCall{Valid: true, Parsed: &Finding{Pattern: "step_increase", Onset: onset, Confidence: 0.3}}
	applyConfidenceRecal(&v1, s.End, ai.Prompt)
	if v1.Parsed.Confidence != 0.3 {
		t.Fatal("v1 agent confidence must not be recalibrated")
	}
}
