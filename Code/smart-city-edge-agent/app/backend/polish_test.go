package main

import (
	"bytes"
	"encoding/json"
	"net/http"
	"net/http/httptest"
	"os"
	"sort"
	"strings"
	"testing"
	"time"
)

// Polish pass (polish_*.go): short events, swallowed events, reboot, severity reasons, playbook, event mode, snooze,
// deploy-check incidents. The reasoner tests run on the refine rig (real engine and pipeline, scripted agents).

func tlHas(inc Incident, sub string) bool {
	for _, t := range inc.Timeline {
		if strings.Contains(t.Msg, sub) {
			return true
		}
	}
	return false
}

func evHas(inc Incident, ev string) bool {
	for _, e := range inc.Events {
		if e.Event == ev {
			return true
		}
	}
	return false
}

// co2Cand: the CO2 sensor of the first air sensor as a candidate at the engine's sensor time.
func (rg *refineRig) co2Cand(fast bool, status string) Candidate {
	node := "SR-AQ-KH03-03"
	xs, ok := rg.eng.WindowAt(node, "co2", rg.eng.sim)
	if !ok {
		rg.t.Fatal("no co2 window")
	}
	f := RuleFinding("air_quality", "co2", node, xs, rg.eng.sim)
	f.Status = status
	return Candidate{node, "co2", "air_quality", f, xs, rg.eng.sim, false, fast, false}
}

// ---- 1. short / rare events

func TestPolishShortEventRunsAIOnLast4h(t *testing.T) {
	rg := newRefineRig(t)
	rg.r.splitFast([]Candidate{rg.co2Cand(true, "critical")})
	if len(rg.r.incidents) != 1 || !rg.r.incidents[0].FastPath {
		t.Fatalf("fast incident missing: %d", len(rg.r.incidents))
	}
	inc := rg.r.incidents[0]
	if n := rg.r.shortEventSweep(time.Now()); n != 1 { // critical fast path: early AI on history at once (owner 2026-11-20)
		t.Fatalf("early AI not queued at once: %d", n)
	}
	got := rg.settle(inc.ID)
	if len(rg.r.incidents) != 1 || got.NPUCalls == 0 || got.ShortRunAt == 0 || len(got.Agents) == 0 {
		t.Fatalf("AI did not run on the same incident: %d incidents, calls %d, agents %d", len(rg.r.incidents), got.NPUCalls, len(got.Agents))
	}
	if !tlHas(got, "Early AI: the event is shorter") {
		t.Fatalf("timeline lacks the short-event line: %+v", got.Timeline)
	}
	if n := rg.r.shortEventSweep(time.Now().Add(30 * time.Minute)); n != 0 {
		t.Fatalf("ran twice: %d", n)
	}
}

func TestPolishSlowSensorWaitsTwoCadences(t *testing.T) {
	e := dqEngine(t)
	wall := int64(2_000_000_100)
	e.mu.Lock()
	e.Live = true
	e.mu.Unlock()
	for i := 0; i < 6; i++ {
		wall += 3600
		if _, err := e.IngestReading(Reading{Node: dqNode, Metric: dqMetric, Value: fp(600), Ts: float64(wall)}, wall); err != nil {
			t.Fatal(err)
		}
		e.mu.Lock()
		e.sim = (wall + bucketSec - 1) / bucketSec * bucketSec
		e.feed(e.sim)
		e.mu.Unlock()
	}
	if c := e.cadenceSec(dqNode, dqMetric); c != 3600 {
		t.Fatalf("cadence %d, want 3600", c)
	}
	dir := t.TempDir()
	r := NewReasoner(NewGenieRunner(dir, dir, true), e, dir, func(string, any) {})
	inc := &Incident{Sensors: []SensorRef{{Node: dqNode, Metric: dqMetric}}}
	if w := r.shortEventWait(inc); w != 2*time.Hour {
		t.Fatalf("wait %v, want 2h", w)
	}
	if w := r.shortEventWait(&Incident{Sensors: []SensorRef{{Node: "SR-AQ-KH03-03", Metric: "temp", Context: true}}}); w != shortEventMin {
		t.Fatalf("context-only wait %v", w)
	}
}

