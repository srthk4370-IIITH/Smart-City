package main

// Polling engine: every poll samples each live sensor (dashboard sliders or real devices via
// /api/ingest - see sensors.go) as its next 5-minute reading, keeps per-sensor rolling buffers,
// computes live statistics (SMA/EMA/Bollinger/slope + Mode-1 pattern), and gates anomaly events into
// incidents. No recorded data is used.

import (
	"fmt"
	"math"
	"math/rand"
	"sort"
	"sync"
	"time"
)

const bucketSec = 300

type NodeInfo struct {
	Role     string   `json:"role"`
	Metrics  []string `json:"metrics"`
	Location string   `json:"location"`
	Building string   `json:"building"`
	Level    string   `json:"level"`
	Kind     string   `json:"kind"`
}

type ReplayMeta struct {
	Start       int64               `json:"start"`
	End         int64               `json:"end"`
	StartIST    string              `json:"start_ist"`
	EndIST      string              `json:"end_ist"`
	History     int                 `json:"history_points"`
	SourceWeeks map[string]string   `json:"source_week_start_ist"`
	Coverage    map[string]float64  `json:"coverage"`
	Nodes       map[string]NodeInfo `json:"nodes"`
}

type Injection struct {
	ID       string  `json:"id"`
	Scenario string  `json:"scenario"`
	Node     string  `json:"node"`
	Metric   string  `json:"metric"`
	Kind     string  `json:"kind"`
	Start    int64   `json:"start"`
	Dur      int     `json:"duration_buckets"`
	Amp      float64 `json:"amplitude"`
	base     float64
	baseSet  bool // base is the value at injection start (else the first value the injection sees)
	Hold     bool `json:"hold"`
}

type SensorState struct {
	Node             string   `json:"node"`
	Metric           string   `json:"metric"`
	Role             string   `json:"role"`
	Location         string   `json:"location"`
	Unit             string   `json:"unit"`
	Last             *float64 `json:"last"`
	Updated          int64    `json:"updated"`
	Points           int      `json:"points_24h"`
	SMA1h            *float64 `json:"sma_1h"`
	EMA1h            *float64 `json:"ema_1h"`
	SlopePerH        *float64 `json:"slope_per_h"`
	Pattern          string   `json:"pattern"`
	Status           string   `json:"status"`
	Cause            string   `json:"likely_cause"`
	DataOK           bool     `json:"data_ok"`
	Injected         bool     `json:"injected"`
	Finding          *Finding `json:"finding,omitempty"`
	AbnormalFor      int      `json:"abnormal_for"`       // CONSECUTIVE abnormal readings so far (display of the current run; the AI gate uses abnormal_in_window)
	AbnormalInWindow int      `json:"abnormal_in_window"` // abnormal readings among the last persist_readings (the AI is called at abnormal_of_window)
	Reported         bool     `json:"reported"`           // already in an incident during this abnormal episode
	// data quality (dataquality.go): good | uncertain | bad | stale | maintenance, why, real-reading
	// coverage of the 4 h window, held (slider / sample-and-hold) or measured (device feed), ingest counters
	Quality     string       `json:"quality"`
	QualityWhy  string       `json:"quality_reason,omitempty"`
	MaintUntil  int64        `json:"maint_until,omitempty"` // sensor time an out-of-service window ends
	Coverage    float64      `json:"coverage_4h"`
	Feed        string       `json:"feed"`
	Ingest      *IngestStats `json:"ingest,omitempty"`
	normalRun   int          // consecutive normal readings (off-delay)
	prev        string       // pattern at the previous poll
	same        int          // consecutive polls with an abnormal status
	abTimes     []int64      // sensor times of the fresh abnormal readings still inside the gate window (K-of-window gate)
	alerted     bool         // already reported during this abnormal episode
	clearedAt   int64        // sensor time the reported episode returned to normal (0 = still abnormal)
	alertedAt   int64        // sensor time the episode was reported
	reportedSev int          // severity rank that was reported
	riseRun     int          // consecutive fresh readings whose rule status ranks above reportedSev (escalation re-ask)
	critRun     int          // consecutive FRESH readings beyond the critical limit (fast path)
	fastAt      int64        // sensor time a fast-path incident was opened for this episode (0 = none)
	earlyAt     int64        // sensor time a provisional early AI run was requested for this episode (0 = none)
	// snoozed (polish_engine.go), filled in by Snapshot: criticals alarm as usual, everything else is held
	// warming up (hardening): a live sensor with fewer than PersistReadings readings since start / restore - the AI gate
	// cannot open yet; minutes left until it can
	WarmingUp   bool   `json:"warming_up"`
	WarmMinLeft int    `json:"warming_min_left"`
	Snoozed     bool   `json:"snoozed,omitempty"`
	SnoozeUntil int64  `json:"snooze_until,omitempty"`
	SnoozeWhy   string `json:"snooze_reason,omitempty"`
}

type Engine struct {
	mu            sync.RWMutex
	dir           string
	Meta          ReplayMeta
	bank          map[string]*SimSensor // node|metric -> live sensor
	bankOrder     []string
	NoiseScale    float64   // multiplier on each sensor's measurement jitter (0 = exact values)
	ClockMin      int       // sensor time-of-day (minutes after midnight IST) at (re)start; default 09:00
	batchUntil    int64     // sensor time when the open incident batch closes (0 = none)
	batchOpen     int64     // sensor time the open batch started
	batchOpenWall time.Time // wall clock the open batch started (latency tracing only)
	rng           *rand.Rand
	series        map[string]map[int64]float64 // node|metric -> bucket -> value
	sim           int64
	Speed         int // buckets per poll
	PollMs        int
	Playing       bool
	injects       []*Injection
	states        map[string]*SensorState
	cooldown      map[string]int64
	lastIncident  int64
	onEvent       func([]Candidate)
	onTick        func(int64)
	onRise        func([]Candidate) // alerted sensors whose rule status rose above what was reported (promote.go)
	rises         []Candidate
	// epoch names this run of the sensor history: reset() discards every reading and nothing survives
	// a backend restart, so a stored incident's windows can only be re-read in the epoch it was created
	// in (refine.go). shift is how far SetClock has moved sensor time within the epoch.
	epoch int64
	shift int64
	dq    map[string]*feedState // node|metric -> data-quality state (dataquality.go)
	// Live: sensor time is the wall clock (campus API input, campus.go). Every bank sensor is a measured feed, readings
	// fall in their own 5-min bucket by device time, and Tick advances one bucket per real 5 minutes.
	Live bool
	// liveHold: the startup backfill is still loading (Tick waits); liveQuiet: catch-up buckets up to this sensor time
	// are fed without running the event gate, so only the last hour of the backfill can raise alerts (fast first alert
	// for what is abnormal now, no alert flood for events of the night)
	liveHold  bool
	liveQuiet int64
}

