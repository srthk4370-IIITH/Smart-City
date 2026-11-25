package main

import (
	"bytes"
	"encoding/json"
	"net/http"
	"net/http/httptest"
	"os"
	"testing"
)

// withSiteCards installs a site config whose cards are assigned to the given sensors (id "NODE/metric" -> card id).
func withSiteCards(t *testing.T, cards map[string]Card, assign map[string]string) {
	t.Helper()
	cfg := &SiteConfig{SiteID: "t", Version: 1, Cards: cards}
	for id, card := range assign {
		cfg.Nodes = append(cfg.Nodes, SiteNode{ID: id, Kind: "sensor", Card: card})
	}
	siteS.mu.Lock()
	oldCfg, oldIx := siteS.cfg, siteS.ix
	siteS.cfg, siteS.ix = cfg, NewSiteIndex(cfg)
	siteS.mu.Unlock()
	t.Cleanup(func() {
		siteS.mu.Lock()
		siteS.cfg, siteS.ix = oldCfg, oldIx
		siteS.mu.Unlock()
	})
}

func withTrigger(t *testing.T, v TriggerRules) {
	t.Helper()
	old := trigRules()
	trigS.mu.Lock()
	trigS.v = v
	trigS.mu.Unlock()
	t.Cleanup(func() {
		trigS.mu.Lock()
		trigS.v, trigS.dir = old, ""
		trigS.mu.Unlock()
	})
}

func flat(v float64) []float64 { return rep(v, Window) }

// A default card changes nothing: every built-in metric with its default card gives the same status, critical / abnormal /
// near-limit verdicts on a grid of windows (pH low side, indoor CO2 < 350, the relative power / level rules included).
func TestEffectiveMetricDefaultsIdentical(t *testing.T) {
	checked := 0
	for id, card := range existingCards {
		role, metric := cardMetricKey(card)
		m0, ok := Metrics[role+"/"+metric]
		if !ok || role == "hvac" {
			continue
		}
		m1 := overlayCard(m0, card)
		checked++
		vals := []float64{}
		lo, hi := m0.Lo, m0.Hi
		for i := 0; i <= 60; i++ {
			vals = append(vals, lo+(hi-lo)*float64(i)/60)
		}
		for _, p := range []float64{m0.Warn, m0.Crit, m0.WarnLo, m0.CritLo, m0.FaultLo, 6.0, 6.5, 7, 8.5, 9, 350, 1, 0.85, 0.7} {
			vals = append(vals, p-0.01, p, p+0.01, p*0.9, p*1.1, p*3)
		}
		for _, v := range vals {
			mid := (m0.Warn + m0.Crit) / 2
			if mid == 0 {
				mid = (lo + hi) / 4
			}
			ramp := make([]float64, Window)
			spike := flat(mid)
			dip := flat(v)
			step := flat(mid)
			for i := range ramp {
				ramp[i] = mid + (v-mid)*float64(i)/float64(Window-1)
				if i >= 30 {
					step[i] = v
				}
			}
			spike[20] = v
			dip[20] = mid
			for _, xs := range [][]float64{flat(v), ramp, spike, dip, step} {
				st := ComputeStats(xs, m0.Dec)
				for _, pat := range ContPatterns {
					a := StatusOfM(m0, role, metric, pat, st, mean(xs[:12]))
					b := StatusOfM(m1, role, metric, pat, st, mean(xs[:12]))
					if a != b {
						t.Fatalf("%s %s/%s pattern %s last %.3f max %.3f min %.3f: status %s with the built-in, %s with its default card",
							id, role, metric, pat, st.Last, st.Max, st.Min, a, b)
					}
				}
			}
			if valueCriticalM(m0, v) != valueCriticalM(m1, v) || valueAbnormalM(m0, v) != valueAbnormalM(m1, v) || nearLimitM(m0, v) != nearLimitM(m1, v) {
				t.Fatalf("%s %s/%s value %.3f: critical/abnormal/near differ", id, role, metric, v)
			}
		}
		if m0.HasLimits != m1.HasLimits || m0.Dir != m1.Dir || m0.Warn != m1.Warn || m0.Crit != m1.Crit || m0.WarnS != m1.WarnS || m0.CritS != m1.CritS || m0.Floor != m1.Floor {
			t.Fatalf("%s: limits changed by the default card: %+v vs %+v", id, m0, m1)
		}
	}
	if checked < 15 {
		t.Fatalf("only %d default cards matched a built-in metric", checked)
	}
	// the hard-coded rules are still there
	if StatusOf("air_quality", "co2", "step_decrease", ComputeStats(flat(300), 0), 300) != "sensor_fault" {
		t.Fatal("co2 < 350 no longer a sensor fault")
	}
	if StatusOf("water", "ph", "stable", ComputeStats(flat(5.8), 2), 5.8) != "critical" || StatusOf("water", "ph", "stable", ComputeStats(flat(6.3), 2), 6.3) != "warning" {
		t.Fatal("pH low side changed")
	}
}

