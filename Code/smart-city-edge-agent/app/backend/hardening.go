package main

// Production hardening (proofs/2026-11-19_prod_audit/FINDINGS.md, owner decisions in POLISH.md):
// one atomic-write helper, panic recovery for every long-lived goroutine and HTTP handler, file rotation caps,
// disk-free reporting, the htpd restart-loop cap.

import (
	"bytes"
	"fmt"
	"log"
	"net/http"
	"os"
	"path/filepath"
	"runtime/debug"
	"sync"
	"time"
)

// atomicWrite replaces path with b: temp file in the same directory, write checked, fsync, rename, directory fsync.
// A power cut leaves either the old or the new file, never half of one; a full disk is an error, not a silent loss.
func atomicWrite(path string, b []byte, perm os.FileMode) error {
	if err := os.MkdirAll(filepath.Dir(path), 0o755); err != nil {
		return err
	}
	tmp := path + ".tmp"
	f, err := os.OpenFile(tmp, os.O_CREATE|os.O_TRUNC|os.O_WRONLY, perm)
	if err != nil {
		return err
	}
	_, werr := f.Write(b)
	serr := f.Sync()
	cerr := f.Close()
	for _, e := range []error{werr, serr, cerr} {
		if e != nil {
			os.Remove(tmp)
			return fmt.Errorf("write %s: %w", filepath.Base(path), e)
		}
	}
	if err := os.Rename(tmp, path); err != nil {
		os.Remove(tmp)
		return err
	}
	if d, err := os.Open(filepath.Dir(path)); err == nil { // make the rename itself durable (not supported everywhere: ignored)
		d.Sync()
		d.Close()
	}
	return nil
}

// appendSync appends b to path and fsyncs; any failure is returned.
func appendSync(path string, b []byte) error {
	f, err := os.OpenFile(path, os.O_APPEND|os.O_CREATE|os.O_WRONLY, 0o644)
	if err != nil {
		return err
	}
	_, werr := f.Write(b)
	serr := f.Sync()
	cerr := f.Close()
	for _, e := range []error{werr, serr, cerr} {
		if e != nil {
			return e
		}
	}
	return nil
}

// ---------------------------------------------------------------- panic recovery

var panicCount struct {
	mu sync.Mutex
	n  int
}

func countPanic() {
	panicCount.mu.Lock()
	panicCount.n++
	panicCount.mu.Unlock()
}

// recoverLog is deferred at the top of a goroutine or handler: a panic is logged with its stack and swallowed.
func recoverLog(name string) {
	if p := recover(); p != nil {
		if p == http.ErrAbortHandler {
			panic(p)
		}
		countPanic()
		log.Printf("PANIC in %s: %v\n%s", name, p, debug.Stack())
	}
}

func panics() int {
	panicCount.mu.Lock()
	defer panicCount.mu.Unlock()
	return panicCount.n
}

// safeGo runs fn in a goroutine that survives a panic in it.
func safeGo(name string, fn func()) {
	go func() {
		defer recoverLog(name)
		fn()
	}()
}

// safeIter runs one iteration of a forever-loop body, so a panic costs one iteration, not the loop.
func safeIter(name string, fn func()) {
	defer recoverLog(name)
	fn()
}

// recoverMW: a panicking handler answers 500 instead of dropping the connection (net/http would only log it).
func recoverMW(next http.Handler) http.Handler {
	return http.HandlerFunc(func(w http.ResponseWriter, r *http.Request) {
		defer func() {
			if p := recover(); p != nil {
				if p == http.ErrAbortHandler {
					panic(p)
				}
				countPanic()
				log.Printf("PANIC in handler %s %s: %v\n%s", r.Method, r.URL.Path, p, debug.Stack())
				http.Error(w, "internal error (logged)", http.StatusInternalServerError)
			}
		}()
		next.ServeHTTP(w, r)
	})
}

// ---------------------------------------------------------------- rotation caps

const (
	archiveCapBytes = 50 << 20 // incidents.archive.jsonl
	fogRowsCapBytes = 50 << 20 // fog_rows.jsonl
	dailyKeepDays   = 90       // state/daily/*.json
)

// fogMu serialises fog_rows.jsonl appends against its rotation.
var fogMu sync.Mutex

// capTail keeps only the newest ~half of path (whole lines) once it is larger than max bytes. Returns true when it cut.
func capTail(path string, max int64) bool {
	fi, err := os.Stat(path)
	if err != nil || fi.Size() <= max {
		return false
	}
	b, err := os.ReadFile(path)
	if err != nil {
		return false
	}
	b = b[len(b)-int(max/2):]
	if i := bytes.IndexByte(b, '\n'); i >= 0 {
		b = b[i+1:]
	}
	if err := atomicWrite(path, b, 0o644); err != nil {
		log.Printf("rotate: %s: %v", path, err)
		return false
	}
	log.Printf("rotate: %s cut to its newest %d KB", filepath.Base(path), len(b)>>10)
	return true
}

// pruneOld deletes files in dir matching pattern that are older than maxAge. Returns how many.
func pruneOld(dir, pattern string, maxAge time.Duration, now time.Time) int {
	files, _ := filepath.Glob(filepath.Join(dir, pattern))
	n := 0
	for _, f := range files {
		if fi, err := os.Stat(f); err == nil && now.Sub(fi.ModTime()) > maxAge && os.Remove(f) == nil {
			n++
		}
	}
	return n
}

