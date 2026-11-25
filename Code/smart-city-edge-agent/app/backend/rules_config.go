package main

// One source of truth for what makes a sensor abnormal (owner 2026-11-17: "cards must be changeable along with the rule
// thresholds that trigger the AI call").
//
//   - effectiveMetric(role, metric, node): the built-in Metrics entry overlaid with the sensor's spec card. Only an
//     owner card from the site config (PUT /api/site/card) can differ from the built-ins: today's default cards agree with
//     Metrics on every number (TestEffectiveMetricDefaultsIdentical), so a sensor without a site card is untouched.
//     The agent prompt shows the same card, so the text the agent reads and the limits the trigger, the fast path,
//     StatusOf and the agent checks apply can no longer disagree.
//   - TriggerRules: the on-delay / batch / fast-path / transient counts of the event gate (engine.go), editable at run
//     time (GET/PUT /api/rules) and kept in state/trigger_rules.json.

import (
	"encoding/json"
	"fmt"
	"math"
	"net/http"
	"os"
	"path/filepath"
	"strings"
	"sync"
)

func init() {
	// the limits that StatusOf used to hard-code now live on the Metric so a card can move them
	m := Metrics["water/ph"]
	m.WarnLo, m.CritLo, m.HasLoSide = 6.5, 6.0, true
	Metrics["water/ph"] = m
	m = Metrics["air_quality/co2"]
	m.FaultLo, m.HasFaultLo = 350, true // indoor CO2 cannot sit below outdoor air (~420 ppm)
	Metrics["air_quality/co2"] = m
}

// ---------------------------------------------------------------- card -> Metric

func numStr(v float64) string { return cardNum(v) }

// overlayCard returns m with the card's thresholds applied: warning / critical limits (both sides), impossible bounds
// that the owner changed, the noise floor and the relative rate rules.
func overlayCard(m Metric, c Card) Metric {
	w, cr := c.Warning, c.Critical
	switch {
	case w == nil && cr == nil:
		if m.HasLimits {
			m.HasLimits, m.Warn, m.Crit, m.WarnS, m.CritS, m.HasLoSide = false, 0, 0, "", "", false
		}
	case w != nil && cr != nil && w.Dir == cr.Dir:
		setHi := func(wv, cv *float64) bool {
			if wv == nil || cv == nil {
				return false
			}
			if *wv != m.Warn || m.WarnS == "" {
				m.WarnS = numStr(*wv)
			}
			if *cv != m.Crit || m.CritS == "" {
				m.CritS = numStr(*cv)
			}
			m.Warn, m.Crit, m.HasLimits = *wv, *cv, true
			return true
		}
		switch w.Dir {
		case "high", "low":
			if setHi(w.At, cr.At) {
				m.Dir, m.HasLoSide = w.Dir, false
			}
		case "both":
			if w.Low != nil && cr.Low != nil && setHi(w.High, cr.High) {
				m.Dir, m.HasLoSide = "both", true
				m.WarnLo, m.CritLo = *w.Low, *cr.Low
			}
		}
	}
	if c.Floor != nil {
		m.Floor = *c.Floor
	}
	if c.Impossible != nil {
		// an impossible bound is a sensor fault for the rules only where the owner set / moved it (or the built-in
		// already had one, indoor CO2): the other default bounds are the sensor's range, not a rule today
		def, hasDef := existingCards[c.CardID]
		var dBelow, dAbove *float64
		if hasDef && def.Impossible != nil {
			dBelow, dAbove = def.Impossible.Below, def.Impossible.Above
		}
		differs := func(a, b *float64) bool { return a != nil && (b == nil || *a != *b) }
		if differs(c.Impossible.Below, dBelow) {
			m.FaultLo, m.HasFaultLo, m.Lo = *c.Impossible.Below, true, *c.Impossible.Below
		}
		if differs(c.Impossible.Above, dAbove) {
			m.FaultHi, m.HasFaultHi, m.Hi = *c.Impossible.Above, true, *c.Impossible.Above
		}
	}
	if rr := c.RateRules; rr != nil {
		m.AbruptWarn, m.AbruptCrit, m.GradualWarn = rr.AbruptWarn, rr.AbruptCrit, rr.GradualWarn
		m.GradualCrit = 0
		if rr.GradualCrit != nil {
			m.GradualCrit = *rr.GradualCrit
		}
		m.Osc = rr.Osc
		if m.Osc == "" {
			m.Osc = "normal"
		}
	}
	return m
}

