package main

import (
	"bufio"
	"encoding/json"
	"fmt"
	"math"
	"os"
	"path/filepath"
	"strings"
	"testing"
)

// withPostRules: v2 agent + an htpd_profile with post_rules=<v> ("" = no profile).
func withPostRules(t *testing.T, v string) {
	t.Helper()
	withAgentVersion(t, "v2")
	old := htpdWorkDir
	htpdWorkDir = t.TempDir()
	t.Cleanup(func() { htpdWorkDir = old })
	if v != "" {
		os.WriteFile(filepath.Join(htpdWorkDir, "htpd_profile"), []byte("post_rules="+v+"\n"), 0o644)
	}
}

// a 4 h window ending Tue 2026-10-20 14:55 IST
const postEnd = int64(1792488300)

func ramp(n int, a, b float64) []float64 {
	xs := make([]float64, n)
	for i := range xs {
		xs[i] = a + (b-a)*float64(i)/float64(n-1)
	}
	return xs
}

func wobble(n int, base, amp float64) []float64 {
	xs := make([]float64, n)
	for i := range xs {
		xs[i] = base + amp*math.Sin(float64(i)*1.7)
	}
	return xs
}

var postSensor = func(role, metric, node string) SensorRef {
	return SensorRef{Ref: "S1", Role: role, Metric: metric, Node: node, End: postEnd, Evidence: []Evidence{{ID: "E1"}, {ID: "E4"}}}
}

func agentText(pattern, status, cause, extra string) string {
	return fmt.Sprintf(`{"pattern": "%s", "status": "%s", "observations": ["Value moved [E1,E4]"], "likely_cause": "%s", `+
		`"confidence": 0.7, "event_active": true, "onset": "12:00"%s}`, pattern, status, cause, extra)
}

// Default (no profile key): the model's answer is checked exactly as before, even with a window passed.
func TestPostRulesOffByDefault(t *testing.T) {
	withPostRules(t, "")
	xs := ramp(48, 7.6, 6.2)
	c := checkAgentWin(postSensor("water", "ph", "WM-WQ-KH00-00"), GenieResult{Text: agentText("gradual_decrease", "normal", "acidic_condition", "")}, "", xs)
	if c.Valid || c.Parsed.LikelyCause != "acidic_condition" || c.Parsed.Status != "normal" {
		t.Fatalf("rules off: the off-label answer must stay rejected: valid=%v %+v", c.Valid, c.Parsed)
	}
	for _, r := range c.Repairs {
		if strings.HasPrefix(r, "post-rule") {
			t.Fatalf("post-rule ran without the profile key: %v", c.Repairs)
		}
	}
	if postRules() != nil {
		t.Fatal("postRules() must be nil without the key")
	}
	withAgentVersion(t, "v1") // the v1 agent never gets them, whatever the profile says
	os.WriteFile(filepath.Join(htpdWorkDir, "htpd_profile"), []byte("post_rules=all\n"), 0o644)
	if postRules() != nil {
		t.Fatal("post-rules are v2 only")
	}
}

// The board weakness (2 of 3 chaos runs): water "acidic_condition" with no action -> rejected by the gate. With the
// rules the cause maps to water_quality_issue, the pH limit sets warning, the action is derived, the call is valid.
func TestPostRulesAcidicCause(t *testing.T) {
	withPostRules(t, "all")
	xs := ramp(48, 7.6, 6.2)
	c := checkAgentWin(postSensor("water", "ph", "WM-WQ-KH00-00"), GenieResult{Text: agentText("gradual_decrease", "normal", "acidic_condition", "")}, "", xs)
	if !c.Valid || c.Parsed.LikelyCause != "water_quality_issue" || c.Parsed.Status != "warning" || c.Parsed.Action == "" {
		t.Fatalf("acidic: valid=%v %+v errors=%v repairs=%v", c.Valid, c.Parsed, c.Errors, c.Repairs)
	}
	// quality_cause (after limit set warning) maps it first; the cause rule is the fallback for other statuses
	if !strings.Contains(strings.Join(c.Repairs, "|"), "post-rule quality_cause: likely_cause 'acidic_condition' -> 'water_quality_issue'") {
		t.Fatalf("repair note missing: %v", c.Repairs)
	}
	// a subset: only the cause rule -> status left as the model said
	withPostRules(t, "cause")
	c = checkAgentWin(postSensor("water", "ph", "WM-WQ-KH00-00"), GenieResult{Text: agentText("gradual_decrease", "normal", "acidic_condition", "")}, "", xs)
	if !c.Valid || c.Parsed.Status != "normal" || c.Parsed.LikelyCause != "water_quality_issue" {
		t.Fatalf("cause only: %+v", c.Parsed)
	}
}

