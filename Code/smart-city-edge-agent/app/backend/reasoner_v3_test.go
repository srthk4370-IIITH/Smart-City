package main

import (
	"bytes"
	"context"
	"encoding/json"
	"os"
	"strconv"
	"strings"
	"testing"
	"time"
)

type v3Fixture struct {
	System string `json:"system"`
	Cases  []struct {
		Input struct {
			End     int64      `json:"end"`
			Outdoor *[3]string `json:"outdoor"`
			IncID   string     `json:"inc_id"`
			Mode    string     `json:"mode"`
			WinH    string     `json:"win_h"`
			Sensors []struct {
				Ref, Node, Metric, Loc, Role, Why, Quality, Stale string
				Flagged                                           bool
				Head                                              []string
				Agent                                             *struct {
					Pattern, Status, Cause string
					Conf                   float64
					Obs                    []string
				}
				Rule []string    `json:"rule"`
				Ev   [][2]string `json:"ev"`
			} `json:"sensors"`
			Recheck     []string  `json:"recheck"`
			Memory      *[]string `json:"memory"`
			Notes       []string  `json:"notes"`
			MissingNote string    `json:"missing_note"`
			Ask         string    `json:"ask"`
		} `json:"input"`
		User string `json:"user"`
		Chat string `json:"chat"`
	} `json:"cases"`
	ToolTurn struct {
		Calls []struct {
			Name      string                     `json:"name"`
			Arguments map[string]json.RawMessage `json:"arguments"`
		} `json:"calls"`
		Results []string `json:"results"`
		Chat    string   `json:"chat"`
	} `json:"tool_turn"`
}

func loadV3Fixture(t *testing.T) v3Fixture {
	b, err := os.ReadFile("testdata/reasoner_v3_fixtures.json")
	if err != nil {
		t.Fatal(err)
	}
	var f v3Fixture
	if err := json.Unmarshal(b, &f); err != nil {
		t.Fatal(err)
	}
	return f
}

func v3Diff(a, b string) string {
	i := 0
	for i < len(a) && i < len(b) && a[i] == b[i] {
		i++
	}
	lo := i - 60
	if lo < 0 {
		lo = 0
	}
	hi := func(s string) int {
		if i+60 < len(s) {
			return i + 60
		}
		return len(s)
	}
	return "at byte " + strconv.Itoa(i) + "\n got: " + strconv.Quote(a[lo:hi(a)]) + "\nwant: " + strconv.Quote(b[lo:hi(b)])
}

// The Go prompt must be byte-identical to the training renderer and the model's chat template (SPEC §9).
func TestReasonerPromptV3Golden(t *testing.T) {
	f := loadV3Fixture(t)
	if f.System != v3System {
		t.Fatal("reasoner_v3_system.txt differs from prompts.SYSTEM_INCIDENT_SHORT")
	}
	for k, c := range f.Cases {
		ci := c.Input
		in := V3Input{End: ci.End, Outdoor: ci.Outdoor, IncID: ci.IncID, Mode: ci.Mode, WinH: ci.WinH, Recheck: ci.Recheck,
			Notes: ci.Notes, MissingNote: ci.MissingNote, Ask: ci.Ask}
		if ci.Memory != nil {
			in.MemoryKnown, in.Memory = true, *ci.Memory
		}
		for _, s := range ci.Sensors {
			vs := V3Sensor{Ref: s.Ref, Node: s.Node, Metric: s.Metric, Loc: s.Loc, Role: s.Role, Why: s.Why, Flagged: s.Flagged,
				Head: s.Head, Quality: s.Quality, Stale: s.Stale, Ev: s.Ev}
			if len(s.Rule) == 2 {
				vs.Rule = [2]string{s.Rule[0], s.Rule[1]}
			}
			if s.Agent != nil {
				vs.Agent = &V3Agent{s.Agent.Pattern, s.Agent.Status, s.Agent.Cause, s.Agent.Conf, s.Agent.Obs}
			}
			in.Sensors = append(in.Sensors, vs)
		}
		user := RenderV3User(in)
		if user != c.User {
			t.Fatalf("case %d user prompt %s", k, v3Diff(user, c.User))
		}
		if p := reasonerPromptV3(user, nil); p != c.Chat {
			t.Fatalf("case %d chat %s", k, v3Diff(p, c.Chat))
		}
	}
	tt := f.ToolTurn
	var turn v3Turn
	for _, c := range tt.Calls {
		vc := V3Call{Name: c.Name}
		// fixture argument order is the call's order (jinja iterates the dict in insertion order)
		keys := []string{"node", "time", "ref", "hours"}
		for _, k := range keys {
			if raw, ok := c.Arguments[k]; ok {
				var s string
				v := string(raw)
				if json.Unmarshal(raw, &s) == nil {
					v = s
				} else {
					v = pyJSONForTest(raw)
				}
				vc.Params = append(vc.Params, V3Param{k, v})
			}
		}
		turn.Calls = append(turn.Calls, vc)
	}
	turn.Results = tt.Results
	if p := reasonerPromptV3(f.Cases[0].User, []v3Turn{turn}); p != tt.Chat {
		t.Fatalf("tool turn %s", v3Diff(p, tt.Chat))
	}
	// parse the rendered calls back
	calls := parseV3Calls(tt.Chat[len(v3StaticPrefix()):]) // the header holds the template's own example call
	if len(calls) != 2 || calls[0].Name != "get_action_history" || calls[1].Args()["hours"] != float64(4) {
		t.Fatalf("parse: %+v", calls)
	}
	if tm, _ := calls[0].Args()["time"].(map[string]any); tm["preset"] != "last_30d" {
		t.Fatalf("time arg: %+v", calls[0].Args())
	}
}

