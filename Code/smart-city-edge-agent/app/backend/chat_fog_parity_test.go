package main

// r3 fog/local tools: device vs training parity, online/offline/timeout behaviour, the all-time index, the r3 header.
//   - TestChatFogParity: proofs/2026-11-06_4b_local/tools/parity_r3_cases.json (90 incidents from the r3 store, 40 of them
//     archived on the device, 8 sensors with 3 days of readings, ~46 calls x fog online/offline) through the Go tools; the
//     fog is a FogHandler over a Reasoner that holds every incident. Compared with tools_r3_impl.py's results
//     (parity_r3_out_py.json): field names, JSON types, values (numbers within 1 unit of their last decimal; monthly sensor
//     means within 1 %: the device averages 5-min readings, the training store hourly/daily rollups). fog_status last_sync is
//     a wall clock and is not compared. Go results -> parity_r3_out_go.json.
//   - TestChatFogFallback*: fog unset, fog down (HTTP 500), fog timeout -> device_fallback with coverage; no second wait
//     within 30 s; fog online -> source fog; bad arguments are the fog's answer, not an outage.
//   - TestChatHeaderR3MatchesTraining: chat_header_r3.txt and chat_system_r3.txt are byte-identical to the training files,
//     the header's tools are tools_r3.json["chat"], and the r3 prompt carries the live fog sentence.
// Skipped when the proofs folder is not there.

import (
	"context"
	"encoding/json"
	"math"
	"net/http"
	"net/http/httptest"
	"os"
	"path/filepath"
	"reflect"
	"strings"
	"testing"
	"time"
)

const r3Dir = "../../../../proofs/2026-11-06_4b_local"

type r3Case struct {
	Now       string                                                          `json:"now"`
	Start     string                                                          `json:"start"`
	StepMin   int                                                             `json:"step_min"`
	Readings  map[string][]float64                                            `json:"readings"`
	Archived  []string                                                        `json:"archived"`
	Sensors   []struct{ Node, Metric, Role, Location, Unit, Building string } `json:"sensors"`
	Incidents []struct {
		ID, At, Severity, Title, Label, Approval, Workflow, State, Outcome string
		Root                                                               string `json:"root_cause"`
		Refine                                                             string `json:"refine_stage"`
		Closed                                                             string `json:"closed_at"`
		Injected                                                           bool
		Sensors                                                            []struct {
			Ref, Node, Metric, Role, Status, Pattern string
			FaultKind                                string `json:"fault_kind"`
			Context                                  bool
		}
		Steps []struct{ Action, State, By string }
	} `json:"incidents"`
	Calls []struct {
		Name string         `json:"name"`
		Args map[string]any `json:"args"`
		Fog  string         `json:"fog"`
	} `json:"calls"`
}

func r3Engine(t *testing.T, c r3Case) *Engine {
	now, start := parityTime(t, c.Now), parityTime(t, c.Start)
	e := &Engine{series: map[string]map[int64]float64{}, states: map[string]*SensorState{}, sim: now.Unix(), Meta: ReplayMeta{Nodes: map[string]NodeInfo{}}}
	for _, s := range c.Sensors {
		k := key(s.Node, s.Metric)
		xs := c.Readings[k]
		ser := map[int64]float64{}
		for i, v := range xs {
			ser[start.Unix()+int64(i*c.StepMin*60)] = v
		}
		e.series[k] = ser
		e.states[k] = &SensorState{Node: s.Node, Metric: s.Metric, Role: s.Role, Location: s.Location, Unit: s.Unit, Last: fp(xs[len(xs)-1]), Status: "normal", DataOK: true}
		info := e.Meta.Nodes[s.Node]
		info.Role, info.Location, info.Building = s.Role, s.Location, s.Building
		info.Metrics = append(info.Metrics, s.Metric)
		e.Meta.Nodes[s.Node] = info
	}
	return e
}