// SetLive switches the engine to the wall clock with measured feeds only (no simulated readings, no slider holds).
// backfill > 0: sensor time starts that far back and waits (LiveReady) until the backfill is loaded; Tick then catches
// up bucket by bucket, the event gate armed for the last hour only.
func (e *Engine) SetLive(backfill time.Duration) {
	e.mu.Lock()
	defer e.mu.Unlock()
	e.Live, e.Playing, e.Speed = true, true, 1
	now := nowTime().Unix() / bucketSec * bucketSec
	e.sim = now - int64(backfill.Seconds())/bucketSec*bucketSec
	e.liveHold = backfill > 0
	e.liveQuiet = now - 3600
	e.Meta.Start = e.sim
	e.Meta.StartIST = time.Unix(e.sim, 0).In(IST).Format("Mon 02 Jan 15:04")
	e.injects = nil
	for _, k := range e.bankOrder {
		fs := e.feedOf(k)
		fs.measured = true
		delete(e.series, k)
		fs.note(e.sim, "live campus feed: readings come from the campus API only")
	}
}

// LiveReady ends the startup hold (the backfill is in, or failed).
func (e *Engine) LiveReady() {
	e.mu.Lock()
	e.liveHold = false
	e.mu.Unlock()
}

type Candidate struct {
	Node, Metric, Role string
	Finding            Finding
	Xs                 []float64
	End                int64
	Injected           bool
	// Fast: critical fast path (2026-10-28) - the sensor is beyond its CRITICAL limit for fastReadings fresh
	// readings; the incident opens at once with the rules-only preliminary report, the AI follows at persistReadings
	Fast bool
	// Early: provisional early AI (earlyai.go, profile ai_early_k / ai_early_shapes, default off) - the sensor has been
	// abnormal for ai_early_k readings with a shape the gate-length study cleared; the AI runs on that young window
	// as refine stage "provisional", and the persistReadings run updates the same incident
	Early bool
}

func key(n, m string) string { return n + "|" + m }

func NewEngine(dir string) (*Engine, error) {
	e := &Engine{dir: dir, series: map[string]map[int64]float64{}, bank: map[string]*SimSensor{},
		NoiseScale: 1, ClockMin: 9 * 60, rng: newRNG(), Speed: 1, PollMs: 2000, Playing: true, states: map[string]*SensorState{},
		cooldown: map[string]int64{}}
	sensors, err := loadSensors(dir)
	if err != nil {
		return nil, err
	}
	if agentV2() { // per-unit HVAC agents (D1): agentversion.go
		units, err := loadHVACUnitsV2(dir)
		if err != nil {
			return nil, err
		}
		sensors = append(sensors, units...)
	}
	e.Meta.Nodes = map[string]NodeInfo{}
	for _, sn := range sensors {
		k := key(sn.Node, sn.Metric)
		if e.bank[k] != nil {
			return nil, fmt.Errorf("sensors.json: duplicate %s %s", sn.Node, sn.Metric)
		}
		e.bank[k] = sn
		e.bankOrder = append(e.bankOrder, k)
		info := e.Meta.Nodes[sn.Node]
		info.Role, info.Location, info.Building, info.Level, info.Kind = sn.Role, sn.Location, sn.Building, sn.Level, "live"
		info.Metrics = append(info.Metrics, sn.Metric)
		e.Meta.Nodes[sn.Node] = info
		unit := sn.Unit
		if sn.Metric == "room_temp" {
			unit = "C"
		}
		e.states[k] = &SensorState{Node: sn.Node, Metric: sn.Metric, Role: sn.Role, Location: sn.Location, Unit: unit,
			Pattern: "-", Status: "no_data"}
	}
	e.Meta.History = Window + 12
	if agentV2() {
		e.Meta.History = v2Hist + 12 // a 12 h window (refinement ladder, E9/E10) exists from the start
	}
	e.reset()
	return e, nil
}

// reset restarts the sensor clock at the current wall time and pre-fills one 4-hour window of
// readings at each sensor's current value, so every sensor is analysable from the first poll.
func (e *Engine) reset() {
	if e.Live { // wall-clock engine: a restart keeps the measured history (nothing here was simulated)
		e.lastIncident = 0
		e.batchUntil, e.batchOpen = 0, 0
		e.cooldown = map[string]int64{}
		for _, st := range e.states {
			st.prev, st.same, st.alerted, st.normalRun, st.abTimes = "", 0, false, 0, nil
		}
		return
	}
	e.series = map[string]map[int64]float64{}
	// Each poll is one 5-minute reading, so sensor time runs ~150x faster than wall time at 2 s polls.
	// It starts at ClockMin today (default 09:00) so a demo has a long daytime runway; SetClock moves it.
	start := dayStart(nowTime()) + int64(e.ClockMin)*60
	e.sim = start/bucketSec*bucketSec - int64(e.Meta.History)*bucketSec
	e.Meta.Start = e.sim
	e.Meta.StartIST = time.Unix(e.sim, 0).In(IST).Format("Mon 02 Jan 15:04")
	if e.Live { // wall clock: no simulated history (the campus backfill fills it)
		e.sim = nowTime().Unix() / bucketSec * bucketSec
		e.Meta.Start = e.sim
	} else {
		for i := 0; i < e.Meta.History; i++ {
			e.sim += bucketSec
			e.feed(e.sim)
		}
	}
	e.lastIncident = 0
	e.batchUntil, e.batchOpen = 0, 0
	e.cooldown = map[string]int64{}
	e.epoch, e.shift = time.Now().UnixNano(), 0
	for _, st := range e.states {
		st.prev, st.same, st.alerted, st.normalRun, st.abTimes = "", 0, false, 0, nil
	}
	for _, fs := range e.dq { // a restart discards every reading; device feeds stay measured
		fs.pending, fs.cnt = map[int64]*bucketAcc{}, map[int64]int{}
		fs.maintFrom, fs.maintUntil, fs.replacedAt, fs.glitchAt, fs.uncertainAt = 0, 0, 0, 0, 0
	}
}

func dayStart(t time.Time) int64 {
	y, m, d := t.In(IST).Date()
	return time.Date(y, m, d, 0, 0, 0, 0, IST).Unix()
}

