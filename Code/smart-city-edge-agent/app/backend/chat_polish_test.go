package main

import (
	"encoding/json"
	"os"
	"path/filepath"
	"strings"
	"testing"
	"time"
)

// 2026-11-20 chat polish (proofs/2026-11-19_prod_audit/HANDS_ON.md C1-C9, F3/F4): sensor lookup by place words, context
// bleed, silent sensors, forecast, false alarms, which-first, asked format, reasoner routing, plain words, sessions.

func chatPolishAsk(t *testing.T, tools chatTools, q string, h []ChatMsg) (chatV25, bool) {
	t.Helper()
	q = chatNormalize(q)
	if v, ok := tools.chatRouteV25(q, h); ok && v.Text != "" {
		return v, true
	}
	if tx, tl, ok := tools.chatRouted(q, h); ok {
		return chatV25{tx, []ChatTool{tl}}, true
	}
	return chatV25{}, false
}

func TestChatPolishSensorLookup(t *testing.T) {
	e, _, tools := chatV25Fixture(t)
	chatV3Write(e, "SR-AQ-KH03-03", "co2", 60, func(i int) float64 {
		if i == 40 {
			return 912
		}
		return 600 + float64(i%5)
	}, "normal")
	for _, loc := range []string{"KH03", "KH 03", "KH level 03", "KH level 3", "level 3", "KH building level 03", "kh 3", "level 3 of KH"} {
		res, err := tools.run("rank_readings", map[string]any{"metric": "co2", "location": loc, "time": map[string]any{"preset": "last_24h"}})
		if err != nil {
			t.Errorf("location %q: %v", loc, err)
			continue
		}
		items, _ := res["items"].([]map[string]any)
		found := false
		for _, it := range items {
			found = found || it["node"] == "SR-AQ-KH03-03"
		}
		if !found {
			t.Errorf("location %q: SR-AQ-KH03-03 missing from %v", loc, items)
		}
	}
	// another level must not match
	res, err := tools.run("rank_readings", map[string]any{"metric": "co2", "location": "KH level 03", "time": map[string]any{"preset": "last_24h"}})
	if err == nil {
		for _, it := range res["items"].([]map[string]any) {
			if !strings.Contains(it["node"].(string), "KH03") {
				t.Errorf("KH level 03 matched %v", it)
			}
		}
	}
	// the question itself: highest value and when
	v, ok := chatPolishAsk(t, tools, "What was the highest CO2 reading in KH level 03 in the last 4 hours and when?", nil)
	if !ok || !strings.Contains(v.Text, "912") || !strings.Contains(v.Text, "SR-AQ-KH03-03") || strings.Contains(v.Text, "No CO2 sensor") {
		t.Errorf("highest + when: %v %s", ok, v.Text)
	}
}

func TestChatPolishNoContextBleed(t *testing.T) {
	_, r, tools := chatV25Fixture(t)
	r.incidents = []*Incident{
		chatV3Inc("INC-0010", tools.now.Add(-2*time.Hour), "warning", wfNeeds, "AC-KH03", "room_temp", "hvac", "warning"),
		chatV3Inc("INC-0011", tools.now.Add(-3*time.Hour), "warning", wfNeeds, "AC-KH03", "room_temp", "hvac", "warning"),
	}
	prev, ok := chatPolishAsk(t, tools, "any incidents on AC-KH03 today?", nil)
	if !ok || !strings.Contains(prev.Text, "INC-0010") {
		t.Fatalf("setup: %v %s", ok, prev.Text)
	}
	h := []ChatMsg{{Role: "user", Text: "any incidents on AC-KH03 today?"}, {Role: "assistant", Text: prev.Text, Tools: prev.Tools}}
	for _, q := range []string{"how many false alarms this week", "when will CO2 cross 1000 ppm", "Which sensors are not sending data right now?"} {
		v, _ := chatPolishAsk(t, tools, q, h)
		if strings.Contains(v.Text, "INC-0010") || strings.Contains(v.Text, "INC-0011") {
			t.Errorf("%q reused the previous incident list: %s", q, v.Text)
		}
	}
	// "this week" is a period, not a pronoun; real back-references still follow
	if chatIsFollowUp("how many false alarms this week", chatPlace{Level: -1, Unit: -1}, nil, chatSpan{}) {
		t.Error("'this week' read as a back-reference")
	}
	for _, q := range []string{"and yesterday?", "why?", "that sensor", "what about those?"} {
		if !chatIsFollowUp(q, chatPlace{Level: -1, Unit: -1}, nil, chatSpan{}) {
			t.Errorf("%q should follow up", q)
		}
	}
}