func r3Incidents(t *testing.T, c r3Case) []*Incident {
	var out []*Incident
	for _, x := range c.Incidents {
		at := parityTime(t, x.At)
		inc := &Incident{ID: x.ID, State: x.State, CreatedSim: at.Unix(), CreatedWall: at.Format("2006-01-02 15:04:05"), Severity: x.Severity,
			Title: x.Title, Injected: x.Injected, Approval: x.Approval, RefineStage: x.Refine}
		inc.Workflow, inc.Outcome = x.Workflow, x.Outcome
		if x.Closed != "" {
			inc.ClosedAt = parityTime(t, x.Closed).Unix()
		}
		if x.Label != "" {
			inc.Final = &ReportCall{Valid: true, Parsed: &Report{Label: x.Label, RootCause: x.Root}}
		}
		for _, s := range x.Sensors {
			inc.Sensors = append(inc.Sensors, SensorRef{Ref: s.Ref, Node: s.Node, Metric: s.Metric, Role: s.Role, Context: s.Context,
				Rule: Finding{Status: s.Status, Pattern: s.Pattern}})
			if s.FaultKind != "" {
				inc.Agents = append(inc.Agents, AgentCall{Ref: s.Ref, Valid: true, Parsed: &Finding{Status: s.Status, Pattern: s.Pattern, FaultKind: s.FaultKind}})
			}
		}
		for _, st := range x.Steps {
			inc.Steps = append(inc.Steps, Step{Action: st.Action, State: st.State, By: st.By})
		}
		out = append(out, inc)
	}
	return out
}

// r3Setup: device Reasoner (full records + an archive file of the archived ones) and a fog server over all incidents.
func r3Setup(t *testing.T, c r3Case, kb []kbPassage) (dev chatTools, fog *httptest.Server) {
	t.Setenv("SCE_CHAT_PROMPT", "r3") // the r3 tools and the archive index are on only with chat_prompt=r3
	dir := t.TempDir()
	arch := map[string]bool{}
	for _, id := range c.Archived {
		arch[id] = true
	}
	all := r3Incidents(t, c)
	e := r3Engine(t, c)
	rd := &Reasoner{eng: e, store: filepath.Join(dir, "incidents.jsonl")}
	f, err := os.Create(archivePath(rd.store))
	if err != nil {
		t.Fatal(err)
	}
	for _, inc := range all {
		if arch[inc.ID] {
			b, _ := json.Marshal(inc)
			f.Write(append(b, '\n'))
		} else {
			rd.incidents = append(rd.incidents, inc)
		}
	}
	f.Close()
	rf := &Reasoner{eng: e, incidents: r3Incidents(t, c)}
	fog = httptest.NewServer(FogHandler(rf, kb))
	t.Cleanup(fog.Close)
	return chatTools{r: rd, now: parityTime(t, c.Now)}, fog
}

func r3KB(t *testing.T) []kbPassage {
	b, err := os.ReadFile(filepath.Join(r3Dir, "tools", "knowledge_r3.json"))
	if err != nil {
		t.Skip("knowledge base not here: ", err)
	}
	var kb []kbPassage
	if err := json.Unmarshal(b, &kb); err != nil {
		t.Fatal(err)
	}
	return kb
}

func r3Exec(tools chatTools, name string, args map[string]any) map[string]any {
	a, _ := json.Marshal(args)
	var cp map[string]any
	json.Unmarshal(a, &cp)
	var res map[string]any
	json.Unmarshal([]byte(tools.Exec(context.Background(), name, cp)), &res)
	delete(res, "query_id")
	return res
}