// SetClock moves sensor time to hh:mm today WITHOUT discarding history (all buckets shift together).
func (e *Engine) SetClock(minutes int) {
	e.mu.Lock()
	defer e.mu.Unlock()
	target := (dayStart(nowTime()) + int64(minutes)*60) / bucketSec * bucketSec
	delta := target - e.sim
	if delta == 0 || e.Live { // the live engine runs on the wall clock
		return
	}
	for k, s := range e.series {
		ns := make(map[int64]float64, len(s))
		for b, v := range s {
			ns[b+delta] = v
		}
		e.series[k] = ns
	}
	e.sim += delta
	e.shift += delta
	for k, v := range e.cooldown {
		e.cooldown[k] = v + delta
	}
	if e.lastIncident != 0 {
		e.lastIncident += delta
	}
	if e.batchUntil != 0 {
		e.batchUntil += delta
		e.batchOpen += delta
	}
	for _, in := range e.injects {
		in.Start += delta
	}
	for _, st := range e.states {
		if st.alertedAt != 0 {
			st.alertedAt += delta
		}
	}
	for _, fs := range e.dq {
		np, nc := map[int64]*bucketAcc{}, map[int64]int{}
		for b, a := range fs.pending {
			np[b+delta] = a
		}
		for b, c := range fs.cnt {
			nc[b+delta] = c
		}
		fs.pending, fs.cnt = np, nc
		for _, p := range []*int64{&fs.maintFrom, &fs.maintUntil, &fs.replacedAt, &fs.glitchAt, &fs.uncertainAt} {
			if *p != 0 {
				*p += delta
			}
		}
	}
	e.ClockMin = minutes
}

// feed records one reading per live sensor for bucket b.
func (e *Engine) feed(b int64) {
	for _, k := range e.bankOrder {
		sn := e.bank[k]
		fs := e.dq[k]
		switch {
		case fs != nil && fs.measured: // a device feed: the mean of its readings in b, or no reading
			e.feedMeasured(k, fs, b)
		case fs.inMaintenance(b), heldStale(sn): // out of service, or a silent device: nothing invented
		default:
			v := e.applyInjections(sn.Node, sn.Metric, b, e.reading(sn))
			if e.series[k] == nil {
				e.series[k] = map[int64]float64{}
			}
			e.series[k][b] = v
		}
		for bb := range e.series[k] { // keep 26 h per sensor
			if bb < b-26*3600 {
				delete(e.series[k], bb)
			}
		}
	}
}

func (e *Engine) applyInjections(node, metric string, b int64, v float64) float64 {
	for _, in := range e.injects {
		if in.Node != node || in.Metric != metric || b < in.Start {
			continue
		}
		k := int((b - in.Start) / bucketSec)
		if k >= in.Dur && !in.Hold {
			continue
		}
		if k >= in.Dur {
			k = in.Dur - 1
		}
		if !in.baseSet { // no reading existed at injection start: anchor to the first value seen
			in.base, in.baseSet = v, true
		}
		fr := float64(k) / float64(maxi(1, in.Dur-1))
		switch in.Kind {
		case "exp_rise":
			v = in.base + in.Amp*(math.Exp(4*fr)-1)/(math.Exp(4)-1) + (v-in.base)*0.3
		case "ramp_up": // anchored to the level at injection start so the trend dominates real variation
			v = in.base + in.Amp*fr + (v-in.base)*0.1
		case "ramp_down":
			v = math.Max(0, in.base-in.Amp*fr+(v-in.base)*0.25)
		case "spike":
			if k == in.Dur/2 || k == in.Dur/2+1 {
				v = v + in.Amp
			}
		case "throttle": // climbs to a hard ceiling in the first 30 % of the event, then held flat
			v = in.base + in.Amp*math.Min(1, fr/0.3) + (v-in.base)*0.15
			if fr >= 0.3 {
				v = in.base + in.Amp - math.Abs(math.Sin(float64(b)))*0.003*in.Amp
			}
		case "flatline": // EXACT constant: no jitter, no blending with live readings
			v = in.base
		case "oscillate":
			c := math.Max(in.base, 1.3*in.Amp) // keep the swing above zero so it is not clipped
			v = math.Max(0, c+in.Amp*math.Sin(2*math.Pi*float64(k)/8.0)+(v-in.base)*0.2)
		case "step_up":
			if k >= 2 {
				v = v + in.Amp
			}
		case "set":
			v = in.Amp
		}
		m := Metrics[e.Meta.Nodes[node].Role+"/"+metric]
		if m.Hi > m.Lo {
			v = math.Min(m.Hi, math.Max(m.Lo, v))
		}
	}
	return v
}

func maxi(a, b int) int {
	if a > b {
		return a
	}
	return b
}

// Window returns the last 48 points ending at end (gap rules mirror training/generate_dataset.windows).
func (e *Engine) Window(node, metric string, end int64) ([]float64, bool) {
	return e.window(node, metric, end, false)
}

// window: Window; critical=true is the event gate's critical bypass (owner 2026-10-31, deploy22): when the
// reading AT end is beyond the CRITICAL limit, the coverage rules (at most 3 of 48 missing, both edges present)
// are skipped so a critical value after a sensor silence opens the incident at once instead of after ~40 new
// readings. Missing leading points take the real readings from before the gap, newest first (time-compressed, no
// invented values; the oldest one repeats if history is short), inner gaps interpolated as usual. Non-critical: unchanged.
func (e *Engine) window(node, metric string, end int64, critical bool) ([]float64, bool) {
	s := e.series[key(node, metric)]
	if s == nil {
		return nil, false
	}
	role := e.Meta.Nodes[node].Role
	minHave := Window - 3
	if role == "weather" || role == "occupancy" {
		minHave = 24
	}
	pts := make([]*float64, Window)
	have := 0
	for i := 0; i < Window; i++ {
		if v, ok := s[end-int64(Window-1-i)*bucketSec]; ok {
			vv := v
			pts[i] = &vv
			have++
		}
	}
	// live edge: forward-fill the newest point from up to 3 buckets back (10-min sensors)
	if pts[Window-1] == nil {
		for j := Window - 2; j >= Window-4; j-- {
			if pts[j] != nil {
				vv := *pts[j]
				pts[Window-1] = &vv
				break
			}
		}
	}
	if pts[0] == nil {
		for j := 1; j < 4; j++ {
			if pts[j] != nil {
				vv := *pts[j]
				pts[0] = &vv
				break
			}
		}
	}
	if have < minHave || pts[0] == nil || pts[Window-1] == nil {
		v, fresh := s[end]
		if !critical || !fresh || role == "occupancy" || !valueCriticalNode(role, metric, node, v) {
			return nil, false
		}
		if pts[0] == nil {
			first := 0
			for pts[first] == nil {
				first++
			}
			var older []int64 // real readings before the window, newest first
			for b := range s {
				if b < end-int64(Window-1)*bucketSec {
					older = append(older, b)
				}
			}
			sort.Slice(older, func(i, j int) bool { return older[i] > older[j] })
			fill := *pts[first]
			for i, j := first-1, 0; i >= 0; i, j = i-1, j+1 {
				if j < len(older) {
					fill = s[older[j]]
				}
				vv := fill
				pts[i] = &vv
			}
		}
	}
	xs := make([]float64, Window)
	for i := 0; i < Window; i++ {
		if pts[i] != nil {
			xs[i] = *pts[i]
			continue
		}
		j := i
		for pts[j] == nil {
			j++
		}
		a, b := xs[i-1], *pts[j]
		for k := i; k < j; k++ {
			xs[k] = a + (b-a)*float64(k-i+1)/float64(j-i+1)
		}
		for k := i; k < j; k++ {
			vv := xs[k]
			pts[k] = &vv
		}
	}
	if role == "occupancy" {
		for i := range xs {
			if xs[i] >= 0.5 {
				xs[i] = 1
			} else {
				xs[i] = 0
			}
		}
	}
	return xs, true
}

