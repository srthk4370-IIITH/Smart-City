package main

// Domain health (GET /api/health, SSE "health"): one tile per domain for the operator's first look.
// Design note: proofs/2026-10-21_v2_research/domain_health/DESIGN.md. Computed from in-memory engine
// and reasoner state only (no NPU, no disk), so it is safe to run on every poll.
//
//   - status: worst live PROCESS status (normal < warning < critical) of the domain's own sensors.
//     Context-only sensors (HVAC context in v1, setpoint/ac_on in v2) never raise it. While the live
//     status is abnormal, an open incident's reasoner severity may raise it further (the AI elevated
//     it); the AI never lowers a live warning (a curb is shown on the incident, not hidden here).
//   - sensor faults and stale / warming-up data are reported separately from the process status
//     (a data-quality problem, not a facility one: ISA-18.2 keeps out-of-service apart from alarms).
//   - headline: what the tile shows - the process status if abnormal, else sensor_fault, else
//     insufficient_data (no fresh data at all), else normal.
//   - trend: elevated / curbed for healthTrendHold of sensor time after the headline moved, then steady.
//   - steps: whitelisted actions from the open incidents' valid agent findings and report (human
//     approval wording, never actuation), else a static playbook for warning / critical / fault.

import (
	"encoding/json"
	"sort"
	"strings"
	"sync"
)

var healthDomains = []string{"air_quality", "water", "power", "occupancy", "weather", "hvac"}

const (
	healthTrendHold = 6 * bucketSec // an elevated/curbed arrow stays this long (30 min sensor time)
	healthStaleSec  = 2 * bucketSec // a sensor whose last reading is older than this is stale
	healthOpenSec   = 12 * 3600     // pending incidents older than this (sensor time) are not "open"
	healthMaxSteps  = 3
)

// headline levels, low to high
var healthRank = map[string]int{"normal": 0, "insufficient_data": 1, "sensor_fault": 2, "warning": 3, "critical": 4}

type DomainIncident struct {
	ID       string `json:"id"`
	Severity string `json:"severity"` // normalised: critical | warning | normal | sensor_fault
	Final    bool   `json:"severity_final"`
	Stage    string `json:"refine_stage,omitempty"` // early | 1.5h | 3h
	Change   string `json:"change,omitempty"`       // elevated | curbed at the latest refinement
	Title    string `json:"title"`
	State    string `json:"state"`
	Workflow string `json:"workflow"`        // needs_decision | in_progress | resolved | ... (workflow.go)
	Owner    string `json:"owner,omitempty"` // who acknowledged it
}

type DomainStep struct {
	Text   string `json:"text"`
	Action string `json:"action,omitempty"` // whitelisted action id (absent for playbook steps)
	Source string `json:"source"`           // report | agent | playbook
	Ref    string `json:"incident,omitempty"`
}

type DomainHealth struct {
	Domain      string           `json:"domain"`
	Headline    string           `json:"headline"`    // normal | insufficient_data | sensor_fault | warning | critical
	Status      string           `json:"status"`      // process status: normal | warning | critical
	LiveStatus  string           `json:"live_status"` // the same from live sensors only (before the AI)
	ByAI        bool             `json:"raised_by_ai,omitempty"`
	Faults      int              `json:"sensor_faults"`
	Counts      map[string]int   `json:"counts"`
	OutOfSvc    int              `json:"out_of_service,omitempty"` // sensors under maintenance: shown, never alarmed
	Sensors     int              `json:"sensors"`
	Context     int              `json:"context_sensors"`
	ContextOnly bool             `json:"context_only,omitempty"` // no sensor of its own is judged (v1 HVAC)
	Trend       string           `json:"trend"`                  // elevated | curbed | steady
	TrendFrom   string           `json:"trend_from,omitempty"`   // headline before the change
	Since       int64            `json:"since"`                  // sensor time the headline took its level
	Fresh       bool             `json:"fresh"`
	Stale       []string         `json:"stale,omitempty"`        // "node metric" of stale / warming-up sensors
	DataQuality []SensorQuality  `json:"data_quality,omitempty"` // sensors whose data is not good, and why
	Incidents   []DomainIncident `json:"incidents"`
	Steps       []DomainStep     `json:"steps"`
}

type HealthOut struct {
	SimTime int64          `json:"sim_time"`
	Worst   string         `json:"worst"`
	Domains []DomainHealth `json:"domains"`
}