// An edited card limit moves the rules of THAT sensor only: status, critical verdict, near-limit, the prompt LIMITS line.
func TestCardOverrideChangesOnlyItsSensor(t *testing.T) {
	c := existingCards["co2_indoor"]
	c.Critical = &CardLim{Dir: "high", At: fptr(1200)}
	c.Warning = &CardLim{Dir: "high", At: fptr(900)}
	withSiteCards(t, map[string]Card{"co2_indoor": c}, map[string]string{"EDIT-1/co2": "co2_indoor"})
	st := ComputeStats(flat(1300), 0)
	if got := StatusOfNode("air_quality", "co2", "EDIT-1", "stable", st, 1300); got != "critical" {
		t.Fatalf("edited sensor at 1300 ppm: %s, want critical (card critical 1200)", got)
	}
	if got := StatusOfNode("air_quality", "co2", "OTHER-2", "stable", st, 1300); got != "warning" {
		t.Fatalf("other co2 sensor at 1300 ppm: %s, want warning (default critical 1500)", got)
	}
	if !valueCriticalNode("air_quality", "co2", "EDIT-1", 1250) || valueCriticalNode("air_quality", "co2", "OTHER-2", 1250) {
		t.Fatal("valueCritical must follow the card for the edited sensor only")
	}
	if !valueAbnormalNode("air_quality", "co2", "EDIT-1", 950) || valueAbnormalNode("air_quality", "co2", "OTHER-2", 950) {
		t.Fatal("valueAbnormal must follow the card for the edited sensor only")
	}
	wob := flat(1300)
	for i := range wob {
		wob[i] += float64(i%3) * 3
	}
	if rf := RuleFinding("air_quality", "co2", "EDIT-1", wob, 1_800_000_000); rf.Status != "critical" {
		t.Fatalf("RuleFinding on the edited sensor: %s", rf.Status)
	}
	p := BuildAgentPrompt("air_quality", "EDIT-1", "room", "co2", flat(1300), 1_800_000_000).Prompt
	if !bytes.Contains([]byte(p), []byte("warning above 900, critical above 1200")) {
		t.Fatalf("v1 prompt LIMITS line does not show the card limits:\n%s", p)
	}
	// a different config object drops the cached overlay
	c2 := c
	c2.Critical = &CardLim{Dir: "high", At: fptr(1400)}
	withSiteCards(t, map[string]Card{"co2_indoor": c2}, map[string]string{"EDIT-1/co2": "co2_indoor"})
	if valueCriticalNode("air_quality", "co2", "EDIT-1", 1250) || !valueCriticalNode("air_quality", "co2", "EDIT-1", 1450) {
		t.Fatal("cache not invalidated when the site config changed")
	}
	// moved impossible bound: below it is a sensor fault; an unchanged default bound stays no rule (temp 5)
	tc := existingCards["temp_indoor"]
	tc.Impossible = &CardImp{Below: fptr(12), Above: tc.Impossible.Above}
	withSiteCards(t, map[string]Card{"temp_indoor": tc}, map[string]string{"EDIT-1/temp": "temp_indoor"})
	if got := StatusOfNode("air_quality", "temp", "EDIT-1", "stable", ComputeStats(flat(10), 1), 10); got != "sensor_fault" {
		t.Fatalf("temp below the card's impossible bound: %s", got)
	}
	if got := StatusOfNode("air_quality", "temp", "OTHER-2", "stable", ComputeStats(flat(10), 1), 10); got == "sensor_fault" {
		t.Fatal("default temp bound became a fault rule")
	}
}

func TestCardLimitProblems(t *testing.T) {
	c := existingCards["co2_indoor"]
	if p := cardLimitProblems(c); len(p) > 0 {
		t.Fatalf("default card rejected: %v", p)
	}
	c.Critical = &CardLim{Dir: "low", At: fptr(10)}
	if p := cardLimitProblems(c); len(p) == 0 {
		t.Fatal("mixed dirs accepted")
	}
	c.Critical = &CardLim{Dir: "high"}
	if p := cardLimitProblems(c); len(p) == 0 {
		t.Fatal("limit without a number accepted")
	}
}

func rulesReq(t *testing.T, mux *http.ServeMux, method, body string) (int, map[string]any) {
	t.Helper()
	req := httptest.NewRequest(method, "/api/rules", bytes.NewBufferString(body))
	rec := httptest.NewRecorder()
	mux.ServeHTTP(rec, req)
	var out map[string]any
	_ = json.Unmarshal(rec.Body.Bytes(), &out)
	return rec.Code, out
}