// WindowAt is Window for callers outside the engine lock (the reasoner's refinements, refine.go).
// end must not be ahead of sensor time: Window forward-fills the newest point.
func (e *Engine) WindowAt(node, metric string, end int64) ([]float64, bool) {
	e.mu.RLock()
	defer e.mu.RUnlock()
	if end > e.sim {
		return nil, false
	}
	return e.Window(node, metric, end)
}

// HistoryAt returns up to n readings ending at end (oldest first) for the 12 h checks: the longest
// stretch back from end whose gaps are at most 3 readings (filled with the next older value).
// nil when end is in the future or the reading at end is missing.
func (e *Engine) HistoryAt(node, metric string, end int64, n int) []float64 {
	e.mu.RLock()
	defer e.mu.RUnlock()
	return e.historyLocked(node, metric, end, n) // engine_v2.go
}

// SimBase is the history epoch, the clock shift within it (see Engine.epoch) and the sensor time.
func (e *Engine) SimBase() (epoch, shift, now int64) {
	e.mu.RLock()
	defer e.mu.RUnlock()
	return e.epoch, e.shift, e.sim
}

// Tick takes Speed new readings from every live sensor (one 5-minute bucket each) and runs detection.
func (e *Engine) Tick() {
	e.mu.Lock()
	if !e.Playing {
		e.mu.Unlock()
		return
	}
	var cands []Candidate
	steps := e.Speed
	if e.Live { // one bucket per real 5 minutes; catch-up after the backfill / a stall: at most 160 buckets per poll
		target := nowTime().Unix() / bucketSec * bucketSec
		steps = int((target - e.sim) / bucketSec)
		if steps > 160 {
			steps = 160
		}
		if steps <= 0 || e.liveHold {
			e.mu.Unlock()
			return
		}
	}
	for i := 0; i < steps; i++ {
		next := e.sim + bucketSec
		e.feed(next)
		e.sim = next
		if e.Live && next <= e.liveQuiet {
			continue // live catch-up older than 1 h: history only, no alerts
		}
		cands = append(cands, e.detect()...) // keep detections from every step (speed > 1)
	}
	// drop finished injections
	keep := e.injects[:0]
	for _, in := range e.injects {
		if in.Hold || e.sim < in.Start+int64(in.Dur+Window)*bucketSec {
			keep = append(keep, in)
		}
	}
	e.injects = keep
	sim := e.sim
	cb, tick := e.onEvent, e.onTick
	rises, rcb := e.rises, e.onRise
	e.rises = nil
	e.mu.Unlock()
	if tick != nil {
		tick(sim)
	}
	if len(rises) > 0 && rcb != nil {
		rcb(rises)
	}
	if len(cands) > 0 && cb != nil {
		cb(cands)
	}
}

// injectionMature: an injection has run long enough (>= 60% of its duration, min 6 buckets) for its
// pattern to be visible in the 4-hour window.
func (e *Engine) injectionMature(node, metric string) bool {
	for _, in := range e.injects {
		if in.Node == node && in.Metric == metric {
			frac := map[string]float64{"throttle": 0.85, "oscillate": 0.85, "ramp_up": 0.95, "ramp_down": 0.95}[in.Kind]
			if frac == 0 {
				frac = 0.6
			}
			need := int64(maxi(6, int(float64(in.Dur)*frac))) * bucketSec
			return e.sim-in.Start >= need
		}
	}
	return true
}

func (e *Engine) injectedSensor(node, metric string) bool {
	for _, in := range e.injects {
		if in.Node == node && in.Metric == metric {
			return true
		}
	}
	return false
}

// steady patterns never open an incident on their own (status still can)
var steadyPatterns = map[string]bool{"stable": true, "vacant": true, "occupied": true, "context": true, "-": true}

var interestingPatterns = map[string]bool{"spike": true, "dip": true, "step_increase": true, "step_decrease": true,
	"exponential_increase": true, "throttling": true, "erratic": true, "off_hours_presence": true}

func sevRank(s string) int {
	switch s {
	case "critical":
		return 3
	case "sensor_fault":
		return 2
	case "warning":
		return 1
	}
	return 0
}

