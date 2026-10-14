package main

// Incident store (state/incidents.jsonl).
//
// Every state change of an incident is appended as a full JSON line, so the newest line for an ID
// wins on load. Left alone that file only grows (≈17 KB per incident version) and every incident
// ever seen stays in RAM. On a board that runs for weeks, and that has been seen to lose power
// mid-write (brownout, HANDBOOK 2.34), the store therefore:
//
//   - compacts: rewrites the file with one line per incident (temp file + rename, so a power cut
//     leaves either the old or the new file, never half of one);
//   - retains the newest SCE_MAX_INCIDENTS (default 1000) incidents; older finished ones move to
//     incidents.archive.jsonl, which the self-learning export still reads (nothing is deleted);
//   - takes the next ID from the highest ID ever seen, so a torn last line can never make an ID be
//     reused.

import (
	"encoding/json"
	"log"
	"os"
	"strconv"
	"strings"
	"sync"
	"sync/atomic"
)

var (
	storeMu    sync.Mutex  // serialises appends against compaction
	compacting atomic.Bool // one background compaction at a time
)

func maxIncidents() int {
	if n, err := strconv.Atoi(os.Getenv("SCE_MAX_INCIDENTS")); err == nil && n >= 50 {
		return n
	}
	return 1000
}

// incNum is the numeric part of "INC-0123" (0 if malformed).
func incNum(id string) int {
	n, _ := strconv.Atoi(strings.TrimPrefix(id, "INC-"))
	return n
}

func (r *Reasoner) load() {
	b, err := os.ReadFile(r.store)
	if err != nil {
		return
	}
	last := map[string]*Incident{}
	order := []string{}
	lines, bad := 0, 0
	for _, line := range strings.Split(string(b), "\n") {
		if strings.TrimSpace(line) == "" {
			continue
		}
		lines++
		var inc Incident
		if json.Unmarshal([]byte(line), &inc) != nil || inc.ID == "" {
			bad++ // torn write (power loss) - the previous version of that incident is still in the file
			continue
		}
		if _, ok := last[inc.ID]; !ok {
			order = append(order, inc.ID)
		}
		if inc.State == "running" {
			inc.State = "failed" // the process died mid-analysis; the operator can rerun it
		}
		c := inc
		last[inc.ID] = &c
		if n := incNum(inc.ID); n > r.seq {
			r.seq = n
		}
	}
	for _, id := range order {
		r.incidents = append(r.incidents, last[id])
	}
	if bad > 0 {
		log.Printf("store: skipped %d unreadable line(s) in %s", bad, r.store)
	}
	r.storeLines = lines
	if bad > 0 || lines > len(r.incidents) || len(r.incidents) > maxIncidents() {
		r.compact()
	}
}

func (r *Reasoner) persist(inc *Incident) {
	b, err := json.Marshal(inc)
	if err != nil {
		return
	}
	storeMu.Lock()
	f, err := os.OpenFile(r.store, os.O_APPEND|os.O_CREATE|os.O_WRONLY, 0o644)
	if err == nil {
		f.Write(append(b, '\n'))
		f.Close()
		r.storeLines++
	}
	lines := r.storeLines
	storeMu.Unlock()
	// rewrite once the file holds well over one line per incident, or retention is exceeded
	r.mu.RLock()
	n := len(r.incidents)
	r.mu.RUnlock()
	if (lines > 2*n+200 || n > maxIncidents()+100) && compacting.CompareAndSwap(false, true) {
		go func() {
			defer compacting.Store(false)
			r.compact()
		}()
	}
}

// compact archives incidents beyond the retention limit and rewrites the store with one line per
// remaining incident. Archived incidents leave memory only after the archive write succeeded.
func (r *Reasoner) compact() {
	storeMu.Lock()
	defer storeMu.Unlock()
	r.mu.RLock()
	var old []*Incident
	for i, extra := 0, len(r.incidents)-maxIncidents(); i < len(r.incidents) && extra > 0; i++ {
		if inc := r.incidents[i]; inc.State != "running" {
			old = append(old, inc)
			extra--
		}
	}
	var ab []byte
	for _, inc := range old {
		if b, err := json.Marshal(inc); err == nil {
			ab = append(append(ab, b...), '\n')
		}
	}
	r.mu.RUnlock()

	if len(old) > 0 {
		f, err := os.OpenFile(archivePath(r.store), os.O_APPEND|os.O_CREATE|os.O_WRONLY, 0o644)
		if err != nil {
			log.Printf("store: archive open failed: %v (nothing archived)", err)
			old = nil
		} else {
			_, werr := f.Write(ab)
			if serr := f.Sync(); werr != nil || serr != nil {
				log.Printf("store: archive write failed: %v %v (nothing archived)", werr, serr)
				old = nil
			}
			f.Close()
		}
	}

	r.mu.Lock()
	if len(old) > 0 {
		gone := map[*Incident]bool{}
		for _, inc := range old {
			gone[inc] = true
		}
		keep := make([]*Incident, 0, len(r.incidents)-len(old))
		for _, inc := range r.incidents {
			if !gone[inc] {
				keep = append(keep, inc)
			}
		}
		r.incidents = keep
	}
	var buf []byte
	for _, inc := range r.incidents {
		if b, err := json.Marshal(inc); err == nil {
			buf = append(append(buf, b...), '\n')
		}
	}
	n := len(r.incidents)
	r.mu.Unlock()

	tmp := r.store + ".tmp"
	f, err := os.OpenFile(tmp, os.O_CREATE|os.O_TRUNC|os.O_WRONLY, 0o644)
	if err != nil {
		log.Printf("store: compaction skipped: %v", err)
		return
	}
	_, werr := f.Write(buf)
	serr := f.Sync()
	f.Close()
	if werr != nil || serr != nil || os.Rename(tmp, r.store) != nil {
		os.Remove(tmp)
		log.Printf("store: compaction failed (write=%v sync=%v), old store kept", werr, serr)
		return
	}
	r.storeLines = n
	log.Printf("store: compacted to %d incidents (%d archived)", n, len(old))
}

func archivePath(store string) string {
	return strings.TrimSuffix(store, ".jsonl") + ".archive.jsonl"
}
