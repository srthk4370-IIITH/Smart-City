package main

// Device/training parity of the chat tools: proofs/2026-10-29_rsn_v3/pipeline/parity_cases.json (a hand-made fixture:
// sensors, 5-min readings, incidents, tool calls) is loaded into an Engine and a Reasoner, every call runs on the Go
// tools, and the results are compared with what the training-store tools (pipeline/tools_v3_impl.py, run by
// pipeline/parity_py.py -> parity_out_py.json) returned for the same fixture: the same field names, JSON types and
// values (numbers within the rounding written: 1 unit of their last decimal; integers exact). The Go results are
// written to parity_out_go.json next to the Python ones. Skipped when the proofs folder is not there.

import (
	"encoding/json"
	"fmt"
	"math"
	"os"
	"path/filepath"
	"sort"
	"strconv"
	"strings"
	"testing"
	"time"
)

const parityDir = "../../../../proofs/2026-10-29_rsn_v3/pipeline"

type parityCase struct {
	Now     string `json:"now"`
	Start   string `json:"start"`
	StepMin int    `json:"step_min"`
	Sensors []struct {
		Node, Metric, Role, Location, Unit, Building string
	} `json:"sensors"`
	Readings  map[string][]float64 `json:"readings"`
	Incidents []struct {
		ID, At, Severity, Title, Label, Approval, Workflow, State, Outcome string
		Root                                                               string `json:"root_cause"`
		Injected                                                           bool
		Sensors                                                            []struct {
			Ref, Node, Metric, Role, Status, Pattern string
			FaultKind                                string `json:"fault_kind"`
			Context                                  bool
		}
	} `json:"incidents"`
	Calls []struct {
		Name string         `json:"name"`
		Args map[string]any `json:"args"`
	} `json:"calls"`
}

func parityTime(t *testing.T, s string) time.Time {
	x, err := time.ParseInLocation("2006-01-02 15:04", s, IST)
	if err != nil {
		t.Fatal(err)
	}
	return x
}

// parityTools builds the Engine (series, live state = last reading, engine status normal) and the incidents.
func parityTools(t *testing.T, c parityCase) chatTools {
	now, start := parityTime(t, c.Now), parityTime(t, c.Start)
	e := &Engine{series: map[string]map[int64]float64{}, states: map[string]*SensorState{}, sim: now.Unix(),
		Meta: ReplayMeta{Nodes: map[string]NodeInfo{}}}
	loc := map[string]string{}
	for _, s := range c.Sensors {
		k := key(s.Node, s.Metric)
		xs := c.Readings[k]
		if len(xs) == 0 {
			t.Fatalf("no readings for %s", k)
		}
		ser := map[int64]float64{}
		for i, v := range xs {
			ser[start.Unix()+int64(i*c.StepMin*60)] = v
		}
		if last := start.Unix() + int64((len(xs)-1)*c.StepMin*60); last != now.Unix() {
			t.Fatalf("%s: readings must end at now", k)
		}
		e.series[k] = ser
		e.states[k] = &SensorState{Node: s.Node, Metric: s.Metric, Role: s.Role, Location: s.Location, Unit: s.Unit,
			Last: fp(xs[len(xs)-1]), Status: "normal", DataOK: true}
		info := e.Meta.Nodes[s.Node]
		info.Role, info.Location, info.Building = s.Role, s.Location, s.Building
		info.Metrics = append(info.Metrics, s.Metric)
		e.Meta.Nodes[s.Node] = info
		loc[k] = s.Location
	}
	r := &Reasoner{eng: e}
	for _, x := range c.Incidents {
		inc := &Incident{ID: x.ID, State: x.State, CreatedSim: parityTime(t, x.At).Unix(), Severity: x.Severity, Title: x.Title,
			Injected: x.Injected, Approval: x.Approval}
		inc.Workflow, inc.Outcome = x.Workflow, x.Outcome
		if x.Label != "" {
			inc.Final = &ReportCall{Valid: true, Parsed: &Report{Label: x.Label, RootCause: x.Root}}
		}
		for _, s := range x.Sensors {
			inc.Sensors = append(inc.Sensors, SensorRef{Ref: s.Ref, Node: s.Node, Metric: s.Metric, Role: s.Role, Location: loc[key(s.Node, s.Metric)],
				Context: s.Context, Rule: Finding{Status: s.Status, Pattern: s.Pattern}})
			if s.FaultKind != "" {
				inc.Agents = append(inc.Agents, AgentCall{Ref: s.Ref, Valid: true, Parsed: &Finding{Status: s.Status, Pattern: s.Pattern, FaultKind: s.FaultKind}})
			}
		}
		r.incidents = append(r.incidents, inc)
	}
	return chatTools{r: r, now: now}
}

