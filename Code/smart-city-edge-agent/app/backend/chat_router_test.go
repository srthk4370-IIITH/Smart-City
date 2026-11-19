package main

import (
	"encoding/json"
	"math"
	"reflect"
	"strings"
	"testing"
	"time"
)

var testBuildings = []string{"KH", "KN", "SB", "VN"}

func TestChatRouteQuestion(t *testing.T) {
	co2 := []ChatMsg{{Role: "user", Text: "How are co2 levels looking today"}, {Role: "assistant", Text: "CO2 is 450 ppm."}}
	cases := []struct {
		q    string
		h    []ChatMsg
		tool string         // "" = left to the model
		args map[string]any // nil = not checked
	}{
		// rank_readings
		{"Highest spike today", co2, "rank_readings", map[string]any{"metric": "co2", "time": map[string]any{"preset": "today"}}},
		{"What was the highest CO2 yesterday?", nil, "rank_readings", map[string]any{"metric": "co2", "time": map[string]any{"preset": "yesterday"}}},
		{"lowest water level this week", nil, "rank_readings", map[string]any{"metric": "level", "time": map[string]any{"preset": "last_7d"}, "order": "lowest"}},
		{"peak power load in KH in the last 24 hours", nil, "rank_readings", map[string]any{"metric": "power_kw", "time": map[string]any{"preset": "last_24h"}, "location": "KH"}},
		{"Which place had the hottest outdoor temperature today?", nil, "rank_readings", map[string]any{"metric": "temp", "time": map[string]any{"preset": "today"}, "domain": "weather"}},
		{"What is the worst incident today?", co2, "", nil},
		{"How many CO2 spikes were there today?", nil, "", nil},
		{"highest CO2 in the last 3 days", nil, "", nil},
		// current_levels
		{"How are CO2 levels?", nil, "current_levels", map[string]any{"metric": "co2"}},
		{"What is the current temperature in KH?", nil, "current_levels", map[string]any{"metric": "temp", "location": "KH"}},
		{"How is the weather right now?", nil, "current_levels", map[string]any{"domain": "weather"}},
		{"and right now?", co2, "current_levels", map[string]any{"metric": "co2"}},
		{"How is CO2 measured?", nil, "", nil},
		{"How was CO2 yesterday?", nil, "", nil},
		{"Show the CO2 trend now", nil, "", nil},
		{"How are you?", nil, "", nil},
		{"What can you do now?", co2, "", nil},
		{"Can I download the report now?", nil, "", nil},
		// recent_incidents
		{"Show me the latest incidents", nil, "recent_incidents", map[string]any{}},
		{"What was the last incident?", nil, "recent_incidents", map[string]any{"limit": 1.0}},
		{"last 3 critical water alerts", nil, "recent_incidents", map[string]any{"limit": 3.0, "domain": "water", "severity": []any{"critical"}}},
		{"list incidents", nil, "recent_incidents", map[string]any{}},
		{"latest incidents today", nil, "", nil},
		{"incidents in the last 7 days", nil, "", nil},
		{"How many incidents were there today?", co2, "count_incidents", map[string]any{"time": map[string]any{"preset": "today"}}}, // deploy24: routed count
		{"Tell me more about INC-0441", nil, "get_incident", map[string]any{"id": "INC-0441"}}, // deploy23
		// open_incidents
		{"Which domains have open incidents?", nil, "open_incidents", map[string]any{}},
		{"What still needs attention?", nil, "open_incidents", map[string]any{}},
		{"any pending water alerts?", nil, "open_incidents", map[string]any{"domain": "water"}},
		{"open incidents from yesterday", nil, "", nil},
		{"Is the window open?", nil, "", nil},
		// faulty_sensors
		{"Which sensors are faulty?", nil, "faulty_sensors", map[string]any{}},
		{"Any broken sensors this week?", nil, "faulty_sensors", map[string]any{"time": map[string]any{"preset": "last_7d"}}},
		{"How many sensors were faulty this month?", nil, "", nil},
		{"Which faulty sensors were replaced?", nil, "", nil},
		{"Is the CO2 sensor faulty?", nil, "", nil},
		{"faulty water sensors", nil, "", nil},
		// what_if
		{"What if occupancy increases by 50%?", nil, "what_if", map[string]any{"driver": "occ", "change_pct": 50.0}},
		{"How would CO2 change if people in KH drop 20 percent?", nil, "what_if", map[string]any{"driver": "occ", "change_pct": -20.0, "location": "KH"}},
		{"what happens if power load doubles", nil, "what_if", map[string]any{"driver": "power_kw", "change_pct": 100.0}},
		{"What if temperature goes up by 2?", nil, "what_if", map[string]any{"driver": "temp", "change_abs": 2.0}},
		{"what if occupancy changes by 30%", nil, "", nil}, // direction unclear
		{"what if occupancy goes to 80", nil, "", nil},     // a target value, not a change
		{"What if I dismiss this alert?", nil, "", nil},
		// everything else
		{"What is the capital of France?", nil, "", nil},
	}
	for _, c := range cases {
		r, ok := chatRouteQuestion(c.q, c.h, testBuildings)
		if c.tool == "" {
			if ok {
				t.Errorf("%q: routed to %s %v, want the model", c.q, r.Tool, r.Args)
			}
			continue
		}
		if !ok || r.Tool != c.tool {
			t.Errorf("%q: got %v %q, want %s", c.q, ok, r.Tool, c.tool)
			continue
		}
		if c.args != nil && !reflect.DeepEqual(r.Args, c.args) {
			t.Errorf("%q: args %v, want %v", c.q, r.Args, c.args)
		}
	}
}

