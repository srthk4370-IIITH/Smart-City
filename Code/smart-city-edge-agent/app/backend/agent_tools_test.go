package main

// Tool-call protocol tests (agent_tools.go). testdata/agent_tools_fixtures.json is generated from the Python reference
// (proofs/2026-11-17_agt_topup_v2/gen_tools.py render_* / short_card_prompt / turn_prompt + evidence.agent_user), so every
// assertion on bytes is a byte-parity check against the training rows.

import (
	"context"
	"encoding/json"
	"os"
	"path/filepath"
	"strings"
	"sync"
	"testing"
)

type toolFx struct {
	Name        string          `json:"name"`
	Card        json.RawMessage `json:"card"`
	Place       *string         `json:"place"`
	Node        string          `json:"node"`
	Location    string          `json:"location"`
	Hist        []float64       `json:"hist"`
	End         int64           `json:"end"`
	N           int             `json:"n"`
	MissingBack []int           `json:"missing_back"`
	P1          string          `json:"p1"`
	Steps       []struct {
		Call   string `json:"call"`
		Result string `json:"result"`
	} `json:"steps"`
	FinalPrompt string `json:"final_prompt"`
}

func (f toolFx) card(t *testing.T) (Card, string) {
	var c Card
	if err := json.Unmarshal(f.Card, &c); err != nil {
		t.Fatal(err)
	}
	if f.Place != nil {
		return c, *f.Place
	}
	return c, ""
}

func (f toolFx) mask() []bool {
	if len(f.MissingBack) == 0 {
		return nil
	}
	m := make([]bool, len(f.Hist))
	for _, i := range f.MissingBack {
		m[len(m)-1-i] = true
	}
	return m
}

func loadToolFx(t *testing.T) map[string]toolFx {
	raw, err := os.ReadFile("testdata/agent_tools_fixtures.json")
	if err != nil {
		t.Fatal(err)
	}
	var all []toolFx
	if err := json.Unmarshal(raw, &all); err != nil {
		t.Fatal(err)
	}
	out := map[string]toolFx{}
	for _, f := range all {
		out[f.Name] = f
	}
	return out
}

// toolRig: agt_v3 + agent_tools=1 profile, a mock NPU that records the prompts and answers from a script.
type toolRig struct {
	t       *testing.T
	r       *Reasoner
	inc     *Incident
	mu      sync.Mutex
	prompts []string
	script  []string
}

func newToolRig(t *testing.T, fx toolFx, ctx int, profile string) *toolRig {
	oldVer, oldDir, oldCard, oldGen := agentVer, htpdWorkDir, toolSensorCard, mockGen
	dir := t.TempDir()
	htpdWorkDir, agentVer = dir, "v2"
	os.WriteFile(filepath.Join(dir, "htpd_profile"), []byte(profile), 0o644)
	c, place := fx.card(t)
	toolSensorCard = func(role, metric, node, loc string) (Card, string, bool) { return c, place, true }
	rg := &toolRig{t: t, inc: &Incident{ID: "T1"}}
	g := NewGenieRunner(dir, dir, true)
	rg.r = NewReasoner(g, nil, dir, func(string, any) {})
	mockGen = func(prompt string) (string, error) {
		rg.mu.Lock()
		defer rg.mu.Unlock()
		rg.prompts = append(rg.prompts, prompt)
		k := len(rg.prompts) - 1
		if k >= len(rg.script) {
			t.Errorf("unexpected generation %d", k+1)
			return `{"pattern": "stable"}`, nil
		}
		return rg.script[k], nil
	}
	t.Cleanup(func() { agentVer, htpdWorkDir, toolSensorCard, mockGen = oldVer, oldDir, oldCard, oldGen })
	return rg
}

const toolAnswer = `{"pattern": "gradual_increase", "status": "warning", "observations": ["rose [E1,H2]"], "likely_cause": "x", "confidence": 0.8}`

func (rg *toolRig) run(fx toolFx, ai string, fresh, allow bool) (GenieResult, string) {
	s := SensorRef{Ref: "S1", Role: "power", Metric: "m", Node: fx.Node, Location: fx.Location, End: fx.End, Hist: fx.Hist}
	return rg.r.runAgentTools(context.Background(), rg.inc, s, ModelBundle{Name: "m", Dir: "d"}, AgentInput{Prompt: ai}, fresh, allow)
}

