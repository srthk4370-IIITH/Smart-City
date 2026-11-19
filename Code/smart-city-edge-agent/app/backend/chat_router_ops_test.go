package main

import (
	"reflect"
	"strings"
	"testing"
	"time"
)

// deploy23: the routes added after the 2026-11-01 board chat sweep (proofs/2026-11-01_chat/VERDICT.md).
func TestChatRouteOps(t *testing.T) {
	latest := []ChatMsg{{Role: "user", Text: "What is the latest incident?"},
		{Role: "assistant", Text: "The most recent incident is INC-0606 Room temperature stuck on (warning)."}}
	two := []ChatMsg{{Role: "user", Text: "last 2"}, {Role: "assistant", Text: "INC-0606 and INC-0605"}}
	cases := []struct {
		q    string
		h    []ChatMsg
		tool string
		act  string
		args map[string]any
	}{
		{"Close all open incidents.", nil, "open_incidents", "refuse", map[string]any{}},
		{"Can you approve INC-0605?", nil, "open_incidents", "refuse", nil},
		{"please dismiss everything", nil, "open_incidents", "refuse", nil},
		{"Why was INC-0605 flagged?", nil, "get_incident", "about", map[string]any{"id": "INC-0605"}},
		{"Tell me about inc-0606.", nil, "get_incident", "about", map[string]any{"id": "INC-0606"}},
		{"Was INC-0605 a real problem or a sensor fault?", nil, "get_incident", "realfault", map[string]any{"id": "INC-0605"}},
		{"What should I do about INC-0605?", nil, "get_incident", "do", nil},
		{"Why did it happen?", latest, "get_incident", "about", map[string]any{"id": "INC-0606"}},
		{"What should I do about it?", latest, "get_incident", "do", map[string]any{"id": "INC-0606"}},
		{"Why did it happen?", two, "", "", nil},  // two incidents named: ambiguous
		{"Why did it happen?", nil, "", "", nil},  // nothing to refer to
		{"Compare INC-0605 and INC-0606", nil, "", "", nil},
		{"How many incidents like INC-0605 this week?", nil, "", "", nil},
		{"Which sensors need maintenance?", nil, "faulty_sensors", "maint", map[string]any{}},
		{"sensors needing repair this week", nil, "faulty_sensors", "maint", map[string]any{"time": map[string]any{"preset": "last_7d"}}},
		{"When was the CO2 sensor in KH level 3 last replaced?", nil, "", "", nil},
		{"What did operators approve in the last 7 days?", nil, "find_incidents", "", map[string]any{"approval": "approved", "time": map[string]any{"preset": "last_7d"}, "limit": 10.0}},
		{"Which incidents were dismissed yesterday?", nil, "find_incidents", "", map[string]any{"approval": "dismissed", "time": map[string]any{"preset": "yesterday"}, "limit": 10.0}},
		{"How many incidents were approved this month?", nil, "count_incidents", "", map[string]any{"approval": "approved", "time": map[string]any{"preset": "this_month"}}},
		{"What if I dismiss this alert?", nil, "", "", nil},
		{"Which incidents need approval?", nil, "open_incidents", "", map[string]any{}},
		{"KH building mein temperature kya hai?", nil, "current_levels", "", map[string]any{"metric": "temp", "location": "KH"}},
		{"What is the overall health of the campus right now?", nil, "open_incidents", "health", map[string]any{}},
		{"How is the campus doing?", nil, "open_incidents", "health", nil},
		{"What happens if the AC setpoint is lowered by 2 degrees?", nil, "what_if", "", map[string]any{"driver": "setpoint", "change_abs": -2.0}},
	}
	for _, c := range cases {
		r, ok := chatRouteQuestion(c.q, c.h, testBuildings)
		if c.tool == "" {
			if ok {
				t.Errorf("%q: routed to %s/%s %v, want the model", c.q, r.Tool, r.Act, r.Args)
			}
			continue
		}
		if !ok || r.Tool != c.tool || r.Act != c.act {
			t.Errorf("%q: got %v %s/%s, want %s/%s", c.q, ok, r.Tool, r.Act, c.tool, c.act)
			continue
		}
		if c.args != nil && !reflect.DeepEqual(r.Args, c.args) {
			t.Errorf("%q: args %v, want %v", c.q, r.Args, c.args)
		}
	}
}

