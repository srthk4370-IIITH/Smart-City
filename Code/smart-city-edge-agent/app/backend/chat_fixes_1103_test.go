package main

import (
	"fmt"
	"strings"
	"testing"
	"time"
)

// 2026-11-03 fixes (proofs/2026-11-03_fixes/README.md).

// chatGuard holds rank_readings, faulty_sensors and what_if to the question's period, as it does the incident tools.
func TestChatGuardTimeSpanMoreTools(t *testing.T) {
	_, _, tools := chatV25Fixture(t)
	g := tools.chatGuardOf("What was the highest CO2 yesterday?", nil)
	if !g.Span.Found() {
		t.Fatalf("no span read")
	}
	for _, name := range []string{"rank_readings", "faulty_sensors", "what_if", "count_incidents"} {
		args := map[string]any{"metric": "co2", "time": map[string]any{"preset": "last_30d"}}
		g.Validate(tools, name, args)
		tv, _ := args["time"].(map[string]any)
		if tv["from"] != g.Span.Args()["from"] || tv["to"] != g.Span.Args()["to"] {
			t.Errorf("%s: time not held to the question: %v", name, args["time"])
		}
	}
	// a call without a time gets the question's period too
	args := map[string]any{"driver": "occ", "change_pct": 50.0}
	g.Validate(tools, "what_if", args)
	if args["time"] == nil {
		t.Errorf("what_if: no time set")
	}
	// tools without a time argument are left alone
	cl := map[string]any{"location": "KH"}
	g.Validate(tools, "current_levels", cl)
	if cl["time"] != nil {
		t.Errorf("current_levels got a time: %v", cl)
	}
	// comparisons keep the model's spans
	g2 := tools.chatGuardOf("compare CO2 yesterday vs today", nil)
	a2 := map[string]any{"metric": "co2", "time": map[string]any{"preset": "today"}}
	g2.Validate(tools, "rank_readings", a2)
	if a2["time"].(map[string]any)["preset"] != "today" {
		t.Errorf("comparison span overridden: %v", a2)
	}
}

// high pH is alkaline (above 8.5), low pH acidic (below 6.5), whatever the retrieved or model wording said.
func TestPHDirectionWording(t *testing.T) {
	high := []SensorRef{{Ref: "S1", Metric: "ph", Xs: []float64{7.4, 8.1, 9.63}}}
	low := []SensorRef{{Ref: "S1", Metric: "ph", Xs: []float64{7.2, 6.4, 5.8}}}
	ok := []SensorRef{{Ref: "S1", Metric: "ph", Xs: []float64{7.1, 7.3}}}
	ctx := []SensorRef{{Ref: "S1", Metric: "ph", Xs: []float64{9.6}, Context: true}, {Ref: "S2", Metric: "tds", Xs: []float64{900}}}
	for _, c := range []struct {
		s    []SensorRef
		want int
	}{{high, 1}, {low, -1}, {ok, 0}, {ctx, 0}, {nil, 0}} {
		if d := phDirection(c.s); d != c.want {
			t.Errorf("phDirection %v = %d, want %d", c.s, d, c.want)
		}
	}
	acid := "The stored water is turning acidic (pH below 6.5), with the source or leak undetermined."
	if got := phFixText(acid, 1); got != "The stored water is turning alkaline (pH above 8.5), with the source or leak undetermined." {
		t.Errorf("high: %q", got)
	}
	if got := phFixText(acid, -1); got != acid {
		t.Errorf("low changed a correct text: %q", got)
	}
	if got := phFixText("Water quality problem: pH keeps falling below the drinking-water limit.", 1); got != "Water quality problem: pH keeps rising above the drinking-water limit." {
		t.Errorf("seed wording: %q", got)
	}
	if got := phFixText("The tank water is alkaline (pH above 9.0).", -1); got != "The tank water is acidic (pH below 6.0)." {
		t.Errorf("low: %q", got)
	}
	// sentences without pH are untouched (power factor "below 0.85" etc.)
	mixed := "Power factor fell below the warning limit. pH rising (S1.E4) to 9.63 (S1.E1), below the critical limit (S1.E1)."
	if got := phFixText(mixed, 1); got != "Power factor fell below the warning limit. pH rising (S1.E4) to 9.63 (S1.E1), above the critical limit (S1.E1)." {
		t.Errorf("mixed: %q", got)
	}
	rep := &Report{Title: "KH building, level 98: pH 9.63 over the critical limit (9.0) (water)", RootCause: acid,
		Checklist: []V3ChecklistItem{{Action: "inspect_water_system", Why: acid}}}
	if !phFixReport(rep, high) || strings.Contains(rep.RootCause, "acidic") || strings.Contains(rep.Checklist[0].Why, "acidic") ||
		rep.Title != "KH building, level 98: pH 9.63 over the critical limit (9.0) (water)" {
		t.Errorf("report: %+v", rep)
	}
	if phFixReport(&Report{RootCause: acid}, low) {
		t.Errorf("low pH report rewritten")
	}
}

// the source badge names the reasoner model the profile runs
func TestReasonerModelLabel(t *testing.T) {
	t.Setenv("SCE_CHAT_THINK", "off")
	t.Setenv("SCE_REASONER_MODEL", "/data/local/tmp/gpu/qwen35_reasoner_q4_0.gguf")
	if l := (htpdReasonLLM{}).Name(); l != "qwen3.5-4b (htpd)" {
		t.Errorf("4B: %q", l)
	}
	t.Setenv("SCE_REASONER_MODEL", "/data/local/tmp/gpu/rsn_v3_2b_q4_0.gguf")
	if l := (htpdReasonLLM{}).Name(); l != "qwen3.5-2b rsn_v3 (htpd)" {
		t.Errorf("2B path: %q", l)
	}
	t.Setenv("SCE_REASONER_MODEL", "/data/local/tmp/gpu/other.gguf")
	t.Setenv("SCE_CHAT_THINK", "adaptive")
	// chat_think=adaptive is the chat format only; the label follows reasoner_model (2B chat: chat_url, chat_gpu.go)
	if l := (htpdChatLLM{}).Name(); l != "qwen3.5-4b chat (htpd)" {
		t.Errorf("adaptive: %q", l)
	}
}