type healthMark struct {
	level   string
	since   int64
	trend   string
	from    string
	trendAt int64
}

// HealthTracker remembers each domain's previous headline so a change shows as a trend.
type HealthTracker struct {
	mu    sync.Mutex
	marks map[string]*healthMark
	last  int64
	sig   string
}

func NewHealthTracker() *HealthTracker { return &HealthTracker{marks: map[string]*healthMark{}} }

// Update computes the current health and reports whether it differs from the previous call's.
func (t *HealthTracker) Update(eng *Engine, rsn *Reasoner) (HealthOut, bool) {
	epoch, _, _ := eng.SimBase()
	sim, states, _ := eng.Snapshot()
	var incs []*Incident
	if rsn != nil {
		rsn.mu.RLock()
		defer rsn.mu.RUnlock()
		incs = rsn.incidents
	}
	t.mu.Lock()
	defer t.mu.Unlock()
	if sim < t.last { // sensor clock restarted: earlier levels no longer apply
		t.marks = map[string]*healthMark{}
	}
	t.last = sim
	out := buildHealth(sim, epoch, states, incs, t.marks)
	b, _ := json.Marshal(out.Domains)
	changed := string(b) != t.sig
	t.sig = string(b)
	return out, changed
}

// contextSensor: shown for context, never judged on its own (engine.detect gives it pattern "context").
func contextSensor(st SensorState) bool {
	return st.Pattern == "context" || (st.Role == "hvac" && !hvacAgentSensor(st.Role, st.Node, st.Metric))
}

func staleSensor(st SensorState, sim int64) bool {
	return st.Last == nil || !st.DataOK || st.Status == "insufficient_data" || (st.Updated > 0 && sim-st.Updated > healthStaleSec)
}

// openIncident: not closed, from this sensor history, and either recent enough to still matter or
// owned by someone. Every workflow state counts (UX v34): an acknowledged incident whose work is not
// done used to vanish from the tile the moment it was approved. Unowned incidents older than the open
// window stay listed by the app as "earlier, still awaiting your decision".
func openIncident(inc *Incident, sim, epoch int64) bool {
	if wfOf(inc) == wfClosed {
		return false
	}
	if inc.SimEpoch != 0 && inc.SimEpoch != epoch {
		return false
	}
	return inc.CreatedSim <= sim && (sim-inc.CreatedSim <= healthOpenSec || inc.Owner != "")
}

func incidentTouches(inc *Incident, domain string) bool {
	if contains(inc.Roles, domain) {
		return true
	}
	if inc.Final != nil && inc.Final.Valid && inc.Final.Parsed != nil {
		for _, d := range inc.Final.Parsed.AffectedDomains {
			if normEnum(d) == domain {
				return true
			}
		}
	}
	return false
}

// latestChange: did the newest refinement raise or lower the incident's severity?
func latestChange(inc *Incident) string {
	n := len(inc.Revisions)
	if n < 2 {
		return ""
	}
	a, b := reportRank[normSeverity(inc.Revisions[n-2].Severity)], reportRank[normSeverity(inc.Revisions[n-1].Severity)]
	switch {
	case b > a:
		return "elevated"
	case b < a:
		return "curbed"
	}
	return ""
}