// pyJSONForTest: Python json.dumps spacing for the small objects in the fixture.
func pyJSONForTest(raw json.RawMessage) string {
	var c bytes.Buffer
	_ = json.Compact(&c, raw)
	s := c.String()
	s = strings.ReplaceAll(s, `":`, `": `)
	s = strings.ReplaceAll(s, `,"`, `, "`)
	return s
}

func TestV3ContextLine(t *testing.T) {
	end := time.Date(2026, 10, 22, 14, 35, 0, 0, IST).Unix()
	if got := v3ContextLine(end, nil); got != "CONTEXT: Thu 22 Oct 2026 14:35 IST | workday | daytime" {
		t.Fatal(got)
	}
	end = time.Date(2026, 11, 8, 5, 0, 0, 0, IST).Unix()
	if got := v3ContextLine(end, nil); !strings.Contains(got, "holiday:Diwali | night") {
		t.Fatal(got)
	}
	if v3HoursStr(48) != "4" || v3HoursStr(144) != "12" || v3HoursStr(18) != "1.5" {
		t.Fatal(v3HoursStr(48), v3HoursStr(144), v3HoursStr(18))
	}
	if v3Unit("power", "pf") != "ratio" || v3Unit("hvac", "room_temp") != "C" || v3Unit("water", "level") != "level" {
		t.Fatal("units")
	}
}

const v3Prompt = `S1 [FLAGGED]: SR-AQ-VN02-03 co2 [ppm] at VN (air_quality)
  S1.E1 last = 1643 ppm
  S1.E4 trend = +266.6 ppm/h (r2 1.00)
S2 [related: occupancy]: SR-OC-GW-VN95-03 occ [0/1] at VN (occupancy)
  S2.E1 current state = 1
  S2.E4 first occupied at 05:50
  R1 08:15 warning`

const v3Good = `{"title": "VN building, level 02: CO2 over the critical limit in an occupied room", "severity": "critical", "label": "occupancy_driven_load", "root_cause": "Occupied room CO2 rose past the critical limit.", "causal_chain": "occupied (S2.E1) -> CO2 rising (S1.E4)", "observations": [{"text": "CO2 1643 ppm is over the critical limit of 1500 ppm", "src": ["S1.E1"]}, {"text": "Occupancy began at 05:50", "src": ["S2.E4"]}], "agent_checks": [{"ref": "S1", "claim": "CO2 within the usual range", "verdict": "contradicted", "fact": "CO2 1643 ppm", "src": ["S1.E1"]}], "affected_domains": ["air_quality", "occupancy"], "suspect_sensors": [], "evidence": ["S1.E1", "S1.E4", "S2.E1"], "confidence": 0.85, "checklist": [{"action": "inspect_ventilation", "target": "S1 (SR-AQ-VN02-03)", "why": "Fresh air for an occupied room"}, {"action": "monitor", "target": "S1", "why": "Watch the trend"}], "monitor_next": "CO2 at the next re-check", "needs_more_data": false, "needs_deeper": false, "explanation": "The room is occupied and CO2 keeps rising."}`

