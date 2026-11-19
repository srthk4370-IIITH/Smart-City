package main

import (
	"sync/atomic"
	"testing"
	"time"
)

func TestIdleWarmOffByDefault(t *testing.T) {
	s := testServer(t)
	if newIdleWarmerFromProfile(s) != nil {
		t.Fatal("warm-up on without warm_idle_min")
	}
	t.Setenv("SCE_WARM_IDLE_MIN", "30")
	if htpdEnabled() {
		t.Skip("htpd engine configured in this environment")
	}
	if newIdleWarmerFromProfile(s) != nil {
		t.Fatal("warm-up on without htpd")
	}
	if k, _ := earlyAIConfig(); k != 0 {
		t.Fatalf("ai_early_k default %d, want 0 (off)", k)
	}
}

func TestIdleWarmRunsOnceWhenIdleAndYields(t *testing.T) {
	s := testServer(t)
	var runs atomic.Int32
	clk := time.Now()
	w := &idleWarmer{idle: 30 * time.Minute, r: s.rsn, g: s.genie, now: func() time.Time { return clk }, last: clk}
	var during func()
	w.action = func() error {
		runs.Add(1)
		if during != nil {
			during()
		}
		return nil
	}
	if w.Check() {
		t.Fatal("warmed while not idle")
	}
	clk = clk.Add(31 * time.Minute)
	s.rsn.mu.Lock()
	s.rsn.active = true // an analysis is running
	s.rsn.mu.Unlock()
	if w.Check() {
		t.Fatal("warmed during an analysis")
	}
	s.rsn.mu.Lock()
	s.rsn.active = false
	s.rsn.mu.Unlock()
	// work that arrives during the warm-up waits for it and then runs at once
	during = func() {
		s.rsn.mu.Lock()
		if !s.rsn.active {
			t.Error("warm-up did not hold the queue slot")
		}
		s.rsn.refines = append(s.rsn.refines, "INC-NONE")
		s.rsn.refineQ["INC-NONE"] = true
		s.rsn.mu.Unlock()
	}
	if !w.Check() || runs.Load() != 1 {
		t.Fatalf("no warm-up after idle (runs %d)", runs.Load())
	}
	waitFor(t, "queued work drained", 5*time.Second, func() bool {
		s.rsn.mu.RLock()
		defer s.rsn.mu.RUnlock()
		return !s.rsn.active && len(s.rsn.refines) == 0
	})
	during = nil
	if w.Check() {
		t.Fatal("warmed twice within the idle period")
	}
	clk = clk.Add(31 * time.Minute)
	if !w.Check() || runs.Load() != 2 {
		t.Fatal("second idle period did not warm")
	}
}