// ---- 2. swallowed events

// A new abnormal episode of a sensor of an open incident (older than 6 h, resolved) re-runs the AI on THAT incident.
func TestPolishNewEpisodeJoinsOpenIncident(t *testing.T) {
	rg := newRefineRig(t)
	inc := rg.alert()
	first := rg.settle(inc.ID)
	rg.r.mu.Lock()
	rg.r.incidents[0].CreatedSim -= 100 * bucketSec // older than the 6 h promotion cap
	rg.r.incidents[0].Workflow, rg.r.incidents[0].ResolvedAt, rg.r.incidents[0].ResolvedSim = wfResolved, wfNow().Unix(), rg.eng.sim
	rg.r.mu.Unlock()
	rg.answer("exponential_increase/critical")
	rg.r.HandleCandidates([]Candidate{rg.co2Cand(true, "critical")}) // a new critical episode: Fast must not open a duplicate
	got := rg.settle(inc.ID)
	if len(rg.r.incidents) != 1 {
		t.Fatalf("a duplicate incident was opened: %d", len(rg.r.incidents))
	}
	if len(got.Revisions) != len(first.Revisions)+1 || got.Revisions[len(got.Revisions)-1].Stage != "promotion" {
		t.Fatalf("no escalation revision: %d -> %d", len(first.Revisions), len(got.Revisions))
	}
	if !tlHas(got, "again (new episode)") {
		t.Fatalf("timeline: %+v", got.Timeline)
	}
	if wfOf(&got) == wfResolved || !evHas(got, "abnormal_again") {
		t.Fatalf("resolved incident not reopened: %s", wfOf(&got))
	}
	rg.mu.Lock()
	defer rg.mu.Unlock()
	last := rg.events[len(rg.events)-1]
	if last["change"] != "elevated" && last["change"] != "again" {
		t.Fatalf("notification: %v", last)
	}
}

func TestPolishFineIncidentAutoClosesAfter2h(t *testing.T) {
	dir := t.TempDir()
	r := NewReasoner(NewGenieRunner(dir, dir, true), nil, dir, func(string, any) {})
	inc := &Incident{ID: "INC-0001", State: "done", Severity: "normal", SeverityFinal: true, CreatedSim: 1000, Approval: "pending"}
	inc.Workflow = wfNeeds
	r.incidents = append(r.incidents, inc)
	r.workflowTick(1000+3600, 0, nil)
	if wfOf(inc) == wfClosed {
		t.Fatal("closed after 1 h")
	}
	r.workflowTick(1000+7300, 0, nil)
	if wfOf(inc) != wfClosed || inc.ClosedBy != "system" || !evHas(*inc, "auto_closed") {
		t.Fatalf("not auto-closed: %s", wfOf(inc))
	}
	if inc.Events[len(inc.Events)-1].Detail != "auto-closed: fine, nothing new for 2 h" {
		t.Fatalf("event text: %q", inc.Events[len(inc.Events)-1].Detail)
	}
	if _, err := r.Reopen("INC-0001", "sam", "still wrong"); err != nil || wfOf(inc) != wfNeeds || inc.ClosedAt != 0 {
		t.Fatalf("reopen: %v %s", err, wfOf(inc))
	}
	// something new inside the 2 h keeps it open
	inc2 := &Incident{ID: "INC-0002", State: "done", Severity: "normal", SeverityFinal: true, CreatedSim: 1000, Approval: "pending", promoSim: 1000 + 6000}
	inc2.Workflow = wfNeeds
	r.incidents = append(r.incidents, inc2)
	r.workflowTick(1000+7300, 0, nil)
	if wfOf(inc2) == wfClosed {
		t.Fatal("closed although something new happened 20 min ago")
	}
	// a warning is never auto-closed as fine
	inc3 := &Incident{ID: "INC-0003", State: "done", Severity: "warning", SeverityFinal: true, CreatedSim: 1000, Approval: "pending"}
	inc3.Workflow = wfNeeds
	r.incidents = append(r.incidents, inc3)
	r.workflowTick(1000+90000, 0, nil)
	if wfOf(inc3) == wfClosed {
		t.Fatal("a warning auto-closed as fine")
	}
}