// ---------------------------------------------------------------- tools on a real engine with written readings

// chatV3Fixture: a real engine (sensors.json) with exact readings, and chat tools at its sensor time.
func chatV3Fixture(t *testing.T) (*Engine, *Reasoner, chatTools) {
	t.Helper()
	e, err := NewEngine("../device")
	if err != nil {
		t.Fatal(err)
	}
	e.NoiseScale = 0
	r := &Reasoner{eng: e}
	return e, r, chatTools{r: r, now: time.Unix(e.sim, 0)}
}

// chatV3Write replaces a sensor's history with n readings ending at sensor time (f(0) oldest) and sets its live state.
func chatV3Write(e *Engine, node, metric string, n int, f func(i int) float64, status string) {
	e.mu.Lock()
	defer e.mu.Unlock()
	s := map[int64]float64{}
	for i := 0; i < n; i++ {
		s[e.sim-int64(n-1-i)*bucketSec] = f(i)
	}
	e.series[key(node, metric)] = s
	st := e.states[key(node, metric)]
	st.Last, st.Status = fp(f(n-1)), status
}

func chatV3Inc(id string, at time.Time, sev, wf, node, metric, role, status string) *Incident {
	inc := &Incident{ID: id, State: "done", CreatedSim: at.Unix(), Severity: sev, Title: "test " + id,
		Sensors: []SensorRef{{Ref: "S1", Node: node, Metric: metric, Role: role, Location: "loc " + node, Rule: Finding{Status: status}}}}
	inc.Workflow = wf
	return inc
}