func TestPostRulesEachRule(t *testing.T) {
	withPostRules(t, "all")
	on := postRules()
	run := func(role, metric, node string, xs []float64, f Finding) Finding {
		applyPostRules(on, role, metric, node, postEnd, xs, &f)
		return f
	}
	tr := true
	// limit: CO2 last 1200 ppm, model says normal -> warning
	f := run("air_quality", "co2", "SR-AQ-KH00-00", ramp(48, 600, 1200), Finding{Pattern: "gradual_increase", Status: "normal", LikelyCause: "occupancy_load"})
	if f.Status != "warning" {
		t.Fatalf("limit: %+v", f)
	}
	// floor: CO2 sitting at 200 ppm -> sensor_fault / bias
	f = run("air_quality", "co2", "SR-AQ-KH00-00", wobble(48, 200, 3), Finding{Pattern: "stable", Status: "normal", LikelyCause: "normal_conditions"})
	if f.Status != "sensor_fault" || f.LikelyCause != "sensor_fault" || f.FaultKind != "bias" {
		t.Fatalf("floor: %+v", f)
	}
	// glitch: one 25-sigma reading in a calm CO2 window, model reads a critical spike -> normal, not active
	xs := wobble(48, 600, 4)
	xs[30] = 1700
	f = run("air_quality", "co2", "SR-AQ-KH00-00", xs, Finding{Pattern: "spike", Status: "critical", LikelyCause: "indoor_emission_source", EventActive: &tr})
	if f.Status != "normal" || f.LikelyCause != "normal_conditions" || f.EventActive == nil || *f.EventActive {
		t.Fatalf("glitch value: %+v", f)
	}
	// glitch sentinel: a single 0 -> sensor_fault dropout
	xs = wobble(48, 600, 4)
	xs[30] = 0
	f = run("air_quality", "co2", "SR-AQ-KH00-00", xs, Finding{Pattern: "dip", Status: "warning", LikelyCause: "ventilation_insufficient"})
	if f.Status != "sensor_fault" || f.FaultKind != "dropout" || f.LikelyCause != "sensor_fault" {
		t.Fatalf("glitch zero: %+v", f)
	}
	// chatter: PF hovering at 0.85 +-1 %, model says flatline / sensor_fault -> stable / warning, active
	f = run("power", "pf", "EM-KH00-00", wobble(48, 0.85, 0.008), Finding{Pattern: "flatline", Status: "sensor_fault", LikelyCause: "sensor_fault", FaultKind: "stuck"})
	if f.Status != "warning" || f.Pattern != "stable" || f.FaultKind != "" || f.LikelyCause == "sensor_fault" || f.EventActive == nil || !*f.EventActive {
		t.Fatalf("chatter: %+v", f)
	}
	// ... but a PF truly stuck at the limit (no crossings) stays a fault
	stuck := make([]float64, 48)
	for i := range stuck {
		stuck[i] = 0.851
	}
	f = run("power", "pf", "EM-KH00-00", stuck, Finding{Pattern: "flatline", Status: "sensor_fault", LikelyCause: "sensor_fault", FaultKind: "stuck"})
	if f.Status != "sensor_fault" || f.FaultKind != "stuck" {
		t.Fatalf("stuck at limit must stay a fault: %+v", f)
	}
	// rel_power: load 2 -> 9 kW step (range / first-hour mean > 1.5) read as warning -> critical
	xs = make([]float64, 48)
	for i := range xs {
		xs[i] = 2
		if i >= 40 {
			xs[i] = 9
		}
	}
	f = run("power", "power_kw", "SR-EM-KH04-00", xs, Finding{Pattern: "step_increase", Status: "warning", LikelyCause: "load_surge"})
	if f.Status != "critical" {
		t.Fatalf("rel_power: %+v", f)
	}
	// erratic water flow read as warning with an invented cause -> sensor_fault / noise (host dev, 3 rows)
	f = run("water", "flow", "WM-WF-KH98-40", wobble(48, 1, 0.8), Finding{Pattern: "erratic", Status: "warning", LikelyCause: "noisy_flow"})
	if f.Status != "sensor_fault" || f.LikelyCause != "sensor_fault" || f.FaultKind != "noise" {
		t.Fatalf("erratic: %+v", f)
	}
	// water_cause + rel_level: a tank rising past its high level -> tank_overflow_risk, warning
	old := NodeLimitsV2
	NodeLimitsV2 = map[string]TankLimit{"WM-WL-KH00-00": {High: 83, Overflow: 95, FillMin: 30}}
	t.Cleanup(func() { NodeLimitsV2 = old })
	f = run("water", "level", "WM-WL-KH00-00", ramp(48, 40, 88), Finding{Pattern: "gradual_increase", Status: "normal", LikelyCause: "tank_filling"})
	if f.Status != "warning" || f.LikelyCause != "tank_overflow_risk" {
		t.Fatalf("tank: %+v", f)
	}
	// hvac and occupancy are never touched
	f = run("occupancy", "occ", "OC-KH00-00", wobble(48, 0.5, 0.5), Finding{Pattern: "erratic", Status: "warning", LikelyCause: "x"})
	if f.Status != "warning" || f.LikelyCause != "x" {
		t.Fatalf("occupancy touched: %+v", f)
	}
}