type effEntry struct {
	base, eff Metric
	ok        bool
}

var effCache = struct {
	mu  sync.Mutex
	cfg *SiteConfig
	m   map[string]effEntry
}{}

// effectiveMetricOK: the thresholds the rule engine uses for one sensor. node "" = the built-in entry. The overlay is
// cached per (node, metric) and dropped whenever the site config is replaced (siteStore.Save / Load swap the pointer).
func effectiveMetricOK(role, metric, node string) (Metric, bool) {
	base, ok := Metrics[role+"/"+metric]
	if !ok || node == "" || role == "hvac" { // hvac has its own rules (hvac_v2.go) and card
		return base, ok
	}
	cfg, _ := siteS.Get()
	if cfg == nil || len(cfg.Cards) == 0 {
		return base, true
	}
	k := node + "/" + metric
	effCache.mu.Lock()
	if effCache.cfg != cfg || effCache.m == nil {
		effCache.cfg, effCache.m = cfg, map[string]effEntry{}
	}
	if e, hit := effCache.m[k]; hit && e.base == base {
		effCache.mu.Unlock()
		return e.eff, true
	}
	effCache.mu.Unlock()
	eff := base
	if c, _, found := siteCardFor(node, metric); found {
		eff = overlayCard(base, c)
	}
	effCache.mu.Lock()
	if effCache.cfg == cfg {
		effCache.m[k] = effEntry{base, eff, true}
	}
	effCache.mu.Unlock()
	return eff, true
}

func effectiveMetric(role, metric, node string) Metric {
	m, _ := effectiveMetricOK(role, metric, node)
	return m
}

// ---------------------------------------------------------------- trigger rules

// TriggerRules are the event-gate counts (readings = 5-minute buckets of sensor time). The constants of the same names in
// engine.go are the defaults.
type TriggerRules struct {
	PersistReadings  int `json:"persist_readings"`   // size of the reading window the AI gate looks at (default 8)
	BatchReadings    int `json:"batch_readings"`     // extra readings the batch stays open for co-occurring sensors
	BatchMaxReadings int `json:"batch_max_readings"` // an alert is never held longer than this after the batch opened
	FastReadings     int `json:"fast_readings"`      // critical fast path: readings beyond the critical limit
	FastCooldown     int `json:"fast_cooldown"`      // readings before a sensor may open another fast incident
	TransientMax     int `json:"transient_max"`      // a spike / dip this many readings wide or less is a transient
	AbnormalOfWindow int `json:"abnormal_of_window"` // abnormal readings out of the last persist_readings before the AI is called (default 4)
	EventAlarms      int `json:"event_mode_alarms"`  // event mode: this many sensors alarming in one building within 10 min (polish_events.go)
}

const defaultEventAlarms = 5

const defaultAbnormalOfWindow = 4

var defaultTrigger = TriggerRules{persistReadings, batchReadings, batchMaxReadings, fastReadings, fastCooldown, transientMax, defaultAbnormalOfWindow, defaultEventAlarms}

type intRange struct {
	Min int `json:"min"`
	Max int `json:"max"`
}

var triggerRanges = map[string]intRange{"persist_readings": {2, 24}, "batch_readings": {1, 24}, "batch_max_readings": {1, 24},
	"fast_readings": {1, 23}, "fast_cooldown": {1, 72}, "transient_max": {1, 12}, "event_mode_alarms": {2, 100}, "abnormal_of_window": {2, 24}}

var triggerConstraints = []string{"fast_readings < persist_readings", "batch_readings <= batch_max_readings", "abnormal_of_window <= persist_readings"}