func TestChatPolishNotSending(t *testing.T) {
	now := int64(1_800_000_000)
	st := []SensorState{
		{Node: "WQ-1", Metric: "ph", Location: "tank"},
		{Node: "WQ-1", Metric: "tds", Location: "tank"},
		{Node: "FM-1", Metric: "flow", Location: "main"},
		{Node: "SR-1", Metric: "co2", Location: "lab"},
		{Node: "INJ", Metric: "co2", Injected: true},
	}
	seen := map[string]int64{key("WQ-1", "ph"): now - 9000, key("WQ-1", "tds"): now - 9000, key("SR-1", "co2"): now - 60}
	rows := chatHealthRows(st, seen, now, 1800, true)
	if len(rows) != 4 {
		t.Fatalf("rows %v", rows)
	}
	states := map[string]string{}
	for _, r := range rows {
		states[r.Node+r.Metric] = r.State
	}
	if states["WQ-1ph"] != "stale" || states["FM-1flow"] != "missing" || states["SR-1co2"] != "fresh" {
		t.Fatalf("states %v", states)
	}
	_, _, tools := chatV25Fixture(t)
	v := tools.chatSayNotSending(rows, 1800)
	for _, want := range []string{"pH WQ-1", "TDS WQ-1", "2.5 h", "never reported", "water flow FM-1"} {
		if !strings.Contains(v.Text, want) {
			t.Errorf("answer lacks %q: %s", want, v.Text)
		}
	}
	if strings.Contains(v.Text, "no faults") {
		t.Errorf("answer: %s", v.Text)
	}
	ok := tools.chatSayNotSending(chatHealthRows(st[3:4], seen, now, 1800, true), 1800)
	if !strings.Contains(ok.Text, "Every one of the 1 sensors") {
		t.Errorf("all fresh: %s", ok.Text)
	}
	// through the router: the question is answered from the data-health logic, not "no faults"
	for _, q := range []string{"Which sensors are not sending data right now?", "which sensors have stopped reporting?", "any silent sensors?"} {
		a, ok := chatPolishAsk(t, tools, q, nil)
		if !ok || !strings.Contains(a.Text, "sensor") || strings.Contains(a.Text, "no faults") {
			t.Errorf("%q: %v %s", q, ok, a.Text)
		}
	}
}

func TestChatPolishForecast(t *testing.T) {
	e, _, tools := chatV25Fixture(t)
	chatV3Write(e, "SR-AQ-KH03-03", "co2", 60, func(i int) float64 { return 600 + 5*float64(i) }, "normal") // +60 ppm per hour, now 895
	v, ok := chatPolishAsk(t, tools, "If CO2 keeps rising at this rate, when will it cross 1000 ppm?", nil)
	if !ok || !strings.Contains(v.Text, "around") || !strings.Contains(v.Text, "SR-AQ-KH03-03") || len(v.Tools) == 0 || v.Tools[0].Name != "forecast_crossing" {
		t.Fatalf("rising: %v %s %v", ok, v.Text, v.Tools)
	}
	if !strings.Contains(v.Text, "1.7 hours") && !strings.Contains(v.Text, "hours") {
		t.Errorf("no time to crossing: %s", v.Text)
	}
	chatV3Write(e, "SR-AQ-KH03-03", "co2", 60, func(i int) float64 { return 600 }, "normal")
	v, ok = chatPolishAsk(t, tools, "when will CO2 cross 1000 ppm?", nil)
	if !ok || !strings.Contains(v.Text, "not rising") {
		t.Errorf("flat: %v %s", ok, v.Text)
	}
	chatV3Write(e, "SR-AQ-KH03-03", "co2", 60, func(i int) float64 { return 1100 }, "normal")
	v, _ = chatPolishAsk(t, tools, "when will CO2 cross 1000 ppm?", nil)
	if !strings.Contains(v.Text, "already") {
		t.Errorf("already above: %s", v.Text)
	}
}