// Parity with the offline scorer: replay proofs/2026-10-25_domain_plan/raw/postrules_parity_p1.jsonl
// (scripts/export_parity_p1.py: every stored mixA50 and v2 answer of the dev / rw5dev / test / rw5test sets, its window,
// the prompt's E9 line and the Python P1 rules' result; supersedes the 2026-10-24 track-B fixture).
// Skipped when the fixture is absent (it is local data, not in git). SCE_POSTRULES_PARITY overrides the path.
func TestPostRulesParity(t *testing.T) {
	p := os.Getenv("SCE_POSTRULES_PARITY")
	if p == "" {
		p = filepath.Join("..", "..", "..", "..", "proofs", "2026-10-25_domain_plan", "raw", "postrules_parity_p1.jsonl")
	}
	fh, err := os.Open(p)
	if err != nil {
		t.Skip("parity fixture not found: " + p)
	}
	defer fh.Close()
	withPostRules(t, "all")
	on := postRules()
	old := NodeLimitsV2
	NodeLimitsV2 = map[string]TankLimit{}
	t.Cleanup(func() { NodeLimitsV2 = old })
	type fin struct {
		Pattern     string  `json:"pattern"`
		Status      string  `json:"status"`
		LikelyCause string  `json:"likely_cause"`
		FaultKind   *string `json:"fault_kind"`
		EventActive *bool   `json:"event_active"`
	}
	type row struct {
		ID, Role, Metric, Node string
		End                    int64
		Xs                     []float64
		Prompt                 string
		Tank                   *struct {
			High     float64 `json:"high"`
			Overflow float64 `json:"overflow"`
			FillMin  float64 `json:"fill_min"`
		}
		Before, After fin
		Rules         []string
	}
	sc := bufio.NewScanner(fh)
	sc.Buffer(make([]byte, 1<<20), 1<<22)
	n, nch, bad := 0, 0, 0
	for sc.Scan() {
		var r row
		if err := json.Unmarshal(sc.Bytes(), &r); err != nil {
			t.Fatal(err)
		}
		if r.Tank != nil {
			NodeLimitsV2[r.Node] = TankLimit{High: r.Tank.High, Overflow: r.Tank.Overflow, FillMin: r.Tank.FillMin}
		}
		f := Finding{Pattern: r.Before.Pattern, Status: r.Before.Status, LikelyCause: r.Before.LikelyCause, EventActive: r.Before.EventActive}
		if r.Before.FaultKind != nil {
			f.FaultKind = *r.Before.FaultKind
		}
		ch := applyPostRules(on, r.Role, r.Metric, r.Node, r.End, r.Xs, &f, r.Prompt)
		n++
		if len(ch) > 0 {
			nch++
		}
		want := r.After
		ok := f.Pattern == want.Pattern && f.Status == want.Status && f.LikelyCause == want.LikelyCause
		if want.Status == "sensor_fault" {
			wk := ""
			if want.FaultKind != nil {
				wk = *want.FaultKind
			}
			ok = ok && f.FaultKind == wk
		}
		if want.EventActive != nil {
			ok = ok && f.EventActive != nil && *f.EventActive == *want.EventActive
		}
		if !ok {
			bad++
			if bad <= 5 {
				t.Errorf("%s: go %+v (changes %v) python %+v rules %v", r.ID, f, ch, want, r.Rules)
			}
		}
	}
	t.Logf("parity: %d rows, %d changed by the Go rules, %d mismatches", n, nch, bad)
	if n == 0 || bad > 0 {
		t.Fatalf("parity failed: %d of %d rows differ", bad, n)
	}
}
