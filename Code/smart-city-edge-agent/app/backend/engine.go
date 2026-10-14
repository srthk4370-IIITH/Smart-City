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
	Hold     bool `json:"hold"`
}

type SensorState struct {
	Node        string   `json:"node"`
	Metric      string   `json:"metric"`
	Role        string   `json:"role"`
	Location    string   `json:"location"`
	Unit        string   `json:"unit"`
	Last        *float64 `json:"last"`
	Updated     int64    `json:"updated"`
	Points      int      `json:"points_24h"`
	SMA1h       *float64 `json:"sma_1h"`
	EMA1h       *float64 `json:"ema_1h"`
	SlopePerH   *float64 `json:"slope_per_h"`
	Pattern     string   `json:"pattern"`
	Status      string   `json:"status"`
	Cause       string   `json:"likely_cause"`
	DataOK      bool     `json:"data_ok"`
	Injected    bool     `json:"injected"`
	Finding     *Finding `json:"finding,omitempty"`
	AbnormalFor int      `json:"abnormal_for"` // consecutive abnormal readings (AI is called at persistReadings)
	Reported    bool     `json:"reported"`     // already in an incident during this abnormal episode
	prev        string   // pattern at the previous poll
	same        int      // consecutive polls with an abnormal status
	alerted     bool     // already reported during this abnormal episode
	clearedAt   int64    // sensor time the reported episode returned to normal (0 = still abnormal)
	reportedSev int      // severity rank that was reported
}

type Engine struct {
	mu           sync.RWMutex
	dir          string
	Meta         ReplayMeta
	bank         map[string]*SimSensor // node|metric -> live sensor
	bankOrder    []string
	NoiseScale   float64 // multiplier on each sensor's measurement jitter (0 = exact values)
	ClockMin     int     // sensor time-of-day (minutes after midnight IST) at (re)start; default 09:00
	batchUntil   int64   // sensor time when the open incident batch closes (0 = none)
	batchOpen    int64   // sensor time the open batch started
	batchOpenWall time.Time // wall clock the open batch started (latency tracing only)
	rng          *rand.Rand
	series       map[string]map[int64]float64 // node|metric -> bucket -> value
	sim          int64
	Speed        int // buckets per poll
	PollMs       int
	Playing      bool
	injects      []*Injection
	states       map[string]*SensorState
	cooldown     map[string]int64
	lastIncident int64
	onEvent      func([]Candidate)
	onTick       func(int64)
}

type Candidate struct {
	Node, Metric, Role string
	Finding            Finding
	Xs                 []float64
	End                int64
	Injected           bool
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
	e.reset()
	return e, nil
}

