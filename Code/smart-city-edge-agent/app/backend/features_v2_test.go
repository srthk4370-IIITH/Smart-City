package main

import (
	"encoding/json"
	"os"
	"strings"
	"testing"
	"time"
)

type v2Fixture struct {
	Kind, Tag, Role, Node, Location, Metric, Prompt string
	N                                               int
	End                                             int64
	Hist, Xs                                        []float64
	Ctx                                             *HVACCtx
	Rule                                            *struct {
		Pattern string
		Onset   int
		Active  bool
		Status  string
		Cause   string
		Action  string
	}
	ExcCount *int     `json:"exc_count"`
	LongView []string `json:"long_view"`
}

func loadV2Fixtures(t *testing.T) ([]v2Fixture, map[string]TankLimit) {
	raw, err := os.ReadFile("testdata/v2_prompt_fixtures.json")
	if err != nil {
		t.Fatal(err)
	}
	var fx struct {
		Meta struct {
			NodeLimits map[string]TankLimit `json:"node_limits"`
		} `json:"meta"`
		Fixtures []v2Fixture `json:"fixtures"`
	}
	if err := json.Unmarshal(raw, &fx); err != nil {
		t.Fatal(err)
	}
	return fx.Fixtures, fx.Meta.NodeLimits
}

func firstDiff(t *testing.T, what, got, want string) {
	for i := 0; i < len(got) || i < len(want); i++ {
		if i >= len(got) || i >= len(want) || got[i] != want[i] {
			lo := i - 80
			if lo < 0 {
				lo = 0
			}
			t.Errorf("%s: mismatch at byte %d:\n go: %q\n py: %q", what, i, got[lo:min(len(got), i+60)], want[lo:min(len(want), i+60)])
			return
		}
	}
}

// v2 prompts built here must be byte-identical to training (features_v2.agent_prompt and the HVAC path of
// hvac_adapter.make_examples); fixtures from training/v2/make_go_fixtures.py.
func TestPromptParityV2(t *testing.T) {
	fx, limits := loadV2Fixtures(t)
	saved := NodeLimitsV2
	NodeLimitsV2 = limits
	defer func() { NodeLimitsV2 = saved }()
	if len(fx) < 250 {
		t.Fatalf("only %d fixtures", len(fx))
	}
	bad, badRule, roles, tank, e9, e10 := 0, 0, map[string]int{}, 0, 0, 0
	for _, f := range fx {
		roles[f.Role]++
		var got AgentInputV2
		if f.Kind == "hvac" {
			c := *f.Ctx
			c.End = f.End
			got = BuildHVACPromptV2(f.Node, f.Location, f.Xs, c, f.Hist)
			st := hvacStats(f.Xs, c)
			p, on, act := ClassifyHVAC(f.Xs, c, st)
			s := HVACStatusOf(p, f.Xs, c, st, on)
			cs := HVACCauseOf(p, st)
			if p != f.Rule.Pattern || on != f.Rule.Onset || act != f.Rule.Active || s != f.Rule.Status || cs != f.Rule.Cause || HVACActionOf(cs, s) != f.Rule.Action {
				badRule++
				if badRule <= 3 {
					t.Errorf("hvac rule %s %s: go %s/%d/%v/%s/%s py %+v", f.Node, f.Tag, p, on, act, s, cs, *f.Rule)
				}
			}
		} else {
			got = BuildAgentPromptV2(f.Role, f.Node, f.Location, f.Metric, f.Hist[len(f.Hist)-f.N:], f.End, f.Hist)
		}
		if got.N != f.N {
			t.Errorf("%s: N %d want %d", f.Node, got.N, f.N)
		}
		if f.ExcCount != nil && f.Role != "occupancy" && got.Hist.ExcCount != *f.ExcCount {
			t.Errorf("%s %s: E10 count %d want %d", f.Node, f.Metric, got.Hist.ExcCount, *f.ExcCount)
		}
		if got.Prompt != f.Prompt {
			bad++
			if bad <= 4 {
				firstDiff(t, f.Kind+" "+f.Node+"/"+f.Metric+" "+f.Tag, got.Prompt, f.Prompt)
			}
		}
		if strings.Contains(f.Prompt, "\nTANK: ") {
			tank++
		}
		if len(f.LongView) > 0 {
			e9++
		}
		if f.ExcCount != nil && *f.ExcCount > 1 {
			e10++
		}
	}
	t.Logf("%d v2 fixtures %v (tank %d, E9 findings %d, E10 >1 %d): %d prompt mismatches, %d HVAC rule mismatches", len(fx), roles, tank, e9, e10, bad, badRule)
	if len(roles) < 6 || tank == 0 || e9 == 0 || e10 == 0 {
		t.Errorf("fixtures do not cover every role / TANK / E9 / E10")
	}
	if bad > 0 || badRule > 0 {
		t.Fail()
	}
}

// At N = 48 the v2 user turn up to E8 equals the v1 user turn (as checks_v2.v1_prefix_equal asserts in Python).
func TestV2PrefixEqualsV1At48(t *testing.T) {
	fx, _ := loadV2Fixtures(t)
	n := 0
	for _, f := range fx {
		if f.Kind == "hvac" || len(f.Hist) < 48 || f.Role == "water" && f.Metric == "level" {
			continue
		}
		xs := f.Hist[len(f.Hist)-48:]
		v1 := BuildAgentPrompt(f.Role, f.Node, f.Location, f.Metric, xs, f.End).Prompt
		v2 := BuildAgentPromptV2(f.Role, f.Node, f.Location, f.Metric, xs, f.End, f.Hist).Prompt
		u1 := v1[strings.Index(v1, "NODE: "):strings.LastIndex(v1, "<|eot_id|>")]
		u2 := v2[strings.Index(v2, "NODE: "):strings.Index(v2, "\nE9 ")]
		if u1 != u2 {
			t.Fatalf("%s/%s: v2 user turn at N=48 differs from v1", f.Node, f.Metric)
		}
		n++
	}
	if n < 50 {
		t.Fatalf("only %d checked", n)
	}
}