func TestChatPolishFalseAlarms(t *testing.T) {
	_, r, tools := chatV25Fixture(t)
	a := chatV3Inc("INC-0020", tools.now.Add(-5*time.Hour), "warning", wfClosed, "SR-AQ-KH03-03", "co2", "air_quality", "warning")
	a.Outcome = "false_alarm"
	b := chatV3Inc("INC-0021", tools.now.Add(-4*time.Hour), "warning", wfClosed, "SR-AQ-KH03-03", "co2", "air_quality", "warning")
	b.Outcome = "fixed_by_action"
	c := chatV3Inc("INC-0022", tools.now.Add(-3*time.Hour), "warning", wfClosed, "SR-AQ-KH03-03", "co2", "air_quality", "warning")
	c.Approval, c.Outcome = "dismissed", "false_alarm"
	d := chatV3Inc("INC-0023", tools.now.Add(-2*time.Hour), "warning", wfNeeds, "SR-AQ-KH03-03", "co2", "air_quality", "warning")
	r.incidents = []*Incident{a, b, c, d}
	v, ok := chatPolishAsk(t, tools, "how many false alarms this week", nil)
	if !ok || !strings.Contains(v.Text, "2 incidents were dismissed or closed as a false alarm") || !strings.Contains(v.Text, "INC-0020") ||
		!strings.Contains(v.Text, "INC-0022") || strings.Contains(v.Text, "INC-0021") || strings.Contains(v.Text, "INC-0023") {
		t.Errorf("false alarms: %v %s", ok, v.Text)
	}
	r.incidents = []*Incident{b}
	v, _ = chatPolishAsk(t, tools, "any false alarms today?", nil)
	if !strings.Contains(v.Text, "No incident was dismissed or closed as a false alarm") {
		t.Errorf("none: %s", v.Text)
	}
}

func TestChatPolishWhichFirst(t *testing.T) {
	e, r, tools := chatV25Fixture(t)
	old1 := chatV3Inc("INC-0018", tools.now.Add(-30*time.Hour), "critical", wfNeeds, "WQ-1", "ph", "water", "critical")
	old2 := chatV3Inc("INC-0019", tools.now.Add(-28*time.Hour), "critical", wfNeeds, "WQ-1", "ph", "water", "critical")
	pmNode := ""
	for id, n := range r.eng.Meta.Nodes {
		for _, m := range n.Metrics {
			if m == "pm25" && (pmNode == "" || id < pmNode) {
				pmNode = id
			}
		}
	}
	live := chatV3Inc("INC-0026", tools.now.Add(-1*time.Hour), "critical", wfNeeds, pmNode, "pm25", "air_quality", "critical")
	warn := chatV3Inc("INC-0027", tools.now.Add(-30*time.Minute), "warning", wfNeeds, "SR-AQ-KH03-03", "co2", "air_quality", "warning")
	r.incidents = []*Incident{old1, old2, live, warn}
	chatV3Write(e, pmNode, "pm25", 10, func(int) float64 { return 300 }, "critical")
	v, ok := chatPolishAsk(t, tools, "Which critical first?", nil)
	if !ok || !strings.Contains(v.Text, "Start with [INC-0026]") {
		t.Fatalf("first: %v %s", ok, v.Text)
	}
	if !strings.Contains(v.Text, "[INC-0019]") || strings.Contains(v.Text, "INC-0027") || !strings.Contains(v.Text, "INC-0018") {
		t.Errorf("duplicates should collapse to the newest: %s", v.Text)
	}
	if strings.Count(v.Text, "[INC-0018]")+strings.Count(v.Text, "[INC-0019]") != 1 {
		t.Errorf("same-sensor duplicates listed twice: %s", v.Text)
	}
}

func TestChatPolishFormat(t *testing.T) {
	long := "[INC-0023] Power factor low (warning, 2026-11-19 10:00). Root cause: the capacitor bank is out. Flagged: EM-CR-SB00-00 power factor, pattern drift. Open checklist: check the bank; call the electrician. Someone tapped I'm on it and its checklist is in progress."
	cases := []struct {
		q    string
		max  int
		want string
	}{
		{"Summarise INC-0023 for my manager in two lines", 2, "[INC-0023]"},
		{"tell me in one line what happened", 1, "[INC-0023]"},
		{"in simple words, what is wrong", 4, "[INC-0023]"},
		{"short answer please: status of the feeder", 2, "[INC-0023]"},
	}
	for _, c := range cases {
		got := chatFinish(c.q, long)
		n := len(chatSentences(got))
		if n > c.max || !strings.Contains(got, c.want) {
			t.Errorf("%q -> %d sentences (max %d): %s", c.q, n, c.max, got)
		}
	}
	if got := chatFinish("what is the feeder load", long); got != long {
		t.Errorf("no format asked, text changed: %s", got)
	}
	// decimals do not split a sentence
	if n := len(chatSentences("The load is 5.2 kW now. It is fine.")); n != 2 {
		t.Errorf("decimal split: %d", n)
	}
	// a long list is cut at an item boundary
	list := "5 incidents this week, newest first: " + strings.Repeat("[INC-0001] some title here (warning, 2026-11-19 10:00); ", 8) + "[INC-0009] last."
	if got := chatFinish("in one line, list the incidents", list); len([]rune(got)) > 300 {
		t.Errorf("one line too long (%d): %s", len([]rune(got)), got)
	}
}

