package main

import (
	"reflect"
	"strings"
	"testing"
	"time"
)

// deploy24: the routes added after the held-out chat sweep (proofs/2026-11-01_chat/VERDICT_heldout.md).
func TestChatRouteV24(t *testing.T) {
	hist := func(q string) []ChatMsg {
		return []ChatMsg{{Role: "user", Text: q}, {Role: "assistant", Text: "answer"}}
	}
	h48 := hist("How many HVAC incidents in the last 48 hours?")
	chain := append(hist("How many HVAC incidents in the last 48 hours?"), hist("and air quality?")...)
	week := hist("How many critical incidents in the last 7 days?")
	one := []ChatMsg{{Role: "user", Text: "Which incident needs my attention first?"}, {Role: "assistant", Text: "Start with [INC-0618] Suspect CO2 ..."}}
	cases := []struct {
		q    string
		h    []ChatMsg
		tool string
		act  string
		args map[string]any
	}{
		// spans and Hindi day words
		{"How many HVAC incidents in the last 48 hours?", nil, "count_incidents", "span", map[string]any{"domain": "hvac", "time": map[string]any{"_hours": 48.0}}},
		{"how many alerts in the past two days", nil, "count_incidents", "span", map[string]any{"time": map[string]any{"_hours": 48.0}}},
		{"How many critical incidents in the last 7 days?", nil, "count_incidents", "span", map[string]any{"severity": []any{"critical"}, "time": map[string]any{"preset": "last_7d"}}},
		{"How many incidents in the last 12 hours?", nil, "count_incidents", "span", map[string]any{"time": map[string]any{"_hours": 12.0}}},
		{"Kal kitne HVAC alerts aaye the?", nil, "count_incidents", "span", map[string]any{"domain": "hvac", "time": map[string]any{"preset": "yesterday"}}},
		{"Kitne incidents aaj hue?", nil, "count_incidents", "span", map[string]any{"time": map[string]any{"preset": "today"}}},
		{"How many CO2 incidents this week?", nil, "count_incidents", "span", map[string]any{"metric": "co2", "time": map[string]any{"preset": "last_7d"}}},
		// counts the model keeps
		{"How many incidents?", nil, "", "", nil},
		{"Which domain had the most incidents in the last 48 hours?", nil, "", "", nil},
		{"How many incidents this week were sensor faults and how many were real problems?", nil, "", "", nil},
		{"How many incidents in KH this week?", nil, "", "", nil},
		// follow-ups on a span count
		{"and air quality?", h48, "count_incidents", "span", map[string]any{"domain": "air_quality", "time": map[string]any{"_hours": 48.0}}},
		{"which of those are still pending?", chain, "find_incidents", "span", map[string]any{"domain": "air_quality", "workflow": wfNeeds, "limit": 10.0, "time": map[string]any{"_hours": 48.0}}},
		{"which ones?", week, "find_incidents", "span", map[string]any{"severity": []any{"critical"}, "limit": 10.0, "time": map[string]any{"preset": "last_7d"}}},
		{"how many of them were in water?", week, "count_incidents", "span", map[string]any{"domain": "water", "severity": []any{"critical"}, "time": map[string]any{"preset": "last_7d"}}},
		{"and?", h48, "", "", nil},
		{"which ones?", hist("Which domains have open incidents right now?"), "", "", nil},
		// summary, priority
		{"Give me a quick summary of what happened on campus in the past 2 days.", nil, "count_incidents", "summary", map[string]any{"time": map[string]any{"_hours": 48.0}}},
		{"Summarise today", nil, "count_incidents", "summary", map[string]any{"time": map[string]any{"preset": "today"}}},
		{"What happened?", nil, "", "", nil},
		{"Which incident needs my attention first?", nil, "open_incidents", "top", map[string]any{}},
		{"What is the most urgent alert in water?", nil, "open_incidents", "top", map[string]any{"domain": "water"}},
		{"When was the first incident today?", nil, "", "", nil},
		{"explain why", one, "get_incident", "about", map[string]any{"id": "INC-0618"}},
		{"is it a real problem?", one, "get_incident", "realfault", map[string]any{"id": "INC-0618"}},
		// state questions without "now", limits, Hindi faulty, what-if targets
		{"wind sped on the roof?", nil, "current_levels", "", map[string]any{"metric": "wind"}},
		{"is the tank about to overflow", nil, "current_levels", "", map[string]any{"metric": "level"}},
		{"Is anything wrong with the feeder power factor?", nil, "current_levels", "", map[string]any{"metric": "pf"}},
		{"Is the CO2 sensor faulty?", nil, "", "", nil},
		{"What are the CO2 alert limits?", nil, "", "", nil},
		{"Show the 3 most recent critical alerts", nil, "recent_incidents", "", map[string]any{"limit": 3.0, "severity": []any{"critical"}}},
		{"Mujhe batao kaunse sensors kharab hain", nil, "faulty_sensors", "", map[string]any{}},
		{"What if outdoor temperature rises to 42 C?", nil, "what_if", "", map[string]any{"driver": "temp", "_to": 42.0, "_domain": "weather"}},
		{"what if occupancy goes to 80", nil, "", "", nil},
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
			t.Errorf("%q: got %v %s/%s %v, want %s/%s", c.q, ok, r.Tool, r.Act, r.Args, c.tool, c.act)
			continue
		}
		if c.args != nil && !reflect.DeepEqual(r.Args, c.args) {
			t.Errorf("%q: args %v, want %v", c.q, r.Args, c.args)
		}
	}
}