// Validate returns the reasons a TriggerRules value is not acceptable (empty = ok).
func (t TriggerRules) Validate() []string {
	var bad []string
	in := func(name string, v int) {
		if r := triggerRanges[name]; v < r.Min || v > r.Max {
			bad = append(bad, fmt.Sprintf("%s %d outside %d..%d", name, v, r.Min, r.Max))
		}
	}
	in("persist_readings", t.PersistReadings)
	in("batch_readings", t.BatchReadings)
	in("batch_max_readings", t.BatchMaxReadings)
	in("fast_readings", t.FastReadings)
	in("fast_cooldown", t.FastCooldown)
	in("transient_max", t.TransientMax)
	in("event_mode_alarms", t.EventAlarms)
	in("abnormal_of_window", t.AbnormalOfWindow)
	if t.AbnormalOfWindow > t.PersistReadings {
		bad = append(bad, fmt.Sprintf("abnormal_of_window %d must not exceed persist_readings %d", t.AbnormalOfWindow, t.PersistReadings))
	}
	if t.FastReadings >= t.PersistReadings {
		bad = append(bad, fmt.Sprintf("fast_readings %d must be below persist_readings %d", t.FastReadings, t.PersistReadings))
	}
	if t.BatchReadings > t.BatchMaxReadings {
		bad = append(bad, fmt.Sprintf("batch_readings %d must not exceed batch_max_readings %d", t.BatchReadings, t.BatchMaxReadings))
	}
	return bad
}

type triggerStore struct {
	mu  sync.RWMutex
	dir string
	v   TriggerRules
}

var trigS = &triggerStore{v: defaultTrigger}

// trigRules: the current trigger settings (the engine reads them every tick).
func trigRules() TriggerRules {
	trigS.mu.RLock()
	defer trigS.mu.RUnlock()
	return trigS.v
}

func (s *triggerStore) path() string { return filepath.Join(s.dir, "state", "trigger_rules.json") }

// Load reads <dir>/state/trigger_rules.json; a missing or invalid file means the defaults.
func (s *triggerStore) Load(dir string) {
	s.mu.Lock()
	defer s.mu.Unlock()
	s.dir, s.v = dir, defaultTrigger
	b, err := os.ReadFile(s.path())
	if err != nil {
		return
	}
	t := defaultTrigger
	if err := json.Unmarshal(b, &t); err != nil || len(t.Validate()) > 0 {
		return
	}
	s.v = t
}

// Save validates t and stores it (.part + rename). Used by the engine from the next tick on.
func (s *triggerStore) Save(t TriggerRules) error {
	if bad := t.Validate(); len(bad) > 0 {
		return fmt.Errorf("%s", strings.Join(bad, "; "))
	}
	s.mu.Lock()
	defer s.mu.Unlock()
	if s.dir != "" {
		b, _ := json.MarshalIndent(t, "", " ")
		if err := atomicWrite(s.path(), b, 0o644); err != nil {
			return err
		}
	}
	s.v = t
	return nil
}

// ---------------------------------------------------------------- API

type ruleSide struct {
	Low  *float64 `json:"low"`
	High *float64 `json:"high"`
}

type ruleImp struct {
	Below *float64 `json:"below"`
	Above *float64 `json:"above"`
}

type ruleSensor struct {
	Node       string   `json:"node"`
	Metric     string   `json:"metric"`
	Role       string   `json:"role"`
	CardID     string   `json:"card_id"`
	Unit       string   `json:"unit"`
	Warning    ruleSide `json:"warning"`
	Critical   ruleSide `json:"critical"`
	Impossible ruleImp  `json:"impossible"`
	Floor      float64  `json:"floor"`
	Source     string   `json:"source"` // site_card | default_card | metrics
}

func fptr(v float64) *float64 { return &v }

// metricSides splits a Metric's warning / critical limit into low / high.
func metricSides(m Metric) (w, c ruleSide) {
	if !m.HasLimits {
		return
	}
	switch m.Dir {
	case "low":
		w.Low, c.Low = fptr(m.Warn), fptr(m.Crit)
	case "both":
		w.High, c.High = fptr(m.Warn), fptr(m.Crit)
		if m.HasLoSide {
			w.Low, c.Low = fptr(m.WarnLo), fptr(m.CritLo)
		}
	default:
		w.High, c.High = fptr(m.Warn), fptr(m.Crit)
	}
	return
}