// parityDecimals: digits after the point as JSON writes the number.
func parityDecimals(x float64) int {
	s := strconv.FormatFloat(x, 'f', -1, 64)
	if i := strings.IndexByte(s, '.'); i >= 0 {
		return len(s) - i - 1
	}
	return 0
}

// parityDiff appends every difference between two decoded JSON values (go = device, py = training store).
func parityDiff(path string, g, p any, out *[]string, maxDiff *float64) {
	switch gv := g.(type) {
	case map[string]any:
		pv, ok := p.(map[string]any)
		if !ok {
			*out = append(*out, fmt.Sprintf("%s: go object, py %T", path, p))
			return
		}
		keys := map[string]bool{}
		for k := range gv {
			keys[k] = true
		}
		for k := range pv {
			keys[k] = true
		}
		ks := make([]string, 0, len(keys))
		for k := range keys {
			ks = append(ks, k)
		}
		sort.Strings(ks)
		for _, k := range ks {
			a, inG := gv[k]
			b, inP := pv[k]
			switch {
			case !inG:
				*out = append(*out, fmt.Sprintf("%s.%s: missing on go (py %v)", path, k, b))
			case !inP:
				*out = append(*out, fmt.Sprintf("%s.%s: missing on py (go %v)", path, k, a))
			default:
				parityDiff(path+"."+k, a, b, out, maxDiff)
			}
		}
	case []any:
		pv, ok := p.([]any)
		if !ok {
			*out = append(*out, fmt.Sprintf("%s: go array, py %T", path, p))
			return
		}
		if len(gv) != len(pv) {
			*out = append(*out, fmt.Sprintf("%s: go %d items, py %d", path, len(gv), len(pv)))
			return
		}
		for i := range gv {
			parityDiff(fmt.Sprintf("%s[%d]", path, i), gv[i], pv[i], out, maxDiff)
		}
	case float64:
		pv, ok := p.(float64)
		if !ok {
			*out = append(*out, fmt.Sprintf("%s: go number %v, py %T %v", path, gv, p, p))
			return
		}
		d := math.Abs(gv - pv)
		dec := max(parityDecimals(gv), parityDecimals(pv))
		tol := 0.0
		if dec > 0 {
			tol = 1.0001 * math.Pow(10, -float64(dec))
		}
		if d > tol+1e-12 {
			*out = append(*out, fmt.Sprintf("%s: go %v, py %v", path, gv, pv))
		}
		if d > *maxDiff {
			*maxDiff = d
		}
	default:
		if fmt.Sprintf("%T %v", g, g) != fmt.Sprintf("%T %v", p, p) {
			*out = append(*out, fmt.Sprintf("%s: go %T %v, py %T %v", path, g, g, p, p))
		}
	}
}

