package main

// History page API (device/web/history.js): GET /api/history?days=N returns every operator incident
// opened in the last N days (default 7, max 90) as compact rows, plus server-side aggregates. It reads
// only the reasoner store and the static sensor metadata: no NPU, no htpd, no disk.
//
// Times are the corrected wall clock: an incident's CreatedWall (IST, written with nowTime(), which
// fixes the board's wrong RTC) and the workflow's AckedAt/ClosedAt (wall unix from wfNow). Only an
// incident created while the clock was invalid and never back-filled falls back to its sensor time.

import (
	"net/http"
	"sort"
	"strconv"
	"time"
)

const (
	histDefaultDays = 7
	histMaxDays     = 90
	histMaxRows     = 5000 // newest rows kept; older ones are counted in the aggregates only
	histTopSensors  = 10
)

// histNow is the corrected clock the window ends at (tests replace it).
var histNow = func() time.Time { return nowTime() }

type HistRow struct {
	ID          string   `json:"id"`
	T           int64    `json:"t"` // opened, corrected wall unix
	Sev         string   `json:"sev"`
	Title       string   `json:"title"`
	Domains     []string `json:"domains"`
	Sensors     []string `json:"sensors"` // "node/metric", flagged sensors only
	Building    string   `json:"building,omitempty"`
	Floor       string   `json:"floor,omitempty"`
	Site        string   `json:"site,omitempty"` // site-tree path of the incident's scope
	State       string   `json:"state"`          // running | done | failed (the AI run)
	Workflow    string   `json:"workflow"`       // analysing | needs_decision | in_progress | resolved | closed | interrupted
	Open        bool     `json:"open"`
	Outcome     string   `json:"outcome,omitempty"`
	Owner       string   `json:"owner,omitempty"`
	AckS        int64    `json:"ack_s,omitempty"`   // seconds open -> acknowledged
	CloseS      int64    `json:"close_s,omitempty"` // seconds open -> closed
	AIMs        float64  `json:"ai_ms,omitempty"`   // AI report latency (finished runs only)
	NPUCalls    int      `json:"npu,omitempty"`
	Recurred    bool     `json:"recurred,omitempty"` // closed, then the same sensor alarmed again within 7 days
	RecurredBy  string   `json:"recurred_by,omitempty"`
	SensorFault bool     `json:"sensor_fault,omitempty"`
	Injected    bool     `json:"injected,omitempty"`
	Demo        bool     `json:"demo,omitempty"`
	ClockGuess  bool     `json:"clock_guess,omitempty"` // time from sensor clock, wall clock was unknown
}

type HistDay struct {
	Date        string `json:"date"` // IST yyyy-mm-dd
	Critical    int    `json:"critical"`
	Warning     int    `json:"warning"`
	SensorFault int    `json:"sensor_fault"`
	Normal      int    `json:"normal"`
}

type HistSensor struct {
	Sensor   string `json:"sensor"`
	Count    int    `json:"count"`
	Recurred int    `json:"recurred"`
	Last     int64  `json:"last"`
	LastID   string `json:"last_id"`
}

type HistAgg struct {
	Total          int            `json:"total"`
	BySeverity     map[string]int `json:"by_severity"`
	PerDay         []HistDay      `json:"per_day"`
	ByDomain       map[string]int `json:"by_domain"`
	ByBuilding     map[string]int `json:"by_building"`
	ByOutcome      map[string]int `json:"by_outcome"`
	ByWorkflow     map[string]int `json:"by_workflow"`
	Open           int            `json:"open"`
	SensorFaults   int            `json:"sensor_faults"`
	SensorFaultPct float64        `json:"sensor_fault_pct"`
	Recurred       int            `json:"recurred"`
	MedianAckS     int64          `json:"median_ack_s"`   // 0 = none acknowledged
	MedianCloseS   int64          `json:"median_close_s"` // 0 = none closed
	MedianAIMs     float64        `json:"median_ai_ms"`
	TopSensors     []HistSensor   `json:"top_sensors"`
	Heat           [7][24]int     `json:"heat"` // [weekday Mon=0..Sun=6][IST hour]
}

type HistResp struct {
	Now       int64     `json:"now"`
	From      int64     `json:"from"`
	Days      int       `json:"days"`
	TZ        string    `json:"tz"`
	Truncated bool      `json:"truncated"`
	Incidents []HistRow `json:"incidents"` // newest first
	Agg       HistAgg   `json:"agg"`
}

func (s *Server) registerHistoryRoutes(mux *http.ServeMux) {
	mux.HandleFunc("/api/history", func(w http.ResponseWriter, r *http.Request) {
		if r.Method != http.MethodGet && r.Method != http.MethodHead {
			http.Error(w, "GET only", http.StatusMethodNotAllowed)
			return
		}
		writeJSON(w, s.history(histDays(r.URL.Query().Get("days")), histNow()))
	})
}