// ---- 3. reboot

func TestPolishEngineStateSaveRestore(t *testing.T) {
	old := devClock
	defer func() { devClock = old }()
	wall := int64(2_000_000_000)
	devClock = func() time.Time { return time.Unix(wall, 0) }
	e := dqEngine(t)
	ev := feedCO2(t, e, 60, 600, rep(1800, 14))
	if len(ev) == 0 {
		t.Fatal("no events")
	}
	e.mu.Lock()
	e.Live = true
	e.mu.Unlock()
	st := stateOf(e, dqNode, dqMetric)
	if !st.alerted || st.fastAt == 0 {
		t.Skip("fixture: no episode flags to persist")
	}
	_, _, _ = e.SetSnooze(dqNode, dqMetric, "", 4, "calibration", "sam")
	wall = 2_000_000_000 + 74*300 // the feed ended here
	dir := t.TempDir()
	if err := e.SaveState(dir); err != nil {
		t.Fatal(err)
	}
	if _, err := os.Stat(enginePath(dir) + ".tmp"); err == nil {
		t.Fatal(".tmp left behind")
	}
	e2 := dqEngine(t)
	e2.SetLive(time.Hour)
	wall += 600 // restart 10 min later
	msg, err := e2.RestoreState(dir, nowTime())
	if err != nil || !strings.Contains(msg, "restored") {
		t.Fatalf("restore: %q %v", msg, err)
	}
	st2 := stateOf(e2, dqNode, dqMetric)
	if st2.alerted != st.alerted || st2.alertedAt != st.alertedAt || st2.fastAt != st.fastAt || st2.reportedSev != st.reportedSev {
		t.Fatalf("flags not restored: %+v vs %+v", st2, st)
	}
	e.mu.RLock()
	n1 := len(e.series[key(dqNode, dqMetric)])
	e.mu.RUnlock()
	e2.mu.RLock()
	n2 := len(e2.series[key(dqNode, dqMetric)])
	e2.mu.RUnlock()
	if n2 == 0 || n2 != n1 {
		t.Fatalf("readings restored %d of %d", n2, n1)
	}
	if e2.dq[key(dqNode, dqMetric)] == nil || e2.dq[key(dqNode, dqMetric)].snoozeUntil == 0 {
		t.Fatal("snooze not restored")
	}
	// older than 2 h: not restored
	e3 := dqEngine(t)
	e3.SetLive(time.Hour)
	wall += 3 * 3600
	if msg, _ := e3.RestoreState(dir, nowTime()); !strings.Contains(msg, "not restored") || stateOf(e3, dqNode, dqMetric).alerted {
		t.Fatalf("stale state restored: %q", msg)
	}
}

func TestPolishBootRecordAndHealth(t *testing.T) {
	old := devClock
	defer func() { devClock = old }()
	wall := int64(2_000_000_000)
	devClock = func() time.Time { return time.Unix(wall, 0) }
	s := testServer(t)
	recordBoot(s.dir)
	wall += 3600
	writeAlive(s.dir) // the saver's last marker before the "crash"
	wall += 60
	b := recordBoot(s.dir)
	if b.PrevUptimeS != 3600 {
		t.Fatalf("previous uptime %d, want 3600", b.PrevUptimeS)
	}
	if w, d := restartCounts(s.dir, nowTime()); w != 2 || d != 2 {
		t.Fatalf("restarts %d/%d", w, d)
	}
	recordBoot(s.dir)
	req := httptest.NewRequest("GET", "/api/health", nil)
	rec := httptest.NewRecorder()
	s.routes().ServeHTTP(rec, req)
	var out map[string]any
	if err := json.Unmarshal(rec.Body.Bytes(), &out); err != nil {
		t.Fatal(err, rec.Body.String())
	}
	if out["restarts_7d"].(float64) != 3 || out["restart_alert"] != true {
		t.Fatalf("health restarts: %v %v", out["restarts_7d"], out["restart_alert"])
	}
	if em, ok := out["event_mode"].(map[string]any); !ok || em["active"] != false || em["threshold"].(float64) != float64(defaultEventAlarms) {
		t.Fatalf("event_mode: %v", out["event_mode"])
	}
	if _, ok := out["domains"]; !ok {
		t.Fatal("health lost its domains")
	}
}