func rulesSensors(sensors []SimSensor) []ruleSensor {
	out := make([]ruleSensor, 0, len(sensors))
	for _, sn := range sensors {
		m := effectiveMetric(sn.Role, sn.Metric, sn.Node)
		rs := ruleSensor{Node: sn.Node, Metric: sn.Metric, Role: sn.Role, Unit: sn.Unit, Floor: m.Floor, Source: "metrics"}
		if rs.Unit == "" {
			rs.Unit = m.Unit
		}
		rs.Warning, rs.Critical = metricSides(m)
		if m.HasFaultLo {
			rs.Impossible.Below = fptr(m.FaultLo)
		}
		if m.HasFaultHi {
			rs.Impossible.Above = fptr(m.FaultHi)
		}
		if c, _, ok := siteCardFor(sn.Node, sn.Metric); ok {
			rs.CardID, rs.Source = c.CardID, "site_card"
		} else if c, ok := existingCardFor(sn.Role, sn.Metric, sn.Node, sn.Location); ok {
			rs.CardID, rs.Source = c.CardID, "default_card"
		}
		out = append(out, rs)
	}
	return out
}

func (s *Server) rulesState() map[string]any {
	var sensors []SimSensor
	if s.eng != nil {
		sensors = s.eng.Sensors()
	}
	return map[string]any{"trigger": trigRules(), "defaults": defaultTrigger, "ranges": triggerRanges,
		"constraints": triggerConstraints, "sensors": rulesSensors(sensors)}
}

// rulesRoutes: GET /api/rules (effective trigger settings + per-sensor thresholds), PUT /api/rules {"trigger":{...}}.
// Card limits are edited through PUT /api/site/card; both are state-changing, so server.guard covers them alike.
func (s *Server) rulesRoutes(mux *http.ServeMux) {
	trigS.Load(s.dir)
	mux.HandleFunc("/api/rules", func(w http.ResponseWriter, r *http.Request) {
		switch r.Method {
		case http.MethodGet:
			w.Header().Set("Cache-Control", "no-store")
			writeJSON(w, s.rulesState())
		case http.MethodPut, http.MethodPost:
			body := struct {
				Trigger *TriggerRules `json:"trigger"`
			}{}
			dec := json.NewDecoder(http.MaxBytesReader(w, r.Body, 1<<16))
			dec.DisallowUnknownFields()
			// fields left out keep their current value
			cur := trigRules()
			body.Trigger = &cur
			if err := dec.Decode(&body); err != nil {
				writeJSONStatus(w, 400, map[string]any{"ok": false, "problems": []string{"bad JSON: " + err.Error()}})
				return
			}
			if body.Trigger == nil {
				writeJSONStatus(w, 400, map[string]any{"ok": false, "problems": []string{"missing trigger"}})
				return
			}
			if bad := body.Trigger.Validate(); len(bad) > 0 {
				writeJSONStatus(w, 400, map[string]any{"ok": false, "problems": bad})
				return
			}
			if err := trigS.Save(*body.Trigger); err != nil {
				http.Error(w, "rules not saved: "+err.Error(), 500)
				return
			}
			writeJSON(w, s.rulesState())
		default:
			http.Error(w, "GET or PUT", 405)
		}
	})
}

// cardLimitProblems: extra checks for a card the owner saves, on top of ValidateCard (a limit with a missing number
// would be silently ignored by the rules; warning and critical must point the same way).
func cardLimitProblems(c Card) []string {
	var bad []string
	for _, x := range []struct {
		l    *CardLim
		name string
	}{{c.Warning, "warning"}, {c.Critical, "critical"}} {
		if x.l == nil {
			continue
		}
		switch x.l.Dir {
		case "high", "low":
			if x.l.At == nil || math.IsNaN(*x.l.At) {
				bad = append(bad, x.name+".at missing")
			}
		case "both":
			if x.l.Low == nil || x.l.High == nil {
				bad = append(bad, x.name+" both needs low and high")
			} else if *x.l.Low >= *x.l.High {
				bad = append(bad, x.name+".low must be below "+x.name+".high")
			}
		}
	}
	if c.Warning != nil && c.Critical != nil && c.Warning.Dir != c.Critical.Dir {
		bad = append(bad, "warning and critical must have the same dir")
	}
	return bad
}
