package main

// night sweep 2026-11-27, workstream D:
//   #87 resource history: one sample a minute (edge-agent RSS, htpd RSS, MemAvailable, NPU/CPU/skin temperature),
//       the last 24 h in memory and in state/resources.jsonl (capped), served at GET /api/resources?hours=N for the
//       health page.
//   #88 thermal budget: every AI run took the board to 92-95 C; a flood would hit the 88 C NPU guard and serialise
//       everything behind cool-downs. Non-urgent NPU work (chat, idle warm-up, gate-wait prefetch) now waits while
//       the NPU is above thermalBudgetC until it is back under thermalResumeC (bounded). Alert analyses never call
//       thermalYield, so they are never delayed by it.

import (
	"bufio"
	"context"
	"encoding/json"
	"log"
	"net/http"
	"os"
	"path/filepath"
	"strconv"
	"strings"
	"sync"
	"time"
)

const (
	thermalBudgetC = 80.0
	thermalResumeC = 75.0
)

var (
	thermalYieldMax = 90 * time.Second
	thermalPoll     = time.Second
	// thermalNPU: the hottest NPU junction now (a test hook)
	thermalNPU = func() float64 { _, npu, _ := ThermalHot(); return npu }
)

// thermalOverBudget: the NPU is hotter than the budget for optional work.
func thermalOverBudget() bool { return thermalNPU() >= thermalBudgetC }

// thermalYield: non-urgent NPU work waits here while the NPU is over the budget (at most thermalYieldMax, or until
// ctx ends). Returns how long it waited (thermalYieldMax is the usual bound; the chat uses a shorter one). Never call it on an alert's path.
func thermalYield(ctx context.Context, what string, max time.Duration) time.Duration {
	npu := thermalNPU()
	if npu < thermalBudgetC {
		return 0
	}
	t0 := time.Now()
	for npu >= thermalResumeC && time.Since(t0) < max {
		select {
		case <-ctx.Done():
			return time.Since(t0)
		case <-time.After(thermalPoll):
		}
		npu = thermalNPU()
	}
	d := time.Since(t0)
	logQuiet("thermal-yield-"+what, "thermal budget: %s waited %v for the NPU to cool (now %.0f C)", what, d.Round(100*time.Millisecond), npu)
	return d
}

// ---------------------------------------------------------------- resource history (#87)

type resSample struct {
	T         int64   `json:"t"` // unix (corrected clock)
	RSSMB     float64 `json:"rss_mb"`
	HtpdRSSMB float64 `json:"htpd_rss_mb,omitempty"`
	MemAvMB   int     `json:"mem_available_mb"`
	NPUC      float64 `json:"npu_c,omitempty"`
	CPUC      float64 `json:"cpu_c,omitempty"`
	SkinC     float64 `json:"skin_c,omitempty"`
}

var resHist struct {
	sync.Mutex
	s []resSample
}

const resKeep = 24 * 60 // one a minute, 24 h

// procRSSMB: VmRSS of a process (0 when unreadable).
func procRSSMB(pid string) float64 {
	f, err := os.Open("/proc/" + pid + "/status")
	if err != nil {
		return 0
	}
	defer f.Close()
	sc := bufio.NewScanner(f)
	for sc.Scan() {
		if l := sc.Text(); strings.HasPrefix(l, "VmRSS:") {
			if fs := strings.Fields(l); len(fs) >= 2 {
				kb, _ := strconv.ParseFloat(fs[1], 64)
				return float64(int(kb/1024*10)) / 10
			}
		}
	}
	return 0
}

func sampleResources() resSample {
	d := deviceStats()
	s := resSample{T: nowTime().Unix(), RSSMB: procRSSMB("self")}
	s.MemAvMB, _ = d["mem_available_mb"].(int)
	s.NPUC, _ = d["npu_c"].(float64)
	s.CPUC, _ = d["cpu_c"].(float64)
	s.SkinC, _ = d["skin_c"].(float64)
	for _, p := range htpdPids() {
		s.HtpdRSSMB += procRSSMB(strconv.Itoa(p))
	}
	return s
}

func addResSample(s resSample) {
	resHist.Lock()
	resHist.s = append(resHist.s, s)
	if n := len(resHist.s); n > resKeep {
		resHist.s = append([]resSample(nil), resHist.s[n-resKeep:]...)
	}
	resHist.Unlock()
}

// resSince: the samples of the last `hours` hours plus the min/max of each series.
func resSince(hours int, now int64) map[string]any {
	resHist.Lock()
	defer resHist.Unlock()
	from := now - int64(hours)*3600
	out := []resSample{}
	peak := map[string]float64{}
	for _, s := range resHist.s {
		if s.T < from {
			continue
		}
		out = append(out, s)
		for k, v := range map[string]float64{"rss_mb": s.RSSMB, "htpd_rss_mb": s.HtpdRSSMB, "npu_c": s.NPUC, "cpu_c": s.CPUC} {
			peak[k] = max(peak[k], v)
		}
		if mv := float64(s.MemAvMB); peak["mem_available_mb_min"] == 0 || mv < peak["mem_available_mb_min"] {
			peak["mem_available_mb_min"] = mv
		}
	}
	return map[string]any{"hours": hours, "samples": out, "peak": peak, "every_s": 60,
		"thermal_budget_c": thermalBudgetC, "thermal_resume_c": thermalResumeC}
}

// StartResourceHistory samples every minute; the newest 24 h are reloaded from state/resources.jsonl at start.
func (s *Server) StartResourceHistory() {
	p := filepath.Join(s.dir, "state", "resources.jsonl")
	if b, err := os.ReadFile(p); err == nil {
		cut := nowTime().Unix() - 24*3600
		for _, ln := range strings.Split(string(b), "\n") {
			var r resSample
			if json.Unmarshal([]byte(ln), &r) == nil && r.T >= cut {
				addResSample(r)
			}
		}
	}
	safeGo("resource history", func() {
		for {
			safeIter("resource history", func() {
				r := sampleResources()
				addResSample(r)
				b, _ := json.Marshal(r)
				if err := appendSync(p, append(b, '\n')); err != nil {
					logQuiet("res-hist", "resources: %v", err)
				}
				capTail(p, 1<<20) // ~1 MB = a few days of samples
			})
			time.Sleep(time.Minute)
		}
	})
	log.Printf("resources: sampling every minute (GET /api/resources)")
}

// resourceRoutes: GET /api/resources?hours=1..24 (default 6).
func (s *Server) resourceRoutes(mux *http.ServeMux) {
	mux.HandleFunc("/api/resources", func(w http.ResponseWriter, r *http.Request) {
		h, err := strconv.Atoi(r.URL.Query().Get("hours"))
		if err != nil || h <= 0 || h > 24 {
			h = 6
		}
		writeJSON(w, resSince(h, nowTime().Unix()))
	})
}