func TestCheckReportV3(t *testing.T) {
	known := v3Prompt + "\nlimit 1500"
	r, errs, _ := checkReportV3(v3Good, known)
	if r == nil || len(errs) != 0 {
		t.Fatalf("good report rejected: %v", errs)
	}
	rep := r.toReport("device:test")
	if rep.Action != "inspect_ventilation" || rep.Source != "device:test" || !rep.RequiresHuman || len(rep.Observations) != 2 {
		t.Fatalf("toReport: %+v", rep)
	}
	bad := map[string]string{
		"not in the input": strings.Replace(v3Good, "CO2 1643 ppm is", "CO2 1720 ppm is", 1),
		"unknown id":       strings.Replace(v3Good, `"S2.E1"]`, `"S3.E1"]`, 1),
		"not whitelisted":  strings.Replace(v3Good, `"inspect_ventilation"`, `"open_windows"`, 1),
		"must start":       strings.Replace(v3Good, `"inspect_ventilation"`, `"monitor"`, 1),
		"actuation":        strings.Replace(v3Good, "Fresh air for an occupied room", "shut down the AHU", 1),
		"says normal":      strings.Replace(v3Good, "over the critical limit in an occupied room", "judged normal", 1),
		"verdict":          strings.Replace(v3Good, `"contradicted"`, `"wrong"`, 1),
	}
	for want, txt := range bad {
		_, errs, _ := checkReportV3(txt, known)
		if !strings.Contains(strings.Join(errs, "; "), want) {
			t.Errorf("%s: not rejected (%v)", want, errs)
		}
	}
	if _, errs, rep := checkReportV3(strings.TrimSuffix(v3Good, "}"), known); len(errs) != 0 || len(rep) != 1 {
		t.Fatalf("missing brace repair: %v %v", errs, rep)
	}
}

func TestV3ClaimFlagsEscalationTitle(t *testing.T) {
	calls := []AgentCall{{Ref: "S1", ClaimFlags: []ClaimFlag{
		{Kind: "time_of_day", Claim: "night-time rise", Fact: "window ends 14:00 on a workday", Evidence: []string{"E1"}},
		{Kind: "direction", Claim: "CO2 within the usual range", Fact: "dup"}}}}
	got := mergeClaimFlags([]V3AgentCheck{{Ref: "S1", Claim: "CO2 within the usual range", Verdict: "contradicted"}}, []string{"S1"}, calls)
	if len(got) != 2 || got[1].By != "claimcheck" || got[1].Src[0] != "S1.E1" {
		t.Fatalf("merge: %+v", got)
	}
	e := v3Escalation(true, 0, 1, []string{`{"coverage": {"source": "device", "complete": false}}`}, true)
	if !e.Offer || strings.Join(e.Reasons, ",") != "coverage,model_offer" {
		t.Fatalf("escalation: %+v", e)
	}
	if e := v3Escalation(true, 0, 1, nil, false); e.Offer {
		t.Fatal("no reason, no offer")
	}
	if e := v3Escalation(false, 6, 1, nil, false); strings.Join(e.Reasons, ",") != "verification_failed,too_big" {
		t.Fatalf("%+v", e)
	}
	if _, ok := v3StreamTitle(`{"title": "CO2 ri`); ok {
		t.Fatal("partial title")
	}
	if tt, ok := v3StreamTitle(`{"title": "CO2 \"high\" at VN", "sev`); !ok || tt != `CO2 "high" at VN` {
		t.Fatal(tt)
	}
}

type fakeLLM struct {
	replies []string
	prompts []string
}

func (f *fakeLLM) Name() string { return "fake" }
func (f *fakeLLM) Complete(_ context.Context, p string, _ int, on func(string)) (string, CallMetrics, error) {
	f.prompts = append(f.prompts, p)
	r := f.replies[0]
	if len(f.replies) > 1 {
		f.replies = f.replies[1:]
	}
	if on != nil {
		on(r)
	}
	return r, CallMetrics{GenTokens: 10}, nil
}

type fakeTools struct{ n int }

func (f *fakeTools) Exec(_ context.Context, name string, _ map[string]any) string {
	f.n++
	return `{"items": [], "coverage": {"source": "device", "complete": true}}`
}