// blind2 Q17, Q30, Q32, Q37 (proofs/2026-11-01_chat/grades16_blind2_d25_2b.json)
func TestChatRouterBlind2Fixes(t *testing.T) {
	e, r, tools := chatV25Fixture(t)
	at := func(h int) time.Time { return tools.now.Add(-time.Duration(h) * time.Hour) }
	var incs []*Incident
	add := func(id string, h int, node, metric, role, approval string) {
		inc := chatV3Inc(id, at(h), "warning", wfClosed, node, metric, role, "warning")
		inc.Approval = approval
		incs = append(incs, inc)
	}
	add("INC-0501", 5, "SR-AQ-KH03-03", "co2", "air_quality", "approved")
	add("INC-0502", 6, "SR-AQ-KH03-03", "co2", "air_quality", "dismissed")
	add("INC-0503", 7, "SR-AC-KH95-02", "room_temp", "hvac", "dismissed")
	add("INC-0504", 8, "EM-CR-SB00-00", "power_kw", "power", "pending")
	add("INC-0505", 30, "WM-WD-KH98-00", "ph", "water", "approved")
	add("INC-0506", 40, "WM-WD-KH98-00", "tds", "water", "dismissed")
	r.incidents = incs
	ask := func(h []ChatMsg, q string) (string, []ChatMsg) {
		q = chatWithNodeOf(chatNormalize(q), e.Meta.Nodes)
		text := ""
		var tl []ChatTool
		if v, ok := tools.chatRouteV25(q, h); ok && v.Text != "" {
			text, tl = v.Text, v.Tools
		} else if tx, x, ok := tools.chatRouted(q, h); ok {
			text, tl = tx, []ChatTool{x}
		} else {
			t.Fatalf("%q: not routed", q)
		}
		return text, append(h, ChatMsg{Role: "user", Text: q}, ChatMsg{Role: "assistant", Text: text, Tools: tl})
	}
	// Q16/Q17: most, then "the one with the fewest" keeps the grouping
	v, h := ask(nil, "Which building had the most incidents in the past 10 days?")
	if !strings.Contains(v, "By building") || !strings.Contains(v, "Most: KH") {
		t.Fatalf("most: %s", v)
	}
	w, _ := ask(h, "what about the one with the fewest")
	if !strings.Contains(w, "Fewest: SB (1)") {
		t.Errorf("fewest: %s", w)
	}
	// a "most serious" follow-up still means the worst incident, not the grouping
	w, _ = ask(h, "which of those is the most serious one?")
	if strings.Contains(w, "By building") {
		t.Errorf("most serious became a grouping: %s", w)
	}
	// Q30: water quality = pH and TDS
	v, _ = ask(nil, "Did any water quality alerts happen in the past fortnight?")
	if !strings.Contains(v, "INC-0505") || !strings.Contains(v, "INC-0506") {
		t.Errorf("water quality: %s", v)
	}
	// Q37: both decisions counted
	// "this week" = since Monday 00:00 of the sensor clock, so INC-0506 (40 h back) is in it only when that is Monday or later
	d := (int(tools.now.Weekday()) + 6) % 7
	wk := time.Date(tools.now.Year(), tools.now.Month(), tools.now.Day()-d, 0, 0, 0, 0, tools.now.Location())
	nWeek, nDis := 5, 2
	if !at(40).Before(wk) {
		nWeek, nDis = 6, 3
	}
	v, _ = ask(nil, "How many incidents were dismissed this week, and how many approved?")
	if !strings.Contains(v, fmt.Sprintf("Of the %d incidents this week", nWeek)) || !strings.Contains(v, fmt.Sprintf("%d were dismissed and 2 approved", nDis)) || !strings.Contains(v, "1 has no decision yet") {
		t.Errorf("approvals: %s", v)
	}
	// no period named: the older route, last 7 days
	if v, _ = ask(nil, "How many incidents were dismissed and how many approved?"); !strings.Contains(v, "3 incidents were dismissed and 2 approved") {
		t.Errorf("approvals, no period: %s", v)
	}
	if v, _ = ask(nil, "How many incidents were dismissed this week?"); !strings.Contains(v, fmt.Sprintf("%d incidents dismissed", nDis)) || strings.Contains(v, "approved") {
		t.Errorf("dismissed only: %s", v)
	}
	// Q31/Q32: occupancy, then "should the AC be on there?" judges the AC against that occupancy
	chatV3Write(e, "SR-AC-KH95-02", "ac_on", 10, func(int) float64 { return 1 }, "normal")
	chatV3Write(e, "SR-OC-GW-KH95-01", "occ", 10, func(int) float64 { return 0 }, "normal")
	v, h = ask(nil, "room KH 3 mein kitne log hain abhi?")
	if !strings.Contains(v, "SR-OC-GW-KH95-01") {
		t.Fatalf("occupancy: %s", v)
	}
	w, _ = ask(h, "then should the AC be on there?")
	if !strings.Contains(w, "SR-AC-KH95-02") || !strings.Contains(w, "empty room") {
		t.Errorf("should the AC be on: %s", w)
	}
}
