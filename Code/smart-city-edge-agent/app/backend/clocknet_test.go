package main

import (
	"net/http"
	"os"
	"path/filepath"
	"testing"
	"time"
)

func TestMain(m *testing.M) {
	netSyncOff.Store(true)
	os.Exit(m.Run())
}

func netClockReset(t *testing.T, dev time.Time) {
	netSyncOff.Store(false)
	old := devClock
	netClock.Lock()
	netClock.set.Store(false)
	netClock.off.Store(0)
	netClock.last.Store(0)
	netClock.stored = 0
	netClock.dir = t.TempDir()
	netClock.Unlock()
	devClock = func() time.Time { return dev }
	t.Cleanup(func() { devClock = old; netClock.set.Store(false); netSyncOff.Store(true) })
}

func dateHdr(tm time.Time) http.Header {
	h := http.Header{}
	h.Set("Date", tm.UTC().Format(http.TimeFormat))
	return h
}

func TestNetClockJumpAndPersist(t *testing.T) {
	dev := time.Date(2023, 3, 1, 0, 0, 0, 0, time.UTC)
	netClockReset(t, dev)
	truth := time.Date(2026, 11, 19, 10, 0, 0, 0, time.UTC)
	noteHTTPDate(dateHdr(truth), "campus Date header")
	if d := nowTime().Sub(truth); d < 0 || d > time.Second {
		t.Fatalf("not jumped: %v", d)
	}
	b, err := os.ReadFile(filepath.Join(netClock.dir, "clock_offset_s"))
	if err != nil || len(b) == 0 {
		t.Fatalf("not persisted: %v", err)
	}
	if clockNetStatus()["source"] != "network (campus Date header)" {
		t.Fatal("status source")
	}
}

func TestNetClockSmallDriftIgnoredAndNoHeader(t *testing.T) {
	dev := time.Date(2026, 11, 19, 10, 0, 0, 0, time.UTC)
	netClockReset(t, dev)
	noteHTTPDate(http.Header{}, "x")
	if netClock.set.Load() {
		t.Fatal("set without header")
	}
	noteHTTPDate(dateHdr(dev.Add(20*time.Second)), "x")
	if d := nowTime().Sub(dev); d != 0 {
		t.Fatalf("20 s drift corrected: %v", d)
	}
}

func TestNetClockSlewForwardAndBackwardHold(t *testing.T) {
	dev := time.Date(2026, 11, 19, 10, 0, 0, 0, time.UTC)
	netClockReset(t, dev)
	noteHTTPDate(dateHdr(dev.Add(3*time.Minute)), "x") // 3 min ahead: slewed 60 s per response
	if d := nowTime().Sub(dev); d != 60*time.Second {
		t.Fatalf("slew: %v", d)
	}
	hi := nowTime()
	noteHTTPDate(dateHdr(dev.Add(-5*time.Minute)), "x") // truth behind: never move back
	if nowTime().Before(hi) {
		t.Fatal("clock moved backwards")
	}
	cur := time.Date(2026, 11, 19, 10, 6, 0, 0, time.UTC)
	devClock = func() time.Time { return cur }
	if nowTime().Before(hi) {
		t.Fatal("still backwards after time passed")
	}
}

func TestNetClockRejectsAbsurd(t *testing.T) {
	dev := time.Date(2026, 11, 19, 10, 0, 0, 0, time.UTC)
	netClockReset(t, dev)
	noteHTTPDate(dateHdr(dev.AddDate(5, 0, 0)), "x")
	if netClock.set.Load() && nowTime().Sub(dev) != 0 {
		t.Fatal("absurd Date accepted")
	}
}