// detect updates live state for every sensor and returns gated candidates (caller holds lock).
func (e *Engine) detect() []Candidate {
	abnormal := map[string]Candidate{}
	var fast []Candidate
	ek, eshapes := earlyAIConfig()
	tr := trigRules()
	for k, st := range e.states {
		s := e.series[k]
		var lastB int64 = -1
		for b := range s {
			if b > lastB {
				lastB = b
			}
		}
		if lastB >= 0 {
			v := s[lastB]
			st.Last, st.Updated = &v, lastB
			n := 0
			for b := range s {
				if b > e.sim-86400 {
					n++
				}
			}
			st.Points = n
		}
		st.Injected = e.injectedSensor(st.Node, st.Metric)
		var xs []float64
		var f Finding
		bypass := false // critical reading through a coverage gap (deploy22): fast path only
		if hvacAgentSensor(st.Role, st.Node, st.Metric) {
			// v2 per-unit HVAC: the HVAC teacher rule on the 4 h window gates events like any other sensor
			var ok bool
			xs, f, ok = e.hvacUnitFinding(st.Node, e.sim)
			st.DataOK = ok
			if !ok {
				st.Pattern, st.Status, st.Cause, st.Finding = "-", "insufficient_data", "", nil
				st.SMA1h, st.EMA1h, st.SlopePerH = nil, nil, nil
				st.same, st.AbnormalFor, st.normalRun, st.abTimes, st.AbnormalInWindow = 0, 0, 0, nil, 0
				e.setQuality(k, st, false)
				continue
			}
			sm, em := sma(xs, 12), ema(xs, 12)
			_, b, _ := linfit(xs)
			sl := b * 12
			st.SMA1h, st.EMA1h, st.SlopePerH = &sm, &em, &sl
		} else if st.Role == "hvac" {
			// context only (no agent): live value + 1 h moving averages over the last 12 buckets
			var w []float64
			for i := 11; i >= 0; i-- {
				if v, ok := s[e.sim-int64(i)*bucketSec]; ok {
					w = append(w, v)
				}
			}
			if len(w) >= 6 {
				sm, em := mean(w), ema(w, 12)
				_, b, _ := linfit(w)
				sl := b * 12
				st.SMA1h, st.EMA1h, st.SlopePerH = &sm, &em, &sl
				st.Status, st.Pattern, st.DataOK = "normal", "context", true
			} else {
				st.Status, st.Pattern, st.DataOK = "insufficient_data", "-", false
			}
			e.setQuality(k, st, st.DataOK)
			continue
		} else {
			var ok bool
			xs, ok = e.Window(st.Node, st.Metric, e.sim)
			if !ok { // critical readings skip the coverage gate (deploy22)
				xs, ok = e.window(st.Node, st.Metric, e.sim, true)
				bypass = ok
			}
			st.DataOK = ok
			if !ok {
				// not enough real readings (gap, offline, warming up, replaced): no AI, a reason instead
				st.Pattern, st.Status, st.Cause, st.Finding = "-", "insufficient_data", "", nil
				st.SMA1h, st.EMA1h, st.SlopePerH = nil, nil, nil
				st.same, st.AbnormalFor, st.normalRun, st.abTimes, st.AbnormalInWindow = 0, 0, 0, nil, 0
				e.setQuality(k, st, false)
				continue
			}
			if st.Role != "occupancy" {
				sm, em := sma(xs, 12), ema(xs, 12)
				_, b, _ := linfit(xs)
				sl := b * 12
				st.SMA1h, st.EMA1h, st.SlopePerH = &sm, &em, &sl
			}
			f = RuleFinding(st.Role, st.Metric, st.Node, xs, e.sim)
			if bypass && f.Pattern == "flatline" {
				// the flat run is the gap fill (history shorter than the window), not a stuck sensor: judge the
				// real critical level as a stable shape
				f = ruleFindingAs("stable", st.Role, st.Metric, st.Node, xs, e.sim)
			}
		}
		if sevRank(f.Status) > 0 && !hvacAgentSensor(st.Role, st.Node, st.Metric) {
			// one isolated single-reading glitch must not raise an alarm on its own (gate only: a candidate
			// still carries the raw window, the AI never sees modified data)
			if ys, at := glitchFree(st.Role, st.Metric, xs); ys != nil {
				if g := RuleFinding(st.Role, st.Metric, st.Node, ys, e.sim); sevRank(g.Status) == 0 {
					f = g
					e.feedOf(k).glitchAt = e.sim - int64(len(xs)-1-at)*bucketSec
				}
			}
		}
		st.prev = f.Pattern
		st.Pattern, st.Status, st.Cause, st.Finding = f.Pattern, f.Status, f.LikelyCause, &f
		e.setQuality(k, st, true)
		if e.dq[k].inMaintenance(e.sim) { // out of service: shown, never alarmed
			st.same, st.AbnormalFor, st.normalRun, st.abTimes, st.AbnormalInWindow = 0, 0, 0, nil, 0
			continue
		}
		if e.dq[k].snoozedAt(e.sim) && f.Status != "critical" { // snoozed: only a critical may still open an incident
			st.same, st.AbnormalFor, st.normalRun, st.critRun, st.abTimes, st.AbnormalInWindow = 0, 0, 0, 0, nil, 0
			continue
		}
		// Only an abnormal STATUS (warning, critical, faulty/stuck sensor) may call the AI. A shape change at
		// normal levels - including a value returning to normal - is shown on the dashboard but never costs
		// an NPU call, so a board at rest makes no LLM calls at all.
		if sevRank(f.Status) == 0 {
			st.critRun = 0
			st.normalRun++
			// ISA-18.2 deadband + off-delay: a reading back to normal but still within the deadband of the
			// limit neither restarts the on-delay count nor ends a reported episode until it has repeated
			// offDelayReadings times (a value hovering at the limit is one episode, not a flood of incidents,
			// and a chattering one still alerts).
			near := nearLimitNode(st.Role, st.Metric, st.Node, xs[len(xs)-1]) && st.normalRun < offDelayReadings
			if near && (st.same > 0 || (st.alerted && st.clearedAt == 0)) {
				continue
			}
			st.same = 0
			st.AbnormalFor = 0
			st.AbnormalInWindow = st.winCount(e.sim, tr.PersistReadings) // normal reading: the window keeps its earlier abnormal ones until they age out
			if st.fastAt != 0 && e.sim-st.fastAt >= int64(tr.FastCooldown)*bucketSec {
				st.fastAt = 0 // episode over and cooled down: a new critical episode may open a fast incident again
			}
			if st.earlyAt != 0 && e.sim-st.earlyAt >= int64(tr.FastCooldown)*bucketSec {
				st.earlyAt = 0
			}
			if st.alerted && st.clearedAt == 0 {
				st.clearedAt = e.sim // episode over; its readings stay in the 4 h window for a while
			}
			continue
		}
		st.normalRun = 0
		if _, fresh := s[e.sim]; !fresh {
			// no new reading this bucket (live edge forward-filled): the window did not change, so it is
			// not another abnormal reading for the on-delay
			st.AbnormalInWindow = st.winCount(e.sim, tr.PersistReadings)
			if st.AbnormalInWindow > 0 && !st.alerted {
				abnormal[k] = Candidate{st.Node, st.Metric, st.Role, f, xs, e.sim, st.Injected, false, false}
			}
			continue
		}
		if st.alerted && !hvacAgentSensor(st.Role, st.Node, st.Metric) && newTransient(f.Pattern, xs, e.sim, st.alertedAt) {
			// A short spike/dip that began AFTER this sensor was reported is a new event, even while the
			// reported episode is still abnormal or has only just cleared. Without this a load surge on a meter
			// whose throttling episode was reported (and is still in the 4 h window) was absorbed into the old
			// episode and never alerted; power has no thresholds, so valueAbnormal cannot re-arm it either.
			st.alerted, st.Reported, st.clearedAt, st.same, st.abTimes = false, false, 0, 0, nil
		}
		if st.alerted && st.clearedAt != 0 {
			// Same sensor abnormal again after a reported episode. The 4-hour window still contains the old
			// anomaly, so the rules keep flagging its shape (a reset looks like a spike/dip). Re-arm only for a
			// genuinely new event: the CURRENT value is beyond a threshold again, or the old readings have
			// left the window.
			if valueAbnormalNode(st.Role, st.Metric, st.Node, xs[len(xs)-1]) || e.sim-st.clearedAt >= int64(Window)*bucketSec {
				st.alerted, st.Reported, st.clearedAt, st.same, st.abTimes = false, false, 0, 0, nil
			} else {
				continue
			}
		}
		if bypass {
			// the gap-filled window only opens the fast incident; the AI and the batch gate wait for real coverage
			// (a filled window reads as a stuck sensor to the reasoner, board INC-0583)
			st.critRun++
			if !st.alerted && st.fastAt == 0 && st.critRun >= tr.FastReadings {
				st.fastAt = e.sim
				fast = append(fast, Candidate{st.Node, st.Metric, st.Role, f, xs, e.sim, st.Injected, true, false})
			}
			continue
		}
		st.same++
		// K-of-window counts READINGS beyond the threshold: after a one-reading spike/dip the window shape keeps the rule
		// abnormal for many readings while the value is back to normal; those must not count (2026-11-20, one 2999 ppm
		// glitch reached the AI). Trend / stuck / erratic findings count as before.
		if !((f.Pattern == "spike" || f.Pattern == "dip") && len(xs) > 0 && hasLimits(st.Role, st.Metric, st.Node) &&
			!valueAbnormalNode(st.Role, st.Metric, st.Node, xs[len(xs)-1])) {
			st.abTimes = append(st.abTimes, e.sim)
		}
		st.AbnormalInWindow = st.winCount(e.sim, tr.PersistReadings)
		inWin := st.AbnormalInWindow
		st.AbnormalFor, st.Reported = st.same, st.alerted
		abnormal[k] = Candidate{st.Node, st.Metric, st.Role, f, xs, e.sim, st.Injected, false, false}
		if st.alerted && sevRank(f.Status) > st.reportedSev {
			// escalation: a reported sensor whose rule status rose; 2 fresh readings in a row, once per level
			if st.riseRun++; st.riseRun >= promoDebounce {
				st.riseRun, st.reportedSev = 0, sevRank(f.Status)
				e.rises = append(e.rises, abnormal[k])
			}
		} else {
			st.riseRun = 0
		}
		if valueCriticalNode(st.Role, st.Metric, st.Node, xs[len(xs)-1]) {
			st.critRun++
		} else {
			st.critRun = 0
		}
		if !st.alerted && st.fastAt == 0 && st.critRun >= tr.FastReadings && inWin < tr.AbnormalOfWindow {
			st.fastAt = e.sim
			fast = append(fast, Candidate{st.Node, st.Metric, st.Role, f, xs, e.sim, st.Injected, true, false})
		}
		if ek > 0 && !st.alerted && st.earlyAt == 0 && inWin >= ek && inWin < tr.AbnormalOfWindow && earlyShapeOK(f, eshapes) {
			st.earlyAt = e.sim
			fast = append(fast, Candidate{st.Node, st.Metric, st.Role, f, xs, e.sim, st.Injected, false, true})
		}
	}
	return append(e.batchEvents(abnormal), fast...)
}