func (rg *toolRig) timeline() string {
	var b []string
	for _, e := range rg.inc.Timeline {
		b = append(b, e.Msg)
	}
	return strings.Join(b, "\n")
}

const toolProfile = "agents=agt_v3\nagent_tools=1\nagent_ctx=4000\n"

// the renderers and the prompt builder with GAPS, byte for byte against the Python reference
func TestAgentToolsParity(t *testing.T) {
	fxs := loadToolFx(t)
	if len(fxs) < 7 {
		t.Fatalf("%d fixtures", len(fxs))
	}
	for name, fx := range fxs {
		c, place := fx.card(t)
		built := BuildAgentPromptV3Gaps(c, fx.Node, fx.Location, place, fx.Hist, fx.N, fx.End, nil, fx.mask()).Prompt
		for _, st := range fx.Steps {
			if st.Call == `{"tool": "get_card", "args": {}}` { // the first prompt carries the withheld-card marker
				built = shortCardPrompt(built, c, place)
			}
		}
		if built != fx.P1 {
			firstDiff(t, name+" first prompt", built, fx.P1)
		}
		for _, st := range fx.Steps {
			tc, isCall, ok := parseAgentToolCall(st.Call)
			if !isCall || !ok || tc.canonical() != st.Call {
				t.Fatalf("%s: call %q parsed as %+v %v %v canonical %q", name, st.Call, tc, isCall, ok, tc.canonical())
			}
			var got string
			switch tc.Tool {
			case "get_history":
				got, _ = renderToolHistory(c, fx.Hist, tc.Hours, fx.End, fx.mask())
			case "get_card":
				got = RenderCardFull(c, place)
			case "get_neighbors":
				var rows []toolNbr
				for _, l := range strings.Split(st.Result, "\n") {
					if l == "no related sensors" {
						continue
					}
					p := strings.Split(l, " | ")
					rows = append(rows, toolNbr{strings.SplitN(p[0], " ", 2)[1], p[1], p[2], p[3], strings.TrimPrefix(p[4], "last ")})
				}
				got = renderToolNeighbors(rows)
			}
			if got != st.Result {
				firstDiff(t, name+" "+st.Call, got, st.Result)
			}
		}
	}
	if g, _ := renderToolHistory(Card{Kind: "continuous"}, make([]float64, 10), 6, 0, nil); g != "" {
		t.Error("short history must not render")
	}
}

func TestAgentToolsGapsOnlyWithMask(t *testing.T) {
	fx := loadToolFx(t)["hist12_gaps"]
	c, place := fx.card(t)
	with := BuildAgentPromptV3Gaps(c, fx.Node, fx.Location, place, fx.Hist, fx.N, fx.End, nil, fx.mask()).Prompt
	without := BuildAgentPromptV3(c, fx.Node, fx.Location, place, fx.Hist, fx.N, fx.End, nil).Prompt
	if !strings.Contains(with, "\nGAPS: ") || strings.Contains(without, "GAPS") {
		t.Fatal("GAPS line only with a mask")
	}
	if strings.Replace(with, gapsLine(fx.mask()[len(fx.Hist)-fx.N:], fx.N)+"\n", "", 1) != without {
		t.Fatal("the GAPS line is the only difference")
	}
}

func TestAgentToolsProfileOff(t *testing.T) {
	old, oldDir := agentVer, htpdWorkDir
	defer func() { agentVer, htpdWorkDir = old, oldDir }()
	htpdWorkDir = t.TempDir()
	agentVer = "v2"
	if agentTools() {
		t.Fatal("default must be off")
	}
	os.WriteFile(filepath.Join(htpdWorkDir, "htpd_profile"), []byte("agents=agt_v3\n"), 0o644)
	if agentTools() {
		t.Fatal("agt_v3 alone must not enable the tools")
	}
	os.WriteFile(filepath.Join(htpdWorkDir, "htpd_profile"), []byte("agent_tools=1\n"), 0o644)
	if agentTools() {
		t.Fatal("tools need agt_v3")
	}
	os.WriteFile(filepath.Join(htpdWorkDir, "htpd_profile"), []byte("agents=agt_v3\nagent_tools=1\n"), 0o644)
	if !agentTools() {
		t.Fatal("agent_tools=1 with agt_v3 must enable")
	}
}