func TestChatPolishOpenQuestionsToReasoner(t *testing.T) {
	data := ChatMsg{Text: "[INC-0023] Power factor low.", Tools: []ChatTool{{Name: "get_incident"}}}
	for _, q := range []string{"why is the power factor low", "should I worry about INC-0023", "compare KH and PB CO2", "explain what happened", "summarise the week"} {
		if !chatSendToReasoner(q, data) {
			t.Errorf("%q should go to the reasoner", q)
		}
	}
	for _, q := range []string{"how many incidents today", "highest CO2 now", "summarise INC-0023 in two lines", "why is it low in simple words"} {
		if chatSendToReasoner(q, data) {
			t.Errorf("%q should stay templated", q)
		}
	}
	if chatSendToReasoner("why is it so", ChatMsg{Text: "That's outside what I can do."}) {
		t.Error("an answer without tool data stays a template")
	}
	if chatSendToReasoner("why did you do that", ChatMsg{Text: "I can't do that: no", Tools: data.Tools}) {
		t.Error("a refusal stays a template")
	}
	if h := chatFactsHint("abc"); !strings.Contains(h, "abc") || !strings.Contains(h, "plain words") {
		t.Errorf("hint: %s", h)
	}
}

func TestChatPolishPlainWords(t *testing.T) {
	in := "Open each one and approve or dismiss it. Domain air_quality had a sensor_fault: pH rising (S1.E4) to 9.6 [S1.E1, S2.E3]. Power S1.E2 fine."
	got := chatPlain(in)
	for _, bad := range []string{"approve or dismiss", "air_quality", "sensor_fault", "S1.E4", "S1.E1", "S1.E2", "()", " ,"} {
		if strings.Contains(got, bad) {
			t.Errorf("still has %q: %s", bad, got)
		}
	}
	for _, want := range []string{"tap I'm on it or Dismiss", "air quality", "sensor fault"} {
		if !strings.Contains(got, want) {
			t.Errorf("lacks %q: %s", want, got)
		}
	}
	// the templates themselves use the app's buttons
	_, r, tools := chatV25Fixture(t)
	r.incidents = []*Incident{chatV3Inc("INC-0001", tools.now.Add(-time.Hour), "warning", wfNeeds, "SR-AQ-KH03-03", "co2", "air_quality", "warning")}
	v, _ := chatPolishAsk(t, tools, "close all open incidents", nil)
	if strings.Contains(v.Text, "approve or dismiss") || !strings.Contains(v.Text, "I'm on it or Dismiss") {
		t.Errorf("refusal wording: %s", v.Text)
	}
}

func TestChatPolishOutdoorAdvice(t *testing.T) {
	_, r, _ := chatV25Fixture(t)
	nodes := r.eng.Meta.Nodes
	var out, in string
	for id, n := range nodes {
		if n.Role == "air_quality" && strings.Contains(strings.ToLower(n.Location), "outdoor") && out == "" {
			out = id
		}
		if n.Role == "air_quality" && !strings.Contains(strings.ToLower(n.Location), "outdoor") && in == "" {
			in = id
		}
	}
	if out == "" || in == "" {
		t.Skip("no outdoor/indoor air node in the fixture")
	}
	steps := []string{"Inspect ventilation (fresh-air dampers, AHU fan)", "Check the sensor inlet for dust", "Close windows"}
	got, dropped := chatOutdoorSteps(steps, []string{out}, nodes)
	if !dropped || len(got) != 1 || !strings.Contains(got[0], "sensor inlet") {
		t.Errorf("outdoor: %v %v", dropped, got)
	}
	got, dropped = chatOutdoorSteps(steps, []string{in}, nodes)
	if dropped || len(got) != 3 {
		t.Errorf("indoor keeps its steps: %v", got)
	}
	// through the incident answer
	r.incidents = []*Incident{chatV3Inc("INC-0026", time.Unix(r.eng.sim, 0).Add(-time.Hour), "critical", wfNeeds, out, "pm25", "air_quality", "critical")}
	r.incidents[0].Steps = []Step{{Action: "a", Text: steps[0], State: "open"}, {Action: "b", Text: steps[1], State: "open"}}
	tools := chatTools{r: r, now: time.Unix(r.eng.sim, 0)}
	v, ok := chatPolishAsk(t, tools, "what should I do about INC-0026?", nil)
	if !ok || strings.Contains(v.Text, "AHU") || !strings.Contains(v.Text, "outdoor station") {
		t.Errorf("outdoor incident advice: %v %s", ok, v.Text)
	}
}