func buildHealth(sim, epoch int64, states []SensorState, incs []*Incident, marks map[string]*healthMark) HealthOut {
	out := HealthOut{SimTime: sim, Worst: "normal"}
	for _, d := range healthDomains {
		dh := DomainHealth{Domain: d, Status: "normal", LiveStatus: "normal", Counts: map[string]int{},
			Fresh: true, Incidents: []DomainIncident{}, Steps: []DomainStep{}}
		for _, st := range states {
			if st.Role != d {
				continue
			}
			if contextSensor(st) {
				dh.Context++
				continue
			}
			dh.Sensors++
			if st.Quality == "maintenance" { // out of service: shown, never alarmed (ISA-18.2 out-of-service)
				dh.OutOfSvc++
				dh.DataQuality = append(dh.DataQuality, SensorQuality{st.Node + " " + st.Metric, st.Quality, st.QualityWhy})
				continue
			}
			s := st.Status
			if s == "" {
				s = "insufficient_data"
			}
			dh.Counts[s]++
			if s == "sensor_fault" {
				dh.Faults++
			}
			if st.Quality != "" && st.Quality != "good" {
				dh.DataQuality = append(dh.DataQuality, SensorQuality{st.Node + " " + st.Metric, st.Quality, st.QualityWhy})
			}
			if staleSensor(st, sim) {
				dh.Fresh = false
				dh.Stale = append(dh.Stale, st.Node+" "+st.Metric)
			}
			if (s == "warning" || s == "critical") && reportRank[s] > reportRank[dh.LiveStatus] {
				dh.LiveStatus = s
			}
		}
		dh.ContextOnly = dh.Sensors == 0 && dh.Context > 0
		dh.Status = dh.LiveStatus
		var open []*Incident
		for i := len(incs) - 1; i >= 0; i-- { // newest first
			inc := incs[i]
			if !openIncident(inc, sim, epoch) || !incidentTouches(inc, d) {
				continue
			}
			open = append(open, inc)
			sev := normSeverity(inc.Severity)
			dh.Incidents = append(dh.Incidents, DomainIncident{ID: inc.ID, Severity: sev, Final: inc.SeverityFinal,
				Stage: inc.RefineStage, Change: latestChange(inc), Title: inc.Title, State: inc.State, Workflow: wfOf(inc), Owner: inc.Owner})
			// the AI may raise a live abnormal status, never lower it or invent one
			if dh.LiveStatus != "normal" && (sev == "warning" || sev == "critical") && reportRank[sev] > reportRank[dh.Status] {
				dh.Status, dh.ByAI = sev, true
			}
		}
		switch {
		case dh.Status != "normal":
			dh.Headline = dh.Status
		case dh.Faults > 0:
			dh.Headline = "sensor_fault"
		case dh.Sensors > 0 && dh.Counts["insufficient_data"] == dh.Sensors:
			dh.Headline = "insufficient_data"
		default:
			dh.Headline = "normal"
		}
		trackTrend(&dh, marks, sim)
		if dh.Headline == "warning" || dh.Headline == "critical" || dh.Headline == "sensor_fault" {
			dh.Steps = domainSteps(d, dh.Headline, open)
		}
		if healthRank[dh.Headline] > healthRank[out.Worst] {
			out.Worst = dh.Headline
		}
		out.Domains = append(out.Domains, dh)
	}
	return out
}

func trackTrend(dh *DomainHealth, marks map[string]*healthMark, sim int64) {
	m := marks[dh.Domain]
	switch {
	case m == nil:
		m = &healthMark{level: dh.Headline, since: sim, trend: "steady"}
		marks[dh.Domain] = m
	case healthRank[dh.Headline] > healthRank[m.level]:
		m.trend, m.from, m.trendAt = "elevated", m.level, sim
		m.level, m.since = dh.Headline, sim
	case healthRank[dh.Headline] < healthRank[m.level]:
		m.trend, m.from, m.trendAt = "curbed", m.level, sim
		m.level, m.since = dh.Headline, sim
	}
	if m.trend != "steady" && sim-m.trendAt > healthTrendHold {
		m.trend, m.from = "steady", ""
	}
	dh.Trend, dh.TrendFrom, dh.Since = m.trend, m.from, m.since
}

// actionStep is how a whitelisted action reads on a tile: a recommendation for a person to carry out.
var actionStep = map[string]string{
	"monitor":                 "Keep watching the flagged readings; no on-site action yet",
	"inspect_ventilation":     "Ask facilities to inspect ventilation (fresh-air dampers, AHU fan) in the affected area",
	"inspect_hvac":            "Ask facilities to inspect the HVAC unit (setpoint, compressor, filters)",
	"check_sensor":            "Check the flagged sensor on site (power, mounting, calibration) before trusting it",
	"inspect_water_system":    "Inspect the water system: tank, pumps, valves and pipes for leaks",
	"inspect_electrical":      "Ask an electrician to inspect the feeder and panel of the flagged meter",
	"review_schedule":         "Review the occupancy and equipment schedule for the area",
	"request_facility_review": "Raise a facility review with the incident's evidence",
	"switch_off_ac":           "Recommended: switch off the AC in the empty room (operator decision; the app switches nothing)",
}