func TestAgentToolsCallThenFinal(t *testing.T) {
	fx := loadToolFx(t)["hist12"]
	rg := newToolRig(t, fx, 4000, toolProfile)
	rg.script = []string{fx.Steps[0].Call, toolAnswer}
	res, p := rg.run(fx, fx.P1, false, true)
	if len(rg.prompts) != 2 || rg.prompts[0] != fx.P1+`{"` || rg.prompts[1] != fx.FinalPrompt+`{"` {
		t.Fatalf("prompts: %d", len(rg.prompts))
	}
	if !strings.HasPrefix(res.Text, `{"pattern": "gradual_increase"`) || p != fx.FinalPrompt+`{"` {
		t.Fatalf("text %q prompt tail %q", res.Text, p[len(p)-30:])
	}
	if !strings.Contains(rg.timeline(), "agent called get_history(12 h)") || rg.inc.NPUCalls != 1 {
		t.Fatalf("timeline %q npu %d", rg.timeline(), rg.inc.NPUCalls)
	}
	if ids := toolPromptIDs(p); !ids["H2"] || !ids["H8"] || ids["N1"] {
		t.Fatalf("ids %v", ids)
	}
}

func TestAgentToolsDirectAnswer(t *testing.T) {
	fx := loadToolFx(t)["hist12"]
	rg := newToolRig(t, fx, 4000, toolProfile)
	rg.script = []string{toolAnswer}
	res, _ := rg.run(fx, fx.P1, false, true)
	if len(rg.prompts) != 1 || !strings.HasPrefix(res.Text, `{"pattern": "gradual_increase"`) || rg.inc.NPUCalls != 0 {
		t.Fatalf("%d prompts, %q", len(rg.prompts), res.Text)
	}
}

func TestAgentToolsChainOfTwoForcesAnswer(t *testing.T) {
	fx := loadToolFx(t)["card_only"] // p1 with the withheld card; the history of the same sensor is 144 long
	rg := newToolRig(t, fx, 4000, toolProfile)
	c, place := fx.card(t)
	call1, call2 := fx.Steps[0].Call, `{"tool": "get_history", "args": {"hours": 6}}`
	h6, _ := renderToolHistory(c, fx.Hist, 6, fx.End, nil)
	p2 := fx.FinalPrompt
	p3 := p2 + call2 + toolEOT + toolIPY + h6 + toolEOT + toolAssist
	rg.script = []string{call1, call2, toolAnswer}
	res, p := rg.run(fx, fx.P1, false, true)
	if len(rg.prompts) != 3 {
		t.Fatalf("%d generations", len(rg.prompts))
	}
	if rg.prompts[1] != p2+`{"` || rg.prompts[2] != p3+AgentPrefill || p != p3+AgentPrefill {
		t.Fatal("chain prompts differ (the third generation must be forced to the answer prefill)")
	}
	if fx.Steps[0].Result != RenderCardFull(c, place) || !strings.HasPrefix(res.Text, `{"pattern": "gradual_increase"`) || rg.inc.NPUCalls != 2 {
		t.Fatalf("npu %d", rg.inc.NPUCalls)
	}
	tl := rg.timeline()
	if !strings.Contains(tl, "agent called get_card()") || !strings.Contains(tl, "agent called get_history(6 h)") {
		t.Fatal(tl)
	}
}

func TestAgentToolsOverflowForcesFinal(t *testing.T) {
	fx := loadToolFx(t)["hist12"]
	// ctx where the first prompt fits but the prompt with the result does not
	next := fx.FinalPrompt + AgentPrefill
	ctx := estTokens(next) + 376 - 1
	if estTokens(fx.P1+AgentPrefill)+376 > ctx {
		t.Skip("fixture sizes leave no room")
	}
	rg := newToolRig(t, fx, ctx, "agents=agt_v3\nagent_tools=1\nagent_ctx="+itoa(ctx)+"\n")
	rg.script = []string{fx.Steps[0].Call, toolAnswer}
	res, p := rg.run(fx, fx.P1, false, true)
	if len(rg.prompts) != 2 || rg.prompts[1] != fx.P1+AgentPrefill || p != fx.P1+AgentPrefill {
		t.Fatalf("the answer must be forced on the first prompt: %d prompts", len(rg.prompts))
	}
	if !strings.Contains(rg.timeline(), "would not fit") || !strings.HasPrefix(res.Text, `{"pattern": "`) {
		t.Fatal(rg.timeline())
	}
}