func TestChatPolishKnowledgeOnBoardFirst(t *testing.T) {
	e, r, tools := chatV25Fixture(t)
	var wq string
	for id, n := range r.eng.Meta.Nodes {
		for _, m := range n.Metrics {
			if m == "ph" && wq == "" {
				wq = id
			}
		}
	}
	if wq == "" {
		t.Skip("no pH sensor")
	}
	chatV3Write(e, wq, "ph", 20, func(int) float64 { return 9.63 }, "critical")
	inc := chatV3Inc("INC-0018", tools.now.Add(-time.Hour), "critical", wfNeeds, wq, "ph", "water", "critical")
	inc.Final = &ReportCall{Parsed: &Report{Label: "real", RootCause: "pH drifted high after dosing"}}
	r.incidents = []*Incident{inc}
	v, ok := chatPolishAsk(t, tools, "why is pH so high, is the water safe?", nil)
	if !ok || !strings.Contains(v.Text, "INC-0018") || !strings.Contains(v.Text, "pH drifted high") || !strings.Contains(v.Text, "9.6") {
		t.Fatalf("on-board facts: %v %s", ok, v.Text)
	}
	if n := strings.Count(strings.ToLower(v.Text), "deeper lookup"); n > 1 {
		t.Errorf("fog note %d times: %s", n, v.Text)
	}
	// nothing on the board about it: not answered here (the fog / model path)
	r.incidents = nil
	if v, ok := tools.chatKnowledge("why is pH so high", chatPlace{Level: -1, Unit: -1}, []string{"ph"}, r.eng.Meta.Nodes); ok {
		t.Errorf("no incident: %s", v.Text)
	}
}

func TestChatPolishSessionArchiveAndClear(t *testing.T) {
	dir := t.TempDir()
	os.MkdirAll(filepath.Join(dir, "state"), 0o755)
	now := time.Now()
	old := &ChatSession{ID: "CHAT-0001", Title: "old", Created: now.Add(-40 * 24 * time.Hour).Unix(), Updated: now.Add(-31 * 24 * time.Hour).Unix(), Msgs: []ChatMsg{{Role: "user", Text: "hi"}}}
	recent := &ChatSession{ID: "CHAT-0002", Title: "new", Created: now.Unix(), Updated: now.Add(-2 * time.Hour).Unix()}
	b, _ := json.Marshal([]*ChatSession{old, recent})
	os.WriteFile(filepath.Join(dir, "state", "chats.json"), b, 0o644)
	cs := newChatStore(dir)
	if len(cs.S) != 1 || cs.S["CHAT-0002"] == nil {
		t.Fatalf("after load: %v", cs.S)
	}
	var onDisk []*ChatSession
	b, _ = os.ReadFile(filepath.Join(dir, "state", "chats.json"))
	json.Unmarshal(b, &onDisk)
	if len(onDisk) != 1 {
		t.Errorf("chats.json: %d sessions", len(onDisk))
	}
	var arch []*ChatSession
	b, err := os.ReadFile(filepath.Join(dir, "state", "chats_archive.json"))
	if err != nil {
		t.Fatal(err)
	}
	json.Unmarshal(b, &arch)
	if len(arch) != 1 || arch[0].ID != "CHAT-0001" {
		t.Errorf("archive: %v", arch)
	}
	cs.mu.Lock()
	n := cs.clearLocked()
	cs.mu.Unlock()
	b, _ = os.ReadFile(filepath.Join(dir, "state", "chats.json"))
	if n != 1 || len(cs.S) != 0 || strings.TrimSpace(string(b)) != "[]" {
		t.Errorf("clear: %d %v %s", n, cs.S, b)
	}
}
