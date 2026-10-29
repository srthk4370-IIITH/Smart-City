package main

import (
	"context"
	"testing"
	"time"
)

type fakeChatLLM struct{}

func (fakeChatLLM) Name() string { return "fake" }
func (fakeChatLLM) Complete(context.Context, string, int, func(string)) (string, CallMetrics, error) {
	return "There were 0 incidents today.", CallMetrics{}, nil
}

// A question asked while an incident is being analysed waits (alerts first) and is answered once the analysis ends.
func TestChatQueuesBehindIncident(t *testing.T) {
	old := chatLLM
	chatLLM = func(string) v3LLM { return fakeChatLLM{} }
	defer func() { chatLLM = old }()
	r := &Reasoner{}
	inc := &Incident{ID: "INC-0901", State: "running"}
	r.incidents = []*Incident{inc}
	cs := &chatStore{path: t.TempDir() + "/chats.json", S: map[string]*ChatSession{}}
	go func() {
		time.Sleep(2500 * time.Millisecond)
		if cs.wait != "INC-0901" {
			t.Errorf("status should name the incident it waits for, got %q", cs.wait)
		}
		r.mu.Lock()
		inc.State = "done"
		r.mu.Unlock()
	}()
	s, err := cs.Ask(context.Background(), r, "", "How many incidents today?")
	if err != nil {
		t.Fatal(err)
	}
	m := s.Msgs[len(s.Msgs)-1]
	if m.Busy || m.Text != "There were 0 incidents today." || m.Queued < 2000 {
		t.Fatalf("expected a queued answer, got %+v", m)
	}
}