func TestAgentToolsBadCallsAndNoCalls(t *testing.T) {
	fx := loadToolFx(t)["hist12"]
	for _, bad := range []string{`{"tool": "nope", "args": {}}`, `{"tool": "get_history", "args": {"hours": 7}}`, `{"tool": "get_card", "args": {"x": 1}}`, `{"tool": "get_hist`} {
		rg := newToolRig(t, fx, 4000, toolProfile)
		rg.script = []string{bad, toolAnswer}
		res, _ := rg.run(fx, fx.P1, false, true)
		if len(rg.prompts) != 2 || rg.prompts[1] != fx.P1+AgentPrefill || !strings.HasPrefix(res.Text, `{"pattern": "`) {
			t.Fatalf("%q: %d prompts", bad, len(rg.prompts))
		}
	}
	rg := newToolRig(t, fx, 4000, toolProfile) // allowCalls=false (more-data rounds): old path
	rg.script = []string{toolAnswer}
	rg.run(fx, fx.P1, false, false)
	if len(rg.prompts) != 1 || rg.prompts[0] != fx.P1+AgentPrefill {
		t.Fatal("no calls: the old prefill")
	}
	rg = newToolRig(t, fx, 4000, toolProfile) // a repeated call is not executed twice
	rg.script = []string{fx.Steps[0].Call, fx.Steps[0].Call, toolAnswer}
	rg.run(fx, fx.P1, false, true)
	if len(rg.prompts) != 3 || rg.prompts[2] != fx.FinalPrompt+AgentPrefill {
		t.Fatalf("repeat: %d prompts", len(rg.prompts))
	}
}

func TestAgentToolsShortCardWhenTight(t *testing.T) {
	fx := loadToolFx(t)["card_only"]
	c, place := fx.card(t)
	full := strings.Replace(fx.P1, strings.SplitN(RenderCardFull(c, place), "\n", 2)[0]+"\n"+cardWithheldMarker, RenderCardFull(c, place), 1)
	if full == fx.P1 {
		t.Fatal("fixture has no marker")
	}
	ctx := estTokens(fx.P1+AgentPrefill) + 376
	if estTokens(full+AgentPrefill)+376 <= ctx {
		t.Skip("short card saves no tokens here")
	}
	rg := newToolRig(t, fx, ctx, "agents=agt_v3\nagent_tools=1\nagent_ctx="+itoa(ctx)+"\n")
	rg.script = []string{toolAnswer}
	rg.run(fx, full, false, true)
	if len(rg.prompts) != 1 || rg.prompts[0] != fx.P1+`{"` {
		t.Fatal("a prompt that does not fit goes out with the card cut to the marker")
	}
}

func TestToolTurnSink(t *testing.T) {
	for _, tc := range []struct {
		in   []string
		want string
	}{
		{[]string{`tool": "get_card", "args": {}}`}, ""},
		{[]string{"to", `ol": "x"`}, ""},
		{[]string{`pattern": "gradual`, `_increase", `}, `gradual_increase", `},
		{[]string{"pat", `tern": "st`, "able"}, "stable"},
		{[]string{`zzz`, ` more`}, "zzz more"},
	} {
		var got string
		s := toolTurnSink(func(x string) { got += x })
		for _, c := range tc.in {
			s(c)
		}
		if got != tc.want {
			t.Errorf("%q -> %q, want %q", tc.in, got, tc.want)
		}
	}
}

func TestToolIDsAccepted(t *testing.T) {
	fx := loadToolFx(t)["hist12_gaps"]
	p := fx.FinalPrompt + AgentPrefill
	ids := toolPromptIDs(p)
	for _, id := range []string{"GAPS", "H2", "H3", "H4", "H8"} {
		if !ids[id] {
			t.Errorf("%s missing from %v", id, ids)
		}
	}
	old := agentVer
	agentVer = "v2"
	defer func() { agentVer = old }()
	js := `{"pattern": "stable", "status": "normal", "observations": ["max over 12 h [H2,H8]", "gap [GAPS]"], "likely_cause": "x", "confidence": 0.7, "action": "monitor"}`
	call := checkAgentWin(SensorRef{Role: "power", Metric: "m"}, GenieResult{Text: js}, p, nil)
	for _, e := range call.Errors {
		if strings.Contains(e, "hallucinated") || strings.Contains(e, "without evidence") {
			t.Errorf("tool ids must be accepted: %v", call.Errors)
		}
	}
}

func itoa(n int) string { b, _ := json.Marshal(n); return string(b) }