// A failed incident hosts its sensor again and is re-run automatically, without a duplicate.
func TestPolishFailedIncidentRerunsAndHosts(t *testing.T) {
	rg := newRefineRig(t)
	inc := rg.alert()
	rg.settle(inc.ID)
	rg.r.mu.Lock()
	i := rg.r.incidents[0]
	i.State, i.Workflow = "failed", wfInterrupted
	c := rg.co2Cand(false, "warning")
	if _, ok := promotionHost(i, c); !ok {
		rg.r.mu.Unlock()
		t.Fatal("a failed incident does not host its sensor")
	}
	rg.r.mu.Unlock()
	if n := rg.r.RerunFailed(); n != 1 {
		t.Fatalf("booked %d", n)
	}
	got := rg.settle(inc.ID)
	if len(rg.r.incidents) != 1 || got.State == "failed" || wfOf(&got) != wfNeeds {
		t.Fatalf("after re-run: %d incidents, state %s wf %s", len(rg.r.incidents), got.State, wfOf(&got))
	}
	if !tlHas(got, "Re-run automatically after a restart") {
		t.Fatalf("timeline: %+v", got.Timeline)
	}
}

// ---- 4. severity changes explained, drops from critical guarded

func TestPolishCriticalDropNeedsRules(t *testing.T) {
	mk := func(rule string) *Incident {
		return &Incident{Severity: "warning", Sensors: []SensorRef{{Ref: "S1", Metric: "co2", Rule: Finding{Status: rule}}},
			Final: &ReportCall{Parsed: &Report{Severity: "warning"}}}
	}
	sh := mk("critical")
	if !guardCriticalDrop("critical", sh) || sh.Severity != "critical" || sh.Final.Parsed.Severity != "critical" {
		t.Fatalf("drop accepted although the rules read critical: %s", sh.Severity)
	}
	sh = mk("warning")
	if guardCriticalDrop("critical", sh) || sh.Severity != "warning" {
		t.Fatal("drop refused although the rules agree")
	}
	if guardCriticalDrop("warning", mk("critical")) {
		t.Fatal("guard fired for a non-critical previous level")
	}
}

func TestPolishSeverityChangeCarriesReason(t *testing.T) {
	dir := t.TempDir()
	r := NewReasoner(NewGenieRunner(dir, dir, true), nil, dir, func(string, any) {})
	inc := &Incident{Severity: "warning", Sensors: []SensorRef{{Ref: "S1", Metric: "co2", Xs: []float64{900, 1820}}}, Final: &ReportCall{Parsed: &Report{}}}
	prev := Revision{Severity: "critical", Sensors: []RevSensor{{Ref: "S1", Pattern: "spike", Status: "critical"}}}
	cur := Revision{Severity: "warning", Sensors: []RevSensor{{Ref: "S1", Metric: "co2", Pattern: "step_increase", Status: "warning"}}}
	r.mu.Lock()
	why := r.noteSeverityChangeLocked(inc, prev, &cur, false)
	r.mu.Unlock()
	for _, want := range []string{"Severity critical -> warning", "CO2", "spike/critical -> step increase/warning", "1820"} {
		if !strings.Contains(why, want) {
			t.Fatalf("reason %q lacks %q", why, want)
		}
	}
	if cur.SeverityWhy != why || inc.SeverityWhy != why || len(inc.Timeline) != 1 || !strings.Contains(inc.Final.Note, why) {
		t.Fatal("reason not recorded on revision, incident, timeline and report")
	}
	cur2 := Revision{Severity: "warning"}
	r.mu.Lock()
	kept := r.noteSeverityChangeLocked(inc, Revision{Severity: "critical"}, &cur2, true)
	r.mu.Unlock()
	if !strings.HasPrefix(kept, "Kept critical") || !inc.SeverityKept {
		t.Fatalf("kept note: %q", kept)
	}
	if r.noteSeverityChangeLocked(inc, Revision{Severity: "warning"}, &Revision{Severity: "warning"}, false) != "" {
		t.Fatal("a reason was written without a change")
	}
}

