package main

// Viewer clock (owner 2026-11-27: "any laptop-independent way" to fix the board clock). Order of trust:
//  1. network time: the Date header of any trusted server reply (campus, heartbeat, fog, Supabase; clocknet.go)
//  2. viewer devices: a phone or browser that opens the dashboard posts its own clock (POST /api/clock/viewer).
//     Used ONLY while no network time has been seen in the last 6 h, and never from the board's own WebView
//     (loopback: it shares the wrong RTC). One viewer is enough when the device clock is obviously wrong (year
//     < 2025); otherwise two different viewers must agree within 2 min. The median of the recent samples is applied
//     through applyTrueTime, which keeps its guards (no backwards jump of the sensor clock, slewing, absurd-date check).

import (
	"encoding/json"
	"net"
	"net/http"
	"sort"
	"sync"
	"time"
)

type viewerSample struct {
	off time.Duration // viewer time - device clock
	at  time.Time
}

var viewerClock struct {
	sync.Mutex
	byIP map[string]viewerSample
}

const viewerFresh = 30 * time.Minute
const viewerMaxStep = 7 * 24 * time.Hour

func netClockRecent() bool {
	if !netClock.set.Load() {
		return false
	}
	netClock.Lock()
	defer netClock.Unlock()
	return time.Since(netClock.at) < 6*time.Hour && netClock.src != "" && netClock.src[:min(6, len(netClock.src))] != "viewer"
}

// noteViewerClock records one viewer sample and applies the median when the rules above allow. Returns what it did.
func noteViewerClock(ip string, viewerMs int64) string {
	if viewerMs <= 0 {
		return "ignored: no time"
	}
	vt := time.UnixMilli(viewerMs)
	if vt.Year() < 2025 {
		return "ignored: viewer clock looks wrong"
	}
	if netClockRecent() {
		return "ignored: network time in use"
	}
	// no token is needed for this write (any phone on the LAN may help), so a viewer can move the clock by at most
	// 7 days unless the app clock is plainly unset (2023 RTC with no offset)
	if d := vt.Sub(nowTime()); (d > viewerMaxStep || d < -viewerMaxStep) && nowTime().Year() >= 2025 {
		return "ignored: more than 7 days from the board clock"
	}
	dev := devClock()
	viewerClock.Lock()
	if viewerClock.byIP == nil {
		viewerClock.byIP = map[string]viewerSample{}
	}
	viewerClock.byIP[ip] = viewerSample{vt.Sub(dev), time.Now()}
	var offs []time.Duration
	for k, s := range viewerClock.byIP {
		if time.Since(s.at) > viewerFresh {
			delete(viewerClock.byIP, k)
			continue
		}
		offs = append(offs, s.off)
	}
	viewerClock.Unlock()
	sort.Slice(offs, func(i, j int) bool { return offs[i] < offs[j] })
	med := offs[len(offs)/2]
	if len(offs) < 2 && !needClockFixViewer() {
		return "waiting for a second viewer"
	}
	if len(offs) >= 2 {
		agree := 0
		for _, o := range offs {
			if d := o - med; d < 2*time.Minute && d > -2*time.Minute {
				agree++
			}
		}
		if agree < 2 && !needClockFixViewer() {
			return "viewers disagree"
		}
	}
	applyTrueTime(dev.Add(med), "viewer device clock")
	return "applied"
}

// needClockFixViewer: the app clock is obviously wrong (2023 RTC, no offset applied): one viewer is then enough.
func needClockFixViewer() bool { return nowTime().Year() < 2025 }

func (s *Server) handleViewerClock(w http.ResponseWriter, r *http.Request) {
	if r.Method != http.MethodPost {
		http.Error(w, "POST only", http.StatusMethodNotAllowed)
		return
	}
	ip, _, _ := net.SplitHostPort(r.RemoteAddr)
	if pip := net.ParseIP(ip); pip == nil || pip.IsLoopback() {
		writeJSON(w, map[string]any{"result": "ignored: board's own screen"})
		return
	}
	var in struct {
		NowMs int64 `json:"now_ms"`
	}
	if json.NewDecoder(http.MaxBytesReader(w, r.Body, 256)).Decode(&in) != nil {
		http.Error(w, "bad body", http.StatusBadRequest)
		return
	}
	writeJSON(w, map[string]any{"result": noteViewerClock(ip, in.NowMs)})
}
