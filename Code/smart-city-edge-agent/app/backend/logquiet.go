package main

// logQuiet: a failure that repeats every few seconds (campus API down, MQTT broker away, fog relay refused) is logged
// the first time, then at most once per logQuietEvery with how many repeats were hidden. Sweep 2026-11-27: agent.log
// held ~750 identical fog lines and a campus line every 10 s, burying the incident lines.

import (
	"log"
	"sync"
	"time"
)

const logQuietEvery = 10 * time.Minute

var logQ = struct {
	sync.Mutex
	last map[string]time.Time
	n    map[string]int
}{last: map[string]time.Time{}, n: map[string]int{}}

func logQuiet(key, format string, a ...any) {
	logQ.Lock()
	now := time.Now()
	if t, ok := logQ.last[key]; ok && now.Sub(t) < logQuietEvery {
		logQ.n[key]++
		logQ.Unlock()
		return
	}
	hidden := logQ.n[key]
	logQ.last[key], logQ.n[key] = now, 0
	logQ.Unlock()
	if hidden > 0 {
		log.Printf(format+" (repeated %d more times in the last %v)", append(a, hidden, logQuietEvery)...)
		return
	}
	log.Printf(format, a...)
}

// logQuietReset: the failure ended (link back): the next failure is logged at once.
func logQuietReset(key string) {
	logQ.Lock()
	delete(logQ.last, key)
	delete(logQ.n, key)
	logQ.Unlock()
}
