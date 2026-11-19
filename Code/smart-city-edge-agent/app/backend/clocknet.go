package main

// Network clock sync: the QIDK RTC resets to 2023 on every reboot and the EdgeService offset only knows the
// downtime it was saved with. Every successful campus poll / heartbeat response carries an HTTP "Date" header
// (true time, 1 s resolution); noteHTTPDate turns it into an offset against the device clock.
//   - differs from the current effective offset by <= 30 s: nothing.
//   - forward correction <= 5 min: slewed at most 60 s per response; larger: jump at once.
//   - backwards correction: the sensor/bucket clock never moves back. nowTime holds its last value until the
//     corrected time catches up (safest: no window restart, no duplicate or reordered buckets).
//   - absurd Date (more than 1 year from the current clock) is rejected unless the device year is < 2025.
//   - the offset is persisted to <dir>/state/clock_offset_s (EdgeService prefers it when newer).

import (
	"log"
	"net/http"
	"os"
	"path/filepath"
	"strconv"
	"sync"
	"sync/atomic"
	"time"
)

var netClock struct {
	sync.Mutex
	set    atomic.Bool
	off    atomic.Int64 // ns added to devClock()
	last   atomic.Int64 // unix ns of the last nowTime result (monotonic hold)
	src    string
	at     time.Time
	dir    string
	stored int64
}

const netSlewMax = 60 * time.Second
const netJumpLimit = 5 * time.Minute

// netNow is nowTime's network branch: devClock+offset, never earlier than the previous result.
func netNow() time.Time {
	t := devClock().Add(time.Duration(netClock.off.Load())).UnixNano()
	for {
		l := netClock.last.Load()
		if t <= l {
			return time.Unix(0, l)
		}
		if netClock.last.CompareAndSwap(l, t) {
			return time.Unix(0, t)
		}
	}
}

func setNetClockDir(dir string) {
	netClock.Lock()
	netClock.dir = filepath.Join(dir, "state")
	netClock.Unlock()
}

// noteHTTPDate reads the Date header of a response from a trusted endpoint.
func noteHTTPDate(h http.Header, src string) {
	d := h.Get("Date")
	if d == "" {
		return
	}
	t, err := http.ParseTime(d)
	if err != nil {
		return
	}
	applyTrueTime(t, src)
}

// netSyncOff disables the Date-header sync (the test binary: httptest servers answer with the laptop clock).
var netSyncOff atomic.Bool

func applyTrueTime(truth time.Time, src string) {
	if netSyncOff.Load() {
		return
	}
	netClock.Lock()
	defer netClock.Unlock()
	dev := devClock()
	cur := nowTime()
	diff := truth.Sub(cur)
	if diff < 0 {
		diff = -diff
	}
	if diff > 366*24*time.Hour && !needClockFix() {
		log.Printf("clock: rejecting absurd Date %s from %s (clock %s)", truth.Format(time.RFC3339), src, cur.Format(time.RFC3339))
		return
	}
	want := truth.Sub(dev)
	curOff := cur.Sub(dev)
	if !netClock.set.Load() {
		netClock.off.Store(int64(curOff)) // start from what the app already uses
		netClock.last.Store(cur.UnixNano())
		netClock.set.Store(true)
	}
	netClock.src, netClock.at = src, time.Now()
	if diff <= 30*time.Second {
		netPersist(want)
		return
	}
	delta := want - time.Duration(netClock.off.Load())
	next := want
	if delta > 0 && delta <= netJumpLimit && delta > netSlewMax {
		next = time.Duration(netClock.off.Load()) + netSlewMax
	}
	if delta < 0 {
		log.Printf("clock: network time is %s behind; sensor clock held until it catches up", (-delta).Round(time.Second))
	}
	netClock.off.Store(int64(next))
	log.Printf("clock: corrected by %s via %s (offset now %s)", delta.Round(time.Second), src, next.Round(time.Second))
	netPersist(want)
}

// netPersist writes the TRUE offset (truth - device clock, whole seconds) when it moved >= 5 s since the last
// write. Caller holds the lock.
func netPersist(want time.Duration) {
	sec := int64(want.Round(time.Second) / time.Second)
	if netClock.dir == "" || (netClock.stored != 0 && sec-netClock.stored < 5 && netClock.stored-sec < 5) {
		return
	}
	os.MkdirAll(netClock.dir, 0o755)
	p := filepath.Join(netClock.dir, "clock_offset_s")
	if os.WriteFile(p+".tmp", []byte(strconv.FormatInt(sec, 10)), 0o644) == nil && os.Rename(p+".tmp", p) == nil {
		netClock.stored = sec
	}
}

func clockNetStatus() map[string]any {
	if !netClock.set.Load() {
		return nil
	}
	netClock.Lock()
	defer netClock.Unlock()
	return map[string]any{"source": "network (" + netClock.src + ")", "age_s": int(time.Since(netClock.at).Seconds()),
		"offset_s": int(time.Duration(netClock.off.Load()).Seconds())}
}