func TestChatFogParity(t *testing.T) {
	b, err := os.ReadFile(filepath.Join(r3Dir, "tools", "parity_r3_cases.json"))
	if err != nil {
		t.Skip("fixture not here: ", err)
	}
	var c r3Case
	if err := json.Unmarshal(b, &c); err != nil {
		t.Fatal(err)
	}
	pb, err := os.ReadFile(filepath.Join(r3Dir, "tools", "parity_r3_out_py.json"))
	if err != nil {
		t.Skip("python results not here (run parity_r3.py): ", err)
	}
	var py []struct {
		Name   string         `json:"name"`
		Fog    string         `json:"fog"`
		Result map[string]any `json:"result"`
	}
	if err := json.Unmarshal(pb, &py); err != nil {
		t.Fatal(err)
	}
	if len(py) != len(c.Calls) {
		t.Fatalf("python results %d != calls %d", len(py), len(c.Calls))
	}
	kb := r3KB(t)
	dev, fog := r3Setup(t, c, kb)
	var gout []map[string]any
	var diffs []string
	maxDiff := 0.0
	for i, call := range c.Calls {
		fogC = &fogClient{}
		if call.Fog == "online" {
			t.Setenv("SCE_FOG_URL", fog.URL)
		} else {
			t.Setenv("SCE_FOG_URL", "")
		}
		g := r3Exec(dev, call.Name, call.Args)
		gout = append(gout, map[string]any{"name": call.Name, "args": call.Args, "fog": call.Fog, "result": g})
		p := py[i].Result
		tag := call.Fog + " " + call.Name + " " + mustJSON(call.Args)
		if _, pe := p["error"]; pe {
			if _, ge := g["error"]; !ge {
				diffs = append(diffs, tag+": py error, go "+mustJSON(g)[:min(200, len(mustJSON(g)))])
			}
			continue
		}
		if call.Name == "fog_status" && call.Fog == "online" {
			g["last_sync"] = p["last_sync"]
		}
		if call.Name == "fog_analytics" && call.Args["analysis"] == "sensor_monthly" {
			gm, _ := g["months"].([]any)
			pm, _ := p["months"].([]any)
			for j := 0; j < len(gm) && j < len(pm); j++ {
				a, b := gm[j].(map[string]any), pm[j].(map[string]any)
				if x, y := a["mean"].(float64), b["mean"].(float64); math.Abs(x-y) <= 0.01*math.Abs(y) {
					a["mean"] = y
				}
			}
		}
		var d []string
		parityDiff("", g, p, &d, &maxDiff)
		for _, x := range d {
			diffs = append(diffs, tag+x)
		}
	}
	ob, _ := json.MarshalIndent(gout, "", " ")
	os.WriteFile(filepath.Join(r3Dir, "tools", "parity_r3_out_go.json"), ob, 0o644)
	if len(diffs) > 0 {
		t.Fatalf("%d differences:\n%s", len(diffs), strings.Join(diffs[:min(40, len(diffs))], "\n"))
	}
	t.Logf("%d calls identical (fog online and offline), max numeric difference %.4g", len(c.Calls), maxDiff)
}

func mustJSON(v any) string { b, _ := json.Marshal(v); return string(b) }

// a tiny fixture for the behaviour tests
func r3Mini(t *testing.T) (chatTools, *httptest.Server) {
	b, err := os.ReadFile(filepath.Join(r3Dir, "tools", "parity_r3_cases.json"))
	if err != nil {
		t.Skip("fixture not here: ", err)
	}
	var c r3Case
	json.Unmarshal(b, &c)
	return r3Setup(t, c, r3KB(t))
}