// valueCritical: is the latest reading beyond the metric's CRITICAL limit (StatusOf's limit branch: pH below 6.0
// or at/above 9.0, "low" metrics below Crit, "high" at/above Crit)? Metrics without limits (power_kw, level, flow)
// never qualify, so they have no fast path.
func valueCritical(role, metric string, last float64) bool {
	return valueCriticalNode(role, metric, "", last)
}

// valueCriticalNode: valueCritical against the thresholds of this sensor (its card, rules_config.go).
func valueCriticalNode(role, metric, node string, last float64) bool {
	m, ok := effectiveMetricOK(role, metric, node)
	return ok && valueCriticalM(m, last)
}

func valueCriticalM(m Metric, last float64) bool {
	if !m.HasLimits {
		return false
	}
	if m.HasLoSide && last < m.CritLo {
		return true
	}
	switch m.Dir {
	case "high", "both":
		return last >= m.Crit
	case "low":
		return last < m.Crit
	}
	return false
}

// The values below are the DEFAULTS of TriggerRules (rules_config.go); the engine reads trigRules() every tick.
const (
	// The domain agents were trained on events that had lasted >= 7 readings; younger windows get misread
	// (a fresh step called a spike), so the AI waits for 8 abnormal readings. Rule status still shows at once.
	persistReadings = 8
	// After the first sensor is ready, wait this many more readings so sensors that turned abnormal at
	// about the same time (e.g. air AND water) land in the SAME incident and the same batch of NPU calls.
	batchReadings = 3
	// ...but never hold an alert longer than this many readings after the batch opened
	batchMaxReadings = 10
	// critical fast path: this many consecutive fresh readings beyond the CRITICAL limit open the incident at once
	// (rules-only preliminary report); the AI still runs at persistReadings and updates that same incident
	fastReadings = 2
	// a sensor opens at most one fast incident per episode, and a new one only this long after the last
	fastCooldown = 12
)

// valueAbnormal: is the latest reading itself beyond the metric's warning threshold?
func valueAbnormal(role, metric string, last float64) bool {
	return valueAbnormalNode(role, metric, "", last)
}

// valueAbnormalNode: valueAbnormal against the thresholds of this sensor (its card, rules_config.go).
func valueAbnormalNode(role, metric, node string, last float64) bool {
	m, ok := effectiveMetricOK(role, metric, node)
	return ok && valueAbnormalM(m, last)
}

// hasLimits: the sensor's card has fixed warning/critical limits (power and similar metrics are judged on shape).
func hasLimits(role, metric, node string) bool {
	m, ok := effectiveMetricOK(role, metric, node)
	return ok && (m.Warn != 0 || m.Crit != 0)
}

func valueAbnormalM(m Metric, last float64) bool {
	if m.Warn == 0 && m.Crit == 0 {
		return false
	}
	switch m.Dir {
	case "high":
		return last >= m.Warn
	case "low":
		return last <= m.Warn
	}
	return false
}

// transientMax: default of TriggerRules.TransientMax - a spike/dip at most this many readings wide (beyond half its
// height) is a transient.
const transientMax = 3

// newTransient: the rules call the window a spike (dip) and that excursion is short - at most transientMax
// readings above (below) half its height - and began inside the window after sensor time since. A hold that is released
// (e.g. CO2 back down after a ventilation failure) is wider than that, so it does not count.
func newTransient(pattern string, xs []float64, end, since int64) bool {
	if (pattern != "spike" && pattern != "dip") || len(xs) == 0 {
		return false
	}
	srt := append([]float64(nil), xs...)
	sortFloats(srt)
	med, lo, hi := srt[len(srt)/2], srt[0], srt[len(srt)-1]
	first, n := -1, 0
	for i, v := range xs {
		if (pattern == "spike" && v > med+(hi-med)/2) || (pattern == "dip" && v < med-(med-lo)/2) {
			if first < 0 {
				first = i
			}
			n++
		}
	}
	// first > 0: the excursion has baseline readings before it. An old event sliding out of the window
	// leaves its tail at index 0, which the rules can read as a narrow dip/spike - that is not a new event.
	return first > 0 && n <= trigRules().TransientMax && end-int64(len(xs)-1-first)*bucketSec > since
}

