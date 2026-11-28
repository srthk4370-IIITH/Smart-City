package main

// Gate countdown + live analysis progress (owner 2026-11-27). /api/status gets:
//   gate.watching: sensors abnormal but not yet reported, with how many abnormal readings they have and need, and
//                  the sensor time until the AI is called if every next reading stays abnormal
//   gate.batch:    the open batch (who opened it, sensor time until it closes at the latest)
//   progress:      the incident being analysed: stage (agents | reasoner), agents done / total, an ETA from the
//                  measured stage times (agent ~3.2 s each, model swap ~3 s, reasoner = median of recent reports)

import (
	"math"
	"sort"
	"strings"
	"sync"
	"time"
)

type gateWatch struct {
	Node     string `json:"node"`
	Metric   string `json:"metric"`
	Location string `json:"location,omitempty"`
	Status   string `json:"status"`
	Have     int    `json:"have"`
	Need     int    `json:"need"`
	Fast     bool   `json:"fast,omitempty"` // critical: the fast path opens the incident on the next critical reading
	EtaS     int64  `json:"eta_s"`          // #84: includes the batch hold (time until the batch can close)
	HeldBy   string `json:"held_by"`        // #84: sensor (site id) the open batch waits for, "" if none
}

// GateView: caller must not hold e.mu.
func (e *Engine) GateView() map[string]any {
	e.mu.RLock()
	defer e.mu.RUnlock()
	tr := trigRules()
	var w []gateWatch
	waiting := e.batchWaitingLocked()
	hold := e.batchHoldLocked(waiting)
	for k, st := range e.states {
		if st == nil || st.alerted || st.AbnormalInWindow <= 0 || sevRank(st.Status) <= 0 {
			continue
		}
		need := tr.AbnormalOfWindow
		if st.AbnormalInWindow < need && !st.nowAb && st.NowStatus == "normal" {
			continue // #77: back to normal and still young: it cannot reach the AI gate, nothing to count down
		}
		g := gateWatch{Node: st.Node, Metric: st.Metric, Location: st.Location, Status: st.Status, Have: st.AbnormalInWindow, Need: need}
		left := need - st.AbnormalInWindow
		if st.Status == "critical" && st.critRun > 0 && st.critRun < fastReadings {
			g.Fast = true
			if l := fastReadings - st.critRun; l < left {
				left = l
			}
		}
		if left < 0 {
			left = 0
		}
		g.EtaS = int64(left) * bucketSec
		if e.batchUntil != 0 && left == 0 && e.relatedToBatch(k) {
			// #84: mature and waiting in the open batch: the real wait is the batch hold, and who causes it
			g.EtaS = hold
			for _, h := range waiting {
				if h != keySite(k) {
					g.HeldBy = h
					break
				}
			}
		}
		w = append(w, g)
	}
	sort.Slice(w, func(i, j int) bool {
		if a, b := sevRank(w[i].Status), sevRank(w[j].Status); a != b {
			return a > b
		}
		return w[i].EtaS < w[j].EtaS
	})
	out := map[string]any{"watching": w, "reading_s": bucketSec}
	if e.batchUntil != 0 {
		max := e.batchOpen + int64(tr.BatchMaxReadings)*bucketSec - e.sim
		if max < 0 {
			max = 0
		}
		out["batch"] = map[string]any{"opened_by": keySite(e.batchKey), "closes_within_s": max,
			"min_close_s": func() int64 {
				if d := e.batchUntil - e.sim; d > 0 {
					return d
				}
				return 0
			}(), "waiting_for": waiting, "eta_s": hold}
	}
	return out
}

// batchHoldLocked: #84, sensor time until the open batch can close, from the same rules as batchEvents: at once for a
// mature critical member; otherwise the minimum hold, or (while related sensors that are abnormal now are maturing)
// until the slowest of them matures, never past the batch cap. 0 = closes at the next reading. Caller holds e.mu.
func (e *Engine) batchHoldLocked(waiting []string) int64 {
	if e.batchUntil == 0 {
		return 0
	}
	tr := trigRules()
	maxClose := e.batchOpen + int64(tr.BatchMaxReadings)*bucketSec - e.sim
	ab := map[string]Candidate{}
	for k, st := range e.states {
		if st != nil && st.nowAb {
			ab[k] = Candidate{}
		}
	}
	if e.criticalMatureLocked(ab) {
		return 0
	}
	var d int64
	if len(waiting) == 0 {
		d = e.batchOpen + bucketSec - e.sim
	} else {
		d = e.batchUntil - e.sim
		for k := range e.states {
			if e.holdsBatchLocked(k) {
				if m := int64(tr.AbnormalOfWindow-e.states[k].AbnormalInWindow) * bucketSec; m > d {
					d = m
				}
			}
		}
		if d > maxClose {
			d = maxClose
		}
	}
	if d < 0 {
		d = 0
	}
	return d
}

// aiRunningID: night sweep 2026-11-27 #110, the incident the NPU is analysing right now ("" = none).
func aiRunningID() string {
	progS.Lock()
	defer progS.Unlock()
	if progS.cur == nil {
		return ""
	}
	return progS.cur.ID
}