// healthPlaybook: fallback steps when no valid agent or report action is available.
var healthPlaybook = map[string]map[string][]string{
	"air_quality": {
		"warning":  {"Increase fresh-air ventilation in the affected room", "Check occupancy against the room's capacity", "Re-check CO2 / PM2.5 over the next 30 min"},
		"critical": {"Ask facilities to ventilate the room now (dampers, AHU, windows)", "Consider limiting occupancy until levels fall", "Look for an indoor source (combustion, cleaning, construction)"},
	},
	"water": {
		"warning":  {"Check the tank level against the pump schedule", "Look for unusual draw (taps left running, overflow)", "Confirm the level / flow reading on site"},
		"critical": {"Inspect the tank and pumps", "Check for leaks or overflow", "Confirm the level sensor with a manual reading"},
	},
	"power": {
		"warning":  {"Check which loads are running against the schedule", "Look for equipment left on after hours", "Re-check the meter over the next 30 min"},
		"critical": {"Ask an electrician to inspect the feeder and panel", "Check for overloaded circuits", "Agree with facilities which non-essential loads can be shed"},
	},
	"occupancy": {
		"warning":  {"Confirm whether the presence is expected (bookings, timetable)", "If after hours, ask security to check the area", "Re-check the occupancy sensor's view"},
		"critical": {"Ask security to check the area", "Confirm the presence against bookings", "Check the occupancy sensor on site"},
	},
	"weather": {
		"warning":  {"Expect knock-on effects on cooling load and indoor temperature", "Check the outdoor sensor's exposure (direct sun, rain)", "Re-check over the next hour"},
		"critical": {"Inform facilities of the extreme weather reading", "Prepare HVAC and drainage for the conditions", "Confirm the reading against a second source"},
	},
	"hvac": {
		"warning":  {"Check the unit's setpoint and schedule", "Compare room temperature with the setpoint", "Re-check the unit over the next 30 min"},
		"critical": {"Ask facilities to inspect the unit (compressor, filters, controls)", "Check whether the unit runs in an empty room", "Confirm the room temperature on site"},
	},
}

var faultPlaybook = []string{"Check the faulty sensor on site (power, wiring, mounting)",
	"Compare it with a nearby sensor or a manual reading", "Treat its readings as unreliable until it is fixed"}

// domainSteps: actions from the open incidents first (report, then this domain's agent findings),
// whitelisted and de-duplicated; the static playbook when none is usable.
func domainSteps(domain, level string, open []*Incident) []DomainStep {
	var steps []DomainStep
	seen := map[string]bool{}
	add := func(action, src, id string) {
		a := normEnum(action)
		if a == "" || a == "none" || seen[a] || !actionAllowed(a) || actionStep[a] == "" || len(steps) >= healthMaxSteps {
			return
		}
		seen[a] = true
		steps = append(steps, DomainStep{Text: actionStep[a], Action: a, Source: src, Ref: id})
	}
	for _, inc := range open {
		if f := inc.Final; f != nil && f.Valid && f.Parsed != nil && normSeverity(f.Parsed.Severity) != "normal" {
			add(f.Parsed.Action, "report", inc.ID)
		}
		for _, a := range inc.Agents {
			if !a.Valid || a.Parsed == nil || normSeverity(a.Parsed.Status) == "normal" {
				continue
			}
			for _, s := range inc.Sensors {
				if s.Ref == a.Ref && !s.Context && s.Role == domain {
					add(a.Parsed.Action, "agent", inc.ID)
				}
			}
		}
	}
	// "monitor" alone is no guidance for an abnormal domain: let the playbook speak instead
	if len(steps) == 1 && steps[0].Action == "monitor" {
		steps = nil
	}
	if len(steps) > 0 {
		sort.SliceStable(steps, func(i, j int) bool { return steps[i].Action != "monitor" && steps[j].Action == "monitor" })
		return steps
	}
	list := faultPlaybook
	if level != "sensor_fault" {
		list = healthPlaybook[domain][level]
	}
	for _, t := range list {
		if len(steps) < healthMaxSteps {
			steps = append(steps, DomainStep{Text: t, Source: "playbook"})
		}
	}
	return steps
}

// healthSummary is a one-line text form (logs, tests).
func healthSummary(h HealthOut) string {
	var p []string
	for _, d := range h.Domains {
		p = append(p, d.Domain+"="+d.Headline+"/"+d.Trend)
	}
	return strings.Join(p, " ")
}

// SensorQuality is one sensor's data-quality flag in the domain health (dataquality.go).
type SensorQuality struct {
	Sensor  string `json:"sensor"`
	Quality string `json:"quality"` // uncertain | bad | stale | maintenance
	Reason  string `json:"reason,omitempty"`
}
