package main

import (
	"context"
	"os"
	"testing"
	"time"
)

// Host smoke test of the chat prompt + tools against a llama-server running the reasoner GGUF:
//
//	SCE_CHAT_URL=http://127.0.0.1:18096 go test -run TestChatHost -v
func TestChatHost(t *testing.T) {
	u := os.Getenv("SCE_CHAT_URL")
	if u == "" {
		t.Skip("SCE_CHAT_URL not set")
	}
	chatLLM = func(string) v3LLM { return &llamaServerLLM{URL: u, Model: "rsn"} }
	r := &Reasoner{}
	base := time.Date(2026, 10, 29, 9, 0, 0, 0, IST)
	mk := func(id, title, sev, role, metric, node string, h int, status string) *Incident {
		inc := &Incident{ID: id, State: "done", CreatedSim: base.Add(-time.Duration(h) * time.Hour).Unix(), Severity: sev, Title: title,
			Sensors: []SensorRef{{Ref: "S1", Node: node, Metric: metric, Role: role, Rule: Finding{Pattern: "step_increase", Status: status}}},
			Final:   &ReportCall{Valid: true, Parsed: &Report{Severity: sev, Label: "ventilation_issue", RootCause: "AC stopped while the room was occupied"}}}
		inc.Workflow = wfNeeds
		return inc
	}
	r.incidents = []*Incident{
		mk("INC-0441", "KH building, level 03: Suspect CO2 readings", "sensor_fault", "air_quality", "co2", "SR-AQ-KH03-03", 30, "sensor_fault"),
		mk("INC-0442", "CO2 rising after AC stop (PB building, level 00)", "warning", "air_quality", "co2", "SR-AQ-PB00-04", 5, "warning"),
		mk("INC-0445", "Tank level falling with no visible use", "warning", "water", "level", "WM-WL-TH98-00", 2, "warning"),
	}
	cs := &chatStore{path: t.TempDir() + "/chats.json", S: map[string]*ChatSession{}}
	id := ""
	for _, q := range []string{"How many incidents were there today?", "Which CO2 incidents happened this week?",
		"Tell me more about INC-0441.", "Please close INC-0442 for me.", "What is the capital of France?"} {
		s, err := cs.Ask(context.Background(), r, id, q)
		if err != nil {
			t.Fatal(err)
		}
		id = s.ID
		m := s.Msgs[len(s.Msgs)-1]
		t.Logf("Q: %s\n   tools: %d %v\n   A (%d ms): %s", q, len(m.Tools), m.Tools, m.Ms, m.Text)
	}
}