// reset restarts the sensor clock at the current wall time and pre-fills one 4-hour window of
// readings at each sensor's current value, so every sensor is analysable from the first poll.
func (e *Engine) reset() {
	e.series = map[string]map[int64]float64{}
	// Each poll is one 5-minute reading, so sensor time runs ~150x faster than wall time at 2 s polls.
	// It starts at ClockMin today (default 09:00) so a demo has a long daytime runway; SetClock moves it.
	start := dayStart(nowTime()) + int64(e.ClockMin)*60
	e.sim = start/bucketSec*bucketSec - int64(e.Meta.History)*bucketSec
	e.Meta.Start = e.sim
	e.Meta.StartIST = time.Unix(e.sim, 0).In(IST).Format("Mon 02 Jan 15:04")
	for i := 0; i < e.Meta.History; i++ {
		e.sim += bucketSec
		e.feed(e.sim)
	}
	e.lastIncident = 0
	e.batchUntil, e.batchOpen = 0, 0
	e.cooldown = map[string]int64{}
	for _, st := range e.states {
		st.prev, st.same, st.alerted = "", 0, false
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
	if delta == 0 {
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
	e.ClockMin = minutes
}

// feed records one reading per live sensor for bucket b.
func (e *Engine) feed(b int64) {
	for _, k := range e.bankOrder {
		sn := e.bank[k]
		v := e.applyInjections(sn.Node, sn.Metric, b, e.reading(sn))
		if e.series[k] == nil {
			e.series[k] = map[int64]float64{}
		}
		e.series[k][b] = v
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
		case "flatline":
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
		return nil, false
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

// Tick takes Speed new readings from every live sensor (one 5-minute bucket each) and runs detection.
func (e *Engine) Tick() {
	e.mu.Lock()
	if !e.Playing {
		e.mu.Unlock()
		return
	}
	var cands []Candidate
	for i := 0; i < e.Speed; i++ {
		next := e.sim + bucketSec
		e.feed(next)
		e.sim = next
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
	e.mu.Unlock()
	if tick != nil {
		tick(sim)
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
		if st.Role == "hvac" {
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
			continue
		}
		xs, ok := e.Window(st.Node, st.Metric, e.sim)
		st.DataOK = ok
		if !ok {
			st.Pattern, st.Status, st.Cause, st.Finding = "-", "insufficient_data", "", nil
			st.SMA1h, st.EMA1h, st.SlopePerH = nil, nil, nil
			continue
		}
		if st.Role != "occupancy" {
			sm, em := sma(xs, 12), ema(xs, 12)
			_, b, _ := linfit(xs)
			sl := b * 12
			st.SMA1h, st.EMA1h, st.SlopePerH = &sm, &em, &sl
		}
		f := RuleFinding(st.Role, st.Metric, st.Node, xs, e.sim)
		st.prev = f.Pattern
		st.Pattern, st.Status, st.Cause, st.Finding = f.Pattern, f.Status, f.LikelyCause, &f
		// Only an abnormal STATUS (warning, critical, faulty/stuck sensor) may call the AI. A shape change at
		// normal levels - including a value returning to normal - is shown on the dashboard but never costs
		// an NPU call, so a board at rest makes no LLM calls at all.
		if sevRank(f.Status) == 0 {
			st.same = 0
			st.AbnormalFor = 0
			if st.alerted && st.clearedAt == 0 {
				st.clearedAt = e.sim // episode over; its readings stay in the 4 h window for a while
			}
			continue
		}
		if st.alerted && st.clearedAt != 0 {
			// Same sensor abnormal again after a reported episode. The 4-hour window still contains the old
			// anomaly, so the rules keep flagging its shape (a reset looks like a spike/dip). Re-arm only for a
			// genuinely new event: the CURRENT value is beyond a threshold again, or the old readings have
			// left the window.
			if valueAbnormal(st.Role, st.Metric, xs[len(xs)-1]) || e.sim-st.clearedAt >= int64(Window)*bucketSec {
				st.alerted, st.Reported, st.clearedAt, st.same = false, false, 0, 0
			} else {
				continue
			}
		}
		st.same++
		st.AbnormalFor, st.Reported = st.same, st.alerted
		abnormal[k] = Candidate{st.Node, st.Metric, st.Role, f, xs, e.sim, st.Injected}
	}
	return e.batchEvents(abnormal)
}

const (
	// The domain agents were trained on events that had lasted >= 7 readings; younger windows get misread
	// (a fresh step called a spike), so the AI waits for 8 abnormal readings. Rule status still shows at once.
	persistReadings = 8
	// After the first sensor is ready, wait this many more readings so sensors that turned abnormal at
	// about the same time (e.g. air AND water) land in the SAME incident and the same batch of NPU calls.
	batchReadings = 3
	// ...but never hold an alert longer than this many readings after the batch opened
	batchMaxReadings = 10
)

// valueAbnormal: is the latest reading itself beyond the metric's warning threshold?
func valueAbnormal(role, metric string, last float64) bool {
	m, ok := Metrics[role+"/"+metric]
	if !ok || (m.Warn == 0 && m.Crit == 0) {
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

// batchEvents turns the currently abnormal sensors into at most one incident batch (caller holds lock).
// The batch opens when the first sensor has persistReadings abnormal readings, then stays open (at least
// batchReadings, at most batchMaxReadings readings) until EVERY alarming sensor in it has persistReadings
// readings too - so all sensors are judged on mature windows and still land in ONE incident.
// Every sensor alerts once per episode; it re-arms only after its status returns to normal.
func (e *Engine) batchEvents(abnormal map[string]Candidate) []Candidate {
	if e.batchUntil == 0 {
		for k := range abnormal {
			if st := e.states[k]; !st.alerted && st.same >= persistReadings {
				e.batchOpen = e.sim
				e.batchUntil = e.sim + batchReadings*bucketSec
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
	if e.sim < e.batchOpen+batchMaxReadings*bucketSec {
		for k := range abnormal {
			if st := e.states[k]; !st.alerted && st.same < persistReadings {
				return nil // a late sensor is still too young: keep the batch open a little longer
			}
		}
	}
	trace("gate: batch closed after %v wall (%d readings)", time.Since(e.batchOpenWall).Round(time.Millisecond), (e.sim-e.batchOpen)/bucketSec)
	e.batchUntil, e.batchOpen = 0, 0
	var out []Candidate
	for k, c := range abnormal {
		if st := e.states[k]; !st.alerted {
			st.alerted, st.Reported, st.clearedAt = true, true, 0
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
		base := 0.0
		if st := e.states[key(t.Node, t.Metric)]; st != nil && st.Last != nil {
			base = *st.Last
		}
		in := &Injection{ID: fmt.Sprintf("%s-%d-%d", sc.ID, time.Now().Unix(), i), Scenario: sc.ID, Node: t.Node, Metric: t.Metric,
			Kind: t.Kind, Start: e.sim + bucketSec, Dur: t.Dur, Amp: t.Amp, base: base, Hold: t.Hold}
		e.injects = append(e.injects, in)
		delete(e.cooldown, key(t.Node, t.Metric))
		out = append(out, in)
	}
	e.lastIncident = 0
	return out
}

// PickTargets swaps a scenario target for its first alternative whose current window is clean
// (data available, not flatline/erratic), so the injected pattern is not masked by idle or noisy real data.
func (e *Engine) PickTargets(ts []Target) []Target {
	e.mu.RLock()
	defer e.mu.RUnlock()
	out := make([]Target, len(ts))
	for i, t := range ts {
		out[i] = t
		for _, n := range append([]string{t.Node}, t.Alt...) {
			st := e.states[key(n, t.Metric)]
			if st != nil && st.DataOK && st.Pattern != "flatline" && st.Pattern != "erratic" {
				out[i].Node = n
				break
			}
		}
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
	for _, s := range e.states {
		out = append(out, *s)
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
	if info.Role != "hvac" {
		if xs, ok := e.Window(node, metric, e.sim); ok {
			ai := BuildAgentPrompt(info.Role, node, info.Location, metric, xs, e.sim)
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
	for k := range abnormal {
		if st := e.states[k]; st != nil && !st.alerted && st.same < persistReadings {
			return true
		}
	}
	return false
}