func TestV2SchemaAndActions(t *testing.T) {
	h := OutputSchemaHintV2("water")
	for _, s := range []string{"tank_overflow_risk", "fill_valve_stuck", "quantised", "event_active (true|false)", "observations (1-2"} {
		if !strings.Contains(h, s) {
			t.Errorf("water schema hint lacks %q", s)
		}
	}
	if strings.Contains(h, "switch_off_ac") || !strings.Contains(OutputSchemaHintV2("hvac"), "|switch_off_ac)") {
		t.Errorf("switch_off_ac must be offered to the HVAC agent only")
	}
	cases := []struct{ role, cause, status, want string }{
		{"water", "tank_overflow_risk", "critical", "inspect_water_system"},
		{"water", "fill_valve_stuck", "warning", "inspect_water_system"},
		{"water", "tank_filling", "normal", "monitor"},
		{"hvac", "unoccupied_running", "warning", "switch_off_ac"},
		{"hvac", "high_heat_load", "critical", "inspect_hvac"},
		{"hvac", "normal_operation", "warning", "monitor"},
		{"hvac", "sensor_fault", "sensor_fault", "check_sensor"},
		{"power", "load_surge", "critical", "inspect_electrical"},
	}
	for _, c := range cases {
		if got := ActionOfRole(c.role, c.cause, c.status); got != c.want {
			t.Errorf("ActionOfRole(%s,%s,%s) = %s want %s", c.role, c.cause, c.status, got, c.want)
		}
	}
	for r, cs := range Causes { // v1 mapping untouched
		for _, c := range cs {
			for _, s := range []string{"normal", "warning", "critical", "sensor_fault"} {
				if ActionOfRole(r, c, s) != ActionOf(c, s) {
					t.Errorf("v1 cause %s/%s changed", r, c)
				}
			}
		}
	}
	if len(CausesV2["water"]) != len(Causes["water"])+2 || len(Causes["water"]) != 9 {
		t.Errorf("v1 water causes must stay as the deployed prompt prints them")
	}
}

func TestLadder(t *testing.T) {
	for _, c := range []struct {
		stage, early, status string
		age, n               int
	}{
		{"early", "flatline", "critical", -1, 48},         // the alert path is 4 h for all
		{"1.5h", "gradual_increase", "critical", -1, 48},  // trends: 4 h, severity alone does not lengthen
		{"3h", "exponential_increase", "warning", 30, 48}, // age 30 + 12 baseline fits in 4 h
		{"3h", "exponential_increase", "warning", 44, 60}, // onset 44 readings back: 56 -> 60 keeps it inside
		{"1.5h", "spike", "warning", -1, 96},              // transients: 8 h at refinement
		{"1.5h", "step_increase", "normal", -1, 48},       // steps: 4 h at 1.5 h, 8 h at 3 h
		{"3h", "step_increase", "normal", -1, 96},
		{"1.5h", "erratic", "warning", -1, 48}, // noisy: 12 h only at 3 h
		{"3h", "oscillation", "warning", -1, 144},
		{"1.5h", "flatline", "sensor_fault", -1, 144},      // flat / fault on flat or noisy: 12 h
		{"3h", "gradual_decrease", "sensor_fault", -1, 96}, // other faults: 8 h
		{"3h", "", "warning", -1, 96},                      // no early pattern: 8 h
		{"3h", "stable", "normal", 200, 144},               // capped at 12 h
		{"3h", "off_hours_presence", "warning", -1, 48},    // occupancy: 4 h
		{"1.5h", "stable", "critical", -1, 96},             // stable yet critical: unrecognised, 8 h
		{"3h", "stable", "critical", -1, 96},
		{"3h", "stable", "normal", -1, 48},
		{"3h", "off_hours_presence", "warning", 60, 72},
	} {
		if got := WindowN(c.stage, c.early, c.status, c.age); got != c.n {
			t.Errorf("WindowN(%s,%s,%s,%d) = %d want %d", c.stage, c.early, c.status, c.age, got, c.n)
		}
	}
	// event age from the latest finding's onset: the 4 h alert window ended at 10:00 (onset 09:20 = 9
	// readings back incl. 10:00), refined 3 h later = 36 more readings
	end0 := time.Date(2026, 10, 12, 10, 0, 0, 0, IST).Unix()
	if a := eventAge(Finding{Onset: "09:20"}, true, end0, end0, end0+36*300); a != 45 {
		t.Errorf("eventAge with onset = %d want 45", a)
	}
	// an onset dated from the 12 h lines, 7 h before the previous window end: 84 + 18 readings
	if a := eventAge(Finding{Onset: "03:00"}, true, end0, end0, end0+18*300); a != 103 {
		t.Errorf("eventAge with an old onset = %d want 103", a)
	}
	if a := eventAge(Finding{}, true, end0, end0, end0+18*300); a != 30 {
		t.Errorf("eventAge without onset = %d want 30", a)
	}
	if ValidV2N(144, 100) != 96 || ValidV2N(50, 200) != 48 || ValidV2N(10, 200) != 24 {
		t.Errorf("ValidV2N")
	}
}
