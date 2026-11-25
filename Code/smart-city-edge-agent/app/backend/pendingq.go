package main

// The pending alert queue (reason.go mergePending): bounded, critical first, and persisted to state/pending.json so
// an alert that is waiting for the NPU survives a restart (audit 2026-11-19 #4). Taken at start by RestorePending.

import (
	"encoding/json"
	"log"
	"os"
	"path/filepath"
	"sort"
	"time"
)

const maxPendingCands = 64 // sensors waiting for the NPU; beyond this the least severe wait are dropped (and logged)

func (r *Reasoner) pendingPath() string { return filepath.Join(filepath.Dir(r.store), "pending.json") }

func candRank(c Candidate) int {
	switch {
	case c.Fast || c.Finding.Status == "critical":
		return 0
	case c.Finding.Status == "warning":
		return 1
	}
	return 2
}

// prioritizePending sorts critical first (stable) and cuts to max. Returns the kept list and how many were dropped.
func prioritizePending(c []Candidate, max int) ([]Candidate, int) {
	sort.SliceStable(c, func(i, j int) bool { return candRank(c[i]) < candRank(c[j]) })
	if len(c) > max {
		return c[:max], len(c) - max
	}
	return c, 0
}

// savePendingLocked mirrors r.pending to disk (caller holds r.mu). Empty = the file is removed.
func (r *Reasoner) savePendingLocked() {
	if len(r.pending) == 0 {
		os.Remove(r.pendingPath())
		return
	}
	b, err := json.Marshal(struct {
		SavedAt int64       `json:"saved_at"`
		Mode    int         `json:"mode"`
		Cands   []Candidate `json:"cands"`
	}{time.Now().Unix(), r.Mode, r.pending})
	if err == nil {
		err = atomicWrite(r.pendingPath(), b, 0o644)
	}
	if err != nil {
		log.Printf("pending queue: not saved: %v", err)
	}
}

// loadPending reads state/pending.json into r.pending (called by NewReasoner before anything runs).
func (r *Reasoner) loadPending() int {
	b, err := os.ReadFile(r.pendingPath())
	if err != nil {
		return 0
	}
	var in struct {
		Cands []Candidate `json:"cands"`
	}
	if json.Unmarshal(b, &in) != nil || len(in.Cands) == 0 {
		return 0
	}
	r.pending, _ = prioritizePending(in.Cands, maxPendingCands)
	return len(r.pending)
}

// RestorePending starts the restored queue once the engine has had a moment to take its first readings.
func (r *Reasoner) RestorePending() {
	r.mu.RLock()
	n := len(r.pending)
	r.mu.RUnlock()
	if n == 0 {
		return
	}
	log.Printf("pending queue: %d alert(s) restored from the last run; analysing them shortly", n)
	safeGo("restore pending", func() {
		time.Sleep(20 * time.Second)
		r.Kick()
	})
}

// Kick starts the next queued unit of work when the NPU loop is idle.
func (r *Reasoner) Kick() {
	r.mu.Lock()
	if r.active || r.coolWait {
		r.mu.Unlock()
		return
	}
	w, ok := r.next()
	if !ok {
		r.mu.Unlock()
		return
	}
	r.active = true
	r.lastNPU = time.Now()
	r.mu.Unlock()
	safeGo("analysis loop", func() { r.loop(w) })
}