func TestChatToolRankReadings(t *testing.T) {
	e, r, tools := chatV3Fixture(t)
	chatV3Write(e, "SR-AQ-KH03-03", "temp", 600, func(i int) float64 {
		if i == 600-5 {
			return 41.25 // today's peak, 20 min ago
		}
		return 25
	}, "normal")
	chatV3Write(e, "WE-VN04-00", "temp", 600, func(i int) float64 { return 30 + float64(i%7) }, "normal")
	// the weather sensor had a sensor_fault incident today
	r.incidents = []*Incident{chatV3Inc("INC-0001", tools.now.Add(-time.Hour), "sensor_fault", wfNeeds, "WE-VN04-00", "temp", "weather", "sensor_fault")}

	res, err := tools.run("rank_readings", map[string]any{"metric": "temp"})
	if err != nil {
		t.Fatal(err)
	}
	items := res["items"].([]map[string]any)
	if len(items) != 2 || items[0]["node"] != "SR-AQ-KH03-03" || items[0]["value"] != 41.3 || items[0]["faulty_suspect"] != false {
		t.Fatalf("rank: %v", items)
	}
	if want := chatTS(tools.now.Add(-20 * time.Minute)); items[0]["at"] != want {
		t.Fatalf("peak at %v, want %s", items[0]["at"], want)
	}
	if items[1]["faulty_suspect"] != true || items[1]["value"] != 36.0 || res["sensors"] != 2 {
		t.Fatalf("second: %v (sensors %v)", items[1], res["sensors"])
	}
	// lowest, without faulty sensors, weather only
	res, _ = tools.run("rank_readings", map[string]any{"metric": "temp", "order": "lowest", "include_faulty": false})
	if items := res["items"].([]map[string]any); len(items) != 1 || items[0]["value"] != 25.0 {
		t.Fatalf("lowest: %v", items)
	}
	res, _ = tools.run("rank_readings", map[string]any{"metric": "temp", "domain": "weather", "limit": 1.0})
	if items := res["items"].([]map[string]any); len(items) != 1 || items[0]["node"] != "WE-VN04-00" {
		t.Fatalf("weather: %v", items)
	}
	if _, err := tools.run("rank_readings", map[string]any{"metric": "nox"}); err == nil {
		t.Fatal("unknown metric must be an error")
	}
}

func TestChatToolCurrentLevels(t *testing.T) {
	e, _, tools := chatV3Fixture(t)
	chatV3Write(e, "SR-AQ-KH03-03", "co2", 100, func(i int) float64 { return 500 + float64(i) }, "normal")
	res, err := tools.run("current_levels", map[string]any{"metric": "co2"})
	if err != nil {
		t.Fatal(err)
	}
	it := res["items"].([]map[string]any)[0]
	if it["last"] != 599.0 || it["unit"] != "ppm" || it["status"] != "normal" {
		t.Fatalf("co2: %v", it)
	}
	if lm := it["limit"].(map[string]any); lm["warning"] != 1000.0 || lm["critical"] != 1500.0 {
		t.Fatalf("limit: %v", lm)
	}
	if td := it["today"].(map[string]any); td["max"] != 599.0 {
		t.Fatalf("today: %v", td)
	}
	res, _ = tools.run("current_levels", map[string]any{"metric": "level"})
	if it := res["items"].([]map[string]any)[0]; it["limit"] != nil {
		t.Fatalf("water level has no limits: %v", it)
	}
	res, _ = tools.run("current_levels", map[string]any{"location": "KH"})
	if n := res["count"].(int); n < 5 {
		t.Fatalf("KH sensors: %d", n)
	}
	if _, err := tools.run("current_levels", map[string]any{}); err == nil {
		t.Fatal("no argument must be an error")
	}
}

