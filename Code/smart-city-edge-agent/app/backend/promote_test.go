package main

import (
	"context"
	"strings"
	"sync"
	"testing"
)

// Promotion of context sensors, cohesive coverage and agentic data requests (promote.go, coverage.go, agent_more.go),
// on the refine rig: real engine and pipeline, scripted agents.

func ctxCandidate(t *testing.T, rg *refineRig, inc Incident, which int) (Candidate, int) {
	t.Helper()
	n := 0
	for i, s := range inc.Sensors {
		if !s.Context {
			continue
		}
		if n == which {
			xs, ok := rg.eng.WindowAt(s.Node, s.Metric, s.End)
			if !ok {
				t.Fatalf("no window for %s %s", s.Node, s.Metric)
			}
			f := RuleFinding(s.Role, s.Metric, s.Node, xs, s.End)
			f.Status, f.Pattern = "warning", "step_increase"
			return Candidate{s.Node, s.Metric, s.Role, f, xs, s.End, false, false, false}, i
		}
		n++
	}
	t.Fatalf("incident has %d context sensor(s), wanted #%d", n, which)
	return Candidate{}, 0
}

// (a) a context sensor turns warning inside an open incident: promoted, agent called, revision added, no second incident.
// Debounce: a second sensor within 2 readings waits and is batched into the next re-run.
func TestPromoteContextSensorInOpenIncident(t *testing.T) {
	rg := newRefineRig(t)
	var mu sync.Mutex
	asked := map[string]int{}
	inner := mockGen
	mockGen = func(prompt string) (string, error) {
		mu.Lock()
		for _, l := range strings.Split(prompt, "\n") {
			if strings.HasPrefix(l, "METRIC: ") {
				asked[strings.Fields(l)[1]]++
			}
		}
		mu.Unlock()
		return inner(prompt)
	}
	inc := rg.alert()
	first := rg.settle(inc.ID)
	c, idx := ctxCandidate(t, rg, first, 0)
	revs := len(first.Revisions)
	mu.Lock()
	before := asked[c.Metric]
	mu.Unlock()

	rg.r.HandleCandidates([]Candidate{c})
	got := rg.settle(inc.ID)

	if len(rg.r.incidents) != 1 {
		t.Fatalf("promotion opened a second incident: %d incidents", len(rg.r.incidents))
	}
	if got.Sensors[idx].Context {
		t.Fatal("sensor still context")
	}
	mu.Lock()
	after := asked[c.Metric]
	mu.Unlock()
	if after <= before {
		t.Fatalf("no domain agent call for %s (%d -> %d)", c.Metric, before, after)
	}
	var agent *AgentCall
	for i := range got.Agents {
		if got.Agents[i].Ref == got.Sensors[idx].Ref {
			agent = &got.Agents[i]
		}
	}
	if agent == nil || strings.Contains(agent.Model, "context agent") {
		t.Fatalf("no NPU agent finding for the promoted sensor: %+v", agent)
	}
	if len(got.Revisions) != revs+1 || got.Revisions[len(got.Revisions)-1].Stage != "promotion" {
		t.Fatalf("revisions %d -> %d, last %+v", revs, len(got.Revisions), got.Revisions[len(got.Revisions)-1])
	}
	found := false
	for _, tl := range got.Timeline {
		found = found || strings.Contains(tl.Msg, "promoted to domain agent, report updated")
	}
	if !found {
		t.Fatalf("no promotion timeline entry: %+v", got.Timeline)
	}
	if got.Final == nil || got.Final.Parsed == nil {
		t.Fatal("no report after the promotion")
	}

	// debounce: the next sensor within 2 readings is held, then re-run together once 2 readings have passed
	if c2, _ := ctxCandidate(t, rg, got, 0); c2.Metric != "" {
		rg.r.HandleCandidates([]Candidate{c2})
		rg.r.mu.RLock()
		held := len(rg.r.promos) == 1 && !rg.r.active
		rg.r.mu.RUnlock()
		if !held && len(rg.r.incidents) == 1 && len(rg.r.promos) == 0 {
			t.Skip("no second context sensor to debounce")
		}
		if len(rg.r.incidents) != 1 || len(rg.r.promos) != 1 {
			t.Fatalf("debounce: %d incidents, %d held promotions", len(rg.r.incidents), len(rg.r.promos))
		}
		rg.r.releasePromos(c2.End + promoDebounce*bucketSec)
		got = rg.settle(inc.ID)
		if len(got.Revisions) != revs+2 {
			t.Fatalf("debounced re-run: revisions %d, want %d", len(got.Revisions), revs+2)
		}
	}
}

