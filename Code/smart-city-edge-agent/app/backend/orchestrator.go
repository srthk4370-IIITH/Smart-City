package main

// Cross-domain orchestrator: for every flagged sensor, pull the sensors of causally related domains
// (same building first) so the synthesizer can reason across domains even when only one domain is flagged.
// Related sensors are analysed by deterministic "context agents" in parallel on the CPU (microseconds);
// only flagged sensors and related sensors that are themselves abnormal get an NPU (LLM) agent call.

import (
	"math"
	"sort"
	"sync"
)

func init() {
	// HVAC is context only (no trained agent): register its metrics so windows/evidence/rules work.
	Metrics["hvac/ac_units_on"] = lim("units", 0, "", "", "high", 1, 0, 200)
	Metrics["hvac/room_temp"] = lim("C", 1, "30", "34", "high", 0.6, 5, 55)
}

type causalLink struct {
	Role, Metric, Why string
}

// causal map: flagged role/metric -> related domains that can explain or be affected by it
var causal = map[string][]causalLink{
	"air_quality/co2":  {{"occupancy", "occ", "people in the room raise CO2"}, {"hvac", "ac_units_on", "AC/ventilation state"}, {"power", "power_kw", "room load follows occupancy and HVAC"}, {"weather", "temp", "outdoor conditions drive ventilation and cooling"}},
	"air_quality/temp": {{"hvac", "room_temp", "AC controls room temperature"}, {"weather", "temp", "outdoor heat load"}, {"occupancy", "occ", "people add heat"}, {"power", "power_kw", "cooling load"}},
	"air_quality/rh":   {{"hvac", "ac_units_on", "AC dehumidifies"}, {"weather", "rh", "outdoor humidity"}},
	"air_quality/pm25": {{"weather", "wind", "wind disperses/brings particles"}, {"air_quality", "pm25", "other station shows if it is campus-wide"}, {"weather", "rh", "humidity affects particle readings"}},
	"air_quality/pm10": {{"weather", "wind", "wind-blown dust"}, {"air_quality", "pm10", "other station shows if it is campus-wide"}},
	"water/level":      {{"water", "flow", "inflow/outflow explains level changes"}, {"occupancy", "occ", "usage follows occupancy"}, {"weather", "temp", "heat raises consumption"}},
	"water/flow":       {{"water", "level", "tank level confirms consumption or leak"}, {"occupancy", "occ", "usage follows occupancy"}},
	"water/tds":        {{"water", "flow", "low flow / stagnation"}, {"water", "level", "tank state"}},
	"water/ph":         {{"water", "flow", "low flow / stagnation"}, {"water", "tds", "water quality context"}},
	"power/power_kw":   {{"hvac", "ac_units_on", "AC is the main load"}, {"occupancy", "occ", "load follows occupancy"}, {"weather", "temp", "heat drives cooling load"}},
	"power/pf":         {{"power", "power_kw", "load level"}, {"hvac", "ac_units_on", "inductive AC compressors"}},
	"weather/temp":     {{"power", "power_kw", "cooling load"}, {"air_quality", "temp", "indoor temperature"}, {"hvac", "ac_units_on", "AC response"}},
	"weather/rh":       {{"air_quality", "rh", "indoor humidity"}, {"weather", "temp", "dew/temperature"}},
	"weather/wind":     {{"air_quality", "pm25", "particle dispersion"}, {"air_quality", "pm10", "dust"}},
	"occupancy/occ":    {{"air_quality", "co2", "CO2 confirms presence"}, {"power", "power_kw", "load confirms presence"}, {"hvac", "ac_units_on", "AC use confirms presence"}},
}

type contextPick struct {
	Cand  Candidate
	Why   string
	Score float64
}

// informative: does this related-domain finding carry evidence the synthesizer should reason about?
// A faulty related sensor (sensor_fault) is not explanatory evidence on its own.
func informative(f Finding) bool {
	if f.Status == "warning" || f.Status == "critical" {
		return true
	}
	return f.Status == "normal" && f.Pattern != "stable" && f.Pattern != "vacant" && f.Pattern != "-" && f.Pattern != "context"
}