func TestChatToolIncidents(t *testing.T) {
	_, r, tools := chatV3Fixture(t)
	now := tools.now
	two := chatV3Inc("INC-0004", now.Add(-10*time.Minute), "critical", wfNeeds, "WM-WL-KH98-00", "level", "water", "critical")
	two.Sensors = append(two.Sensors, SensorRef{Ref: "S2", Node: "EM-CR-SB00-00", Metric: "power_kw", Role: "power", Rule: Finding{Status: "warning"}})
	r.incidents = []*Incident{
		chatV3Inc("INC-0001", now.Add(-72*time.Hour), "warning", wfNeeds, "SR-AQ-KH03-03", "co2", "air_quality", "warning"),
		chatV3Inc("INC-0002", now.Add(-48*time.Hour), "sensor_fault", wfClosed, "SR-AQ-KH03-03", "co2", "air_quality", "sensor_fault"),
		chatV3Inc("INC-0003", now.Add(-2*time.Hour), "warning", wfAnalysing, "SR-AQ-KH03-03", "co2", "air_quality", "warning"),
		two,
	}
	r.incidents[2].State = "running"
	inj := chatV3Inc("INC-0005", now, "critical", wfNeeds, "WM-WL-KH98-00", "level", "water", "critical")
	inj.Injected = true
	r.incidents = append(r.incidents, inj)

	res, err := tools.run("recent_incidents", map[string]any{"limit": 2.0})
	if err != nil {
		t.Fatal(err)
	}
	items := res["items"].([]map[string]any)
	if len(items) != 2 || items[0]["id"] != "INC-0004" || items[1]["id"] != "INC-0003" || res["total"] != 4 {
		t.Fatalf("recent: %v total %v", items, res["total"])
	}
	res, _ = tools.run("recent_incidents", map[string]any{"severity": []any{"sensor_fault"}})
	if items := res["items"].([]map[string]any); len(items) != 1 || items[0]["id"] != "INC-0002" {
		t.Fatalf("severity filter: %v", items)
	}

	res, _ = tools.run("open_incidents", map[string]any{})
	if res["total_pending_review"] != 2 {
		t.Fatalf("pending: %v", res["total_pending_review"])
	}
	doms := map[string]map[string]any{}
	for _, d := range res["domains"].([]map[string]any) {
		doms[d["domain"].(string)] = d
	}
	aq := doms["air_quality"]
	if aq["pending_review"] != 1 || aq["analysing"] != 1 || aq["oldest_pending"] != chatTS(now.Add(-72*time.Hour)) ||
		aq["by_severity"].(map[string]int)["warning"] != 1 {
		t.Fatalf("air_quality: %v", aq)
	}
	if doms["water"]["pending_review"] != 1 || doms["power"]["pending_review"] != 1 || doms["weather"]["oldest_pending"] != nil {
		t.Fatalf("water/power/weather: %v %v %v", doms["water"], doms["power"], doms["weather"])
	}
}

func TestChatToolFaultySensors(t *testing.T) {
	e, r, tools := chatV3Fixture(t)
	e.mu.Lock()
	st := e.states[key("AQ-KN00-00", "pm25")]
	st.Status, st.AbnormalFor = "sensor_fault", 3
	e.mu.Unlock()
	now := tools.now
	a := chatV3Inc("INC-0001", now.Add(-30*time.Hour), "sensor_fault", wfNeeds, "SR-AQ-KH03-03", "co2", "air_quality", "sensor_fault")
	b := chatV3Inc("INC-0002", now.Add(-5*time.Hour), "sensor_fault", wfNeeds, "SR-AQ-KH03-03", "co2", "air_quality", "sensor_fault")
	b.Agents = []AgentCall{{Ref: "S1", Valid: true, Parsed: &Finding{Status: "sensor_fault", FaultKind: "drift"}}}
	c := chatV3Inc("INC-0003", now.Add(-20*24*time.Hour), "sensor_fault", wfNeeds, "WE-VN04-00", "wind", "weather", "sensor_fault") // outside 7 days
	r.incidents = []*Incident{a, b, c}

	res, err := tools.run("faulty_sensors", map[string]any{})
	if err != nil {
		t.Fatal(err)
	}
	live := res["live"].([]map[string]any)
	if len(live) != 1 || live[0]["node"] != "AQ-KN00-00" || live[0]["since"] != chatTS(now.Add(-10*time.Minute)) {
		t.Fatalf("live: %v", live)
	}
	ai := res["ai_diagnosed"].([]map[string]any)
	if len(ai) != 1 || ai[0]["incidents"] != 2 || ai[0]["fault_kind"] != "drift" || ai[0]["last"] != chatTS(now.Add(-5*time.Hour)) {
		t.Fatalf("ai: %v", ai)
	}
	if res["count_distinct"] != 2 {
		t.Fatalf("count_distinct %v", res["count_distinct"])
	}
}