// ---- 5. playbook

func TestPolishPlaybookPerMetricAndLocation(t *testing.T) {
	has := func(l []string, sub string) bool { return strings.Contains(strings.Join(l, "|"), sub) }
	if pl := metricPlaybookFor("air_quality", "pm25", "KN building, outdoor air station"); !has(pl, "Close windows") || !has(pl, "Warn the occupants") || !has(pl, "outdoor source") {
		t.Fatalf("outdoor PM: %v", pl)
	}
	if pl := metricPlaybookFor("air_quality", "pm25", "KH building, level 03, indoor air sensor"); has(pl, "Close windows") {
		t.Fatalf("indoor PM got the outdoor playbook: %v", pl)
	}
	for _, m := range []string{"ph", "tds"} {
		if pl := metricPlaybookFor("water", m, "KH building, level 98, water quality sensor 00"); !has(pl, "water sample") || !has(pl, "Stop drinking") || !has(pl, "dosing") {
			t.Fatalf("%s: %v", m, pl)
		}
	}
	if pl := metricPlaybookFor("water", "level", "tank"); !has(pl, "tank") || !has(pl, "valves") {
		t.Fatalf("tank: %v", pl)
	}
	if pl := metricPlaybookFor("power", "power_kw", "x"); !has(pl, "electrician") {
		t.Fatalf("power: %v", pl)
	}
	if pl := metricPlaybookFor("air_quality", "co2", "KH building, level 03, indoor air sensor 03"); !has(pl, "Ventilate") {
		t.Fatalf("co2: %v", pl)
	}
	if pl := metricPlaybookFor("hvac", "room_temp", "KH building, level 03, AC units"); !has(pl, "HVAC") {
		t.Fatalf("hvac: %v", pl)
	}
	if metricPlaybookFor("occupancy", "occ", "x") != nil {
		t.Fatal("occupancy has no specific playbook")
	}
	// wired into the checklist: no valid report/agent action -> the per-metric playbook, source "playbook"
	inc := &Incident{Severity: "critical", Roles: []string{"air_quality"}, State: "done",
		Sensors: []SensorRef{{Ref: "S1", Role: "air_quality", Metric: "pm25", Location: "KN building, outdoor air station", Rule: Finding{Status: "critical"}}}}
	steps := suggestedSteps(inc)
	if len(steps) == 0 || steps[0].Source != "playbook" || !strings.Contains(steps[0].Text, "Close windows") || !strings.Contains(steps[0].Why, "outdoor") {
		t.Fatalf("steps: %+v", steps)
	}
	// the reasoner's own action wins
	inc.Final = &ReportCall{Valid: true, Parsed: &Report{Severity: "critical", Action: "inspect_ventilation"}}
	if s := suggestedSteps(inc); len(s) == 0 || s[0].Source == "playbook" {
		t.Fatalf("the report's checklist lost to the playbook: %+v", s)
	}
}

// ---- 6. event mode