// batchEvents turns the currently abnormal sensors into at most one incident batch (caller holds lock).
// The batch opens when the first sensor has persistReadings abnormal readings, then stays open (at least
// batchReadings, at most batchMaxReadings readings) until EVERY alarming sensor in it has persistReadings
// readings too - so all sensors are judged on mature windows and still land in ONE incident.
// Every sensor alerts once per episode; it re-arms only after its status returns to normal.
func (e *Engine) batchEvents(abnormal map[string]Candidate) []Candidate {
	tr := trigRules()
	if e.batchUntil == 0 {
		for k := range abnormal {
			if st := e.states[k]; !st.alerted && st.AbnormalInWindow >= tr.AbnormalOfWindow {
				e.batchOpen = e.sim
				e.batchUntil = e.sim + int64(tr.BatchReadings)*bucketSec
				e.batchOpenWall = time.Now()
				trace("gate: batch opened by %s", k)
				break
			}
		}
	}
	if e.batchUntil == 0 {
		return nil
	}
	if e.sim < e.batchUntil {
		// The window exists so co-occurring sensors land in ONE incident (Mode 3's cross-domain
		// case). It used to run its full batchReadings unconditionally, which on an isolated event
		// was ~6 s (3 readings at the 2 s poll) of waiting for nobody - measured as the largest
		// non-model delay in the whole pipeline (HANDBOOK 2.29). Close it early only when that is
		// provably safe: at least one reading has passed AND no other sensor is abnormal at all. If
		// anything else is abnormal, even far from maturity, keep the full window as before.
		if e.sim < e.batchOpen+bucketSec || anyOtherAbnormal(e, abnormal) {
			return nil
		}
	}
	if e.sim < e.batchOpen+int64(tr.BatchMaxReadings)*bucketSec {
		for k := range abnormal {
			if st := e.states[k]; !st.alerted && st.AbnormalInWindow < tr.AbnormalOfWindow {
				return nil // a late sensor is still too young: keep the batch open a little longer
			}
		}
	}
	trace("gate: batch closed after %v wall (%d readings)", time.Since(e.batchOpenWall).Round(time.Millisecond), (e.sim-e.batchOpen)/bucketSec)
	e.batchUntil, e.batchOpen = 0, 0
	var out []Candidate
	for k, c := range abnormal {
		if st := e.states[k]; !st.alerted {
			st.alerted, st.Reported, st.clearedAt, st.alertedAt = true, true, 0, e.sim
			st.reportedSev = sevRank(c.Finding.Status)
			out = append(out, c)
		}
	}
	sort.Slice(out, func(i, j int) bool {
		if a, b := sevRank(out[i].Finding.Status), sevRank(out[j].Finding.Status); a != b {
			return a > b
		}
		return out[i].Node+out[i].Metric < out[j].Node+out[j].Metric
	})
	return out
}

func (e *Engine) Inject(sc Scenario) []*Injection {
	e.mu.Lock()
	defer e.mu.Unlock()
	var out []*Injection
	for i, t := range sc.Targets {
		base, baseSet := 0.0, false
		if st := e.states[key(t.Node, t.Metric)]; st != nil && st.Last != nil {
			base, baseSet = *st.Last, true
		}
		// a new held scenario on a sensor supersedes an older injection there: stacked held injections masked
		// the new pattern (chaos run 2026-10-27: ventilation_failure on the CO2 node still held by crowded_room
		// read as a flatline, and no ventilation incident opened). It starts from the current value. Transient
		// patterns (spikes) still stack, e.g. a load surge on a held throttle (TestLoadSurgeOnReportedThrottle).
		if t.Hold {
			kept := make([]*Injection, 0, len(e.injects)+1)
			for _, old := range e.injects {
				if old.Node != t.Node || old.Metric != t.Metric {
					kept = append(kept, old)
				}
			}
			e.injects = kept
		}
		in := &Injection{ID: fmt.Sprintf("%s-%d-%d", sc.ID, time.Now().Unix(), i), Scenario: sc.ID, Node: t.Node, Metric: t.Metric,
			Kind: t.Kind, Start: e.sim + bucketSec, Dur: t.Dur, Amp: t.Amp, base: base, baseSet: baseSet, Hold: t.Hold}
		e.injects = append(e.injects, in)
		delete(e.cooldown, key(t.Node, t.Metric))
		out = append(out, in)
	}
	e.lastIncident = 0
	return out
}

// PickTargets resolves each scenario target to a live sensor: the primary, then its Alt nodes, then ANY live sensor
// of the same role+metric that is not already injected or picked in this call. Live = clean window (data available,
// not flatline/erratic) and not flat-zero (occ excepted). If nothing qualifies the target is kept as is.
func (e *Engine) PickTargets(ts []Target) []Target {
	e.mu.RLock()
	defer e.mu.RUnlock()
	out := make([]Target, len(ts))
	picked := map[string]bool{}
	live := func(n, metric string) bool {
		st := e.states[key(n, metric)]
		if st == nil || !st.DataOK || st.Pattern == "flatline" || st.Pattern == "erratic" {
			return false
		}
		return metric == "occ" || st.Last == nil || *st.Last != 0
	}
	for i, t := range ts {
		out[i] = t
		cands := append([]string{t.Node}, t.Alt...)
		found := ""
		for _, n := range cands {
			if live(n, t.Metric) && !picked[key(n, t.Metric)] {
				found = n
				break
			}
		}
		if found == "" {
			role := ""
			for _, n := range cands {
				if info, ok := e.Meta.Nodes[n]; ok && info.Role != "" {
					role = info.Role
					break
				}
			}
			for _, k := range e.bankOrder {
				sn := e.bank[k]
				if sn.Metric != t.Metric || (role != "" && sn.Role != role) || picked[k] {
					continue
				}
				if live(sn.Node, t.Metric) && !e.injectedSensor(sn.Node, t.Metric) {
					found = sn.Node
					break
				}
			}
		}
		if found != "" {
			out[i].Node = found
		}
		picked[key(out[i].Node, t.Metric)] = true
	}
	return out
}

func (e *Engine) ClearInjections() {
	e.mu.Lock()
	e.injects = nil
	e.mu.Unlock()
}