func TestChatFogFallbackUnset(t *testing.T) {
	dev, _ := r3Mini(t)
	fogC = &fogClient{}
	t.Setenv("SCE_FOG_URL", "")
	r := r3Exec(dev, "fog_search_history", map[string]any{"time": map[string]any{"preset": "all"}, "limit": 3})
	cov, _ := r["coverage"].(map[string]any)
	if r["source"] != "device_fallback" || r["fog"] != "unreachable" || cov == nil || cov["complete"] != false || cov["counts_exact"] != true ||
		cov["incidents"] != 50.0 || cov["from"] == nil || cov["index_from"] == nil || !strings.Contains(cov["note"].(string), "fog unreachable") {
		t.Fatalf("fallback result: %s", mustJSON(r))
	}
	if r["total"].(float64) < 80 { // the index keeps the 40 archived incidents countable
		t.Fatalf("total %v: archived incidents missing from the device index", r["total"])
	}
	k := r3Exec(dev, "search_knowledge", map[string]any{"query": "drinking water pH limit"})
	if k["source"] != "device_fallback" || k["available"] != true || !strings.Contains(mustJSON(k), "KB-IS10500-PH") {
		t.Fatalf("knowledge fallback: %s", mustJSON(k))
	}
	s := r3Exec(dev, "fog_status", nil)
	if s["fog"] != "unreachable" || s["last_sync"] != nil || s["pending_uploads"].(float64) != 90 {
		t.Fatalf("fog_status unset: %s", mustJSON(s))
	}
	if !strings.Contains(chatFogLine(), "unreachable (never synced)") {
		t.Fatalf("fog line: %q", chatFogLine())
	}
	if n := r3Exec(dev, "count_incidents", map[string]any{"time": map[string]any{"preset": "all"}}); n["count"].(float64) < 80 {
		t.Fatalf("count_incidents without the archived index: %s", mustJSON(n))
	}
}

func TestChatFogFallbackDownAndTimeout(t *testing.T) {
	dev, _ := r3Mini(t)
	slow := httptest.NewServer(http.HandlerFunc(func(w http.ResponseWriter, r *http.Request) { time.Sleep(600 * time.Millisecond) }))
	defer slow.Close()
	down := httptest.NewServer(http.HandlerFunc(func(w http.ResponseWriter, r *http.Request) { http.Error(w, "x", 500) }))
	defer down.Close()
	t.Setenv("SCE_FOG_TIMEOUT_MS", "200")
	for _, srv := range []*httptest.Server{down, slow} {
		fogC = &fogClient{}
		t.Setenv("SCE_FOG_URL", srv.URL)
		t0 := time.Now()
		r := r3Exec(dev, "fog_analytics", map[string]any{"analysis": "incident_trend", "time": map[string]any{"preset": "all"}})
		if r["source"] != "device_fallback" || r["fog"] != "unreachable" {
			t.Fatalf("%s: %s", srv.URL, mustJSON(r))
		}
		if d := time.Since(t0); d > 450*time.Millisecond {
			t.Fatalf("fallback took %v (timeout 200 ms)", d)
		}
		t1 := time.Now() // a second fog call within 30 s does not wait again
		r3Exec(dev, "search_knowledge", map[string]any{"query": "pH"})
		if d := time.Since(t1); d > 100*time.Millisecond {
			t.Fatalf("second call waited %v", d)
		}
		if !strings.Contains(chatFogLine(), "unreachable") {
			t.Fatalf("fog line after failure: %q", chatFogLine())
		}
	}
}

func TestChatFogOnline(t *testing.T) {
	dev, fog := r3Mini(t)
	fogC = &fogClient{}
	t.Setenv("SCE_FOG_URL", fog.URL)
	r := r3Exec(dev, "fog_search_history", map[string]any{"time": map[string]any{"preset": "all"}, "limit": 10})
	cov, _ := r["coverage"].(map[string]any)
	if r["source"] != "fog" || r["fog"] != nil || cov["complete"] != true || cov["incidents"] != 90.0 {
		t.Fatalf("online: %s", mustJSON(r))
	}
	if !strings.Contains(chatFogLine(), "online: the fog server is reachable") {
		t.Fatalf("fog line online: %q", chatFogLine())
	}
	if n := r3Exec(dev, "count_incidents", map[string]any{"time": map[string]any{"preset": "all"}}); n["coverage"].(map[string]any)["note"] != "device store" {
		t.Fatalf("device coverage note online: %s", mustJSON(n))
	}
	e := r3Exec(dev, "fog_analytics", map[string]any{"analysis": "forecast", "time": map[string]any{"preset": "all"}})
	if e["error"] == nil || e["source"] != nil {
		t.Fatalf("a bad argument is the fog's answer: %s", mustJSON(e))
	}
	if _, ok, _ := fogC.State(); !ok {
		t.Fatal("an error result marked the fog unreachable")
	}
}