func buildingCands(t *testing.T, rg *refineRig, building string, n int) []Candidate {
	t.Helper()
	var keys []string
	for k, info := range rg.eng.Meta.Nodes {
		_ = k
		_ = info
	}
	rg.eng.mu.RLock()
	for _, k := range rg.eng.bankOrder {
		sn := rg.eng.bank[k]
		if sn.Building == building && sn.Role != "hvac" {
			keys = append(keys, k)
		}
	}
	rg.eng.mu.RUnlock()
	sort.Strings(keys)
	var out []Candidate
	for _, k := range keys {
		p := strings.SplitN(k, "|", 2)
		xs, ok := rg.eng.WindowAt(p[0], p[1], rg.eng.sim)
		if !ok {
			continue
		}
		role := rg.eng.Meta.Nodes[p[0]].Role
		f := RuleFinding(role, p[1], p[0], xs, rg.eng.sim)
		f.Status, f.Pattern = "warning", "step_increase"
		out = append(out, Candidate{p[0], p[1], role, f, xs, rg.eng.sim, false, false, false})
		if len(out) == n {
			break
		}
	}
	if len(out) < n {
		t.Skipf("only %d sensors in building %s", len(out), building)
	}
	return out
}

func TestPolishEventModeOneIncidentPerBuilding(t *testing.T) {
	rg := newRefineRig(t)
	withTrigger(t, defaultTrigger)
	cs := buildingCands(t, rg, "KH", 6)
	cs[0].Finding.Status = "critical"
	rg.r.HandleCandidates(cs)
	if len(rg.r.incidents) != 1 {
		t.Fatalf("event mode opened %d incidents, want 1", len(rg.r.incidents))
	}
	first := rg.r.incidents[0]
	rg.r.mu.RLock()
	sev, em, zone, title := first.Severity, first.EventMode, first.Zone, first.Title
	rg.r.mu.RUnlock()
	if sev != "critical" || !em || zone != "KH" || !strings.Contains(title, "Event mode") {
		t.Fatalf("event incident: sev %s em %v zone %s %q", sev, em, zone, title)
	}
	st := rg.r.EventModeStatus()
	if !st.Active || len(st.Buildings) != 1 || st.Buildings[0] != "KH" || len(st.Incidents) != 1 {
		t.Fatalf("status %+v", st)
	}
	got := rg.settle(first.ID)
	if len(rg.r.incidents) != 1 || len(got.Sensors) < 6 {
		t.Fatalf("after the AI: %d incidents, %d sensors", len(rg.r.incidents), len(got.Sensors))
	}
	if !tlHas(got, "Event mode: 6 sensors alarming in building KH") || !tlHas(got, "the AI reads level") {
		t.Fatalf("timeline: %+v", got.Timeline)
	}
	if got.State == "running" || got.Severity != "critical" && got.Severity != "warning" {
		t.Fatalf("state %s severity %s", got.State, got.Severity)
	}
	// a late 7th alarm in the same building joins the incident instead of opening another one
	more := buildingCands(t, rg, "KH", 8)
	have := map[string]bool{}
	for _, s := range got.Sensors {
		have[key(s.Node, s.Metric)] = true
	}
	var extra []Candidate
	for _, c := range more {
		if !have[key(c.Node, c.Metric)] {
			extra = append(extra, c)
		}
	}
	if len(extra) > 0 {
		rg.r.HandleCandidates(extra[:1])
		got = rg.settle(first.ID)
		if len(rg.r.incidents) != 1 {
			t.Fatalf("late alarm opened a second incident: %d", len(rg.r.incidents))
		}
	}
}

func TestPolishEventModeBelowThresholdIsNormal(t *testing.T) {
	rg := newRefineRig(t)
	withTrigger(t, defaultTrigger)
	cs := buildingCands(t, rg, "KH", 4)
	rg.r.HandleCandidates(cs)
	for t0 := time.Now(); time.Since(t0) < 5*time.Second; time.Sleep(10 * time.Millisecond) {
		rg.r.mu.RLock()
		n := len(rg.r.incidents)
		rg.r.mu.RUnlock()
		if n > 0 {
			break
		}
	}
	got := rg.settle(rg.r.incidents[0].ID)
	if got.EventMode || rg.r.EventModeStatus().Active {
		t.Fatal("event mode below the threshold")
	}
}