// (c) the incident is closed: the sensor opens a new incident through the normal gate.
func TestPromoteClosedIncidentOpensNewOne(t *testing.T) {
	rg := newRefineRig(t)
	inc := rg.alert()
	first := rg.settle(inc.ID)
	c, _ := ctxCandidate(t, rg, first, 0)
	rg.r.mu.Lock()
	rg.r.incidents[0].Workflow = wfClosed
	rg.r.mu.Unlock()
	rg.r.HandleCandidates([]Candidate{c})
	rg.settle(inc.ID)
	if len(rg.r.incidents) != 2 {
		t.Fatalf("closed incident: %d incidents, want a new one", len(rg.r.incidents))
	}
	if len(rg.r.incidents[0].Revisions) != len(first.Revisions) {
		t.Fatal("the closed incident was changed")
	}
}

// (b) the report leaves an alerting sensor out: one retry with the instruction, then covered.
type covLLM struct {
	mu      sync.Mutex
	prompts []string
	reply   func(p string) string
}

func (f *covLLM) Name() string { return "fake" }
func (f *covLLM) Complete(_ context.Context, p string, _ int, on func(string)) (string, CallMetrics, error) {
	f.mu.Lock()
	f.prompts = append(f.prompts, p)
	f.mu.Unlock()
	r := f.reply(p)
	if on != nil {
		on(r)
	}
	return r, CallMetrics{GenTokens: 10}, nil
}

func covReport(refs ...string) string {
	obs := ""
	for i, r := range refs {
		if i > 0 {
			obs += ", "
		}
		obs += `{"text": "` + r + ` is abnormal", "src": ["` + r + `.E1"]}`
	}
	ev := `"` + strings.Join(refs, `.E1", "`) + `.E1"`
	return `{"title": "Two sensors alarming", "severity": "warning", "label": "unknown", "root_cause": "Both sensors left their usual range.", "causal_chain": "` +
		strings.Join(refs, " and ") + `", "observations": [` + obs + `], "agent_checks": [], "affected_domains": ["air_quality"], "suspect_sensors": [], "evidence": [` + ev +
		`], "confidence": 0.8, "checklist": [{"action": "inspect_ventilation", "target": "` + refs[0] + `", "why": "Check the room"}, {"action": "monitor", "target": "` + refs[0] + `", "why": "Watch the trend"}], "monitor_next": "next re-check", "needs_more_data": false, "needs_deeper": false, "explanation": "Both are abnormal."}`
}

func TestReasonerCoverageRetry(t *testing.T) {
	t.Setenv("SCE_REASONER", "v3")
	t.Setenv("SCE_COVERAGE_RETRY", "1") // the old retry path (default since 2026-11-27: add lines, no retry)
	rg := newRefineRig(t)
	// two flagged sensors: CO2 and the first context candidate's sensor
	inc0 := rg.alert()
	first := rg.settle(inc0.ID)
	c, _ := ctxCandidate(t, rg, first, 0)
	co2 := first.Sensors[0]
	xs, _ := rg.eng.WindowAt(co2.Node, co2.Metric, co2.End)
	cc := Candidate{co2.Node, co2.Metric, co2.Role, RuleFinding(co2.Role, co2.Metric, co2.Node, xs, co2.End), xs, co2.End, false, false, false}
	cc.Finding.Status = "warning"
	llm := &covLLM{}
	llm.reply = func(p string) string {
		if strings.Contains(p, "Your report must also cover: S2") {
			return covReport("S1", "S2")
		}
		return covReport("S1")
	}
	old := reasonerLLMHook
	reasonerLLMHook = llm
	t.Cleanup(func() { reasonerLLMHook = old })

	inc := rg.r.Process([]Candidate{cc, c}, 3)
	if inc.Sensors[1].Context {
		t.Fatalf("second sensor should be flagged: %+v", inc.Sensors[1])
	}
	if inc.Final == nil || inc.Final.Parsed == nil {
		t.Fatal("no final report")
	}
	llm.mu.Lock()
	n := len(llm.prompts)
	retry := n > 1 && strings.Contains(llm.prompts[n-1], "Your report must also cover: S2 "+c.Metric)
	llm.mu.Unlock()
	if !retry {
		t.Fatalf("no retry with the coverage instruction (%d reasoner call(s)); timeline: %+v", n, inc.Timeline)
	}
	if miss := coverageMissing(inc, nil, inc.Final.Parsed); len(miss) != 0 {
		t.Fatalf("report still misses %+v", miss)
	}
	ok := false
	for _, tl := range inc.Timeline {
		ok = ok || strings.Contains(tl.Msg, "Coverage check: the retry covers")
	}
	if !ok {
		t.Fatalf("no coverage timeline entry: %+v", inc.Timeline)
	}

	// still missing after the retry: the deterministic report with a line for the sensor
	llm.reply = func(p string) string { return covReport("S1") }
	inc2 := rg.r.Process([]Candidate{cc, c}, 3)
	if miss := coverageMissing(inc2, nil, inc2.Final.Parsed); len(miss) != 0 {
		t.Fatalf("fallback report still misses %+v", miss)
	}
	if !strings.Contains(inc2.Final.Parsed.Source, "missed alerting sensors") {
		t.Fatalf("source %q", inc2.Final.Parsed.Source)
	}
}

