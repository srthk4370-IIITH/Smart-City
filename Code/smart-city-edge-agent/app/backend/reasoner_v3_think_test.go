package main

// r4 adaptive thinking for incident reports (proofs/2026-11-12_topup_r4/train/TOPUP.md): a short <think> block may come
// before the report JSON; it is stripped before parsing and kept as ReportCall.Think. Default (no reasoner_think) unchanged.

import (
	"context"
	"strings"
	"testing"
)

const v3Thought = "S1 CO2 and S2 occupancy rose together {same room}; ventilation, not a sensor fault."

func TestSplitReportThink(t *testing.T) {
	cases := []struct {
		in       string
		opened   bool
		th, rest string
	}{
		{v3Good, false, "", v3Good}, // default: unchanged
		{v3Good, true, v3Good, ""},  // opened block never closed: all reasoning
		{"<think>\n" + v3Thought + "\n</think>\n\n" + v3Good, false, v3Thought, v3Good}, // explicit leading block
		{"<think>\n\n</think>\n\n" + v3Good, false, "", v3Good},                         // empty block
		{v3Thought + "\n</think>\n\n" + v3Good, true, v3Thought, v3Good},                // prompt opened the block
		{"\n</think>\n\n" + v3Good, true, "", v3Good},                                   // empty, prompt opened it
		{`{"title": "a </think> b"}`, false, "", `{"title": "a </think> b"}`},           // tag inside the JSON, no block
	}
	for i, c := range cases {
		th, rest := splitReportThink(c.in, c.opened)
		if th != c.th || rest != c.rest {
			t.Errorf("case %d: got (%q, %.40q)", i, th, rest)
		}
	}
}

func TestCheckReportV3AcceptsLeadingThink(t *testing.T) {
	known := v3Prompt + "\nlimit 1500"
	r0, e0, _ := checkReportV3(v3Good, known)
	r1, e1, _ := checkReportV3("<think>\n"+v3Thought+"\n</think>\n\n"+v3Good, known)
	if r0 == nil || r1 == nil || len(e0) != 0 || len(e1) != 0 || r0.Title != r1.Title || r0.Label != r1.Label {
		t.Fatalf("think block changed the report: %v %v", e0, e1)
	}
	// the "{" inside the reasoning must not be taken as the report
	if _, e, _ := checkReportV3("<think>\n{not json}\n</think>\n"+v3Good, known); len(e) != 0 {
		t.Fatalf("brace in the think block: %v", e)
	}
}

func TestRunV3LoopDefaultPromptUnchanged(t *testing.T) {
	t.Setenv("SCE_REASONER_THINK", "")
	if reasonerPromptV3("U", nil) != v3StaticPrefix()+"U<|im_end|>\n"+v3AssistantOpen {
		t.Fatal("default prompt changed")
	}
	l := &fakeLLM{replies: []string{v3Good}}
	run, err := runV3Loop(context.Background(), l, &fakeTools{}, "U", 1, 100, nil)
	if err != nil || run.Text != v3Good || run.Think != "" || !strings.HasSuffix(l.prompts[0], v3AssistantOpen) {
		t.Fatalf("default loop: %+v %v", run, err)
	}
}

func TestRunV3LoopAdaptiveThink(t *testing.T) {
	t.Setenv("SCE_REASONER_THINK", "adaptive")
	// multi-domain: reasoning, then the JSON; the prompt opens the block
	l := &fakeLLM{replies: []string{v3Thought + "\n</think>\n\n" + v3Good}}
	run, err := runV3Loop(context.Background(), l, &fakeTools{}, "U", 1, 100, nil)
	if err != nil || run.Text != v3Good || run.Think != v3Thought || run.LLMCalls != 1 {
		t.Fatalf("adaptive direct: %+v %v", run, err)
	}
	if !strings.HasSuffix(l.prompts[0], "U<|im_end|>\n<|im_start|>assistant\n<think>\n") {
		t.Fatalf("adaptive prompt tail: %q", l.prompts[0][len(l.prompts[0])-60:])
	}
	// single-domain: the block is closed at once
	l = &fakeLLM{replies: []string{"\n</think>\n\n" + v3Good}}
	if run, _ = runV3Loop(context.Background(), l, &fakeTools{}, "U", 1, 100, nil); run.Text != v3Good || run.Think != "" {
		t.Fatalf("adaptive empty think: %+v", run)
	}
	// tool round: the round's reasoning is kept in the next prompt (HF template, current turn); the cap forces the answer
	// after closing the open block empty
	l = &fakeLLM{replies: []string{"need history\n</think>\n\n" + v3CallText, strings.TrimPrefix(v3Good, v3AnswerPrefix)}}
	ft := &fakeTools{}
	run, err = runV3Loop(context.Background(), l, ft, "U", 1, 100, nil)
	if err != nil || ft.n != 1 || !run.Forced || run.Text != v3Good {
		t.Fatalf("adaptive tool round: %+v %v", run, err)
	}
	p := l.prompts[1]
	if !strings.Contains(p, "<think>\nneed history\n</think>\n\n<tool_call>") || !strings.HasSuffix(p, "<|im_start|>assistant\n<think>\n"+v3ThinkClose+v3AnswerPrefix) {
		t.Fatalf("adaptive round-2 prompt: %q", p[len(p)-200:])
	}
	// reasoning that never closes (max_new): closed and the answer forced in a second completion
	l = &fakeLLM{replies: []string{"long reasoning", strings.TrimPrefix(v3Good, v3AnswerPrefix)}}
	run, _ = runV3Loop(context.Background(), l, &fakeTools{}, "U", 1, 100, nil)
	if run.Text != v3Good || run.Think != "long reasoning" || !run.Forced || run.LLMCalls != 2 ||
		!strings.HasSuffix(l.prompts[1], "<think>\nlong reasoning"+v3ThinkClose+v3AnswerPrefix) {
		t.Fatalf("unclosed think: %+v", run)
	}
}

func TestReasonerHtpdForceOffWithAdaptiveThink(t *testing.T) {
	t.Setenv("SCE_REASONER_ENGINE", "htpd")
	t.Setenv("SCE_REASONER_FORCE", "1")
	t.Setenv("SCE_REASONER_THINK", "")
	if l, ok := reasonerLLM().(htpdReasonLLM); !ok || !l.Force {
		t.Fatal("default: htpd forced schema should stay on")
	}
	t.Setenv("SCE_REASONER_THINK", "adaptive")
	if l, ok := reasonerLLM().(htpdReasonLLM); !ok || l.Force {
		t.Fatal("adaptive think: forced schema must be off (it would forbid the think block)")
	}
}