func TestPolishEventThresholdEditableAndValidated(t *testing.T) {
	bad := defaultTrigger
	bad.EventAlarms = 1
	if len(bad.Validate()) == 0 {
		t.Fatal("event_mode_alarms 1 accepted")
	}
	bad.EventAlarms = 101
	if len(bad.Validate()) == 0 {
		t.Fatal("event_mode_alarms 101 accepted")
	}
	s := testServer(t)
	withTrigger(t, defaultTrigger)
	mux := http.NewServeMux()
	s.rulesRoutes(mux)
	if code, out := rulesReq(t, mux, "PUT", `{"trigger":{"event_mode_alarms":8}}`); code != 200 || out["trigger"].(map[string]any)["event_mode_alarms"].(float64) != 8 {
		t.Fatalf("PUT %d %v", code, out)
	}
	if code, _ := rulesReq(t, mux, "PUT", `{"trigger":{"event_mode_alarms":0}}`); code != 400 {
		t.Fatalf("0 accepted: %d", code)
	}
	if trigRules().EventAlarms != 8 {
		t.Fatalf("rejected PUT changed the rules: %d", trigRules().EventAlarms)
	}
}

// ---- 7. maintenance snooze

func TestPolishSnoozeHoldsWarningsButNotCriticals(t *testing.T) {
	var warn []float64
	for i := 1; i <= 16; i++ {
		warn = append(warn, 1000+20*float64(i)) // warning, never critical
	}
	ctrl := dqEngine(t)
	if ev := feedCO2(t, ctrl, 60, 600, warn); len(ev) == 0 {
		t.Skip("fixture: the warning drift raises nothing without a snooze")
	}
	e := dqEngine(t)
	if _, _, err := e.SetSnooze(dqNode, dqMetric, "", 72, "AC repair", "sam"); err != nil {
		t.Fatal(err)
	}
	if ev := feedCO2(t, e, 60, 600, warn); len(ev) != 0 {
		t.Fatalf("a snoozed sensor raised %d events", len(ev))
	}
	if st := stateOf(e, dqNode, dqMetric); st.AbnormalFor != 0 {
		t.Fatalf("snoozed sensor counts abnormal readings: %d", st.AbnormalFor)
	}
	_, states, _ := e.Snapshot()
	shown := false
	for _, st := range states {
		if st.Node == dqNode && st.Metric == dqMetric {
			shown = st.Snoozed && st.SnoozeWhy == "AC repair" && st.SnoozeUntil > 0
		}
	}
	if !shown {
		t.Fatal("snoozed state not shown in the snapshot (/api/live)")
	}
	// a critical still alerts
	c := dqEngine(t)
	if _, _, err := c.SetSnooze(dqNode, dqMetric, "", 72, "AC repair", "sam"); err != nil {
		t.Fatal(err)
	}
	fast, _ := fpSplit(feedCO2(t, c, 60, 600, rep(1800, 14)))
	if len(fast) != 1 {
		t.Fatalf("a critical reading on a snoozed sensor did not alert: %d", len(fast))
	}
	dir := t.TempDir()
	r := NewReasoner(NewGenieRunner(dir, dir, true), c, dir, func(string, any) {})
	r.Mode = 1
	r.splitFast([]Candidate{fast[0].c})
	if len(r.incidents) != 1 || !tlHas(*r.incidents[0], "is snoozed (AC repair) but a critical reading still alerts") {
		t.Fatalf("critical on snoozed sensor: %+v", r.incidents)
	}
}