// rotateStateFiles applies every cap under <dir>/state. Safe to call often (it only acts past a limit).
func rotateStateFiles(dir string, now time.Time) {
	st := filepath.Join(dir, "state")
	capTail(filepath.Join(st, "incidents.archive.jsonl"), archiveCapBytes)
	capTail(filepath.Join(st, "boots.jsonl"), 1<<20)
	fogMu.Lock()
	capTail(filepath.Join(st, "fog_rows.jsonl"), fogRowsCapBytes)
	fogMu.Unlock()
	if n := pruneOld(filepath.Join(st, "daily"), "*.json", dailyKeepDays*24*time.Hour, now); n > 0 {
		log.Printf("rotate: %d daily summaries older than %d days removed", n, dailyKeepDays)
	}
}

// ---------------------------------------------------------------- disk

// DiskInfo is the state partition's usage, for /api/health.
type DiskInfo struct {
	OK      bool    `json:"ok"` // false: could not be read
	UsedPct float64 `json:"used_pct"`
	FreeMB  int64   `json:"free_mb"`
	TotalMB int64   `json:"total_mb"`
	Alert   bool    `json:"alert"` // more than diskAlertPct used
}

const diskAlertPct = 85.0

func diskInfo(dir string) DiskInfo {
	free, total, ok := diskFreeTotal(dir)
	if !ok || total == 0 {
		return DiskInfo{}
	}
	used := 100 * float64(total-free) / float64(total)
	return DiskInfo{OK: true, UsedPct: float64(int(used*10+0.5)) / 10, FreeMB: int64(free >> 20), TotalMB: int64(total >> 20), Alert: used > diskAlertPct}
}

// StartHousekeeping: hourly rotation + disk alarm (one alert per day through the alerter when it is configured).
func (s *Server) StartHousekeeping() {
	safeGo("housekeeping", func() {
		for {
			safeIter("housekeeping", func() {
				now := nowTime()
				rotateStateFiles(s.dir, now)
				if d := diskInfo(s.dir); d.Alert {
					log.Printf("DISK: %.1f%% used, %d MB free on the state partition", d.UsedPct, d.FreeMB)
					if prod.alert != nil {
						prod.alert.SendSystem("disk|"+now.Format("2006-01-02"), "Board disk almost full",
							fmt.Sprintf("The state disk is %.0f%% full (%d MB free). Old data is rotated, but check the board.", d.UsedPct, d.FreeMB))
					}
				}
			})
			time.Sleep(time.Hour)
		}
	})
}

// ---------------------------------------------------------------- htpd restart-loop cap

// restartLoop stops a crash-looping htpd from being restarted every 15 s forever: 6 starts within 15 min trips a
// backoff of 5, 10, 20, then 30 min during which the board runs rules-only (health shows it).
type restartLoop struct {
	mu       sync.Mutex
	starts   []time.Time
	until    time.Time
	level    int
	lastTrip time.Time
	now      func() time.Time
}

const (
	restartLoopMax    = 6
	restartLoopWindow = 15 * time.Minute
)

var htpdLoop = &restartLoop{now: time.Now}

func (l *restartLoop) allow() bool {
	l.mu.Lock()
	defer l.mu.Unlock()
	return !l.now().Before(l.until)
}

// note records one start; returns true when it tripped the cap.
func (l *restartLoop) note() bool {
	l.mu.Lock()
	defer l.mu.Unlock()
	now := l.now()
	keep := l.starts[:0]
	for _, t := range l.starts {
		if now.Sub(t) < restartLoopWindow {
			keep = append(keep, t)
		}
	}
	l.starts = append(keep, now)
	if len(l.starts) < restartLoopMax {
		return false
	}
	if now.Sub(l.lastTrip) > 2*time.Hour {
		l.level = 0
	}
	back := []time.Duration{5 * time.Minute, 10 * time.Minute, 20 * time.Minute, 30 * time.Minute}[min(l.level, 3)]
	l.level++
	l.until, l.lastTrip, l.starts = now.Add(back), now, nil
	log.Printf("htpd: %d starts within %v - restart loop; no new start for %v (rules-only meanwhile)", restartLoopMax, restartLoopWindow, back)
	return true
}

// status: rules-only now? minutes left.
func (l *restartLoop) status() (bool, int) {
	l.mu.Lock()
	defer l.mu.Unlock()
	if left := l.until.Sub(l.now()); left > 0 {
		return true, int(left.Minutes()) + 1
	}
	return false, 0
}

// warmingLocked: a live sensor that holds fewer than PersistReadings readings in the last PersistReadings buckets
// (a fresh start, or a restore that was older than 2 h) cannot open an AI incident yet: how many minutes until it can.
// Slider / replay engines are never "warming up". Caller holds e.mu.
func (e *Engine) warmingLocked(k string) (bool, int) {
	if !e.Live {
		return false, 0
	}
	need := trigRules().PersistReadings
	if need <= 0 {
		return false, 0
	}
	top := e.sim / bucketSec * bucketSec
	have := 0
	for i := 0; i < need; i++ {
		if _, ok := e.series[k][top-int64(i)*bucketSec]; ok {
			have++
		}
	}
	if have >= need {
		return false, 0
	}
	return true, (need - have) * int(bucketSec/60)
}

const demoWatermark = "DEMO - injected test event, not a real sensor event"

// markDemo watermarks an incident that came from an injected scenario, so nobody mistakes it for a real event.
func markDemo(inc *Incident) {
	if inc.Injected {
		inc.Watermark = demoWatermark
	}
}
