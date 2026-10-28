package main

// Data-quality layer for real-world feeds (proofs/2026-10-23_realworld/REALWORLD.md).
//
// The sliders (and plain /api/ingest {node,metric,value}) keep the demo's sample-and-hold model: every
// poll samples the held value as the next reading. A real device feed is different and is handled here:
//
//   - Measured feed: a reading posted with a device timestamp ("ts") switches the sensor to measured
//     mode. Each 5-minute bucket is the MEAN of the readings that fall in it (as training built its series),
//     and a bucket without readings stays EMPTY. Nothing is held, nothing is invented: the existing gap
//     rules (Window: at most 3 missing of 48, live edge forward-filled at most 3 readings) then decide if
//     a window is good enough for the AI; otherwise the sensor is insufficient_data with a reason.
//   - Late / out-of-order readings (gateway store-and-forward bursts after a reconnect) are merged into
//     their own bucket, not the arrival bucket. Duplicates (MQTT QoS1 redelivery: same device ts) are
//     dropped. Device clocks that are not unix time, or run ahead, fall back to arrival time and are
//     flagged uncertain. Readings older than the 26 h retention are dropped.
//   - Quality flags (OPC UA style good / uncertain / bad): "bad" readings are never stored. Measured
//     readings outside the sensor's physical range are bad (a sentinel like -999 must not become a 0 dip).
//     Legacy held values are still clamped (the app suite drives rail faults that way) but flagged.
//   - A legacy held API value older than apiHoldSec of wall time stops producing readings: a device that
//     went silent no longer becomes a fabricated flatline.
//   - Maintenance windows: readings are not recorded and the event gate is held; the gate state re-arms.
//   - Sensor replacement: history before the swap is dropped, so the new sensor's level is never compared
//     with the old one (no false level shift / E9) and the AI waits for a full window of new data.
//
// The AI never receives modified data: the glitch filter (glitchFree) only changes what the EVENT GATE
// judges; a candidate always carries the raw window. Prompt formats are untouched.

import (
	"fmt"
	"math"
	"sort"
	"time"
)

const (
	retentionSec     = 26 * 3600
	clockAheadSec    = 300 // a device timestamp more than 5 min in the future is a clock error
	deadbandFrac     = 0.05
	offDelayReadings = 3 // near a limit, a reading back to normal must repeat this often to end an episode
	glitchSigma      = 8.0
)

// IngestStats counts what happened to a sensor's real readings.
type IngestStats struct {
	Accepted   int    `json:"accepted"`
	Late       int    `json:"late"`       // merged into an earlier bucket (out of order / gateway burst)
	Backfilled int    `json:"backfilled"` // late readings that filled an empty bucket
	Duplicates int    `json:"duplicates"`
	Rejected   int    `json:"rejected"` // bad quality, out of range, too old, before a replacement
	ClockFixes int    `json:"clock_fixes"`
	Clamped    int    `json:"clamped"`
	LastNote   string `json:"last_note,omitempty"`
	LastNoteAt int64  `json:"last_note_at,omitempty"` // sensor time
}

type bucketAcc struct {
	sum float64
	n   int
}

// feedState is the per-sensor data-quality state (caller holds e.mu).
type feedState struct {
	measured    bool
	pending     map[int64]*bucketAcc // readings for buckets not fed yet
	cnt         map[int64]int        // readings merged into each stored bucket (measured)
	seen        map[float64]bool     // device timestamps seen (dedup)
	stats       IngestStats
	uncertainAt int64 // sensor time of the newest uncertain reading
	maintFrom   int64
	maintUntil  int64 // sensor time; 0 = none
	maintWhy    string
	replacedAt  int64 // sensor time of the last replacement (0 = never)
	glitchAt    int64 // bucket of the last single-reading glitch the gate ignored
}

func (e *Engine) feedOf(k string) *feedState {
	if e.dq == nil {
		e.dq = map[string]*feedState{}
	}
	fs := e.dq[k]
	if fs == nil {
		fs = &feedState{pending: map[int64]*bucketAcc{}, cnt: map[int64]int{}, seen: map[float64]bool{}}
		e.dq[k] = fs
	}
	return fs
}

func (fs *feedState) note(at int64, f string, a ...any) {
	fs.stats.LastNote, fs.stats.LastNoteAt = fmt.Sprintf(f, a...), at
}

func (fs *feedState) inMaintenance(sim int64) bool {
	return fs != nil && fs.maintUntil != 0 && sim >= fs.maintFrom && sim < fs.maintUntil
}

// Reading is one real measurement. Ts is the device time (unix s, 0 = unknown: use arrival).
type Reading struct {
	Node    string   `json:"node"`
	Metric  string   `json:"metric"`
	Value   *float64 `json:"value"`
	Ts      float64  `json:"ts"`
	Quality string   `json:"quality"` // good (default) | uncertain | bad
}