// hvacFinding: deterministic summary of an AC-units / room-temperature window (context only).
func hvacFinding(metric string, xs []float64, end int64) Finding {
	m := Metrics["hvac/"+metric]
	st := ComputeStats(xs, m.Dec)
	pat := RulePattern("hvac", metric, xs, end)
	if metric == "ac_units_on" && pat == "flatline" {
		pat = "stable" // a constant number of running AC units is normal, not a stuck sensor
	}
	status := "normal"
	if metric == "room_temp" && st.Last >= m.Warn {
		status = "warning"
	}
	var obs string
	if metric == "ac_units_on" {
		obs = "AC units running: now " + Fmt(st.Last, 0) + ", 1h average " + Fmt(st.SMA1h, 1) + ", max " + Fmt(st.Max, 0) + " [E1,E6,E2]"
	} else {
		obs = "Room temperature (AC sensors) " + Fmt(st.Last, 1) + " C, trend " + sgn(st.SlopePerH, 1) + " C/h [E1,E4]"
	}
	return Finding{Pattern: pat, Status: status, Observations: []string{obs}, LikelyCause: "hvac_context", Confidence: 0.8, Action: "none"}
}

func contextFinding(role, metric, node string, xs []float64, end int64) Finding {
	if role == "hvac" {
		return hvacFinding(metric, xs, end)
	}
	return RuleFinding(role, metric, node, xs, end)
}

// ContextFor picks up to max related sensors for the flagged ones (same building first, informative
// first) and runs their deterministic context agents concurrently.
func (e *Engine) ContextFor(flagged []Candidate, max int) []contextPick {
	e.mu.RLock()
	defer e.mu.RUnlock()
	taken := map[string]bool{}
	for _, c := range flagged {
		taken[key(c.Node, c.Metric)] = true
	}
	type option struct {
		node, metric, role, why string
		score                   float64
		xs                      []float64
		end                     int64
	}
	var opts []option
	for _, c := range flagged {
		fi := e.Meta.Nodes[c.Node]
		for _, l := range causal[c.Role+"/"+c.Metric] {
			best := option{score: -100}
			for _, n := range e.nodeOrder() { // sorted: deterministic choice on ties
				info := e.Meta.Nodes[n]
				if info.Role != l.Role || taken[key(n, l.Metric)] || !contains(info.Metrics, l.Metric) {
					continue
				}
				xs, ok := e.Window(n, l.Metric, c.End)
				if !ok {
					continue
				}
				s := 0.0
				if st := e.states[key(n, l.Metric)]; st != nil && st.Status == "sensor_fault" {
					s -= 4 // prefer a healthy sensor of the same domain over a faulty one
				}
				if info.Building == fi.Building {
					s += 3
					if info.Level == fi.Level {
						s += 1
					}
				}
				if l.Role == "weather" {
					s += 2 // campus-wide: always relevant
				}
				if s > best.score {
					best = option{n, l.Metric, l.Role, l.Why, s, xs, c.End}
				}
			}
			if best.score > -100 {
				taken[key(best.node, best.metric)] = true
				opts = append(opts, best)
			}
		}
	}
	// context agents in parallel (deterministic, CPU)
	picks := make([]contextPick, len(opts))
	var wg sync.WaitGroup
	for i, o := range opts {
		wg.Add(1)
		go func(i int, o option) {
			defer wg.Done()
			f := contextFinding(o.role, o.metric, o.node, o.xs, o.end)
			score := o.score
			if informative(f) {
				score += 2 + float64(sevRank(f.Status))
			}
			picks[i] = contextPick{Candidate{o.node, o.metric, o.role, f, o.xs, o.end, false, false, false}, o.why, score}
		}(i, o)
	}
	wg.Wait()
	sort.SliceStable(picks, func(a, b int) bool { return picks[a].Score > picks[b].Score })
	if len(picks) > max {
		picks = picks[:max]
	}
	return picks
}

func (e *Engine) nodeOrder() []string {
	ns := make([]string, 0, len(e.Meta.Nodes))
	for n := range e.Meta.Nodes {
		ns = append(ns, n)
	}
	sort.Strings(ns)
	return ns
}

// evidenceFor builds the E1..E8 evidence list for any sensor (incl. HVAC context).
func evidenceFor(role, node, location, metric string, xs []float64, end int64) []Evidence {
	return BuildAgentPrompt(role, node, location, metric, xs, end).Evidence
}

var _ = math.Abs