// The chat prompt after the system text must equal the HF Qwen3.5 chat template's rendering (expected strings below
// were rendered with ~/models/qwen3.5-4b's tokenizer.apply_chat_template, add_generation_prompt=True; "off" with
// enable_thinking=False as rsn_v1 was trained, "adaptive" with thinking on as rsn_v3): history answers carry no think
// block, the current question's rounds keep their reasoning.
func TestChatPromptMatchesHFTemplate(t *testing.T) {
	hist := []ChatMsg{{Role: "user", Text: "How are CO2 levels?"}, {Role: "assistant", Text: "CO2 is 820 ppm at SR-AQ-KH03-03."}}
	turn := func(think string) []v3Turn {
		return []v3Turn{{Calls: []V3Call{{Name: "rank_readings", Params: []V3Param{{"metric", "co2"}, {"time", `{"preset": "yesterday"}`}}}},
			Results: []string{`{"items": []}`}, Think: think}}
	}
	const calls = "<tool_call>\n<function=rank_readings>\n<parameter=metric>\nco2\n</parameter>\n<parameter=time>\n{\"preset\": \"yesterday\"}\n" +
		"</parameter>\n</function>\n</tool_call><|im_end|>\n<|im_start|>user\n<tool_response>\n{\"items\": []}\n</tool_response><|im_end|>\n<|im_start|>assistant\n"
	const head = "How are CO2 levels?<|im_end|>\n<|im_start|>assistant\nCO2 is 820 ppm at SR-AQ-KH03-03.<|im_end|>\n<|im_start|>user\nand yesterday?<|im_end|>\n<|im_start|>assistant\n"
	cases := []struct {
		name     string
		adaptive bool
		think    string
		want     string
	}{
		{"off", false, "", head + "<think>\n\n</think>\n\n" + calls + "<think>\n\n</think>\n\n"},
		{"adaptive", true, "Need yesterday's peak.", head + "<think>\nNeed yesterday's peak.\n</think>\n\n" + calls + "<think>\n"},
	}
	for _, c := range cases {
		if got := chatPromptMode("P", hist, "and yesterday?", turn(c.think), c.adaptive); got != "P"+c.want {
			t.Errorf("%s:\n got %q\nwant %q", c.name, got, "P"+c.want)
		}
	}
	if got := chatPromptMode("P", nil, "How are CO2 levels?", nil, true); got != "PHow are CO2 levels?<|im_end|>\n<|im_start|>assistant\n<think>\n" {
		t.Errorf("first, adaptive: %q", got)
	}
	if got := chatThinkOf("Need the peak.\n</think>\n\n<tool_call>"); got != "Need the peak." {
		t.Errorf("think: %q", got)
	}
	if got := chatClean("\n</think>\n\nCO2 is fine."); got != "CO2 is fine." {
		t.Errorf("clean: %q", got)
	}
}

func TestChatToolsParityWithTraining(t *testing.T) {
	b, err := os.ReadFile(filepath.Join(parityDir, "parity_cases.json"))
	if err != nil {
		t.Skip("parity fixture not here: ", err)
	}
	var c parityCase
	if err := json.Unmarshal(b, &c); err != nil {
		t.Fatal(err)
	}
	tools := parityTools(t, c)
	type row struct {
		Name   string         `json:"name"`
		Args   map[string]any `json:"args"`
		Result map[string]any `json:"result"`
	}
	var goRows []row
	for _, call := range c.Calls {
		args := map[string]any{}
		for k, v := range call.Args {
			args[k] = v
		}
		res, err := tools.run(call.Name, args)
		if err != nil {
			res = map[string]any{"error": err.Error()}
		}
		// through JSON, as the model sees it
		enc, _ := json.Marshal(res)
		var dec map[string]any
		json.Unmarshal(enc, &dec)
		goRows = append(goRows, row{call.Name, call.Args, dec})
	}
	if out, err := json.MarshalIndent(map[string]any{"cases": "parity_cases.json", "results": goRows}, "", " "); err == nil {
		os.WriteFile(filepath.Join(parityDir, "parity_out_go.json"), out, 0o644)
	}
	pb, err := os.ReadFile(filepath.Join(parityDir, "parity_out_py.json"))
	if err != nil {
		t.Skip("run pipeline/parity_py.py first: ", err)
	}
	var py struct {
		Results []row `json:"results"`
	}
	if err := json.Unmarshal(pb, &py); err != nil {
		t.Fatal(err)
	}
	if len(py.Results) != len(goRows) {
		t.Fatalf("py has %d results, go %d", len(py.Results), len(goRows))
	}
	maxDiff, bad := 0.0, 0
	for i, g := range goRows {
		p := py.Results[i]
		if p.Name != g.Name {
			t.Fatalf("call %d: py %s, go %s", i, p.Name, g.Name)
		}
		_, ge := g.Result["error"]
		_, pe := p.Result["error"]
		if ge || pe {
			if ge != pe {
				t.Errorf("call %d %s %v: error on one side only: go %v / py %v", i, g.Name, g.Args, g.Result["error"], p.Result["error"])
				bad++
			}
			continue
		}
		var diffs []string
		parityDiff(fmt.Sprintf("[%d]%s", i, g.Name), g.Result, p.Result, &diffs, &maxDiff)
		for _, d := range diffs {
			t.Error(d)
		}
		if len(diffs) > 0 {
			bad++
		}
	}
	t.Logf("parity: %d calls, %d with differences, largest numeric difference %.4g", len(goRows), bad, maxDiff)
}