// IngestReading stores one measured reading (see the file comment). now is the wall clock (unix s).
// It returns what happened: accepted | late | duplicate | rejected_bad | rejected_range | too_old |
// before_replacement | maintenance, plus "+clock" when the device time was not usable.
func (e *Engine) IngestReading(rd Reading, now int64) (string, error) {
	e.mu.Lock()
	defer e.mu.Unlock()
	k := key(rd.Node, rd.Metric)
	sn := e.bank[k]
	if sn == nil {
		return "", fmt.Errorf("unknown sensor %s %s", rd.Node, rd.Metric)
	}
	if rd.Value == nil || math.IsNaN(*rd.Value) || math.IsInf(*rd.Value, 0) {
		return "", fmt.Errorf("value must be a number")
	}
	q := rd.Quality
	if q == "" {
		q = "good"
	}
	if q != "good" && q != "uncertain" && q != "bad" {
		return "", fmt.Errorf("quality must be good, uncertain or bad")
	}
	fs := e.feedOf(k)
	if !fs.measured {
		// switching to the real feed: the held / pre-filled readings were never measured, drop them
		fs.measured = true
		delete(e.series, k)
		fs.note(e.sim, "live device feed started: earlier readings were simulated and are not used")
	}
	v := *rd.Value
	if q == "bad" {
		fs.stats.Rejected++
		fs.note(e.sim, "reading marked bad by the device: not stored")
		return "rejected_bad", nil
	}
	if v < sn.Min || v > sn.Max {
		fs.stats.Rejected++
		fs.note(e.sim, "reading %g outside the sensor range %g..%g: not stored", v, sn.Min, sn.Max)
		return "rejected_range", nil
	}
	if fs.inMaintenance(e.sim + bucketSec) {
		fs.stats.Rejected++
		return "maintenance", nil
	}
	clock := ""
	age := int64(0)
	switch {
	case rd.Ts == 0:
	case rd.Ts < 1e9: // uptime counter or an unset RTC (seen in the raw SCRC energy-meter export)
		clock, q = "+clock", "uncertain"
		fs.stats.ClockFixes++
		fs.note(e.sim, "device clock not set (ts %.0f): arrival time used", rd.Ts)
	default:
		if fs.seen[rd.Ts] {
			fs.stats.Duplicates++
			return "duplicate", nil
		}
		age = now - int64(rd.Ts)
		if age < -clockAheadSec {
			clock, q, age = "+clock", "uncertain", 0
			fs.stats.ClockFixes++
			fs.note(e.sim, "device clock ahead of the board: arrival time used")
		} else if age < 0 {
			age = 0
		}
		if age > retentionSec-bucketSec {
			fs.stats.Rejected++
			return "too_old", nil
		}
		fs.seen[rd.Ts] = true
		if len(fs.seen) > 20000 {
			for t := range fs.seen {
				if int64(t) < now-retentionSec {
					delete(fs.seen, t)
				}
			}
		}
	}
	b := e.sim + bucketSec - age/bucketSec*bucketSec // the bucket the reading falls in (5-min buckets end at b)
	if fs.replacedAt != 0 && b <= fs.replacedAt {
		fs.stats.Rejected++
		return "before_replacement", nil
	}
	if q == "uncertain" {
		fs.uncertainAt = b
	}
	fs.stats.Accepted++
	if b > e.sim {
		a := fs.pending[b]
		if a == nil {
			a = &bucketAcc{}
			fs.pending[b] = a
		}
		a.sum += v
		a.n++
		return "accepted" + clock, nil
	}
	// late: merge into its own bucket (mean with what that bucket already holds)
	if e.series[k] == nil {
		e.series[k] = map[int64]float64{}
	}
	fs.stats.Late++
	if old, ok := e.series[k][b]; ok && fs.cnt[b] > 0 {
		c := fs.cnt[b]
		e.series[k][b] = (old*float64(c) + v) / float64(c+1)
		fs.cnt[b] = c + 1
	} else {
		e.series[k][b] = v
		fs.cnt[b] = 1
		fs.stats.Backfilled++
	}
	return "late" + clock, nil
}

// feedMeasured records bucket b of a measured sensor: the mean of its readings, or nothing.
func (e *Engine) feedMeasured(k string, fs *feedState, b int64) {
	if a := fs.pending[b]; a != nil && a.n > 0 {
		if e.series[k] == nil {
			e.series[k] = map[int64]float64{}
		}
		e.series[k][b] = a.sum / float64(a.n)
		fs.cnt[b] = a.n
	}
	for bb := range fs.pending {
		if bb <= b {
			delete(fs.pending, bb)
		}
	}
	for bb := range fs.cnt {
		if bb < b-retentionSec {
			delete(fs.cnt, bb)
		}
	}
}