const v3CallText = "<tool_call>\n<function=get_action_history>\n<parameter=node>\nN1\n</parameter>\n</function>\n</tool_call>"

func TestRunV3LoopCap(t *testing.T) {
	// direct answer: one completion, no tools
	l := &fakeLLM{replies: []string{v3Good}}
	run, err := runV3Loop(context.Background(), l, &fakeTools{}, "U", 1, 100, nil)
	if err != nil || run.LLMCalls != 1 || run.Forced || run.Text != v3Good {
		t.Fatalf("direct: %+v %v", run, err)
	}
	// a model that keeps calling tools: 1 call executed, then the answer is forced with the trained prefix
	l = &fakeLLM{replies: []string{v3CallText + "\n" + v3CallText, strings.TrimPrefix(v3Good, v3AnswerPrefix)}}
	ft := &fakeTools{}
	run, err = runV3Loop(context.Background(), l, ft, "U", 1, 100, nil)
	if err != nil || ft.n != 1 || run.LLMCalls != 2 || !run.Forced || run.Text != v3Good || run.Wanted != 2 {
		t.Fatalf("cap: n=%d %+v %v", ft.n, run, err)
	}
	if !strings.HasSuffix(l.prompts[1], "</tool_response><|im_end|>\n"+v3AssistantOpen+v3AnswerPrefix) {
		t.Fatalf("forced prompt tail: %q", l.prompts[1][len(l.prompts[1])-120:])
	}
	if !strings.HasPrefix(l.prompts[0], v3StaticPrefix()) {
		t.Fatal("static prefix (prefix cache) not at the start of the prompt")
	}
	// cap 0: never a tool; the call is refused and the answer forced
	l = &fakeLLM{replies: []string{v3CallText, strings.TrimPrefix(v3Good, v3AnswerPrefix)}}
	ft = &fakeTools{}
	run, _ = runV3Loop(context.Background(), l, ft, "U", 0, 100, nil)
	if ft.n != 0 || run.LLMCalls != 2 || !run.Forced || run.Text != v3Good {
		t.Fatalf("cap 0: %+v", run)
	}
}

func TestReasonerV3DefaultOff(t *testing.T) {
	t.Setenv("SCE_REASONER", "")
	if reasonerV3Enabled() && htpdProfile()["reasoner"] != "v3" {
		t.Fatal("reasoner v3 must be off by default")
	}
	if reasonerMaxCalls("early") != 1 || reasonerMaxCalls("refine-3h") != 2 {
		t.Fatal("D7 caps")
	}
	t.Setenv("SCE_REASONER_MAX_CALLS", "5")
	if reasonerMaxCalls("refine-1.5h") != 2 {
		t.Fatal("the profile may only lower the cap")
	}
}

func TestV3StreamSeverity(t *testing.T) {
	for _, c := range []struct {
		in, want string
		ok       bool
	}{
		{`{"title": "x", "severity": "warn`, "", false},
		{`{"title": "x", "severity": "warning"`, "warning", true},
		{`{"title": "x", "severity": "bogus", "label"`, "", false},
		{`no answer`, "", false},
	} {
		if got, ok := v3StreamSeverity(c.in); got != c.want || ok != c.ok {
			t.Fatalf("%q: got %q %v, want %q %v", c.in, got, ok, c.want, c.ok)
		}
	}
}

// Board 2026-10-27, INC-0361 3 h refinement: a sound report with 7 evidence ids was rejected whole. Now trimmed.
func TestV3GateTrimsOverlongLists(t *testing.T) {
	b, err := os.ReadFile("testdata/reasoner_v3_board_7ev.json")
	if err != nil {
		t.Fatal(err)
	}
	var c struct{ Raw, Prompt string }
	if err := json.Unmarshal(b, &c); err != nil {
		t.Fatal(err)
	}
	r, errs, repairs := checkReportV3(c.Raw, c.Prompt)
	if r == nil || len(errs) != 0 {
		t.Fatalf("board report rejected: %v", errs)
	}
	if len(r.Evidence) != 6 || len(repairs) == 0 {
		t.Fatalf("evidence %d (want 6), repairs %v", len(r.Evidence), repairs)
	}
}