// aiEtaOf: #110 ai_eta_s, sensor seconds until the next AI run for this incident (early look or full reading): 0 when
// it is queued for the NPU, the gate ETA of its soonest flagged sensor while it waits for the full reading (awaiting:
// a fast-path / early-look incident still mapped to its sensors), -1 when unknown or nothing is due.
func aiEtaOf(gw []gateWatch, inc *Incident, awaiting, queued bool) int64 {
	if queued {
		return 0
	}
	if !awaiting && inc.RefineStage != "provisional" {
		return -1
	}
	best := int64(-1)
	for _, s := range inc.Sensors {
		if s.Context {
			continue
		}
		for _, w := range gw {
			if w.Node == s.Node && w.Metric == s.Metric && (best < 0 || w.EtaS < best) {
				best = w.EtaS
			}
		}
	}
	return best
}

// aiQueueLocked: #110, incidents waiting for the full reading (fast path / early look still mapped to their sensors)
// and incidents queued for the NPU (early look jobs, or a pending alert batch on a mapped sensor). Caller holds r.mu.
func (r *Reasoner) aiQueueLocked() (awaiting, queued map[*Incident]bool) {
	awaiting, queued = map[*Incident]bool{}, map[*Incident]bool{}
	for _, inc := range r.fastInc {
		if inc != nil {
			awaiting[inc] = true
		}
	}
	for _, j := range r.early {
		if j.inc != nil {
			queued[j.inc] = true
		}
	}
	for _, c := range r.pending {
		if inc := r.fastInc[key(c.Node, c.Metric)]; inc != nil {
			queued[inc] = true
		}
	}
	return awaiting, queued
}

// ---- analysis progress

type anProgress struct {
	ID     string `json:"id"`
	Stage  string `json:"stage"` // agents | reasoner
	Done   int    `json:"done"`
	Total  int    `json:"total"`
	Since  int64  `json:"since"` // unix (corrected clock) the stage started
	EtaS   int    `json:"eta_s"`
	start  time.Time
	rsnMed float64
}

var progS struct {
	sync.Mutex
	cur  *anProgress
	rsnS []float64 // recent reasoner seconds (last 10)
}

const agentSecs, swapSecs, rsnDefault = 3.2, 3.0, 28.0

func progAgents(id string, total int) {
	progS.Lock()
	progS.cur = &anProgress{ID: id, Stage: "agents", Total: total, Since: nowTime().Unix(), start: time.Now()}
	progS.Unlock()
}

func progAgentDone(id string) {
	progS.Lock()
	if p := progS.cur; p != nil && p.ID == id && p.Stage == "agents" {
		p.Done++
	}
	progS.Unlock()
}

func progReasoner(id string) {
	progS.Lock()
	progS.cur = &anProgress{ID: id, Stage: "reasoner", Since: nowTime().Unix(), start: time.Now()}
	progS.Unlock()
}

// progEnd: the analysis is over; a reasoner stage feeds the ETA median.
func progEnd(id string) {
	progS.Lock()
	if p := progS.cur; p != nil && p.ID == id {
		if p.Stage == "reasoner" {
			if s := time.Since(p.start).Seconds(); s > 2 && s < 300 {
				progS.rsnS = append(progS.rsnS, s)
				if len(progS.rsnS) > 10 {
					progS.rsnS = progS.rsnS[1:]
				}
			}
		}
		progS.cur = nil
	}
	progS.Unlock()
}

func rsnMedian() float64 {
	if len(progS.rsnS) == 0 {
		return rsnDefault
	}
	s := append([]float64(nil), progS.rsnS...)
	sort.Float64s(s)
	return s[len(s)/2]
}

// progressView: the current analysis with an ETA, or nil.
func progressView() *anProgress {
	progS.Lock()
	defer progS.Unlock()
	p := progS.cur
	if p == nil {
		return nil
	}
	c := *p
	el := time.Since(p.start).Seconds()
	var eta float64
	if c.Stage == "agents" {
		eta = float64(c.Total-c.Done)*agentSecs + swapSecs + rsnMedian()
		eta -= el - float64(c.Done)*agentSecs // time already spent on the running agent
	} else {
		eta = rsnMedian() - el
	}
	if eta < 1 {
		eta = 1
	}
	c.EtaS = int(eta + 0.5)
	return &c
}

// placeOf: "KH building, level 03, indoor air sensor 03" -> "KH building, level 03" (building + floor, for the
// incident list filter and the Android notification).
func placeOf(loc string) string {
	parts := strings.Split(loc, ",")
	if len(parts) >= 3 {
		parts = parts[:2]
	} else if len(parts) == 2 && !strings.Contains(strings.ToLower(parts[1]), "level") {
		parts = parts[:1]
	}
	for i := range parts {
		parts[i] = strings.TrimSpace(parts[i])
	}
	return strings.Join(parts, ", ")
}

func containsStr(xs []string, x string) bool {
	for _, y := range xs {
		if y == x {
			return true
		}
	}
	return false
}

// sparkOfWindow: at most n points of a window (bucket means), rounded to 3 significant decimals.
func sparkOfWindow(raw []float64, n int) []float64 {
	xs := make([]float64, 0, len(raw)) // NaN / Inf (missing readings) would break the JSON reply
	for _, x := range raw {
		if !math.IsNaN(x) && !math.IsInf(x, 0) {
			xs = append(xs, x)
		}
	}
	if len(xs) == 0 {
		return nil
	}
	if len(xs) <= n {
		out := make([]float64, len(xs))
		for i, x := range xs {
			out[i] = math.Round(x*1000) / 1000
		}
		return out
	}
	out := make([]float64, n)
	for k := 0; k < n; k++ {
		a, b := k*len(xs)/n, (k+1)*len(xs)/n
		sum := 0.0
		for _, x := range xs[a:b] {
			sum += x
		}
		out[k] = math.Round(sum/float64(b-a)*1000) / 1000
	}
	return out
}