// apiHoldSec: a held /api/ingest value stops producing readings after 15 min of wall time (a var so the
// real-data replay test can reproduce the old unlimited hold).
var apiHoldSec int64 = 900

// heldStale: a legacy held API value nobody has refreshed for apiHoldSec of wall time.
func heldStale(sn *SimSensor) bool {
	return sn.Source == "api" && sn.SetAt > 0 && nowTime().Unix()-sn.SetAt > apiHoldSec
}

// SetMaintenance puts a sensor (metric "" = every metric of the node) out of service for minutes of
// sensor time: readings are not recorded and the event gate is held. replaced also drops the history
// before now (a new sensor's level is not comparable with the old one's).
func (e *Engine) SetMaintenance(node, metric string, minutes int, why string, replaced bool) ([]string, error) {
	e.mu.Lock()
	defer e.mu.Unlock()
	var ks []string
	for _, k := range e.bankOrder {
		sn := e.bank[k]
		if sn.Node == node && (metric == "" || sn.Metric == metric) {
			ks = append(ks, k)
		}
	}
	if len(ks) == 0 {
		return nil, fmt.Errorf("unknown sensor %s %s", node, metric)
	}
	if minutes < 0 || minutes > 7*24*60 {
		return nil, fmt.Errorf("minutes must be 0..10080")
	}
	for _, k := range ks {
		fs := e.feedOf(k)
		if minutes > 0 {
			fs.maintFrom, fs.maintUntil, fs.maintWhy = e.sim, e.sim+int64(minutes)*60, why
		} else {
			fs.maintFrom, fs.maintUntil, fs.maintWhy = 0, 0, ""
		}
		if replaced {
			e.replacedLocked(k, fs)
		}
		if st := e.states[k]; st != nil { // a fresh start for the gate
			st.alerted, st.Reported, st.clearedAt, st.same, st.AbnormalFor, st.normalRun = false, false, 0, 0, 0, 0
		}
	}
	return ks, nil
}

func (e *Engine) replacedLocked(k string, fs *feedState) {
	for b := range e.series[k] {
		if b <= e.sim {
			delete(e.series[k], b)
		}
	}
	fs.replacedAt = e.sim
	fs.cnt = map[int64]int{}
	fs.note(e.sim, "sensor replaced: older readings are not compared with the new sensor")
}

// glitchFree: the window with one isolated single-reading glitch removed, for the event gate only.
// A glitch is one reading far (glitchSigma robust sigmas of the 5-min changes) from BOTH neighbours while
// the neighbours agree. Two or more such readings are not a glitch but a fault pattern (dropouts, noise),
// left to the rules and the AI. The last reading cannot be judged yet (no right neighbour).
func glitchFree(role, metric string, xs []float64) ([]float64, int) {
	if !glitchMetric(role, metric) || len(xs) < 5 {
		return nil, -1
	}
	d := make([]float64, len(xs)-1)
	for i := range d {
		d[i] = math.Abs(xs[i+1] - xs[i])
	}
	sort.Float64s(d)
	sig := 1.4826 * d[len(d)/2]
	if m, ok := Metrics[role+"/"+metric]; ok && sig < m.Floor/10 {
		sig = m.Floor / 10 // quantised or very quiet sensors: the metric's noise floor
	}
	if sig <= 0 {
		return nil, -1
	}
	at := -1
	for i := 1; i < len(xs)-1; i++ {
		a, b, c := xs[i-1], xs[i], xs[i+1]
		if math.Abs(b-a) > glitchSigma*sig && math.Abs(b-c) > glitchSigma*sig && math.Abs(c-a) < 2*sig {
			if at >= 0 {
				return nil, -1
			}
			at = i
		}
	}
	if at < 0 {
		return nil, -1
	}
	out := append([]float64(nil), xs...)
	out[at] = (xs[at-1] + xs[at+1]) / 2
	return out, at
}

// glitchMetric: physical quantities that cannot jump and come back within one 5-minute mean. Power,
// flow, PM2.5 and occupancy can (a load surge, a pump, smoke), so they are never filtered.
func glitchMetric(role, metric string) bool {
	switch role + "/" + metric {
	case "air_quality/co2", "air_quality/temp", "air_quality/rh", "water/tds", "water/ph", "water/level",
		"weather/temp", "weather/rh", "hvac/room_temp":
		return true
	}
	return false
}

// nearLimit: the value is within the deadband of the metric's warning limit (ISA-18.2 deadband): a
// reading this close to the limit does not end an abnormal count or episode on its own.
func nearLimit(role, metric string, v float64) bool {
	m, ok := Metrics[role+"/"+metric]
	if !ok || !m.HasLimits || m.Warn == 0 {
		return false
	}
	db := math.Abs(m.Warn) * deadbandFrac
	switch m.Dir {
	case "high", "both":
		return v > m.Warn-db
	case "low":
		return v < m.Warn+db
	}
	return false
}

