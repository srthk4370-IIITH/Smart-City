package main

import (
	"bufio"
	"encoding/json"
	"os"
	"testing"
)

// Prompts built on device must be byte-identical to the training prompts (training/features.py).
func TestPromptParity(t *testing.T) {
	f, err := os.Open("testdata_parity.jsonl")
	if err != nil {
		t.Skip("no fixtures")
	}
	defer f.Close()
	sc := bufio.NewScanner(f)
	sc.Buffer(make([]byte, 1<<20), 1<<22)
	n, bad, badRule := 0, 0, 0
	for sc.Scan() {
		var fx struct {
			Role, Node, Location, Metric, Prompt, Rule string
			Xs                                         []float64
			End                                        int64
		}
		if err := json.Unmarshal(sc.Bytes(), &fx); err != nil {
			t.Fatal(err)
		}
		n++
		got := BuildAgentPrompt(fx.Role, fx.Node, fx.Location, fx.Metric, fx.Xs, fx.End).Prompt
		if got != fx.Prompt {
			bad++
			if bad <= 3 {
				for i := 0; i < len(got) && i < len(fx.Prompt); i++ {
					if got[i] != fx.Prompt[i] {
						lo := i - 80
						if lo < 0 {
							lo = 0
						}
						t.Errorf("prompt mismatch %s/%s at %d:\n go: %q\n py: %q", fx.Node, fx.Metric, i, got[lo:min(len(got), i+60)], fx.Prompt[lo:min(len(fx.Prompt), i+60)])
						break
					}
				}
			}
		}
		if r := RulePattern(fx.Role, fx.Metric, fx.Xs, fx.End); r != fx.Rule {
			badRule++
			if badRule <= 3 {
				t.Errorf("rule mismatch %s/%s: go %s py %s", fx.Node, fx.Metric, r, fx.Rule)
			}
		}
	}
	t.Logf("%d fixtures: %d prompt mismatches, %d rule mismatches", n, bad, badRule)
	if bad > 0 || badRule > 0 {
		t.Fail()
	}
}
