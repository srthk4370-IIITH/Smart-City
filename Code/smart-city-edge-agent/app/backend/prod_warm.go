package main

// Automatic NPU warm-up after idle (ROADMAP 2026-11-09 §2.3 L4: the first incident after 4 h idle took 78 s).
// OFF unless htpd_profile warm_idle_min=N (N >= 5).
//
// At start htpd already warms itself (htpdWarmup, htpd_warmup.jsonl). This adds the same after N minutes without
// NPU work: a 1-token reasoner call on the cached static prefix (rsn_v3 reasoner on htpd only), then the agents'
// warm-up file, so the agents' model is the resident one when the next alert comes. Rules:
//   - one NPU client: everything goes through the app's own htpd; the warm-up takes the reasoner's queue slot
//     (r.active) so no analysis starts in the middle of it, and anything that queued meanwhile runs right after;
//   - never while an analysis, a chat answer (runner busy) or the thermal guard is active, never twice within N min;
//   - an alert that arrives during the warm-up waits for it (a few seconds: the same model loads it would pay cold).

import (
	"context"
	"log"
	"sync"
	"time"
)

type idleWarmer struct {
	mu      sync.Mutex
	idle    time.Duration
	r       *Reasoner
	g       *GenieRunner
	action  func() error
	ready   func() bool // htpd up
	now     func() time.Time
	last    time.Time // last warm-up (or start)
	runs    int
	lastErr string
	lastMs  int64
}

func newIdleWarmerFromProfile(s *Server) *idleWarmer {
	n := profInt("warm_idle_min", 0, 5, 24*60)
	if n == 0 || !htpdEnabled() {
		return nil
	}
	w := &idleWarmer{idle: time.Duration(n) * time.Minute, r: s.rsn, g: s.genie, ready: htpdUp, now: time.Now}
	w.last = w.now()
	w.action = func() error { return npuWarm(s.genie, s.dir) }
	return w
}

// npuWarm: reasoner ping (rsn_v3 on htpd), then the agents' warm-up file.
func npuWarm(g *GenieRunner, dir string) error {
	if l, ok := reasonerLLM().(htpdReasonLLM); ok && reasonerV3Enabled() {
		ctx, cancel := context.WithTimeout(context.Background(), 90*time.Second)
		err := htpdReasonCaps(ctx)
		if err == nil {
			p := v3StaticPrefix()
			_, _, err = l.Complete(ctx, p+"Hi", 1, nil)
		}
		cancel()
		if err != nil {
			return err
		}
	}
	htpdWarmup(g, dir)
	return nil
}

func (w *idleWarmer) Stats() map[string]any {
	w.mu.Lock()
	defer w.mu.Unlock()
	return map[string]any{"idle_min": int(w.idle / time.Minute), "runs": w.runs, "last_error": w.lastErr,
		"last_ms": w.lastMs, "since_last_s": int(w.now().Sub(w.last).Seconds())}
}

// lastActivity: the newest of the last warm-up, the last analysis start and the runner's last call end.
// ok=false when the runner is busy right now.
func (w *idleWarmer) lastActivity() (time.Time, bool) {
	w.mu.Lock()
	t := w.last
	w.mu.Unlock()
	if w.g != nil {
		if w.g.busy.Load() || !w.g.mu.TryLock() {
			return t, false
		}
		if w.g.lastEnd.After(t) {
			t = w.g.lastEnd
		}
		w.g.mu.Unlock()
	}
	w.r.mu.RLock()
	if w.r.lastNPU.After(t) {
		t = w.r.lastNPU
	}
	w.r.mu.RUnlock()
	return t, true
}

// Check runs one warm-up when everything was idle for w.idle. Returns whether it ran.
func (w *idleWarmer) Check() bool {
	last, free := w.lastActivity()
	if !free || w.now().Sub(last) < w.idle {
		return false
	}
	if hot, _, _ := ThermalHot(); hot {
		return false
	}
	if w.ready != nil && !w.ready() {
		return false
	}
	r := w.r
	r.mu.Lock()
	if r.active || r.coolWait || r.pending != nil || len(r.jobs) > 0 || len(r.early) > 0 || len(r.refines) > 0 {
		r.mu.Unlock()
		return false
	}
	r.active = true // the queue slot: alerts queue behind the warm-up instead of interleaving with it
	r.mu.Unlock()

	t0 := w.now()
	err := w.action()
	w.mu.Lock()
	w.last, w.runs, w.lastMs = w.now(), w.runs+1, w.now().Sub(t0).Milliseconds()
	w.lastErr = ""
	if err != nil {
		w.lastErr = err.Error()
	}
	w.mu.Unlock()
	if err != nil {
		log.Printf("warm: idle warm-up failed after %d ms: %v", w.lastMs, err)
	} else {
		log.Printf("warm: idle warm-up done in %d ms", w.lastMs)
	}

	r.mu.Lock()
	if next, ok := r.next(); ok { // something queued during the warm-up: run it now, as loop would have
		r.lastNPU = time.Now()
		r.mu.Unlock()
		safeGo("analysis loop", func() { r.loop(next) })
		return true
	}
	r.active = false
	r.mu.Unlock()
	return true
}

func (w *idleWarmer) Run(stop <-chan struct{}) {
	t := time.NewTicker(time.Minute)
	defer t.Stop()
	for {
		select {
		case <-stop:
			return
		case <-t.C:
			w.Check()
		}
	}
}