// windowCoverage: real readings among the last n buckets ending at end, and the newest reading's bucket.
func windowCoverage(s map[int64]float64, end int64, n int) (int, int64) {
	have, newest := 0, int64(0)
	for i := 0; i < n; i++ {
		b := end - int64(i)*bucketSec
		if _, ok := s[b]; ok {
			have++
			if b > newest {
				newest = b
			}
		}
	}
	if newest == 0 {
		for b := range s {
			if b <= end && b > newest {
				newest = b
			}
		}
	}
	return have, newest
}

// gapReason explains why a sensor has no usable window at end ("" when it has one). Caller holds e.mu.
func (e *Engine) gapReason(k string, end int64) string {
	s := e.series[k]
	have, newest := windowCoverage(s, end, Window)
	fs := e.dq[k]
	switch {
	case fs.inMaintenance(end):
		return "out of service (maintenance" + whyText(fs.maintWhy) + ")"
	case newest == 0:
		if fs != nil && fs.replacedAt != 0 {
			return "sensor replaced: waiting for readings from the new sensor"
		}
		return "no readings"
	case end-newest > 3*bucketSec:
		return fmt.Sprintf("no reading for %d min (sensor or gateway offline)", (end-newest)/60)
	case have < Window-3:
		if fs != nil && fs.replacedAt != 0 && end-fs.replacedAt < int64(Window)*bucketSec {
			return fmt.Sprintf("sensor replaced: %d of %d readings since the swap", have, Window)
		}
		if fs != nil && fs.measured && have > 0 && end-int64(Window-1)*bucketSec < firstBucket(s) {
			return fmt.Sprintf("warming up: %d of %d readings so far", have, Window)
		}
		return fmt.Sprintf("%d of %d readings missing in the 4 h window", Window-have, Window)
	}
	return ""
}

func whyText(w string) string {
	if w == "" {
		return ""
	}
	return ": " + w
}

func firstBucket(s map[int64]float64) int64 {
	first := int64(math.MaxInt64)
	for b := range s {
		if b < first {
			first = b
		}
	}
	return first
}

// GapReasonAt is gapReason outside the engine lock (refinements).
func (e *Engine) GapReasonAt(node, metric string, end int64) string {
	e.mu.RLock()
	defer e.mu.RUnlock()
	return e.gapReason(key(node, metric), end)
}

// setQuality fills a sensor's data-quality fields after detect judged it (caller holds e.mu).
func (e *Engine) setQuality(k string, st *SensorState, ok bool) {
	fs := e.dq[k]
	st.Feed = "held"
	if fs != nil && fs.measured {
		st.Feed = "measured"
	}
	have, _ := windowCoverage(e.series[k], e.sim, Window)
	st.Coverage = math.Round(float64(have)/float64(Window)*1000) / 1000
	st.Quality, st.QualityWhy, st.Ingest, st.MaintUntil = "good", "", nil, 0
	if fs != nil && (fs.measured || fs.stats != (IngestStats{})) {
		cp := fs.stats
		st.Ingest = &cp
	}
	switch {
	case fs.inMaintenance(e.sim):
		st.Quality, st.QualityWhy, st.MaintUntil = "maintenance", "out of service"+whyText(fs.maintWhy), fs.maintUntil
	case !ok:
		why := e.gapReason(k, e.sim)
		st.Quality, st.QualityWhy = "bad", why
		if _, newest := windowCoverage(e.series[k], e.sim, Window); newest == 0 || e.sim-newest > 3*bucketSec {
			st.Quality = "stale"
		}
	case fs != nil && fs.glitchAt != 0 && e.sim-fs.glitchAt < int64(Window)*bucketSec:
		st.Quality, st.QualityWhy = "uncertain", "one-reading glitch at "+timeOf(fs.glitchAt)+" ignored by the alarm gate"
	case have < Window:
		st.Quality, st.QualityWhy = "uncertain", fmt.Sprintf("%d of %d readings in the 4 h window filled in", Window-have, Window)
	case fs != nil && fs.uncertainAt != 0 && e.sim-fs.uncertainAt < int64(Window)*bucketSec:
		st.Quality, st.QualityWhy = "uncertain", "the window holds readings flagged uncertain"
	case e.bank[k] != nil && e.bank[k].Source == "api" && e.bank[k].clamped:
		st.Quality, st.QualityWhy = "uncertain", "the last device value was outside the sensor range and was clamped"
	}
}

func timeOf(b int64) string { return time.Unix(b, 0).In(IST).Format("15:04") }
