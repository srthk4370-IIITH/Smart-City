package main

import "testing"

func TestChatPeakQuestion(t *testing.T) {
	hist := []ChatMsg{{Role: "user", Text: "How are co2 levels looking today"}, {Role: "assistant", Text: "49 incidents involved CO2 today."}}
	cases := []struct {
		q              string
		h              []ChatMsg
		metric, preset string
		low, ok        bool
	}{
		{"Highest spike today", hist, "co2", "today", false, true},
		{"What was the highest CO2 yesterday?", nil, "co2", "yesterday", false, true},
		{"lowest water level this week", nil, "level", "last_7d", true, true},
		{"Which room was hottest today?", nil, "temp", "today", false, true},
		{"peak power load in the last 24 hours", nil, "power_kw", "last_24h", false, true},
		{"How many incidents were there today?", hist, "", "", false, false},
		{"What is the worst incident today?", nil, "", "", false, false},
	}
	for _, c := range cases {
		m, p, low, ok := chatPeakQuestion(c.q, c.h)
		if m != c.metric || p != c.preset || low != c.low || ok != c.ok {
			t.Errorf("%q: got %q %q %v %v, want %q %q %v %v", c.q, m, p, low, ok, c.metric, c.preset, c.low, c.ok)
		}
	}
}