func TestChatRoutedOpsAnswers(t *testing.T) {
	e, r, tools := chatV3Fixture(t)
	chatV3Write(e, "SR-AQ-KH03-03", "co2", 50, func(i int) float64 { return 600 + float64(i) }, "normal")
	sf := chatV3Inc("INC-0012", tools.now.Add(-2*time.Hour), "sensor_fault", wfNeeds, "WE-VN04-00", "temp", "weather", "sensor_fault")
	sf.Steps = []Step{{ID: "s1", Text: "Check the outdoor temperature sensor", State: "open"}}
	ok := chatV3Inc("INC-0013", tools.now.Add(-time.Hour), "warning", wfInProgress, "SR-AQ-KH03-03", "co2", "air_quality", "warning")
	ok.Approval = "approved"
	r.incidents = []*Incident{sf, ok}
	// the substation meter went silent: no new readings, the last value is old
	e.mu.Lock()
	st := e.states[key("EM-CR-SB00-00", "power_kw")]
	st.Last, st.Quality, st.QualityWhy = fp(596.34567), "stale", "no readings"
	e.mu.Unlock()

	for _, c := range []struct{ q, want, not string }{
		{"Close all open incidents.", "I can't do that", ""},
		{"Why was INC-0012 flagged?", "Open checklist: Check the outdoor temperature sensor", ""},
		{"Was INC-0012 a real problem or a sensor fault?", "The AI judged it a sensor fault", ""},
		{"Tell me about INC-0999", "There is no INC-0999 on this device", ""},
		{"Which sensors need maintenance?", "WE-VN04-00 temperature (1 incident, newest [INC-0012])", ""},
		{"Which sensors are faulty?", "still waiting for your decision", ""},
		{"How is the power consumption right now?", "no new reading (sensor silent: no readings); last value 596.3 kW", "596.3 kW (fine)"},
		{"What did operators approve this week?", "[INC-0013]", ""},
		{"What is the overall health of the campus?", "1 incident is waiting for an operator decision (weather 1)", ""},
	} {
		text, tool, routed := tools.chatRouted(c.q, nil)
		if !routed || tool.Name == "" {
			t.Errorf("%q: not routed", c.q)
			continue
		}
		if !strings.Contains(text, c.want) || (c.not != "" && strings.Contains(text, c.not)) {
			t.Errorf("%q: %q (want %q, not %q)", c.q, text, c.want, c.not)
		}
	}
	// follow-up on the incident the previous answer named
	h := []ChatMsg{{Role: "user", Text: "latest incident?"}, {Role: "assistant", Text: "The most recent incident is INC-0012 ..."}}
	if text, _, routed := tools.chatRouted("What should I do about it?", h); !routed || !strings.Contains(text, "[INC-0012]") || !strings.Contains(text, "). Open checklist: Check the outdoor") {
		t.Errorf("follow-up: %v %q", routed, text)
	}
	// highest of a metric whose only sensor is silent: say so (deploy22 fell to the model, 16 s, invented a node id)
	e.mu.Lock()
	e.series[key("SR-AQ-KH03-03", "co2")] = map[int64]float64{}
	co2 := e.states[key("SR-AQ-KH03-03", "co2")]
	co2.Quality = "stale"
	e.mu.Unlock()
	if text, _, routed := tools.chatRouted("What was the highest CO2 reading today?", nil); !routed || !strings.Contains(text, "No CO2 readings were recorded today") ||
		!strings.Contains(text, "SR-AQ-KH03-03") {
		t.Errorf("silent rank: %v %q", routed, text)
	}
}

// list_sensors (model path) printed raw floats ("299.7486223143493"): rounded like get_sensor_history now.
func TestChatListSensorsRounded(t *testing.T) {
	e, _, tools := chatV3Fixture(t)
	e.mu.Lock()
	e.states[key("WM-WL-KH98-00", "level")].Last = fp(299.7486223143493)
	e.mu.Unlock()
	res, err := tools.run("list_sensors", map[string]any{"domain": "water"})
	if err != nil {
		t.Fatal(err)
	}
	found := false
	for _, s := range res["sensors"].([]map[string]any) {
		if s["node"] == "WM-WL-KH98-00" {
			found = s["last"] == "299.7 level"
			if !found {
				t.Errorf("last %q", s["last"])
			}
		}
	}
	if !found {
		t.Error("level sensor missing")
	}
}