func (e *Engine) Snapshot() (int64, []SensorState, []*Injection) {
	e.mu.RLock()
	defer e.mu.RUnlock()
	out := make([]SensorState, 0, len(e.states))
	for k, s := range e.states {
		c := *s
		if fs := e.dq[k]; fs.snoozedAt(e.sim) {
			c.Snoozed, c.SnoozeUntil, c.SnoozeWhy = true, fs.snoozeUntil, fs.snoozeWhy
		}
		c.WarmingUp, c.WarmMinLeft = e.warmingLocked(k)
		out = append(out, c)
	}
	sort.Slice(out, func(i, j int) bool { return out[i].Node+out[i].Metric < out[j].Node+out[j].Metric })
	inj := append([]*Injection(nil), e.injects...)
	return e.sim, out, inj
}

type SeriesOut struct {
	Node   string         `json:"node"`
	Metric string         `json:"metric"`
	Role   string         `json:"role"`
	Unit   string         `json:"unit"`
	Points [][2]float64   `json:"points"`
	SMA    [][2]float64   `json:"sma_1h"`
	EMA    [][2]float64   `json:"ema_1h"`
	Upper  [][2]float64   `json:"bollinger_upper"`
	Lower  [][2]float64   `json:"bollinger_lower"`
	Limits map[string]any `json:"limits"`
	Window *AgentPreview  `json:"window,omitempty"`
}

type AgentPreview struct {
	Pattern  string     `json:"pattern"`
	Finding  Finding    `json:"rule_finding"`
	Evidence []Evidence `json:"evidence"`
	Prompt   string     `json:"prompt"`
}

func (e *Engine) Series(node, metric string, hours int) SeriesOut {
	e.mu.RLock()
	defer e.mu.RUnlock()
	info := e.Meta.Nodes[node]
	out := SeriesOut{Node: node, Metric: metric, Role: info.Role}
	if m, ok := Metrics[info.Role+"/"+metric]; ok {
		out.Unit = m.Unit
		if m.HasLimits {
			out.Limits = map[string]any{"warn": m.Warn, "crit": m.Crit, "dir": m.Dir}
		}
	}
	s := e.series[key(node, metric)]
	var bs []int64
	for b := range s {
		if b > e.sim-int64(hours)*3600 && b <= e.sim {
			bs = append(bs, b)
		}
	}
	sort.Slice(bs, func(i, j int) bool { return bs[i] < bs[j] })
	var vals []float64
	emaV := 0.0
	for i, b := range bs {
		v := s[b]
		vals = append(vals, v)
		out.Points = append(out.Points, [2]float64{float64(b), v})
		if i == 0 {
			emaV = v
		} else {
			emaV = (2.0/13)*v + (1-2.0/13)*emaV
		}
		out.EMA = append(out.EMA, [2]float64{float64(b), emaV})
		if len(vals) >= 12 {
			w := vals[len(vals)-12:]
			m, sd := mean(w), stdev(w)
			out.SMA = append(out.SMA, [2]float64{float64(b), m})
			out.Upper = append(out.Upper, [2]float64{float64(b), m + 2*sd})
			out.Lower = append(out.Lower, [2]float64{float64(b), m - 2*sd})
		}
	}
	if hvacAgentSensor(info.Role, node, metric) {
		if xs, c, hist, ok := e.hvacWindowLocked(node, e.sim, Window); ok {
			ai := BuildHVACPromptV2(node, info.Location, xs, c, hist)
			f := HVACRuleFinding(xs, c)
			out.Window = &AgentPreview{Pattern: f.Pattern, Finding: f, Evidence: ai.Evidence, Prompt: ai.Prompt}
		}
	} else if info.Role != "hvac" {
		if xs, ok := e.Window(node, metric, e.sim); ok {
			ai := BuildAgentPrompt(info.Role, node, info.Location, metric, xs, e.sim)
			if agentV2() { // the prompt the v2 agent would get for the 4 h alert window
				if hist := e.historyLocked(node, metric, e.sim, v2Hist); len(hist) >= Window {
					ai = BuildAgentPromptV2(info.Role, node, info.Location, metric, hist[len(hist)-Window:], e.sim, hist).AgentInput
				}
			}
			out.Window = &AgentPreview{Pattern: RulePattern(info.Role, metric, xs, e.sim), Finding: RuleFinding(info.Role, metric, node, xs, e.sim),
				Evidence: ai.Evidence, Prompt: ai.Prompt}
		}
	}
	return out
}

// anyOtherAbnormal reports whether some abnormal sensor has not yet reached persistReadings - i.e.
// there is a plausible late joiner the batch window should wait for. Mature, already-qualifying
// sensors are exactly the ones the batch will report, so they are not a reason to keep waiting.
func anyOtherAbnormal(e *Engine, abnormal map[string]Candidate) bool {
	pr := trigRules().AbnormalOfWindow
	for k := range abnormal {
		if st := e.states[k]; st != nil && !st.alerted && st.AbnormalInWindow < pr {
			return true
		}
	}
	return false
}

// winCount: abnormal readings among the last w readings (buckets) ending at sim, from the fresh abnormal ones kept in
// abTimes; a missing reading is never in the list, so it counts as not abnormal. Old entries are dropped.
func (st *SensorState) winCount(sim int64, w int) int {
	from := sim - int64(w-1)*bucketSec
	j := 0
	for _, t := range st.abTimes {
		if t >= from && t <= sim {
			st.abTimes[j] = t
			j++
		}
	}
	st.abTimes = st.abTimes[:j]
	return j
}

// SparseWindowAt: the AI window of a slow-cadence sensor (an hourly pH probe has 4 real readings in 4 h, never the 45
// the grid window needs). Built only from the real readings up to end, newest 48 at most, oldest first, time-compressed;
// a short history is front-padded with its oldest real reading (as window's critical bypass does). Needs at least 4
// real readings with the newest at most 3 cadences old. Nothing is invented. ok=false with a reason otherwise.
func (e *Engine) SparseWindowAt(node, metric string, end int64) ([]float64, string, bool) {
	cad := e.cadenceSec(node, metric)
	e.mu.RLock()
	defer e.mu.RUnlock()
	s := e.series[key(node, metric)]
	var ts []int64
	for b := range s {
		if b <= end && b <= e.sim {
			ts = append(ts, b)
		}
	}
	if len(ts) == 0 {
		return nil, "the sensor has no readings yet", false
	}
	sort.Slice(ts, func(i, j int) bool { return ts[i] > ts[j] })
	if end-ts[0] > 3*cad {
		return nil, fmt.Sprintf("the newest reading is %d min old", (end-ts[0])/60), false
	}
	if len(ts) < 4 {
		return nil, fmt.Sprintf("only %d real reading(s) exist (at least 4 needed)", len(ts)), false
	}
	if len(ts) > Window {
		ts = ts[:Window]
	}
	xs := make([]float64, Window)
	for i := 0; i < Window; i++ {
		j := i // i-th from the newest
		if j >= len(ts) {
			j = len(ts) - 1
		}
		xs[Window-1-i] = s[ts[j]]
	}
	return xs, "", true
}