func TestChatHeaderR3MatchesTraining(t *testing.T) {
	want, err := os.ReadFile(filepath.Join(r3Dir, "tools", "chat_header_r3.txt"))
	if err != nil {
		t.Skip("training header not here: ", err)
	}
	if chatHeaderR3 != string(want) {
		t.Fatalf("chat_header_r3.txt differs from the training header (%d vs %d bytes)", len(chatHeaderR3), len(want))
	}
	sys, _ := os.ReadFile(filepath.Join(r3Dir, "tools", "chat_system_r3.txt"))
	if chatSystemR3 != string(sys) {
		t.Fatal("chat_system_r3.txt differs from the training system text")
	}
	tb, err := os.ReadFile(filepath.Join(r3Dir, "data", "final", "tools_r3.json"))
	if err != nil {
		t.Skip("tools_r3.json not here: ", err)
	}
	var tools map[string][]any
	json.Unmarshal(tb, &tools)
	if got := chatHeaderTools(t, chatHeaderR3); !reflect.DeepEqual(got, tools["chat"]) {
		t.Fatalf("r3 header tools %v != tools_r3 chat %v", chatToolNamesOf(got), chatToolNamesOf(tools["chat"]))
	}
	t.Setenv("SCE_CHAT_PROMPT", "r3") // the r3 tools are served only with chat_prompt=r3
	for _, x := range tools["chat"] { // every header tool is served
		n := x.(map[string]any)["function"].(map[string]any)["name"].(string)
		if _, err := (chatTools{r: &Reasoner{}, now: time.Now()}).run(n, map[string]any{}); err != nil && strings.HasPrefix(err.Error(), "unknown tool") {
			t.Fatalf("header tool %s has no executor", n)
		}
	}
	fogC = &fogClient{}
	chatFogRef.Store(nil)
	t.Setenv("SCE_FOG_URL", "")
	t.Setenv("SCE_CHAT_PROMPT", "r3")
	now := time.Date(2026, 10, 22, 12, 7, 0, 0, IST)
	p := chatStaticPrefixMode(now, true)
	wantP := string(want) + "You are the operator assistant of a smart-campus edge monitor (IIIT Hyderabad) on a Qualcomm QIDK. Device time: 2026-10-22 12:00 IST (Thursday). " +
		"The device is offline: the fog server is unreachable (never synced). Full incident records on the device since 2026-10-22.\n" + string(sys) + "<|im_end|>\n<|im_start|>user\n"
	if p != wantP {
		i := 0
		for i < len(p) && i < len(wantP) && p[i] == wantP[i] {
			i++
		}
		t.Fatalf("r3 static prefix differs from the training render at byte %d: %q vs %q", i, p[i:min(len(p), i+80)], wantP[i:min(len(wantP), i+80)])
	}
	if q := chatStaticPrefixMode(now, false); strings.Contains(q, "fog_search_history") { // thinking off (rsn_v1) keeps its prompt
		t.Fatal("rsn_v1 prompt changed")
	}
	if chatHeaderFor(true) != chatHeaderR3 {
		t.Fatal("keep-warm must send the r3 header")
	}
	chatFogRef.Store(&Reasoner{incidents: []*Incident{{ID: "INC-0001", CreatedSim: time.Date(2026, 6, 24, 0, 39, 0, 0, IST).Unix()}}})
	defer chatFogRef.Store(nil)
	if p := chatStaticPrefixMode(now, true); !strings.Contains(p, "(never synced). Full incident records on the device since 2026-06-24.\n") {
		t.Fatal("device-store sentence missing")
	}
}