func TestChatToolWhatIf(t *testing.T) {
	e, _, tools := chatV3Fixture(t)
	const n = 3 * 288 // 3 days of 5-min readings
	occ := func(i int) float64 { return 0.5 + 0.4*math.Sin(2*math.Pi*float64(i)/288) }
	chatV3Write(e, "SR-OC-GW-KH95-01", "occ", n, occ, "normal")
	e.mu.Lock()
	e.states[key("SR-OC-GW-KH95-01", "occ")].Last = fp(0.4)
	e.mu.Unlock()
	chatV3Write(e, "SR-AQ-KH03-03", "co2", n, func(i int) float64 { return 400 + 500*occ(i) }, "normal")
	e.mu.Lock()
	e.states[key("SR-AQ-KH03-03", "co2")].Last = fp(800)
	e.mu.Unlock()
	chatV3Write(e, "SR-AQ-KH03-03", "rh", n, func(i int) float64 { return 50 + 5*math.Sin(float64(i)*1.7) }, "normal") // unrelated
	chatV3Write(e, "SR-AQ-KH03-03", "temp", n, func(i int) float64 { return 24 }, "normal")                            // constant

	res, err := tools.run("what_if", map[string]any{"driver": "occ", "change_pct": 50.0})
	if err != nil {
		t.Fatal(err)
	}
	if res["location"] != "KH" || res["change"] != "+50%" || res["driver_now"] != 0.4 || res["driver_after"] != 0.6 {
		t.Fatalf("driver: %v", res)
	}
	ests := res["estimates"].([]map[string]any)
	if len(ests) != 1 || ests[0]["metric"] != "co2" || ests[0]["now"] != 800.0 || ests[0]["after"] != 900.0 || ests[0]["r2"] != 1.0 || ests[0]["hours"].(int) < 24 {
		t.Fatalf("estimates: %v", ests)
	}
	nl := res["no_clear_link"].([]string)
	if !contains(nl, "rh") || !contains(nl, "temp") || contains(nl, "co2") {
		t.Fatalf("no_clear_link: %v", nl)
	}
	if _, err := tools.run("what_if", map[string]any{"driver": "occ"}); err == nil {
		t.Fatal("a change is required")
	}
	if _, err := tools.run("what_if", map[string]any{"driver": "occ", "change_pct": 10.0, "location": "VN"}); err == nil {
		t.Fatal("no occupancy sensor in VN")
	}

	// routed end to end: the answer says it is an estimate and lists each estimate and the unlinked metrics
	text, tool, ok := tools.chatRouted("What if occupancy increases by 50%?", nil)
	if !ok || tool.Name != "what_if" {
		t.Fatalf("not routed: %v %v", ok, tool)
	}
	for _, w := range []string{"estimate", "not a guarantee", "CO2 (SR-AQ-KH03-03) 800 ppm -> 900 ppm", "No clear link found for:", "humidity"} {
		if !strings.Contains(text, w) {
			t.Errorf("answer misses %q: %s", w, text)
		}
	}
	var args map[string]any
	if json.Unmarshal([]byte(tool.Args), &args) != nil || args["driver"] != "occ" || !strings.Contains(tool.Result, `"estimates"`) {
		t.Fatalf("tool record: %+v", tool)
	}
}

// Every routed tool answers in a sentence and records its call for "How I found this".
func TestChatRoutedAnswers(t *testing.T) {
	e, r, tools := chatV3Fixture(t)
	chatV3Write(e, "SR-AQ-KH03-03", "co2", 50, func(i int) float64 { return 600 + float64(i) }, "normal")
	r.incidents = []*Incident{chatV3Inc("INC-0007", tools.now.Add(-time.Hour), "warning", wfNeeds, "SR-AQ-KH03-03", "co2", "air_quality", "warning")}
	for q, want := range map[string]string{
		"Highest CO2 today":                  "Highest CO2 today: 649 ppm",
		"How are CO2 levels?":                "649 ppm (fine)",
		"Show me the latest incidents":       "INC-0007",
		"Which domains have open incidents?": "air quality 1 (1 warning",
		"Which sensors are faulty?":          "No sensor reports a sensor fault right now.",
	} {
		text, tool, ok := tools.chatRouted(q, nil)
		if !ok || tool.Name == "" || tool.Result == "" {
			t.Errorf("%q: not routed", q)
			continue
		}
		if !strings.Contains(text, want) {
			t.Errorf("%q: %q misses %q", q, text, want)
		}
	}
	// nothing to rank (no sensor of the metric): the model answers
	if _, _, ok := tools.chatRouted("highest wind in SB today", nil); ok {
		t.Error("an empty ranking must fall through to the model")
	}
}