func TestRulesAPIValidationAndPersistence(t *testing.T) {
	s := testServer(t)
	withTrigger(t, defaultTrigger)
	mux := http.NewServeMux()
	s.rulesRoutes(mux)
	code, st := rulesReq(t, mux, "GET", "")
	if code != 200 {
		t.Fatalf("GET %d", code)
	}
	for _, k := range []string{"trigger", "defaults", "ranges", "sensors", "constraints"} {
		if st[k] == nil {
			t.Fatalf("GET /api/rules lacks %q: %v", k, st)
		}
	}
	sensors, _ := st["sensors"].([]any)
	if len(sensors) == 0 {
		t.Fatal("no sensors listed")
	}
	var co2 map[string]any
	for _, x := range sensors {
		if m := x.(map[string]any); m["node"] == dqNode && m["metric"] == dqMetric {
			co2 = m
		}
	}
	if co2 == nil || co2["warning"].(map[string]any)["high"].(float64) != 1000 || co2["critical"].(map[string]any)["high"].(float64) != 1500 ||
		co2["impossible"].(map[string]any)["below"].(float64) != 350 || co2["source"] != "default_card" || co2["card_id"] != "co2_indoor" {
		t.Fatalf("effective co2 thresholds: %v", co2)
	}
	for _, bad := range []string{
		`{"trigger":{"persist_readings":1}}`,
		`{"trigger":{"persist_readings":30}}`,
		`{"trigger":{"persist_readings":4,"fast_readings":4}}`,
		`{"trigger":{"batch_readings":6,"batch_max_readings":5}}`,
		`{"trigger":{"batch_max_readings":25}}`,
		`{"trigger":{"fast_cooldown":100}}`,
		`{"trigger":{"transient_max":13}}`,
		`{"trigger":{"nonsense":1}}`,
		`not json`,
	} {
		code, out := rulesReq(t, mux, "PUT", bad)
		if code != 400 || out["ok"] != false || len(out["problems"].([]any)) == 0 {
			t.Errorf("PUT %s -> %d %v, want 400 with problems", bad, code, out)
		}
	}
	if trigRules() != defaultTrigger {
		t.Fatalf("rejected PUTs changed the rules: %+v", trigRules())
	}
	code, out := rulesReq(t, mux, "PUT", `{"trigger":{"persist_readings":6,"fast_readings":3,"transient_max":5}}`)
	if code != 200 {
		t.Fatalf("valid PUT %d %v", code, out)
	}
	want := TriggerRules{6, 3, 10, 3, 12, 5, defaultAbnormalOfWindow, defaultEventAlarms}
	if got := trigRules(); got != want {
		t.Fatalf("rules after PUT %+v, want %+v", got, want)
	}
	if out["trigger"].(map[string]any)["persist_readings"].(float64) != 6 {
		t.Fatalf("PUT response: %v", out["trigger"])
	}
	if _, err := os.Stat(trigS.path()); err != nil {
		t.Fatalf("not persisted: %v", err)
	}
	if _, err := os.Stat(trigS.path() + ".part"); err == nil {
		t.Fatal(".part left behind")
	}
	trigS.Load(s.dir) // a restart
	if got := trigRules(); got != want {
		t.Fatalf("after reload %+v, want %+v", got, want)
	}
	trigS.Load(t.TempDir()) // no file: defaults
	if trigRules() != defaultTrigger {
		t.Fatal("missing file did not give the defaults")
	}
}

// The engine reads the rules every tick: a lower persist count calls the AI earlier, with no restart.
func TestEngineUsesRuntimePersistReadings(t *testing.T) {
	var vals []float64
	for i := 1; i <= 16; i++ {
		vals = append(vals, 1000+20*float64(i))
	}
	tr := defaultTrigger
	tr.PersistReadings, tr.AbnormalOfWindow = 4, 4
	tr.BatchReadings = 1
	withTrigger(t, tr)
	_, ai := fpSplit(feedCO2(t, dqEngine(t), 60, 600, vals))
	if len(ai) != 1 || ai[0].reading < 4 || ai[0].reading > 4+tr.BatchReadings+1 {
		t.Fatalf("AI gate with persist 4: %+v, want one candidate at readings 4..%d", ai, 4+tr.BatchReadings+1)
	}
	tr.PersistReadings, tr.AbnormalOfWindow = 12, 12
	withTrigger(t, tr)
	_, ai = fpSplit(feedCO2(t, dqEngine(t), 60, 600, vals))
	if len(ai) != 1 || ai[0].reading < 12 {
		t.Fatalf("AI gate with persist 12: %+v, want a candidate at >= 12", ai)
	}
}

// End to end: a card critical limit of 1200 opens the fast path at 1300 ppm, where the default (1500) does not.
func TestEngineFastPathFollowsCard(t *testing.T) {
	vals := rep(1300, 6)
	if fast, _ := fpSplit(feedCO2(t, dqEngine(t), 60, 600, vals)); len(fast) != 0 {
		t.Fatalf("1300 ppm took the fast path with the default card: %+v", fast)
	}
	c := existingCards["co2_indoor"]
	c.Critical = &CardLim{Dir: "high", At: fptr(1200)}
	withSiteCards(t, map[string]Card{"co2_indoor": c}, map[string]string{dqNode + "/" + dqMetric: "co2_indoor"})
	fast, _ := fpSplit(feedCO2(t, dqEngine(t), 60, 600, vals))
	if len(fast) != 1 || fast[0].c.Finding.Status != "critical" {
		t.Fatalf("1300 ppm with a card critical of 1200: %+v, want one critical fast candidate", fast)
	}
}