// default since the 2026-11-27 sweep: a report that misses an alerting sensor is KEPT (no second NPU call) and gets a
// line per missing sensor; the source stays the AI's.
func TestReasonerCoverageAddsLines(t *testing.T) {
	t.Setenv("SCE_REASONER", "v3")
	rg := newRefineRig(t)
	inc0 := rg.alert()
	first := rg.settle(inc0.ID)
	c, _ := ctxCandidate(t, rg, first, 0)
	co2 := first.Sensors[0]
	xs, _ := rg.eng.WindowAt(co2.Node, co2.Metric, co2.End)
	cc := Candidate{co2.Node, co2.Metric, co2.Role, RuleFinding(co2.Role, co2.Metric, co2.Node, xs, co2.End), xs, co2.End, false, false, false}
	cc.Finding.Status = "warning"
	llm := &covLLM{}
	llm.reply = func(p string) string { return covReport("S1") }
	old := reasonerLLMHook
	reasonerLLMHook = llm
	t.Cleanup(func() { reasonerLLMHook = old })
	inc := rg.r.Process([]Candidate{cc, c}, 3)
	llm.mu.Lock()
	n := len(llm.prompts)
	llm.mu.Unlock()
	if n != 1 {
		t.Fatalf("want one reasoner call, got %d", n)
	}
	if inc.Final == nil || inc.Final.Parsed == nil || strings.Contains(inc.Final.Parsed.Source, "missed alerting sensors") {
		t.Fatalf("AI report not kept: %+v", inc.Final)
	}
	if miss := coverageMissing(inc, nil, inc.Final.Parsed); len(miss) != 0 {
		t.Fatalf("report still misses %+v", miss)
	}
}

// (d) an unsure agent answer is re-asked with the longer window; the confident answer is kept.
func TestAgentAsksForMoreData(t *testing.T) {
	withAgentVersion(t, "v2")
	oldRecal := ConfidenceRecalV2
	ConfidenceRecalV2 = nil
	t.Cleanup(func() { ConfidenceRecalV2 = oldRecal })
	rg := newRefineRig(t)
	var mu sync.Mutex
	var lens []string
	inner := mockGen
	mockGen = func(prompt string) (string, error) {
		if !strings.Contains(prompt, "METRIC: co2") {
			return inner(prompt)
		}
		n := "48"
		if strings.Contains(prompt, ", 144 x 5 min") {
			n = "144"
		}
		mu.Lock()
		lens = append(lens, n)
		mu.Unlock()
		conf := "0.4"
		dq := `, "data_quality": {"verdict": "suspect"}`
		if n == "144" {
			conf, dq = "0.9", ""
		}
		return `{"pattern": "step_increase", "status": "warning", "observations": ["CO2 now [E1]"], "likely_cause": "ventilation_insufficient", "confidence": ` + conf + dq + `, "action": "inspect_ventilation"}`, nil
	}
	inc := rg.alert()
	got := rg.settle(inc.ID)
	mu.Lock()
	defer mu.Unlock()
	if len(lens) != 2 || lens[0] != "48" || lens[1] != "144" {
		t.Fatalf("window lengths %v, want [48 144]", lens)
	}
	var co2 *AgentCall
	for i := range got.Agents {
		if got.Agents[i].Ref == "S1" {
			co2 = &got.Agents[i]
		}
	}
	if co2 == nil || co2.Parsed == nil || co2.Parsed.Confidence != 0.9 || !strings.Contains(co2.Prompt, ", 144 x 5 min") {
		t.Fatalf("confident answer not kept: %+v", co2)
	}
	if got.Sensors[0].WinN != 144 {
		t.Fatalf("sensor window %d, want 144", got.Sensors[0].WinN)
	}
	ok := false
	for _, tl := range got.Timeline {
		ok = ok || strings.Contains(tl.Msg, "asked for more data (data quality suspect): re-run with 12 h window")
	}
	if !ok {
		t.Fatalf("no more-data timeline entry: %+v", got.Timeline)
	}
}