func histDays(q string) int {
	d, err := strconv.Atoi(q)
	if err != nil || d <= 0 {
		return histDefaultDays
	}
	if d > histMaxDays {
		return histMaxDays
	}
	return d
}

// histOpened is the incident's corrected open time and whether it had to be guessed from sensor time.
func histOpened(inc *Incident) (int64, bool) {
	if t := wallOf(inc); !t.IsZero() {
		return t.Unix(), false
	}
	return inc.CreatedSim, true
}

func histSensorFault(inc *Incident) bool {
	if normSeverity(inc.Severity) == "sensor_fault" || inc.Outcome == "sensor_replaced" || inc.Outcome == "sensor_repaired" {
		return true
	}
	if rp := reportOf(inc); rp != nil && normSeverity(rp.Label) == "sensor_fault" {
		return true
	}
	return false
}

func (s *Server) history(days int, now time.Time) HistResp {
	from := now.Add(-time.Duration(days) * 24 * time.Hour).Unix()
	resp := HistResp{Now: now.Unix(), From: from, Days: days, TZ: "Asia/Kolkata", Incidents: []HistRow{}}

	var nodes map[string]NodeInfo
	if s.eng != nil {
		nodes = s.eng.Meta.Nodes // written once at engine load
	}
	_, ix := siteS.Get()

	type sk struct {
		t      int64
		id     string
		closed int64
	}
	bySensor := map[string][]sk{} // every incident on each sensor (all time, for recurrence)
	var rows []HistRow

	if s.rsn != nil {
		s.rsn.mu.RLock()
		for _, inc := range s.rsn.incidents {
			if inc.SystemCheck {
				continue
			}
			t, guess := histOpened(inc)
			for _, sr := range inc.Sensors {
				if !sr.Context {
					k := sr.Node + "/" + sr.Metric
					bySensor[k] = append(bySensor[k], sk{t, inc.ID, inc.ClosedAt})
				}
			}
			if t < from || t > now.Unix()+3600 { // outside the window (allow a little clock skew ahead)
				continue
			}
			wf := wfOf(inc)
			row := HistRow{ID: inc.ID, T: t, Sev: normSeverity(incSeverity(inc)), Title: inc.Title, Domains: append([]string{}, inc.Roles...),
				Sensors: []string{}, State: inc.State, Workflow: wf, Open: wf != wfClosed, Outcome: inc.Outcome, Owner: inc.Owner,
				NPUCalls: inc.NPUCalls, SensorFault: histSensorFault(inc), Injected: inc.Injected, Demo: inc.Watermark != "", ClockGuess: guess}
			if row.Sev == "" {
				row.Sev = "warning"
			}
			if inc.AckedAt > 0 && inc.AckedAt >= t {
				row.AckS = inc.AckedAt - t
			}
			if inc.ClosedAt > 0 && inc.ClosedAt >= t {
				row.CloseS = inc.ClosedAt - t
			}
			if inc.State == "done" && inc.TotalMs > 0 {
				row.AIMs = inc.TotalMs
			}
			for _, sr := range inc.Sensors {
				if sr.Context {
					continue
				}
				row.Sensors = append(row.Sensors, sr.Node+"/"+sr.Metric)
				if row.Building == "" {
					if ni, ok := nodes[sr.Node]; ok {
						row.Building, row.Floor = ni.Building, ni.Level
					}
				}
			}
			if row.Building == "" && inc.Zone != "" {
				row.Building = inc.Zone
			}
			if ix != nil && inc.Scope != "" {
				row.Site = ix.PathText(inc.Scope, true)
			}
			rows = append(rows, row)
		}
		s.rsn.mu.RUnlock()
	}

	// recurrence: a closed incident followed by a newer one on the same sensor within recurWindow
	idx := map[string]int{}
	for i := range rows {
		idx[rows[i].ID] = i
	}
	recurN := map[string]int{}
	for k, list := range bySensor {
		sort.Slice(list, func(i, j int) bool { return incNum(list[i].id) < incNum(list[j].id) })
		for i := 0; i+1 < len(list); i++ {
			a, b := list[i], list[i+1]
			if a.closed <= 0 || b.t < a.closed || b.t-a.closed > int64(recurWindow/time.Second) {
				continue
			}
			if j, ok := idx[a.id]; ok {
				recurN[k]++
				if !rows[j].Recurred {
					rows[j].Recurred, rows[j].RecurredBy = true, b.id
				}
			}
		}
	}

	sort.Slice(rows, func(i, j int) bool {
		if rows[i].T != rows[j].T {
			return rows[i].T > rows[j].T
		}
		return incNum(rows[i].ID) > incNum(rows[j].ID)
	})
	resp.Agg = histAggregate(rows, recurN, from, now)
	if len(rows) > histMaxRows {
		rows, resp.Truncated = rows[:histMaxRows], true
	}
	resp.Incidents = rows
	return resp
}