func TestSeverityGuardLight(t *testing.T) {
	r := &Reasoner{notify: func(string, any) {}}
	inc := func(rule string) *Incident {
		return &Incident{ID: "INC-T", Sensors: []SensorRef{{Ref: "S1", Rule: Finding{Status: rule}}, {Ref: "S2", Context: true, Rule: Finding{Status: "critical"}}}}
	}
	for _, c := range []struct{ rule, sev, want, title string }{
		{"warning", "normal", "warning", ""},    // the dangerous downgrade: blocked, calm title dropped
		{"critical", "normal", "warning", ""},   // blocked to warning only (not critical)
		{"critical", "warning", "warning", "x"}, // warning vs critical stays the reasoner's choice
		{"warning", "critical", "critical", "x"},
		{"warning", "sensor_fault", "sensor_fault", "x"}, // a fault diagnosis is not a downgrade
		{"normal", "normal", "normal", "x"},              // context sensors do not anchor
	} {
		title := "x"
		if c.sev == "normal" {
			title = "Power load stepped up, no fault: KH"
			if c.want == "normal" {
				title = "x"
			}
		}
		rep := Report{Severity: c.sev, Title: title}
		i := inc(c.rule)
		r.severityGuard(i, &rep)
		if rep.Severity != c.want || rep.Title != c.title || rep.SeverityBasis == nil || rep.SeverityBasis.Reasoner != c.sev || rep.SeverityBasis.Rule != c.rule {
			t.Fatalf("rule %s reasoner %s: got %s title %q basis %+v", c.rule, c.sev, rep.Severity, rep.Title, rep.SeverityBasis)
		}
	}
}

func TestPreliminaryReport(t *testing.T) {
	r := &Reasoner{notify: func(string, any) {}}
	inc := &Incident{ID: "INC-P"}
	r.preliminary(inc, &ReportCall{Model: "deterministic (related domains verified steady)", Parsed: &Report{Severity: "warning"}, Valid: true})
	if inc.Final == nil || !inc.Final.Preliminary || inc.Final.Model != "preliminary (rules + agent findings)" {
		t.Fatalf("stage 1 not shown: %+v", inc.Final)
	}
	r.preliminary(inc, nil) // nothing to show: keeps what is there
	if inc.Final == nil || !inc.Final.Preliminary {
		t.Fatal("nil preliminary cleared the report")
	}
}

func TestV3SplitProfile(t *testing.T) {
	t.Setenv("SCE_REASONER_SPLIT", "")
	if v3SplitGroups() != nil || reasonerStreams() != 1 {
		t.Fatal("split must be off by default")
	}
	t.Setenv("SCE_REASONER_SPLIT", "3")
	sp := v3SplitGroups()
	if sp == nil || reasonerStreams() != 3 || sp.After != "causal_chain" {
		t.Fatalf("split 3: %+v", sp)
	}
	// the groups cover the schema keys after the head, in order
	var keys []string
	for _, g := range sp.Groups {
		keys = append(keys, g...)
	}
	all := v3ForceSchema()["keys"].([]string)
	if strings.Join(keys, ",") != strings.Join(all[5:], ",") {
		t.Fatalf("groups %v != schema tail %v", keys, all[5:])
	}
}

func TestCheckReportV3ContractRepairs(t *testing.T) {
	known := v3Prompt + "\nlimit 1500\nS1 at VN building, level 02"
	moved := strings.Replace(v3Good, "VN building, level 02", "TH building, level 03", 1)
	r, errs, rep := checkReportV3(moved, known)
	if len(errs) != 0 || !strings.HasPrefix(r.Title, "VN building, level 02:") || len(rep) != 1 {
		t.Fatalf("title location repair: %q %v %v", r.Title, errs, rep)
	}
	nmd := strings.Replace(strings.Replace(v3Good, `"needs_more_data": false`, `"needs_more_data": true`, 1),
		`"severity": "critical"`, `"severity": "normal"`, 1)
	nmd = strings.Replace(nmd, `"inspect_ventilation"`, `"monitor"`, 1)
	nmd = strings.Replace(nmd, "CO2 over the critical limit in an occupied room", "data gaps", 1)
	r, _, rep = checkReportV3(nmd, known)
	if r.Label != "unknown" || len(rep) != 1 {
		t.Fatalf("normal + needs_more_data label repair: %q %v", r.Label, rep)
	}
	if r, _, _ = checkReportV3(v3Good, known); r.Label != "occupancy_driven_load" || !strings.HasPrefix(r.Title, "VN building, level 02:") {
		t.Fatalf("good report changed: %q %q", r.Label, r.Title)
	}
}