func TestPolishSnoozeRulesAndAPI(t *testing.T) {
	s := testServer(t)
	post := func(body string) (int, map[string]any) {
		req := httptest.NewRequest("POST", "/api/snooze", bytes.NewBufferString(body))
		req.RemoteAddr = "127.0.0.1:5000"
		rec := httptest.NewRecorder()
		s.routes().ServeHTTP(rec, req)
		var out map[string]any
		_ = json.Unmarshal(rec.Body.Bytes(), &out)
		return rec.Code, out
	}
	for _, bad := range []string{
		`{"node":"SR-AQ-KH03-03","metric":"co2","hours":4}`,                    // no reason
		`{"node":"SR-AQ-KH03-03","metric":"co2","hours":73,"reason":"repair"}`, // over 72 h
		`{"node":"SR-AQ-KH03-03","metric":"co2","hours":-1,"reason":"repair"}`, // negative
		`{"hours":4,"reason":"repair"}`,                                        // no target
		`{"node":"NOPE","hours":4,"reason":"repair"}`,                          // unknown
		`{"node":"SR-AQ-KH03-03","room":"x","hours":4,"reason":"repair"}`,      // both targets
	} {
		if code, _ := post(bad); code != 400 {
			t.Errorf("%s -> %d, want 400", bad, code)
		}
	}
	if code, out := post(`{"node":"SR-AQ-KH03-03","metric":"co2","hours":72,"reason":"AC repair","operator":"sam"}`); code != 200 || out["until"] == nil {
		t.Fatalf("snooze: %d %v", code, out)
	}
	if got := s.eng.SnoozeReason("SR-AQ-KH03-03", "co2"); got != "AC repair" {
		t.Fatalf("reason %q", got)
	}
	// a room = every sensor at that location
	room := ""
	for _, sn := range s.eng.Sensors() {
		if sn.Node == "SR-AQ-KH03-03" {
			room = sn.Location
		}
	}
	rb, _ := json.Marshal(map[string]any{"room": room, "hours": 2, "reason": "painting"})
	if code, out := post(string(rb)); code != 200 || len(out["sensors"].([]any)) < 3 {
		t.Fatalf("room snooze: %d %v", code, out)
	}
	req := httptest.NewRequest("GET", "/api/snooze", nil)
	rec := httptest.NewRecorder()
	s.routes().ServeHTTP(rec, req)
	var list struct {
		Snoozes []snoozeRow `json:"snoozes"`
	}
	_ = json.Unmarshal(rec.Body.Bytes(), &list)
	if len(list.Snoozes) < 3 {
		t.Fatalf("list: %+v", list.Snoozes)
	}
	if code, _ := post(`{"node":"SR-AQ-KH03-03","metric":"co2","hours":0}`); code != 200 || s.eng.SnoozeReason("SR-AQ-KH03-03", "co2") != "" {
		t.Fatal("hours 0 did not end the snooze")
	}
}

// ---- 8. deploy-check incidents

func TestPolishSystemCheckHiddenAndClosed(t *testing.T) {
	rg := newRefineRig(t)
	rg.r.ExpectSystemCheck("SR-AQ-KH03-03", "co2")
	chk := rg.alert()
	got := rg.settle(chk.ID)
	if !got.SystemCheck || wfOf(&got) != wfClosed || got.ClosedBy != "system" {
		t.Fatalf("system check: flag %v wf %s", got.SystemCheck, wfOf(&got))
	}
	if len(rg.r.List()) != 0 || rg.r.visibleCountLocked() != 0 {
		t.Fatalf("the operator sees the system check: list %d count %d", len(rg.r.List()), rg.r.visibleCountLocked())
	}
	if rg.r.Get(chk.ID) == nil {
		t.Fatal("the system check is gone (it must stay readable by ID)")
	}
	// a real analysis of the same sensor afterwards is a normal incident
	real := rg.alert()
	rgot := rg.settle(real.ID)
	if rgot.SystemCheck || len(rg.r.List()) != 1 {
		t.Fatalf("a real incident was hidden: %v, list %d", rgot.SystemCheck, len(rg.r.List()))
	}
}