func histAggregate(rows []HistRow, recurN map[string]int, from int64, now time.Time) HistAgg {
	a := HistAgg{Total: len(rows), BySeverity: map[string]int{}, ByDomain: map[string]int{}, ByBuilding: map[string]int{},
		ByOutcome: map[string]int{}, ByWorkflow: map[string]int{}, PerDay: []HistDay{}, TopSensors: []HistSensor{}}
	// one bucket per IST day from the window start to today
	dayIdx := map[string]int{}
	d0 := time.Unix(from, 0).In(IST)
	d := time.Date(d0.Year(), d0.Month(), d0.Day(), 0, 0, 0, 0, IST)
	end := now.In(IST)
	for !d.After(end) {
		k := d.Format("2006-01-02")
		dayIdx[k] = len(a.PerDay)
		a.PerDay = append(a.PerDay, HistDay{Date: k})
		d = d.AddDate(0, 0, 1)
	}
	var acks, closes []int64
	var ais []float64
	sens := map[string]*HistSensor{}
	for _, r := range rows {
		a.BySeverity[r.Sev]++
		t := time.Unix(r.T, 0).In(IST)
		if i, ok := dayIdx[t.Format("2006-01-02")]; ok {
			switch r.Sev {
			case "critical":
				a.PerDay[i].Critical++
			case "sensor_fault":
				a.PerDay[i].SensorFault++
			case "normal":
				a.PerDay[i].Normal++
			default:
				a.PerDay[i].Warning++
			}
		}
		a.Heat[(int(t.Weekday())+6)%7][t.Hour()]++
		if len(r.Domains) == 0 {
			a.ByDomain["unknown"]++
		}
		for _, dm := range r.Domains {
			a.ByDomain[dm]++
		}
		b := r.Building
		if b == "" {
			b = "unknown"
		}
		a.ByBuilding[b]++
		o := r.Outcome
		if o == "" {
			if r.Open {
				o = "open"
			} else {
				o = "unrecorded"
			}
		}
		a.ByOutcome[o]++
		a.ByWorkflow[r.Workflow]++
		if r.Open {
			a.Open++
		}
		if r.SensorFault {
			a.SensorFaults++
		}
		if r.Recurred {
			a.Recurred++
		}
		if r.AckS > 0 {
			acks = append(acks, r.AckS)
		}
		if r.CloseS > 0 {
			closes = append(closes, r.CloseS)
		}
		if r.AIMs > 0 {
			ais = append(ais, r.AIMs)
		}
		for _, k := range r.Sensors {
			hs := sens[k]
			if hs == nil {
				hs = &HistSensor{Sensor: k, Recurred: recurN[k]}
				sens[k] = hs
			}
			hs.Count++
			if r.T > hs.Last {
				hs.Last, hs.LastID = r.T, r.ID
			}
		}
	}
	if a.Total > 0 {
		a.SensorFaultPct = float64(int(float64(a.SensorFaults)*1000/float64(a.Total)+0.5)) / 10
	}
	a.MedianAckS = medianInt(acks)
	a.MedianCloseS = medianInt(closes)
	a.MedianAIMs = medianFloat(ais)
	for _, hs := range sens {
		if hs.Count >= 2 || hs.Recurred > 0 {
			a.TopSensors = append(a.TopSensors, *hs)
		}
	}
	sort.Slice(a.TopSensors, func(i, j int) bool {
		x, y := a.TopSensors[i], a.TopSensors[j]
		if x.Count != y.Count {
			return x.Count > y.Count
		}
		if x.Recurred != y.Recurred {
			return x.Recurred > y.Recurred
		}
		return x.Sensor < y.Sensor
	})
	if len(a.TopSensors) > histTopSensors {
		a.TopSensors = a.TopSensors[:histTopSensors]
	}
	return a
}

func medianInt(v []int64) int64 {
	if len(v) == 0 {
		return 0
	}
	sort.Slice(v, func(i, j int) bool { return v[i] < v[j] })
	m := len(v) / 2
	if len(v)%2 == 1 {
		return v[m]
	}
	return (v[m-1] + v[m]) / 2
}

func medianFloat(v []float64) float64 {
	if len(v) == 0 {
		return 0
	}
	sort.Float64s(v)
	m := len(v) / 2
	if len(v)%2 == 1 {
		return v[m]
	}
	return (v[m-1] + v[m]) / 2
}