func TestChatWithNode(t *testing.T) {
	nodes := map[string]NodeInfo{
		"SR-AC-KH02-24":    {Role: "hvac", Building: "KH", Level: "02"},
		"SR-AC-KH03-15":    {Role: "hvac", Building: "KH", Level: "03"},
		"SR-AQ-KH03-03":    {Role: "air_quality", Building: "KH", Level: "03"},
		"SR-EM-KH04-01":    {Role: "power", Building: "KH", Level: "04"},
		"SR-OC-GW-KH95-01": {Role: "occupancy", Building: "KH", Level: "95"},
	}
	for q, want := range map[string]string{
		"Has the KH level 2 AC unit 24 had repeated problems?": "SR-AC-KH02-24",
		"CO2 sensor 3 on level 3":                              "SR-AQ-KH03-03",
		"unit 1 in KH":                                         "", // two nodes end in 01: ambiguous
		"How is SR-AC-KH03-15 doing, unit 15?":                 "",
		"What is the temperature on level 2?":                  "",
	} {
		got := chatWithNodeOf(q, nodes)
		if want == "" && got != q || want != "" && !strings.HasSuffix(got, " (sensor "+want+")") || want != "" && strings.Contains(got, "level 2") {
			t.Errorf("%q -> %q, want node %q", q, got, want)
		}
	}
}

func TestChatRoutedV24Answers(t *testing.T) {
	e, r, tools := chatV3Fixture(t)
	now := tools.now
	a := chatV3Inc("INC-0101", now.Add(-30*time.Hour), "warning", wfNeeds, "SR-AC-KH02-24", "room_temp", "hvac", "warning")
	b := chatV3Inc("INC-0102", now.Add(-60*time.Hour), "critical", wfClosed, "SR-AC-KH02-24", "room_temp", "hvac", "critical")
	c := chatV3Inc("INC-0103", now.Add(-2*time.Hour), "sensor_fault", wfNeeds, "SR-AQ-KH03-03", "co2", "air_quality", "sensor_fault")
	a.Approval, b.Approval, c.Approval = "pending", "approved", "pending"
	r.incidents = []*Incident{b, a, c}
	_ = e
	h48 := []ChatMsg{{Role: "user", Text: "How many HVAC incidents in the last 48 hours?"}, {Role: "assistant", Text: "x"}}
	for _, c := range []struct {
		q    string
		h    []ChatMsg
		want []string
	}{
		{"How many HVAC incidents in the last 48 hours?", nil, []string{"1 HVAC incident in the last 2 days (", " to "}},
		{"How many HVAC incidents in the last 3 days?", nil, []string{"2 HVAC incidents in the last 3 days"}},
		{"and air quality?", h48, []string{"1 air quality incident in the last 2 days"}},
		{"which of those are pending?", h48, []string{"1 HVAC incident waiting for your decision", "[INC-0101]"}},
		{"Give me a summary of the past 2 days", nil, []string{"Summary in the last 2 days", "2 incidents", "By severity:", "Newest: [INC-0103]", "2 incidents are waiting"}},
		{"Which incident needs my attention first?", nil, []string{"Start with [INC-0103]", "of the 2 incidents waiting"}},
	} {
		text, tool, routed := tools.chatRouted(c.q, c.h)
		if !routed || tool.Name == "" {
			t.Errorf("%q: not routed", c.q)
			continue
		}
		for _, w := range c.want {
			if !strings.Contains(text, w) {
				t.Errorf("%q: %q (want %q)", c.q, text, w)
			}
		}
		if strings.Contains(tool.Args, "_hours") {
			t.Errorf("%q: relative span not resolved: %s", c.q, tool.Args)
		}
	}
	// the priority answer names exactly one incident, so a follow-up can refer to it
	text, _, _ := tools.chatRouted("Which incident needs my attention first?", nil)
	if ids := chatIDs(text); len(ids) != 1 {
		t.Errorf("priority answer names %v", ids)
	}
	// a what-if target becomes a change from the driver's latest reading
	rt := chatRoute{Tool: "what_if", Args: map[string]any{"driver": "temp", "_to": 42.0, "_domain": "weather"}}
	st := r.eng.states[key("WE-VN04-00", "temp")]
	st.Last = fp(30)
	if !tools.chatPrepV24(&rt) || rt.Args["change_abs"] != 12.0 || rt.Args["location"] != "WE-VN04-00" || rt.Args["_to"] != nil {
		t.Errorf("what-if target: %v", rt.Args)
	}
}
